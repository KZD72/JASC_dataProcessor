"""Real GUI review/playback, child cancellation and stale-workspace protection."""
from __future__ import annotations

import gc
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pandas as pd
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.script_jobs import ScriptRequest, run_script
from tests.test_script_security import recording
from ui.main_window import MainWindow
from ui.script_dialog import ScriptDialog


class ScriptUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.window = MainWindow()
        self.source = self.window._workspace.add_dataset("source", pd.DataFrame({"x": [0., 1., 2.], "y": [1., 3., 5.]}))
        self.window._refresh_dataset_list("source")
        self.player = self.window._macros.script_player
        self.errors = []
        error = patch.object(self.player, "error", side_effect=self.errors.append)
        error.start()
        self.addCleanup(error.stop)

    def wait(self):
        limit = time.monotonic()+30
        while self.window._jobs.is_running and time.monotonic() < limit:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertFalse(self.window._jobs.is_running)

    def tearDown(self):
        self.window._jobs.cancel()
        self.wait()
        with patch.object(self.window, "_confirm_project_plot_changes", return_value=True):
            self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()

    def request(self, body="sheet = session.sheet('source')\nsession.formula(sheet, output_column='twice', expression='col(\"y\")*2')"):
        return ScriptRequest(recording(body), self.root, self.root/"outputs")

    def test_review_rejects_hostile_scripts_and_keeps_source_read_only(self):
        path = self.root/"recording.py"
        path.write_text(recording("session.new_sheet(rows=2)"), encoding="utf-8")
        dialog = ScriptDialog(self.window)
        try:
            dialog.load(path)
            self.assertTrue(dialog.run_button.isEnabled())
            self.assertTrue(dialog.preview.isReadOnly())
            self.assertEqual(dialog.request().source, path.read_bytes().decode("utf-8"))
            path.write_text("import os\n"+recording("pass"), encoding="utf-8")
            # The reviewed bytes are immutable even if the source file changes.
            self.assertNotIn("import os", dialog.request().source)
            dialog.load(path)
            self.assertFalse(dialog.run_button.isEnabled())
            self.assertIsNone(dialog.program)
        finally:
            dialog.deleteLater()

    def test_unsafe_script_is_rejected_before_starting_a_job(self):
        original = self.window._workspace
        self.assertFalse(self.player.start(self.request("session.new_sheet()\nopen('bad', 'w')")))
        self.assertFalse(self.window._jobs.is_running)
        self.assertIs(self.window._workspace, original)
        self.assertFalse((self.root/"outputs").exists())
        self.assertTrue(self.errors)

    def test_real_gui_run_publishes_complete_workspace_plot_and_exports(self):
        original = self.window._workspace
        body = "sheet = session.sheet('source')\nsession.formula(sheet, output_column='twice', expression='col(\"y\")*2')\nplot = session.plot([series(x=(sheet,'x'),y=(sheet,'twice'))], name='Processed')\nsession.export_plot(plot, 'figure.png')\nsession.export_data(sheet, 'data.csv')"
        self.assertTrue(self.player.start(self.request(body)))
        self.wait()
        self.assertEqual(self.errors, [])
        self.assertIsNot(self.window._workspace, original)
        self.assertNotIn("twice", self.source.frame)
        self.assertEqual(self.window._workspace.get_dataset("source").frame.twice.tolist(), [2., 6., 10.])
        folders = list((self.root/"outputs").glob("jasc_script_run_*"))
        self.assertEqual(len(folders), 1)
        for name in ("figure.png", "data.csv", "_jasc_result.jasc", "_jasc_run.json"):
            self.assertTrue((folders[0]/name).is_file(), name)
        self.assertTrue(self.window._macro_outputs_dirty)
        self.assertTrue(self.player.action.isEnabled())

    def test_stale_workspace_discards_every_staged_result(self):
        original = self.window._workspace
        self.assertTrue(self.player.start(self.request()))
        self.source.frame.loc[0, "y"] = 100.
        self.wait()
        self.assertIs(self.window._workspace, original)
        self.assertNotIn("twice", self.source.frame)
        self.assertEqual(list((self.root/"outputs").iterdir()), [])
        self.assertEqual(self.errors, [])

    def test_late_cancel_discards_completed_child_before_gui_publication(self):
        original = self.window._workspace
        def cancel_after_child(*args, **kwargs):
            result = run_script(*args, **kwargs)
            self.window._jobs.cancel()
            return result
        with patch("ui.script_controller.run_script", side_effect=cancel_after_child):
            self.assertTrue(self.player.start(self.request()))
            self.wait()
        self.assertIs(self.window._workspace, original)
        self.assertEqual(list((self.root/"outputs").iterdir()), [])
        self.assertIsNone(self.player.progress)

    def test_close_waits_for_child_and_keeps_original_workspace(self):
        original = self.window._workspace
        self.assertTrue(self.player.start(self.request()))
        with patch.object(self.window, "_confirm_project_plot_changes", return_value=True):
            self.window.close()
        self.assertTrue(self.window._closing_when_idle)
        self.wait()
        self.assertIs(self.window._workspace, original)
        self.assertNotIn("twice", self.source.frame)
        output = self.root/"outputs"
        self.assertFalse(output.exists() and list(output.iterdir()))
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
