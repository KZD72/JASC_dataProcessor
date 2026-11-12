"""Build a deterministic Linux source/dependency installer on any host platform."""
from __future__ import annotations

import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED


SHELL_HEADER = '''#!/bin/sh
# JASC Python-based Linux installer. No sudo or system-Python changes.
set -eu
if [ -n "${JASC_PYTHON:-}" ]; then
    jasc_python=$JASC_PYTHON
else
    jasc_python=
    for jasc_candidate in python3.12 python3.11 python3.10 python3 python; do
        if command -v "$jasc_candidate" >/dev/null 2>&1 &&
           "$jasc_candidate" -I -B -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            jasc_python=$jasc_candidate
            break
        fi
    done
fi
if [ -z "$jasc_python" ]; then
    printf '%s\\n' 'JASC needs Python 3.10-3.12 with venv/pip. Set JASC_PYTHON to its interpreter path.' >&2
    exit 1
fi
"$jasc_python" -I -B - "$0" "$@" <<'JASC_INSTALLER_PYTHON'
'''


def safe_source(root: Path, path: Path) -> Path:
    """Do not follow links/junctions or package files outside the chosen checkout."""
    path.relative_to(root)
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise ValueError(f"Release sources cannot be links/junctions: {part}")
    path.resolve(strict=True).relative_to(root)
    return path


def files_below(root: Path, directory: Path, *, python_only: bool = False) -> list[Path]:
    """Walk only explicit release directories, rejecting linked directories before entry."""
    safe_source(root, directory)
    result = []
    for current, directories, names in os.walk(directory, followlinks=False):
        for name in directories:
            safe_source(root, Path(current)/name)
        directories[:] = [name for name in directories if name != "__pycache__"]
        for name in names:
            path = Path(current)/name
            if name.endswith(".pyc") or (python_only and path.suffix != ".py"):
                continue
            result.append(safe_source(root, path))
    return result


def release_sources(root: Path) -> dict[str, bytes]:
    """Include application and curated examples; exclude user projects, keys and run outputs."""
    root = root.resolve(strict=True)
    paths = [root/name for name in ("main.py", "jasc_api.py", "requirements.txt", "README.md",
                                    "JASC_Manual.pdf", "LINUX_INSTALL.txt", "LICENSE", "resources/logo.png")]
    for name in ("core", "math_engine", "models", "ui"):
        paths.extend(files_below(root, root/name, python_only=True))
    examples = root/"Test_Data"/"Feature_Examples"
    paths.extend(examples/name for name in ("README.txt", "catalog.json", "generate_data.py"))
    paths.extend(files_below(root, examples/"generators", python_only=True))
    catalog = json.loads(safe_source(root, examples/"catalog.json").read_text(encoding="utf-8"))
    for family in catalog["families"]:
        directory = examples/family["directory"]
        paths.extend(directory/name for name in ("README.txt", "expected.json"))
        if family["macro"]:
            paths.append(directory/family["macro"])
        paths.extend(files_below(root, directory/"input"))
        preview = directory/"comparison_preview.png"
        if preview.is_file():
            paths.append(preview)
    macro = root/"Test_Data"/"Macro_Example"
    paths.extend(macro/name for name in ("README.txt", "process_spectra.py", "generate_data.py", "expected_truth.json", "comparison_preview.png"))
    paths.extend(files_below(root, macro/"input"))
    paths.append(root/"Test_Data"/"README.txt")
    paths.extend(root/"Test_Data"/name for name in ("SurfaceMap_README.txt", "SurfaceMap_RegularGrid.csv", "SurfaceMap_Irregular.csv"))
    return {path.relative_to(root).as_posix(): safe_source(root, path).read_bytes() for path in sorted(set(paths))}


def build_installer(root: Path, output: Path, version: str = "0.1.0") -> Path:
    """Write one self-extracting .sh with deterministic ZIP content and a checksum sidecar."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,50}", version):
        raise ValueError("Use a simple release version without path characters.")
    sources = release_sources(root)
    manifest = {"version": version, "kind": "linux-python-installer", "python": ">=3.10,<3.13",
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in sources.items()}}
    sources["jasc-release.json"] = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(sources.items()):
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data)
    payload = buffer.getvalue()
    bootstrap = (Path(__file__).parent/"linux_installer.py").read_text(encoding="utf-8")
    bootstrap = bootstrap.replace("@JASC_PAYLOAD_SHA256@", hashlib.sha256(payload).hexdigest())
    header = (SHELL_HEADER + bootstrap + "\nJASC_INSTALLER_PYTHON\nexit 0\n__JASC_ARCHIVE_FOLLOWS__\n").encode("utf-8")
    output.mkdir(parents=True, exist_ok=True)
    installer = output/f"JASC-Linux-{version}.sh"
    installer.write_bytes(header + payload)
    installer.chmod(0o755)
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    installer.with_suffix(".sh.sha256").write_text(f"{digest}  {installer.name}\n", encoding="ascii")
    return installer
