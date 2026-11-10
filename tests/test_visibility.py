"""Contrast pairing and actual light/dark control-state rendering."""

from __future__ import annotations

import gc
import os
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QImage, QPalette
from PySide6.QtGui import QColor, QIcon
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleFactory

from benchmarks.theme_visibility_audit import gallery, palette_for, probe_colors
from ui.main_window import MainWindow
from ui.theme import contrast, readable_text, theme_colors


class VisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.isolated = os.environ.get("JASC_THEME_TEST_ISOLATED") == "1"
        if not self.isolated:
            self.standard = self.app.style().standardPalette()
            return
        self.original_palette = QPalette(self.app.palette())
        self.original_style = self.app.style().objectName()
        self.app.setStyle("Fusion")
        self.standard = self.app.style().standardPalette()
        self.window = None

    def tearDown(self) -> None:
        if not self.isolated:
            return
        if self.window is not None:
            with patch.object(self.window, "_confirm_project_plot_changes", return_value=True):
                self.window.close()
            self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.setStyle(self.original_style)
        self.app.setPalette(self.original_palette)
        gc.collect()

    def isolated_render(self) -> bool:
        # Application palette/style changes repaint all retained Qt fixtures in
        # the full suite. Exercise these global transitions in a fresh process.
        if self.isolated:
            return False
        environment = {**os.environ, "JASC_THEME_TEST_ISOLATED": "1", "QT_QPA_PLATFORM": "offscreen"}
        result = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests",
                                 "-p", "test_visibility.py", "-k", self._testMethodName],
                                env=environment, cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return True

    def test_semantic_text_pairs_and_control_boundaries_have_contrast(self) -> None:
        for profile in ("light", "dark", "mixed_dark"):
            colors = theme_colors(palette_for(profile, self.standard))
            for text, background in (("text", "window"), ("input_text", "base"), ("button_text", "button"),
                                     ("highlight_text", "highlight"), ("hover_text", "hover"),
                                     ("muted", "window"), ("disabled_text", "disabled_bg")):
                self.assertGreaterEqual(contrast(colors[text], colors[background]), 4.5, (profile, text))
            self.assertGreaterEqual(contrast(colors["border"], colors["base"]), 3.)
            self.assertGreaterEqual(contrast(colors["border"], colors["button"]), 3.)
        for grey in range(256):
            background = f"#{grey:02x}{grey:02x}{grey:02x}"
            self.assertGreaterEqual(contrast(background, readable_text(background)), 4.5)

    def test_checked_controls_are_distinct_in_all_audited_palettes_and_styles(self) -> None:
        if self.isolated_render():
            return
        for style in ("Fusion", "windowsvista"):
            if style not in QStyleFactory.keys():
                continue
            self.app.setStyle(style)
            for profile in ("light", "dark", "mixed_dark"):
                self.app.setPalette(palette_for(profile, self.standard))
                window = MainWindow()
                dialog, controls = gallery(window, f"{style}/{profile}")
                dialog.show()
                QTest.qWait(5)
                controls["choices"].setFocus()
                values = probe_colors(controls)
                self.assertFalse(values["toggle_off_on_raster_equal"], (style, profile))
                for control in ("button", "field", "checkbox"):
                    self.assertGreaterEqual(values["Unchecked"][control]["contrast_ratio"], 4.5, (style, profile, control))
                for disabled in (False, True):
                    off = controls["Disabled unchecked" if disabled else "Unchecked"]["checkbox"]
                    on = controls["Disabled checked" if disabled else "Checked"]["checkbox"]
                    first = off.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
                    second = on.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
                    self.assertNotEqual(bytes(first.constBits()), bytes(second.constBits()))
                dialog.close()
                dialog.deleteLater()
                with patch.object(window, "_confirm_project_plot_changes", return_value=True):
                    window.close()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_palette_changes_update_existing_controls_without_changing_plot_style(self) -> None:
        if self.isolated_render():
            return
        self.app.setPalette(self.standard)
        self.window = MainWindow()
        editor = self.window._plot_tab_widget._active_editor
        original_face = editor._plot_canvas.figure.get_facecolor()
        self.app.setPalette(palette_for("mixed_dark", self.standard))
        QTest.qWait(15)
        button = editor._copy_plot_button
        self.assertGreaterEqual(contrast(button.palette().color(QPalette.ButtonText), button.palette().color(QPalette.Button)), 4.5)
        self.assertEqual(editor._plot_canvas.figure.get_facecolor(), original_face)
        readout = editor._plot_canvas.coordinate_readout
        self.assertGreaterEqual(contrast(readout.palette().color(QPalette.WindowText), readout.palette().color(QPalette.Window)), 4.5)
        self.app.setPalette(self.standard)
        QTest.qWait(15)
        self.assertGreaterEqual(contrast(button.palette().color(QPalette.ButtonText), button.palette().color(QPalette.Button)), 4.5)

    def test_checked_navigation_icons_follow_high_contrast_highlight_foreground(self) -> None:
        if self.isolated_render():
            return
        palette = palette_for("dark", self.standard)
        palette.setColor(QPalette.Highlight, QColor("yellow"))
        palette.setColor(QPalette.HighlightedText, QColor("white"))
        self.app.setPalette(palette)
        self.window = MainWindow()
        toolbar = self.window._plot_tab_widget._active_editor._plot_canvas.toolbar
        icon = toolbar._actions["pan"].icon()
        image = icon.pixmap(toolbar.iconSize(), QIcon.Normal, QIcon.On).toImage()
        opaque = [image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height())
                  if image.pixelColor(x, y).alpha() > 220]
        self.assertTrue(opaque)
        self.assertTrue(all(contrast(color, "yellow") >= 3 for color in opaque))


if __name__ == "__main__":
    unittest.main()
