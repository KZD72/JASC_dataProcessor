"""Opt-in smoke tests against the real Windows bundle, with no Python in PATH."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from core import project_io


@unittest.skipUnless(os.environ.get("JASC_TEST_BUNDLE"), "Set JASC_TEST_BUNDLE to test a built Windows distribution")
class StandaloneScriptTests(unittest.TestCase):
    def setUp(self):
        self.root_owner = tempfile.TemporaryDirectory()
        self.root = Path(self.root_owner.name)
        self.addCleanup(self.root_owner.cleanup)
        self.bundle = Path(os.environ["JASC_TEST_BUNDLE"]).resolve()
        self.environment = dict(os.environ, PATH=str(Path(os.environ["WINDIR"])/"System32"),
                                PYTHONHOME=str(self.root/"no-python"), PYTHONPATH=str(self.root/"hostile"),
                                QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1")

    def run_exe(self, name: str, *arguments: str):
        return subprocess.run([str(self.bundle/name), *arguments], cwd=self.root, env=self.environment,
                              capture_output=True, text=True, timeout=60,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    def test_gui_bundle_constructs_and_closes_without_external_python(self):
        result = self.run_exe("JASC.exe", "--self-test")
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_both_entry_points_replay_data_and_export_a_real_figure(self):
        script = self.root/"recording.py"
        script.write_text('from jasc_api import Session, series, launch_recording\n\ndef run(session):\n'
            '    sheet = session.new_sheet(name="sample", rows=3)\n'
            '    session.edit(sheet, operation="fill_range", parameters={"target_column":"x","start_row":1,"count":3,"start_value":0.0,"step":1.0})\n'
            '    session.formula(sheet, output_column="y", expression="col(\'x\')*3+2")\n'
            '    fit = session.fit(sheet, x_column="x", y_column="y", model_key="linear", method="trf")\n'
            '    plot = session.plot([series(x=(sheet,"x"), y=(sheet,"y"))], name="Example")\n'
            '    session.export_plot(plot, "figure.png")\n'
            '\nif __name__ == "__main__":\n    launch_recording(__file__)\n', encoding="utf-8")
        for executable in ("JASC.exe", "JASC-cli.exe"):
            with self.subTest(executable=executable):
                output = self.root/(executable+".jasc")
                result = self.run_exe(executable, "--run-script", str(script), "--output", str(output))
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                workspace = project_io.load_project(output)
                self.assertEqual(workspace.get_dataset("sample").frame.y.tolist(), [2., 5., 8.])
                self.assertAlmostEqual(workspace.get_dataset("sample_fit").frame.fit_y.iloc[-1], 8., places=5)
        self.assertEqual(len(list(self.root.glob("jasc_script_run_*/figure.png"))), 2)

    def test_both_entry_points_reject_code_injection_without_a_marker_file(self):
        script = self.root/"malicious.py"
        marker = self.root/"executed.txt"
        script.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\ndef run(session):\n    pass\n", encoding="utf-8")
        for executable in ("JASC.exe", "JASC-cli.exe"):
            with self.subTest(executable=executable):
                result = self.run_exe(executable, "--run-script", str(script))
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(marker.exists())
        self.assertFalse((self.root/"jasc_script_outputs").exists())


if __name__ == "__main__":
    unittest.main()
