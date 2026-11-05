"""Real Qt wheel dispatch and Matplotlib mouse navigation regressions."""

from __future__ import annotations

from dataclasses import replace
import gc
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matplotlib.backend_bases import MouseButton, MouseEvent
import numpy as np
import pandas as pd
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

from core.workspace import Workspace
from ui.plot_canvas import PlotCanvas, PlotSeries


class PlotNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.workspace = Workspace()
        self.data = self.workspace.add_dataset("signal", pd.DataFrame({"x": [0., 5., 10.], "y": [1., 4., 2.]}))
        self.series = PlotSeries("signal", "x", "signal", "y")
        self.widget = PlotCanvas()
        self.widget.resize(750, 550)
        self.widget.show()
        self.widget.plot_series(self.workspace, [self.series], x_label="Time", y_label="Signal")
        self.axes = self.widget.axes
        self.axes.set_xlim(0, 10)
        self.axes.set_ylim(0, 10)
        self.widget.canvas.draw()

    def tearDown(self) -> None:
        self.widget._mouse_navigation.reset()
        self.widget.close()
        self.widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()

    def point(self, region: str = "center") -> tuple[float, float]:
        box = self.axes.bbox
        if region == "x":
            return (box.x0 + box.x1) / 2, box.y0 - 4
        if region == "y":
            return box.x0 - 4, (box.y0 + box.y1) / 2
        if region == "right":
            return box.x1 + 4, (box.y0 + box.y1) / 2
        return (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2

    def mouse(self, name: str, point: tuple[float, float], **kwargs: object) -> None:
        event = MouseEvent(name, self.widget.canvas, *point, **kwargs)
        self.widget.canvas.callbacks.process(name, event)

    def wheel(self, point: tuple[float, float], modifiers: Qt.KeyboardModifier = Qt.NoModifier,
              delta: int = 120) -> QWheelEvent:
        canvas = self.widget.canvas
        ratio = canvas.device_pixel_ratio
        local = QPointF(point[0] / ratio, (canvas.figure.bbox.height - point[1]) / ratio)
        event = QWheelEvent(local, canvas.mapToGlobal(local.toPoint()), QPoint(), QPoint(0, delta),
                            Qt.NoButton, modifiers, Qt.NoScrollPhase, False)
        QApplication.sendEvent(canvas, event)
        return event

    def test_wheel_zoom_axes_and_interior_through_real_qt_events(self) -> None:
        for region, directions in (("x", {"x"}), ("y", {"y"}), ("center", {"x", "y"})):
            with self.subTest(region=region):
                self.axes.set_xlim(0, 10)
                self.axes.set_ylim(0, 10)
                event = self.wheel(self.point(region))
                self.assertTrue(event.isAccepted())
                for axis in ("x", "y"):
                    limits = getattr(self.axes, f"get_{axis}lim")()
                    self.assertAlmostEqual(limits[1] - limits[0], 10 / 1.2 if axis in directions else 10.)

    def test_shift_wheel_pans_only_targeted_axes(self) -> None:
        for region, directions in (("x", {"x"}), ("y", {"y"}), ("center", {"x", "y"})):
            self.axes.set_xlim(0, 10)
            self.axes.set_ylim(0, 10)
            self.wheel(self.point(region), Qt.ShiftModifier)
            for axis in ("x", "y"):
                limits = getattr(self.axes, f"get_{axis}lim")()
                np.testing.assert_allclose(limits, (1., 11.) if axis in directions else (0., 10.))

    def test_zoom_anchor_reversibility_and_inverted_axes(self) -> None:
        point = self.axes.transData.transform((2., 7.))
        self.wheel(point)
        # Matplotlib quantizes mouse events to physical pixels.
        np.testing.assert_allclose(self.axes.transData.transform((2., 7.)), point, atol=1.)
        self.wheel(point, delta=-120)
        np.testing.assert_allclose(self.axes.get_xlim(), (0., 10.), atol=1.e-12)
        np.testing.assert_allclose(self.axes.get_ylim(), (0., 10.), atol=1.e-12)
        self.axes.set_xlim(10, 0)
        self.wheel(self.point("x"))
        self.assertGreater(self.axes.get_xlim()[0], self.axes.get_xlim()[1])
        self.assertAlmostEqual(abs(np.diff(self.axes.get_xlim())[0]), 10 / 1.2)

    def test_log_zoom_and_pan_work_in_log_coordinates(self) -> None:
        self.axes.set_xscale("log")
        self.axes.set_xlim(1, 1000)
        self.widget.canvas.draw()
        self.wheel(self.point("x"))
        limits = np.log10(self.axes.get_xlim())
        self.assertAlmostEqual(limits[1] - limits[0], 3 / 1.2)
        self.wheel(self.point("x"), Qt.ShiftModifier)
        np.testing.assert_allclose(np.log10(self.axes.get_xlim()), limits + .25)
        self.assertGreater(self.axes.get_xlim()[0], 0)

    def test_axis_label_hit_testing_and_right_y_independence(self) -> None:
        self.widget.plot_series(self.workspace, [self.series, replace(self.series, y_axis="right")],
                                x_label="Time", y_label="Signal", right_y_label="Right response")
        self.axes = self.widget.axes
        right = self.widget.right_axes
        self.axes.set_xlim(0, 10)
        self.axes.set_ylim(0, 10)
        right.set_ylim(100, 200)
        self.widget.canvas.draw()
        box = self.axes.xaxis.label.get_window_extent()
        self.wheel(((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2))
        self.assertLess(np.diff(self.axes.get_xlim())[0], 10)
        np.testing.assert_allclose(self.axes.get_ylim(), (0, 10))
        self.wheel(self.point("right"))
        self.assertLess(np.diff(right.get_ylim())[0], 100)
        np.testing.assert_allclose(self.axes.get_ylim(), (0, 10))
        self.wheel(self.point("center"))
        self.assertLess(np.diff(self.axes.get_ylim())[0], 10)
        self.assertLess(np.diff(right.get_ylim())[0], 100 / 1.2)

    def test_middle_drag_targets_axes_and_tracks_motion_outside_plot(self) -> None:
        for region, directions in (("x", {"x"}), ("y", {"y"}), ("center", {"x", "y"})):
            self.axes.set_xlim(0, 10)
            self.axes.set_ylim(0, 10)
            point = self.point(region)
            self.mouse("button_press_event", point, button=MouseButton.MIDDLE)
            self.mouse("motion_notify_event", (point[0] + 40, point[1] + 30), buttons={MouseButton.MIDDLE})
            self.mouse("button_release_event", (point[0] + 40, point[1] + 30), button=MouseButton.MIDDLE)
            for axis in ("x", "y"):
                limits = getattr(self.axes, f"get_{axis}lim")()
                self.assertAlmostEqual(limits[1] - limits[0], 10.)
                self.assertEqual(limits[0] != 0., axis in directions)
            self.assertFalse(self.widget._mouse_navigation._drag)

    def test_toolbar_history_supports_wheel_and_middle_drag(self) -> None:
        self.wheel(self.point())
        zoomed = self.axes.get_xlim()
        self.widget.toolbar.back()
        np.testing.assert_allclose(self.axes.get_xlim(), (0., 10.))

        self.widget.toolbar.forward()
        np.testing.assert_allclose(self.axes.get_xlim(), zoomed)
        point = self.point()
        self.mouse("button_press_event", point, button=2)
        self.mouse("motion_notify_event", (point[0] + 30, point[1] + 30), buttons={MouseButton.MIDDLE})
        self.mouse("button_release_event", point, button=2)
        self.widget.toolbar.back()
        np.testing.assert_allclose(self.axes.get_xlim(), zoomed)
        self.widget.toolbar.home()
        np.testing.assert_allclose(self.axes.get_xlim(), (0., 10.))

    def test_wheel_bursts_do_not_add_duplicate_history_entries(self) -> None:
        self.wheel(self.point())
        self.widget._mouse_navigation.finish()
        first = self.axes.get_xlim()
        self.wheel(self.point())
        self.widget._mouse_navigation.finish()
        self.widget.toolbar.back()
        np.testing.assert_allclose(self.axes.get_xlim(), first)
        self.widget.toolbar.back()
        np.testing.assert_allclose(self.axes.get_xlim(), (0., 10.))

    def test_cut_selection_locks_and_colourbars_ignore_wheel(self) -> None:
        self.widget._surface_cut_pick_active = True
        self.wheel(self.point())
        np.testing.assert_allclose(self.axes.get_xlim(), (0, 10))
        self.widget._surface_cut_pick_active = False
        lock = object()
        self.widget.canvas.widgetlock(lock)
        self.wheel(self.point())
        np.testing.assert_allclose(self.axes.get_xlim(), (0, 10))
        self.widget.canvas.widgetlock.release(lock)
        image = self.axes.imshow(np.arange(9).reshape(3, 3), extent=(0, 10, 0, 10))
        bar = self.widget.figure.colorbar(image, ax=self.axes)
        self.widget.canvas.draw()
        box = bar.ax.bbox
        self.wheel(((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2))
        np.testing.assert_allclose(self.axes.get_xlim(), (0, 10))
        np.testing.assert_allclose(self.axes.get_ylim(), (0, 10))

    def test_rerender_discards_pending_gesture_and_releases_old_axes(self) -> None:
        self.wheel(self.point())
        self.widget.plot_series(self.workspace, [self.series])
        self.assertFalse(self.widget._mouse_navigation._wheel_timer.isActive())
        self.assertFalse(self.widget._mouse_navigation._drag)
        self.assertIsNone(self.widget.toolbar._nav_stack())
        QTest.qWait(280)
        self.assertIsNone(self.widget.toolbar._nav_stack())

    def test_navigation_does_not_scroll_containing_grid(self) -> None:
        scroll = QScrollArea()
        scroll.resize(400, 300)
        scroll.setWidget(self.widget)
        scroll.show()
        QTest.qWait(20)
        bar = scroll.verticalScrollBar()
        bar.setValue(30)
        position = bar.value()
        self.wheel(self.point())
        self.assertEqual(bar.value(), position)
        scroll.takeWidget()
        scroll.close()
        scroll.deleteLater()


if __name__ == "__main__":
    unittest.main()
