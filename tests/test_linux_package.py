"""Source-installer payload, POSIX invocation and non-destructive install contracts."""
from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from release_tools import linux_installer as bootstrap
from release_tools.linux_package import build_installer


ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which("sh") or (str(Path("C:/Program Files/Git/bin/bash.exe")) if Path("C:/Program Files/Git/bin/bash.exe").is_file() else None)


class LinuxPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.owner = tempfile.TemporaryDirectory()
        cls.root = Path(cls.owner.name)
        cls.package = build_installer(ROOT, cls.root/"release")
        cls.payload = cls.package.read_bytes().partition(bootstrap.MARKER)[2]
        cls.sha = hashlib.sha256(cls.payload).hexdigest()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.owner.cleanup()

    def test_release_is_reproducible_and_contains_curated_examples_without_private_files(self) -> None:
        other = build_installer(ROOT, self.root/"second")
        self.assertEqual(other.read_bytes(), self.package.read_bytes())
        data, manifest = bootstrap.package_contents(self.package, self.sha)
        self.assertEqual(manifest["python"], ">=3.10,<3.13")
        self.assertIn("ui/plot_colors.py", data)
        self.assertIn("ui/fit_report_dialog.py", data)
        self.assertIn("JASC_Manual.pdf", data)
        self.assertIn("resources/logo.png", data)
        self.assertIn("Test_Data/Feature_Examples/09_Asymmetric_Uncertainty/run_example.py", data)
        self.assertIn("Test_Data/Macro_Example/input/spectrum_01.csv", data)
        self.assertFalse(any("__pycache__" in name or name.startswith(("artifacts/", "tests/")) for name in data))
        self.assertFalse(any(name.endswith((".pyc", ".jasc", ".jascx", ".jasc-key", ".log")) for name in data))

    def test_corrupted_payload_is_rejected_before_extraction(self) -> None:
        corrupt = self.root/"corrupted.sh"
        data = bytearray(self.package.read_bytes())
        data[-1] ^= 1
        corrupt.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "checksum"):
            bootstrap.package_contents(corrupt, self.sha)

    def forged(self, name: str, *, symlink: bool = False, wrong_manifest: bool = False) -> tuple[Path, str]:
        buffer = BytesIO()
        content = b"sample"
        manifest = {"version": "0.1.0", "files": {name: "wrong" if wrong_manifest else hashlib.sha256(content).hexdigest()}}
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            info = ZipInfo(name)
            info.external_attr = ((stat.S_IFLNK if symlink else stat.S_IFREG) | 0o644) << 16
            archive.writestr(info, content)
            archive.writestr("jasc-release.json", json.dumps(manifest))
        payload = buffer.getvalue()
        path = self.root/"unsafe.sh"
        path.write_bytes(bootstrap.MARKER + payload)
        return path, hashlib.sha256(payload).hexdigest()

    def test_traversal_absolute_backslash_and_link_members_are_rejected(self) -> None:
        for name in ("../outside.txt", "/etc/outside", "C:/outside", "core/../outside", "core\\outside"):
            with self.subTest(name=name):
                self.assertFalse(bootstrap.safe_member_name(name))
                path, sha = self.forged(name)
                # ZipInfo normalizes Windows separators while writing; either the
                # unsafe name or the now-inconsistent member manifest must fail.
                with self.assertRaises(ValueError):
                    bootstrap.package_contents(path, sha)
        path, sha = self.forged("link", symlink=True)
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            bootstrap.package_contents(path, sha)

    def test_member_hash_mismatch_is_rejected(self) -> None:
        path, sha = self.forged("main.py", wrong_manifest=True)
        with self.assertRaisesRegex(ValueError, "member checksum"):
            bootstrap.package_contents(path, sha)

    def test_extraction_never_overwrites_existing_directories_or_escapes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)/"existing"
            target.mkdir()
            (target/"keep").write_text("original")
            with self.assertRaisesRegex(ValueError, "already exists"):
                bootstrap.extract_fresh({"main.py": b"replace"}, target)
            self.assertEqual((target/"keep").read_text(), "original")
            fresh = Path(temporary)/"fresh"
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                bootstrap.extract_fresh({"../escape": b"bad"}, fresh)
            self.assertFalse(fresh.exists())
            self.assertFalse((Path(temporary)/"escape").exists())

    @unittest.skipUnless(SHELL, "A POSIX shell is needed for the installer integration check")
    def test_real_shell_verifies_and_extracts_the_installer_with_quoted_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jasc linux space ") as temporary:
            target = Path(temporary)/"extracted sources"
            environment = dict(os.environ, JASC_PYTHON=sys.executable,
                               PYTHONHOME=str(target/"missing-home"), PYTHONPATH=str(target/"hostile"))
            for args in (("--verify",), ("--extract-only", str(target))):
                result = subprocess.run([SHELL, str(self.package), *args], env=environment,
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((target/"main.py").read_bytes(), (ROOT/"main.py").read_bytes())
            self.assertTrue((target/"Test_Data/Feature_Examples/catalog.json").is_file())
            result = subprocess.run([SHELL, str(self.package), "--extract-only", str(target)],
                                    env=environment, capture_output=True, text=True, timeout=60)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already exists", result.stderr)

    def test_install_preflight_refuses_non_linux_or_unsupported_python_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)/"not-created"
            with patch.object(bootstrap.sys, "platform", "win32"):
                with self.assertRaisesRegex(ValueError, "requires Linux"):
                    bootstrap.install({}, {}, destination)
            with patch.object(bootstrap.sys, "platform", "linux"), patch.object(bootstrap.sys, "version_info", (3, 13)):
                with self.assertRaisesRegex(ValueError, "3.10-3.12"):
                    bootstrap.install({}, {}, destination)
            self.assertFalse(destination.exists())

    @unittest.skipUnless(SHELL, "A POSIX shell is needed for launcher argument checks")
    def test_launcher_preserves_arguments_and_ignores_hostile_python_environment(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jasc launch space ") as temporary:
            root = Path(temporary)
            (root/"app").mkdir()
            (root/"venv/bin").mkdir(parents=True)
            interpreter = root/"venv/bin/python"
            quoted_python = "'" + sys.executable.replace("'", "'\\''") + "'"
            interpreter.write_text('#!/bin/sh\nexec ' + quoted_python + ' "$@"\n', encoding="utf-8", newline="\n")
            interpreter.chmod(0o755)
            (root/"app/main.py").write_text("import json,sys; print(json.dumps(sys.argv[1:]))", encoding="utf-8")
            launcher = root/"JASC"
            launcher.write_text(bootstrap.launcher_text(), encoding="utf-8", newline="\n")
            arguments = ["--run-script", "macro with spaces.py", "literal; printf injected"]
            environment = dict(os.environ, PYTHONHOME=str(root/"missing-home"), PYTHONPATH=str(root/"hostile"))
            result = subprocess.run([SHELL, str(launcher), *arguments], env=environment,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), arguments)

    def test_install_commands_are_isolated_and_launchers_follow_successful_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)/"JASC space"
            completed = subprocess.CompletedProcess([], 0, stdout="numpy==1.26.4\n", stderr="")
            with patch.object(bootstrap.sys, "platform", "linux"), patch.object(bootstrap.sys, "version_info", (3, 12)), \
                 patch.object(bootstrap.venv, "EnvBuilder") as builder, \
                 patch.object(bootstrap.subprocess, "run", return_value=completed) as run, redirect_stdout(StringIO()):
                bootstrap.install({"main.py": b"pass", "requirements.txt": b"numpy<2"}, {"version": "0.1.0"}, destination)
            builder.assert_called_once_with(with_pip=True)
            self.assertEqual(len(run.call_args_list), 3)
            self.assertIn("--only-binary=:all:", run.call_args_list[0].args[0])
            self.assertIn("--require-virtualenv", run.call_args_list[0].args[0])
            self.assertIn("--self-test", run.call_args_list[1].args[0])
            for name in ("JASC", "JASC-cli"):
                text = (destination/name).read_text()
                self.assertIn('"$jasc_root/venv/bin/python"', text)
                self.assertIn('"$@"', text)
                self.assertIn("unset PYTHONHOME PYTHONPATH", text)
            self.assertTrue((destination/"installed_requirements.txt").is_file())

    def test_failed_dependency_install_preserves_diagnostics_without_success_launchers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)/"failed"
            with patch.object(bootstrap.sys, "platform", "linux"), patch.object(bootstrap.sys, "version_info", (3, 12)), \
                 patch.object(bootstrap.venv, "EnvBuilder"), \
                 patch.object(bootstrap.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["pip"])), redirect_stdout(StringIO()):
                with self.assertRaisesRegex(RuntimeError, "Installation incomplete"):
                    bootstrap.install({"requirements.txt": b"missing"}, {"version": "0.1.0"}, destination)
            self.assertTrue((destination/"INSTALL_FAILED.txt").is_file())
            self.assertFalse((destination/"JASC").exists())
            self.assertTrue((destination/"app/requirements.txt").is_file())


if __name__ == "__main__":
    unittest.main()
