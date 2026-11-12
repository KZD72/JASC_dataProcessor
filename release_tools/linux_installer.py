"""Standard-library bootstrap embedded into the self-extracting Linux installer."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import venv
from zipfile import ZipFile


EXPECTED_PAYLOAD_SHA256 = "@JASC_PAYLOAD_SHA256@"
MARKER = b"__JASC_ARCHIVE_" + b"FOLLOWS__\n"
MAX_UNPACKED_BYTES = 128 * 1024 * 1024


def safe_member_name(name: str) -> bool:
    return bool(name and "\\" not in name and ":" not in name and not PurePosixPath(name).is_absolute()
                and all(part not in {"", ".", ".."} for part in name.split("/")))


def package_contents(installer: Path, expected_sha256: str) -> tuple[dict[str, bytes], dict]:
    """Verify all content before writing, rejecting unsafe or ambiguous ZIP members."""
    _header, marker, payload = installer.read_bytes().partition(MARKER)
    if not marker or hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("Installer archive checksum failed; download/copy the release again.")
    with ZipFile(BytesIO(payload)) as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive members are not allowed.")
        if sum(member.file_size for member in members) > MAX_UNPACKED_BYTES:
            raise ValueError("Archive exceeds its extraction budget.")
        for member in members:
            name = member.filename
            if not safe_member_name(name) or member.is_dir() or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError(f"Unsafe archive member: {name!r}")
        contents = {member.filename: archive.read(member) for member in members}
    manifest = json.loads(contents.pop("jasc-release.json"))
    if not isinstance(manifest, dict) or set(manifest.get("files", {})) != set(contents):
        raise ValueError("Archive member manifest does not match its content.")
    for name, data in contents.items():
        if hashlib.sha256(data).hexdigest() != manifest["files"][name]:
            raise ValueError(f"Archive member checksum failed: {name}")
    version = manifest.get("version", "")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,50}", version):
        raise ValueError("Invalid release version.")
    return contents, manifest


def extract_fresh(contents: dict[str, bytes], destination: Path) -> None:
    """Write to a newly created directory and never overwrite an existing tree."""
    if not all(safe_member_name(name) for name in contents):
        raise ValueError("Unsafe extraction member.")
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"Destination already exists; choose a new directory: {destination}")
    destination.mkdir(parents=True, mode=0o700)
    for name, data in contents.items():
        path = destination.joinpath(*PurePosixPath(name).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)


def launcher_text() -> str:
    """Keep arguments intact and locate a non-relocatable environment beside the launcher."""
    return ('#!/bin/sh\nset -eu\n'
            'jasc_root=$(CDPATH= cd -P -- "$(dirname -- "$0")" && pwd)\n'
            'unset PYTHONHOME PYTHONPATH\n'
            'exec "$jasc_root/venv/bin/python" -E -s -B "$jasc_root/app/main.py" "$@"\n')


def install(contents: dict[str, bytes], manifest: dict, destination: Path) -> None:
    """Create one isolated user installation without privileged package-manager calls."""
    if sys.platform != "linux":
        raise ValueError("Installation requires Linux. --verify and --extract-only work without installing.")
    if not (3, 10) <= sys.version_info[:2] < (3, 13):
        raise ValueError("Use Python 3.10-3.12 (JASC_PYTHON=/path/to/python3.12); the NumPy <2 constraint is retained.")
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"Install directory already exists; choose a NEW --install-dir: {destination}")
    destination.mkdir(parents=True, mode=0o700)
    log_path = destination/"install.log"
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
        environment.pop(name, None)
    try:
        extract_fresh(contents, destination/"app")
        print(f"Creating isolated environment in {destination}", flush=True)
        venv.EnvBuilder(with_pip=True).create(destination/"venv")
        python = destination/"venv"/"bin"/"python"
        with log_path.open("w", encoding="utf-8") as log:
            print(f"Downloading binary dependencies; log: {log_path}", flush=True)
            subprocess.run([str(python), "-I", "-m", "pip", "--require-virtualenv", "install", "--disable-pip-version-check",
                            "--only-binary=:all:", "-r", str(destination/"app"/"requirements.txt")],
                           cwd=destination/"app", env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
            print("Checking application startup (offscreen)...", flush=True)
            subprocess.run([str(python), "-E", "-s", "-B", str(destination/"app"/"main.py"), "--self-test"],
                           cwd=destination/"app", env=environment, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
            frozen = subprocess.run([str(python), "-I", "-m", "pip", "freeze"],
                                    env=environment, capture_output=True, text=True, check=True)
        (destination/"installed_requirements.txt").write_text(frozen.stdout, encoding="utf-8")
        for name in ("JASC", "JASC-cli"):
            launcher = destination/name
            launcher.write_text(launcher_text(), encoding="utf-8", newline="\n")
            launcher.chmod(0o755)
        (destination/"installation.json").write_text(json.dumps({"version": manifest["version"],
            "python": sys.version, "installer_payload_sha256": EXPECTED_PAYLOAD_SHA256}, indent=2) + "\n", encoding="utf-8")
    except Exception as error:
        message = (f"Installation incomplete: {error}\nDirectory retained for inspection: {destination}\n"
                   f"Check {log_path} and Python venv/Qt/network prerequisites. Retry in a new directory.\n")
        (destination/"INSTALL_FAILED.txt").write_text(message, encoding="utf-8")
        raise RuntimeError(message) from error
    print(f"Installed. GUI: {destination/'JASC'}\nCommand line: {destination/'JASC-cli'}")


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="JASC Linux installer",
        description="Install JASC in a private Python 3.10-3.12 environment (internet and Qt host libraries required).")
    parser.add_argument("installer", type=Path, help=argparse.SUPPRESS)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--verify", action="store_true", help="Check the embedded archive without installing")
    actions.add_argument("--extract-only", type=Path, metavar="NEW_DIRECTORY", help="Extract sources only; no dependency download")
    parser.add_argument("--install-dir", type=Path, help="Fresh installation directory (default ~/.local/opt/JASC-VERSION)")
    options = parser.parse_args(arguments)
    try:
        contents, manifest = package_contents(options.installer, EXPECTED_PAYLOAD_SHA256)
        if options.verify:
            print(f"Verified JASC {manifest['version']}: {len(contents)} source/data files; dependency downloads not performed.")
        elif options.extract_only is not None:
            destination = options.extract_only.expanduser().absolute()
            extract_fresh(contents, destination)
            print(f"Extracted sources: {destination}")
        else:
            destination = options.install_dir or Path.home()/".local"/"opt"/f"JASC-{manifest['version']}"
            install(contents, manifest, destination.expanduser().absolute())
        return 0
    except Exception as error:
        print(f"JASC installer: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
