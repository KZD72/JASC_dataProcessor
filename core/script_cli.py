"""Shared restricted entry points for source Python and the frozen executable."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from threading import Event
import sys
import time

from core.script_language import Program, ScriptError


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay a restricted JASC API recording.")
    parser.add_argument("script", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--output", type=Path, help="Also copy the result project to this new .jasc file (never overwrite)")
    parser.add_argument("--input-dir", type=Path, help="Only this folder can supply imported data; defaults to the script folder")
    parser.add_argument("--output-dir", type=Path, help="Parent for a new run folder; defaults to --output's folder or jasc_script_outputs")
    parser.add_argument("--timeout", type=float, default=120.)
    options = parser.parse_args(arguments)
    try:
        program = Program.read(options.script)
        if options.output is not None and (options.output.suffix.lower() != ".jasc" or options.output.exists()):
            raise ScriptError("--output must name a new .jasc file; existing files are never overwritten.")
        output = options.output_dir or (options.output.resolve().parent if options.output else Path.cwd()/"jasc_script_outputs")
        from core.script_jobs import ScriptRequest, run_script
        from core.jobs import JobContext
        run = run_script(JobContext(Event(), lambda _: None), ScriptRequest(program.source,
                         options.input_dir or options.script.resolve().parent, output, options.timeout,
                         script_name=options.script.name), project=options.project)
        if options.output:
            # Hard-link is exclusive and atomic: a concurrent new file is retained.
            options.output.parent.mkdir(parents=True, exist_ok=True)
            os.link(run.folder/"_jasc_result.jasc", options.output)
        print(f"Completed {run.calls} recorded commands. Results: {run.folder}")
        return 0
    except (ScriptError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


def worker_main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("script", type=Path)
    for key in ("input-dir", "output-dir", "result", "progress", "permit"):
        parser.add_argument("--"+key, type=Path, required=True)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--memory-mb", type=int, required=True)
    options = parser.parse_args(arguments)
    deadline = time.monotonic()+15
    while not options.permit.is_file():
        if time.monotonic() > deadline:
            return 3
        time.sleep(0.02)
    try:
        from core.script_process import child_limits
        child_limits(options.memory_mb)
        program = Program.read(options.script)
        from core.script_runtime import Interpreter
        from core.script_safety import FilePolicy
        from core import project_io
        from jasc_api import Session
        workspace = project_io.load_project(options.project) if options.project else None
        def report(step: int, label: str) -> None:
            temporary = options.progress.with_suffix(".tmp")
            try:
                temporary.write_text(json.dumps({"step": step, "label": label}), encoding="utf-8")
                temporary.replace(options.progress)
            except OSError:
                # Windows can briefly hold the previous file open in the reader.
                # A missed progress update must never fail a scientific command.
                pass
        session = Session(workspace)
        Interpreter(session, FilePolicy(options.input_dir, options.output_dir), report).run(program)
        session.save_project(options.result)
        return 0
    except Exception as exc:
        try:
            options.progress.write_text(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), encoding="utf-8")
        except OSError:
            pass
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
