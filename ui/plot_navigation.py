"""Pointer-aware wheel zoom, wheel pan, and middle-button dragging."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from matplotlib.axes import Axes
from matplotlib.backend_bases import MouseButton, MouseEvent
import numpy as np
from PySide6.QtCore import QEvent, QObject, Qt, QTimer

if TYPE_CHECKING:
    from ui.plot_canvas import PlotCanvas


@dataclass
class _PanAxis:
    axes: Axes
    direction: str
    limits: np.ndarray
    origin: float
    pixels: float


class PlotMouseNavigation(QObject):
    """Navigate in scale coordinates, preserving log scales and axis direction.

    The Qt filter normalizes wheel/trackpad deltas and consumes gestures over
    plots so a containing scroll area does not also scroll. Matplotlib callbacks
    also support synthetic scroll events and middle-button drag outside axes.
    """

    def __init__(self, owner: PlotCanvas) -> None:
        super().__init__(owner)
        self.owner = owner
        self.canvas = owner.canvas
        self._drag: list[_PanAxis] = []
        self._wheeling = False
        self._wheel_timer = QTimer(self)
        self._wheel_timer.setSingleShot(True)
        self._wheel_timer.setInterval(250)
        self._wheel_timer.timeout.connect(self.finish)
        self.canvas.installEventFilter(self)
        for name, callback in (("scroll_event", self.scroll), ("button_press_event", self.press),
                               ("motion_notify_event", self.motion), ("button_release_event", self.release),
                               ("figure_leave_event", self.release), ("key_press_event", self.key_press)):
            self.canvas.mpl_connect(name, callback)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.canvas and event.type() == QEvent.Wheel:
            angle = event.angleDelta().y()
            step = angle / 120 if angle else event.pixelDelta().y() / 60
            scroll = MouseEvent("scroll_event", self.canvas, *self.canvas.mouseEventCoords(event),
                                step=step, modifiers=self.canvas._mpl_modifiers(event.modifiers()), guiEvent=event)
            if self.scroll(scroll):
                event.accept()
            else:
                event.ignore()
            return True
        return super().eventFilter(watched, event)

    def _available(self) -> bool:
        toolbar = self.owner.toolbar
        return (self.owner.axes.axison and not self.owner._surface_cut_pick_active
                and self.canvas.widgetlock.available(toolbar)
                and getattr(toolbar, "_pan_info", None) is None
                and getattr(toolbar, "_zoom_info", None) is None)

    def targets(self, event: object) -> list[tuple[Axes, str]]:
        """Hit-test the plot interior, ticks, labels, and axis spines in display pixels."""
        axes, right = self.owner.axes, self.owner.right_axes
        if not self._available():
            return []
        x, y = getattr(event, "x", None), getattr(event, "y", None)
        if x is None or y is None or not np.isfinite([x, y]).all():
            return []
        # Colour bars are separate axes: never interpret them as a Y-axis strip.
        if getattr(event, "inaxes", None) not in (None, axes, right):
            return []
        bounds = axes.bbox
        renderer = self.canvas.get_renderer()
        padding = 6 * self.canvas.device_pixel_ratio
        x_band = axes.xaxis.get_tightbbox(renderer)
        left_band = axes.yaxis.get_tightbbox(renderer)
        right_band = right.yaxis.get_tightbbox(renderer) if right is not None else None
        if bounds.x0 - padding <= x <= bounds.x1 + padding:
            if (abs(y - bounds.y0) <= padding
                    or (x_band is not None and x_band.y0 - padding <= y < bounds.y0)):
                return [(axes, "x")]
        if bounds.y0 - padding <= y <= bounds.y1 + padding:
            if (abs(x - bounds.x0) <= padding
                    or (left_band is not None and left_band.x0 - padding <= x < bounds.x0)):
                return [(axes, "y")]
            if right is not None and (abs(x - bounds.x1) <= padding
                    or (right_band is not None and bounds.x1 < x <= right_band.x1 + padding)):
                return [(right, "y")]
        if bounds.contains(x, y):
            targets = [(axes, "x"), (axes, "y")]
            if right is not None:
                targets.append((right, "y"))
            return targets
        return []

    @staticmethod
    def _coordinates(axes: Axes, direction: str, limits: object) -> np.ndarray:
        axis = getattr(axes, f"{direction}axis")
        return np.asarray(axis.get_transform().transform(limits), dtype=float)

    @staticmethod
    def _apply(axes: Axes, direction: str, coordinates: np.ndarray) -> bool:
        axis = getattr(axes, f"{direction}axis")
        with np.errstate(over="ignore", invalid="ignore", under="ignore"):
            limits = np.asarray(axis.get_transform().inverted().transform(coordinates), dtype=float)
        if not np.isfinite(limits).all() or limits[0] == limits[1]:
            return False
        if axis.get_scale() == "log" and (limits <= 0).any():
            return False
        getattr(axes, f"set_{direction}lim")(limits)
        return True

    def scroll(self, event: object) -> bool:
        targets = self.targets(event)
        step = float(getattr(event, "step", 0))
        if not targets or not np.isfinite(step) or step == 0 or self._drag:
            return False
        modifiers = set(getattr(event, "modifiers", ()) or ())
        key = str(getattr(event, "key", "") or "")
        pan = "shift" in modifiers or "shift" in key.split("+")
        step = float(np.clip(step, -8, 8))
        if not self._wheeling:
            self._remember_view()
        for axes, direction in targets:
            limits = self._coordinates(axes, direction, getattr(axes, f"get_{direction}lim")())
            if pan:
                updated = limits + step * .1 * (limits[1] - limits[0])
            else:
                index = 0 if direction == "x" else 1
                anchor = axes.transData.inverted().transform((event.x, event.y))[index]
                anchor = self._coordinates(axes, direction, anchor)
                updated = anchor + (limits - anchor) * (1.2 ** -step)
            self._apply(axes, direction, updated)
        self._wheeling = True
        self._wheel_timer.start()
        self.canvas.draw_idle()
        return True

    def press(self, event: object) -> None:
        if getattr(event, "button", None) != MouseButton.MIDDLE or getattr(event, "dblclick", False):
            return
        targets = self.targets(event)
        if not targets:
            return
        self.finish()
        self._remember_view()
        for axes, direction in targets:
            limits = self._coordinates(axes, direction, getattr(axes, f"get_{direction}lim")())
            self._drag.append(_PanAxis(axes, direction, limits, event.x if direction == "x" else event.y,
                                      max(1., axes.bbox.width if direction == "x" else axes.bbox.height)))
        self.canvas.setCursor(Qt.ClosedHandCursor)

    def motion(self, event: object) -> None:
        if not self._drag:
            return
        buttons = getattr(event, "buttons", None)
        if buttons is not None and MouseButton.MIDDLE not in buttons:
            self.finish()
            return
        for target in self._drag:
            position = getattr(event, "x" if target.direction == "x" else "y", None)
            if position is None:
                continue
            shift = (position - target.origin) / target.pixels
            self._apply(target.axes, target.direction,
                        target.limits - shift * (target.limits[1] - target.limits[0]))
        self.canvas.draw_idle()

    def release(self, event: object) -> None:
        if self._drag and (getattr(event, "button", None) == MouseButton.MIDDLE
                           or getattr(event, "name", "") == "figure_leave_event"):
            self.finish()

    def key_press(self, event: object) -> None:
        if getattr(event, "key", None) == "escape":
            self.finish()

    def finish(self) -> None:
        self._wheel_timer.stop()
        if self._wheeling or self._drag:
            self._remember_view()
        self.reset()

    def _remember_view(self) -> None:
        toolbar = self.owner.toolbar
        previous = toolbar._nav_stack()
        if previous is None or any(axes not in previous or previous[axes][0] != axes._get_view()
                                   for axes in self.owner.figure.axes):
            toolbar.push_current()

    def reset(self) -> None:
        """Discard pending gesture state when a view is rerendered or released."""
        self._wheel_timer.stop()
        self._wheeling = False
        if self._drag:
            self.canvas.unsetCursor()
        self._drag.clear()
