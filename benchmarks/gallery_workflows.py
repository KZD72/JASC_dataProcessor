"""Capture the additional feature families through the application's real controls."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

import pandas as pd
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from benchmarks.gallery_digitization import colour_dialog, curve_dialog
from benchmarks.gallery_experiments import create_experiments
from core import project_io
from core.script_language import Program
from core.script_runtime import Interpreter
from core.script_safety import FilePolicy
from jasc_api import Session
from ui.dialogs import SmoothingDialog, select_list_items
from ui.main_window import MainWindow


def capture_more(window: MainWindow, directory: Path,
                 capture: Callable[[QWidget, str], dict]) -> tuple[list[dict], dict]:
    """Capture extraction, recording, signal, spatial and statistics workflows."""
    images, checks = [], {}
    for prepare, filename in ((curve_dialog, "05-image-digitization.png"),
                               (colour_dialog, "06-heatmap-digitization.png")):
        dialog, evidence = prepare(directory / "digitization", window)
        images.append(capture(dialog, filename))
        imported, skipped = window._import_figure_results(dialog.extraction_results())
        if skipped or len(imported) != 1 or imported[0].figure_session is None:
            raise RuntimeError(f"The extracted worksheet was not imported with its session: {skipped}")
        checks.update(evidence)
        dialog.close()
        dialog.deleteLater()

    extras = create_experiments(Session(window._workspace))
    checks.update(extras.checks)
    manager = window._plot_tab_widget
    manager.flush()
    manager.set_workspace(window._workspace)
    window._refresh_dataset_list(extras.signal.name)
    window._refresh_plot_list()
    window._tabs.setCurrentWidget(manager)
    window._workspace_nav_tabs.setCurrentWidget(window._plot_nav_page)
    for plot, filename in ((extras.signal_plot, "09-signal-processing.png"),
                            (extras.map_plot, "10-maps-and-profiles.png"),
                            (extras.statistics_plot, "11-statistics.png")):
        manager.open_plot(plot.name)
        manager._active_editor.set_plot_options_visible(False)
        window.resize(1880, 1080)
        images.append(capture(window, filename))

    window._refresh_dataset_list(extras.signal.name)
    initial_workspace = deepcopy(window._workspace)
    controller = window._macros
    controller.start_recording(name="Signal processing workflow")
    smoothing = SmoothingDialog(extras.signal.frame, list(extras.signal.frame), "time_s",
                                 window._workspace.dataset_names(), extras.signal.name, window)
    select_list_items(smoothing._y_column_list, ["measured"])
    smoothing._method_combo.setCurrentIndex(smoothing._method_combo.findData("savgol"))
    smoothing._window_spin.setValue(21)
    smoothing._polynomial_spin.setValue(3)
    smoothing._target_edit.setText("recorded_smooth")
    smoothing._plot_result_checkbox.setChecked(True)
    window._run_smoothing_batch(extras.signal, smoothing)
    smoothing.deleteLater()
    if "recorded_smooth" not in extras.signal.frame:
        raise RuntimeError("The recorded GUI smoothing action produced no result.")
    plot_editor = manager._active_editor
    plot_editor._title_edit.setText("Record and replay a signal workflow")
    plot_editor._x_label_edit.setText("Time (s)")
    plot_editor._y_label_edit.setText("Signal (V)")
    plot_editor._render_plot()
    manager._active_editor.set_plot_options_visible(False)
    window.resize(1660, 1040)
    images.append(capture(window, "07-macro-recording.png"))

    controller.view_api_calls()
    editor = controller._api_view()
    editor.setFont(QFont("DejaVu Sans Mono", 10))
    editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
    editor.window().resize(1420, 960)
    images.append(capture(editor.window(), "08-recorded-api-calls.png"))
    editor.window().close()
    controller.stop_recording()
    recording = controller.api_recording
    if recording.issues:
        raise RuntimeError(f"The real GUI recording contains unsupported actions: {recording.issues}")
    script = directory / "recording.py"
    recording.save(script)
    controller._saved_api_source = recording.source()
    replay = Session(initial_workspace)
    replay_directory = directory / "replay"
    replay_directory.mkdir(exist_ok=True)
    Interpreter(replay, FilePolicy(directory, replay_directory)).run(Program.parse(recording.source()))
    pd.testing.assert_series_equal(
        replay.sheet(extras.signal.name).frame["recorded_smooth"], extras.signal.frame["recorded_smooth"],
    )
    checks["gui_recording_replayed"] = True
    checks["recorded_smoothing_rows"] = len(extras.signal.frame)
    manager.flush()
    project_io.save_project(window._workspace, directory / "demo.jasc")
    manager.mark_saved()
    images.sort(key=lambda entry: entry["file"])
    return images, checks
