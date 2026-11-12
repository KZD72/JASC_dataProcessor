"""Isolated, cancellable playback with staged outputs and workspace publication."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from core.jobs import JobContext, JobCancelled
from core.script_language import Program, ScriptError
from core.script_process import ProcessLimits


@dataclass(frozen=True)
class ScriptRequest:
    source: str
    input_dir: Path
    output_dir: Path
    timeout: float = 120.0
    memory_mb: int = 2048
    script_name: str = "recording.py"


@dataclass
class ScriptRun:
    workspace: object
    folder: Path
    calls: int
    sha256: str
    final_folder: Path | None = None

    def commit(self) -> None:
        if self.final_folder is not None:
            self.folder.rename(self.final_folder)
            self.folder, self.final_folder = self.final_folder, None

    def discard(self) -> None:
        if self.final_folder is None:
            return
        import shutil
        root = self.final_folder.parent.resolve()
        target = self.folder.resolve()
        if target.parent != root or not target.name.startswith(".jasc-script-ready-"):
            raise ScriptError("Refusing to remove a staging folder outside this run's output directory.")
        shutil.rmtree(target)
        self.final_folder = None


def snapshot_workspace(workspace: object) -> object:
    """Detach editable state; immutable Parquet owners remain alive during saving."""
    return deepcopy(workspace, {id(item): item for item in workspace.list_large_datasets()})


def workspace_stamp(workspace: object) -> str:
    from core.api_recording import fingerprint
    digest = hashlib.sha256()
    for sheet in workspace.list_datasets():
        digest.update(fingerprint(sheet).encode())
        digest.update(repr(sheet.formulas).encode())
        digest.update(repr(sheet.worksheet_metadata.to_metadata()).encode())
    for plot in workspace.list_plots():
        digest.update(repr((plot.name, plot.plot_id, plot.state, plot.editor_state)).encode())
    for analysis in workspace.list_spectral_analyses():
        digest.update(repr(analysis.metadata()).encode())
        for frame in (analysis.curves_frame, analysis.metrics_frame, analysis.parameters_frame, analysis.peaks_frame):
            import pandas as pd
            digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    for source in workspace.list_large_datasets():
        digest.update(repr((id(source), source.name, source.row_count, source.columns)).encode())
    digest.update(repr(workspace.list_custom_fit_models()).encode())
    return digest.hexdigest()


def worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--script-worker"]
    return [sys.executable, "-E", "-s", "-B", str(Path(__file__).resolve().parents[1]/"main.py"), "--script-worker"]


def run_script(context: JobContext, request: ScriptRequest, *, workspace: object | None = None,
               project: Path | None = None, publish: bool = True) -> ScriptRun:
    """Validate before any work; publish one new output folder only after success."""
    program = Program.parse(request.source)
    from core.script_safety import local_spelling
    local_spelling(str(request.input_dir))
    local_spelling(str(request.output_dir))
    if not 0.1 <= request.timeout <= 3600 or not 512 <= request.memory_mb <= 16384:
        raise ScriptError("Playback limits are outside the supported range.")
    input_root = request.input_dir.resolve(strict=True)
    if not input_root.is_dir():
        raise ScriptError("Choose an existing input folder.")
    output_root = request.output_dir.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    context.check_cancelled()
    from core import project_io
    token = uuid4().hex
    final = output_root/f"jasc_script_run_{datetime.now():%Y%m%d_%H%M%S}_{token[:8]}"
    with tempfile.TemporaryDirectory(prefix=".jasc-script-", dir=output_root) as temporary:
        root = Path(temporary)
        script = root/"recording.py"
        # Preserve reviewed CRLF/LF bytes; Windows text-mode translation could
        # otherwise change an edited recording between validation and playback.
        script.write_bytes(program.source.encode("utf-8"))
        outputs = root/"outputs"
        outputs.mkdir()
        initial = Path(project).resolve(strict=True) if project is not None else None
        if workspace is not None:
            initial = root/"input.jasc"
            context.report(0, 0, "Preparing the starting workspace...")
            project_io.save_project(workspace, initial)
        context.check_cancelled()
        result = root/"result.jasc"
        progress = root/"progress.json"
        permit = root/"start"
        log = root/"worker.log"
        command = worker_command()+[str(script), "--input-dir", str(input_root), "--output-dir", str(outputs),
                                    "--result", str(result), "--progress", str(progress), "--permit", str(permit),
                                    "--memory-mb", str(request.memory_mb)]
        if initial is not None:
            command += ["--project", str(initial)]
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1",
                           MPLCONFIGDIR=str(root/"matplotlib"))
        for key in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
            environment.pop(key, None)
        process = None
        limits = None
        started = time.monotonic()
        previous = None
        try:
            with log.open("wb") as stream:
                process = subprocess.Popen(command, cwd=root, env=environment, stdin=subprocess.DEVNULL,
                                           stdout=stream, stderr=subprocess.STDOUT,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                limits = ProcessLimits(process.pid, request.memory_mb)
                permit.write_text("start", encoding="ascii")
                while process.poll() is None:
                    context.check_cancelled()
                    if time.monotonic()-started > request.timeout:
                        raise ScriptError(f"Playback exceeded the {request.timeout:g} second time limit.")
                    if progress.exists() and progress.stat().st_size < 4096:
                        try:
                            current = json.loads(progress.read_text(encoding="utf-8"))
                            if current != previous:
                                context.report(int(current["step"]), 0, "Running API call: "+str(current["label"]))
                                previous = current
                        except (OSError, ValueError, KeyError):
                            pass
                    time.sleep(0.03)
            context.check_cancelled()
            if process.returncode != 0:
                with log.open("rb") as stream:
                    stream.seek(max(0, log.stat().st_size-8000))
                    detail = stream.read().decode("utf-8", errors="replace")
                if progress.is_file():
                    try:
                        detail = json.loads(progress.read_text(encoding="utf-8")).get("error", detail)
                    except (ValueError, OSError):
                        pass
                raise ScriptError("Script worker failed or exceeded its memory limit.\n"+detail[-8000:])
            if not result.is_file():
                raise ScriptError("The script worker did not produce a result project.")
            context.report(0, 0, "Loading completed script results...")
            loaded = project_io.load_project(result)
            context.check_cancelled()
            destination = outputs/"_jasc_result.jasc"
            if destination.exists():
                raise ScriptError("The recording used the reserved result-project filename.")
            result.replace(destination)
            digest = hashlib.sha256(program.source.encode("utf-8")).hexdigest()
            (outputs/"_jasc_run.json").write_text(json.dumps({"script": request.script_name, "sha256": digest,
                "commands": len(program.commands), "input_folder": str(input_root), "status": "completed"}, indent=2), encoding="utf-8")
            context.check_cancelled()
            destination = final if publish else output_root/(".jasc-script-ready-"+token)
            outputs.rename(destination)
            return ScriptRun(loaded, destination, len(program.commands), digest, None if publish else final)
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            if limits is not None:
                limits.close()
