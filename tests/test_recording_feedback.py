"""Recording feedback remains visible and does not intercept application input."""

import gc
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from ui.main_window import MainWindow
from ui.theme import stylesheet


class RecordingFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()
        self.window.resize(1100, 780)
        self.window.show()
        self.app.processEvents()
        self.controller = self.window._macros
        self.feedback = self.controller.recording_feedback

    def tearDown(self) -> None:
        with patch.object(self.window, "_confirm_project_plot_changes", return_value=True):
            self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()

    def test_badge_persists_mouse_passes_through_and_stop_clears_feedback(self) -> None:
        self.assertFalse(self.feedback.active)
        self.assertTrue(self.feedback.badge.isHidden())
        self.assertTrue(self.feedback.border.isHidden())
        self.controller.start_recording(name="Visible recording")
        self.app.processEvents()
        self.assertTrue(self.feedback.active)
        self.assertTrue(self.feedback.badge.isVisible())
        self.assertTrue(self.feedback.border.isVisible())
        self.assertIn(".py", self.feedback.label.text())
        self.window.statusBar().showMessage("Another operation completed")
        self.app.processEvents()
        self.assertTrue(self.feedback.badge.isVisible())

        clicked = []
        button = QPushButton("Input target", self.window)
        button.setGeometry(420, 160, 150, 40)
        button.clicked.connect(lambda: clicked.append(True))
        button.show()
        self.app.processEvents()
        point = button.mapToGlobal(button.rect().center())
        target = self.app.widgetAt(point)
        self.assertIs(target, button)
        QTest.mouseClick(target, Qt.LeftButton)
        self.assertEqual(clicked, [True])

        stop = self.feedback.stop_button
        # Large test windows can extend beyond the offscreen platform's virtual
        # screen, where global widgetAt() returns None despite a visible control.
        self.assertTrue(stop.isVisible())
        self.assertTrue(self.window.rect().contains(stop.mapTo(self.window, stop.rect().center())))
        QTest.mouseClick(stop, Qt.LeftButton)
        self.assertIsNone(self.controller.recorder)
        self.assertFalse(self.feedback.active)
        self.assertTrue(self.feedback.badge.isHidden())
        self.assertTrue(self.feedback.border.isHidden())

    def test_border_tracks_resize_and_is_red_in_light_and_dark_palettes(self) -> None:
        self.controller.start_recording(name="Palette recording")
        for background in ("#ffffff", "#20252c"):
            palette = QPalette(self.window.palette())
            palette.setColor(QPalette.Window, QColor(background))
            # MainWindow normally follows the application palette. Scope this
            # test's theme to its own window without repolishing other fixtures.
            with patch.object(self.window, "_apply_visual_style"):
                self.window.setPalette(palette)
                self.window.setStyleSheet(stylesheet(palette, dark=background != "#ffffff"))
            self.window.resize(1150 if background == "#ffffff" else 1050, 800)
            self.app.processEvents()
            self.assertEqual(self.feedback.border.geometry(), self.window.rect())
            image = self.window.grab().toImage()
            ratio = image.devicePixelRatio()
            color = image.pixelColor(int(ratio), int(image.height()/2))
            self.assertGreater(color.red(), color.green()+60)
            self.assertGreater(color.red(), color.blue()+60)
        self.controller.stop_recording()
        self.assertTrue(self.feedback.border.isHidden())

    def test_cancelled_start_and_cancelled_save_do_not_leave_a_false_indicator(self) -> None:
        with patch("ui.macro_controller.QInputDialog.getText", return_value=("", False)):
            self.controller.start_recording()
        self.assertFalse(self.feedback.active)
        self.controller.start_recording(name="Save cancels")
        with patch("ui.macro_controller.QFileDialog.getSaveFileName", return_value=("", "")):
            self.assertFalse(self.controller.save_api_script())
        self.assertIsNone(self.controller.recorder)
        self.assertFalse(self.feedback.active)


if __name__ == "__main__":
    unittest.main()
