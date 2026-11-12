"""Build the one-folder Windows app without changing PowerShell execution policy."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Build JASC GUI and command-line executables")
    parser.add_argument("--tools", type=Path, help="Optional local PyInstaller installation directory")
    options = parser.parse_args()
    root = Path(__file__).resolve().parent
    artifacts = root/"artifacts"
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                       PYINSTALLER_CONFIG_DIR=str(artifacts/"pyinstaller_cache"),
                       MPLCONFIGDIR=str(artifacts/"pyinstaller_cache"/"matplotlib"))
    # An unactivated Conda interpreter does not expose its native runtime DLLs
    # through PATH. Include them for dependency discovery, never at playback.
    conda_bin = Path(sys.prefix)/"Library"/"bin"
    if conda_bin.is_dir():
        environment["PATH"] = str(conda_bin)+os.pathsep+environment.get("PATH", "")
    if options.tools:
        environment["PYTHONPATH"] = str(options.tools.resolve(strict=True))
    command = [sys.executable, "-B", "-m", "PyInstaller", "--noconfirm", "--distpath", str(artifacts/"standalone"),
               "--workpath", str(artifacts/"pyinstaller_build"), str(root/"JASC.spec")]
    result = subprocess.run(command, cwd=root, env=environment)
    if result.returncode == 0:
        print("Build ready: artifacts/standalone/JASC/JASC.exe and JASC-cli.exe")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
