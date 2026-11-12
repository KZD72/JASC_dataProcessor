"""Public Python API for editable recordings and scripted JASC processing.

Numerical operations do not require a Qt application. Plot definitions are ordinary
project objects; map extraction and figure export load the Qt renderer lazily.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

from core import project_io
from core.file_io import ImportOptions, export_tabular_file
from core.import_jobs import inspect_text_files, prepare_text_files
from core.jobs import JobContext
from core.macro_jobs import folder_sources
from core.operations import apply_column_expression
from core.workspace import ColumnMetadata, Dataset, SavedPlot, WorksheetMetadata, Workspace, set_column_operation_comment
from math_engine.calculus import derivative_column, integral_column, fft_dataset, ifft_dataset
from math_engine.curve_fitting import FitReport, fit_curve
from math_engine.smoothing import SmoothingParameters, smooth_column, smoothing_operation_text
from models.fit_functions import CustomFitModel
from models.uncertainty import PercentileBounds
from core.api_analysis import AnalysisApi
from core.api_editing import WorksheetApi, record_undo
from core.api_summary_api import SummaryApi
from core.api_spectral import SpectralApi
from core.api_large_data import LargeDataApi

API_VERSION = 1


@dataclass(frozen=True)
class FitOutput:
    curve: Dataset
    residuals: Dataset | None
    report: FitReport

    @property
    def fit_frame(self) -> pd.DataFrame:
        return self.curve.frame

    @property
    def residual_frame(self) -> pd.DataFrame | None:
        return self.residuals.frame if self.residuals else None


def series(*, x: tuple[Dataset, str], y: tuple[Dataset, str], z: tuple[Dataset, str] | None = None,
           **appearance: object) -> dict[str, object]:
    """Build one plot series with explicit sheet/column references."""
    result = {"x_dataset": x[0].name, "x_column": x[1], "y_dataset": y[0].name, "y_column": y[1], **appearance}
    if z is not None:
        result.update(z_dataset=z[0].name, z_column=z[1])
    from ui.plot_canvas import PlotSeries
    return asdict(PlotSeries(**result))


class Session(AnalysisApi, WorksheetApi, SummaryApi, SpectralApi, LargeDataApi):
    """One explicit workspace shared by all API calls in a recording."""

    def __init__(self, workspace: Workspace | None = None) -> None:
        self.workspace = workspace if workspace is not None else Workspace()
        self._output_path: str | None = None

    @classmethod
    def from_cli(cls, arguments: Sequence[str] | None = None) -> Session:
        parser = argparse.ArgumentParser(description="Run a recorded JASC API script.")
        parser.add_argument("--project", help="Starting project for recorded workspace-sheet references")
        parser.add_argument("--output", help="Save the resulting workspace to this project")
        options = parser.parse_args(arguments)
        result = cls(project_io.load_project(options.project) if options.project else None)
        result._output_path = options.output
        return result

    def finish(self) -> None:
        if self._output_path:
            self.save_project(self._output_path)

    def sheet(self, name: str) -> Dataset:
        """Resolve an existing sheet (load its starting project with --project)."""
        try:
            return self.workspace.get_dataset(name)
        except KeyError:
            raise ValueError(f"Sheet '{name}' is unavailable. Load its starting project or import data first.") from None

    def load(self, path: str | Path, *, name: str | None = None, pattern_choice: str = "keep", **options: object) -> Dataset:
        """Import one text data file using the same parser as the GUI."""
        if pattern_choice not in {"keep", "generic"}:
            raise ValueError("Header handling must be keep or generic.")
        path = Path(path)
        context = JobContext(Event(), lambda _progress: None)
        settings = ImportOptions(**options)
        inspections = inspect_text_files(context, [path], settings)
        batch = prepare_text_files(context, [path], inspections, settings, pattern_choice)
        if batch.errors or not batch.files:
            raise ValueError("; ".join(batch.errors) or "No data were imported.")
        prepared = batch.files[0]
        output = self.workspace.add_dataset(name or path.stem, prepared.frame, source_path=path, copy_frame=False)
        output.worksheet_metadata = prepared.metadata
        from core.import_metadata import apply_imported_column_hints
        apply_imported_column_hints(output, prepared.inspection)
        return output

    def load_excel(self, path: str | Path, *, worksheet: str, has_header: bool = True,
                   name: str | None = None) -> Dataset:
        from core.file_io import read_excel_sheets
        from core.import_metadata import apply_imported_column_hints
        path = Path(path)
        result = read_excel_sheets(path, [worksheet], has_header=has_header)
        if worksheet not in result.frames:
            raise ValueError(result.errors.get(worksheet, "The workbook tab could not be imported."))
        output = self.workspace.add_dataset(name or f"{path.stem} - {worksheet}", result.frames[worksheet], source_path=path, copy_frame=False)
        output.worksheet_metadata = WorksheetMetadata(import_details={"Format": "Excel workbook", "Worksheet tab": worksheet,
                                                                     "Header": "Present" if has_header else "Not present"})
        apply_imported_column_hints(output)
        return output

    def load_folder(self, folder: str | Path, *, recursive: bool = False, **options: object) -> list[Dataset]:
        return [self.load(source.path, **options) for source in folder_sources(Path(folder), recursive)]

    @record_undo
    def smooth(self, sheet: Dataset, *, x_column: str, y_column: str, method: str,
               output_column: str, **parameters: object) -> str:
        settings = SmoothingParameters(**parameters)
        frame = sheet.frame.copy()
        result = smooth_column(frame, x_column, y_column, method, output_column, settings)
        sheet.frame[result.column_name] = frame[result.column_name]
        sheet.column_metadata[result.column_name] = deepcopy(sheet.column_metadata.get(y_column, ColumnMetadata()))
        sheet.formulas.pop(result.column_name, None)
        set_column_operation_comment(sheet, result.column_name, smoothing_operation_text(x_column, y_column, method, settings))
        return result.column_name

    @record_undo
    def derivative(self, sheet: Dataset, *, x_column: str, y_column: str, method: str, output_column: str) -> str:
        frame = sheet.frame.copy()
        result = derivative_column(frame, x_column, y_column, method, output_column)
        sheet.frame[result.column_name] = frame[result.column_name]
        set_column_operation_comment(sheet, result.column_name, f"Derivative {y_column} vs {x_column}: {method}")
        return result.column_name

    @record_undo
    def integral(self, sheet: Dataset, *, x_column: str, y_column: str, method: str,
                 output_column: str, initial_value: float = 0.) -> str:
        frame = sheet.frame.copy()
        result = integral_column(frame, x_column, y_column, method, output_column, initial_value)
        sheet.frame[result.column_name] = frame[result.column_name]
        set_column_operation_comment(sheet, result.column_name, f"Integral {y_column} vs {x_column}: {method}")
        return result.column_name

    @record_undo
    def formula(self, sheet: Dataset, *, output_column: str, expression: str,
                row_positions: list[int] | None = None) -> str:
        frames = {item.name: item.frame for item in self.workspace.list_datasets()}
        result = apply_column_expression(sheet.frame, output_column, expression, row_positions, frames)
        if row_positions is None:
            sheet.formulas[result.target_column] = expression.strip()
        else:
            sheet.formulas.pop(result.target_column, None)
        set_column_operation_comment(sheet, result.target_column, f"Formula: {expression}")
        return result.target_column

    def fft(self, sheet: Dataset, *, signal_column: str, x_column: str | None = None,
            window_method: str = "boxcar", name: str | None = None) -> Dataset:
        return self.workspace.add_dataset(name or sheet.name+"_fft", fft_dataset(sheet.frame, signal_column, x_column, window_method), copy_frame=False)

    def ifft(self, sheet: Dataset, *, real_column: str, imaginary_column: str | None = None, name: str | None = None) -> Dataset:
        return self.workspace.add_dataset(name or sheet.name+"_ifft", ifft_dataset(sheet.frame, real_column, imaginary_column), copy_frame=False)

    def fit(self, sheet: Dataset, *, x_column: str, y_column: str, model_key: str, method: str,
            curve_name: str | None = None, residual_name: str | None = None,
            create_residuals: bool = True, **settings: object) -> FitOutput:
        settings = deepcopy(settings)
        custom = settings.pop("custom_models", [])
        settings["custom_models"] = [item if isinstance(item, CustomFitModel) else CustomFitModel.from_metadata(item) for item in custom]
        for axis in ("x", "y"):
            if axis+"_bounds" in settings:
                settings[axis+"_bounds"] = PercentileBounds.from_state(settings[axis+"_bounds"])
        result = fit_curve(sheet.frame, x_column, y_column, model_key, method, **settings)
        created = []
        try:
            curve = self.workspace.add_dataset(curve_name or sheet.name+"_fit", result.fit_frame, copy_frame=False)
            created.append(curve)
            residuals = None
            if create_residuals:
                residuals = self.workspace.add_dataset(residual_name or sheet.name+"_residuals", result.residual_frame, copy_frame=False)
                created.append(residuals)
            for item in created:
                item.worksheet_metadata.fields.append(("Fit report", result.report.to_text()))
            return FitOutput(curve, residuals, result.report)
        except Exception:
            for item in reversed(created):
                self.workspace.remove_dataset(item.name)
            raise

    def plot(self, series_list: list[dict[str, object]], *, name: str, settings: dict[str, object] | None = None,
             locators: list[dict[str, object]] | None = None) -> SavedPlot:
        return self.workspace.add_plot(name, {"version": 5, "series": deepcopy(series_list),
                                             "settings": deepcopy(settings or {}), "locators": deepcopy(locators or [])})

    def update_plot(self, plot: SavedPlot, series_list: list[dict[str, object]], *,
                    settings: dict[str, object] | None = None, locators: list[dict[str, object]] | None = None) -> SavedPlot:
        return self.workspace.update_plot(plot.name, {"version": 5, "series": deepcopy(series_list),
                                                      "settings": deepcopy(settings or {}), "locators": deepcopy(locators or [])})

    def plot_by_name(self, name: str) -> SavedPlot:
        return self.workspace.get_plot(name)

    def rename_plot(self, plot: SavedPlot, name: str) -> SavedPlot:
        return self.workspace.rename_plot(plot.name, name)

    def delete_plot(self, plot: SavedPlot) -> None:
        self.workspace.remove_plot(plot.name)

    def compare(self, plots: list[SavedPlot], *, name: str, **layout: object) -> SavedPlot:
        from core.plot_comparison import comparison_state
        return self.workspace.add_plot(name, comparison_state([plot.plot_id for plot in plots], **layout))

    def update_comparison(self, plot: SavedPlot, plots: list[SavedPlot], **layout: object) -> SavedPlot:
        from core.plot_comparison import comparison_state
        return self.workspace.update_plot(plot.name, comparison_state([item.plot_id for item in plots], **layout))

    def export_data(self, sheet: Dataset, path: str | Path, *, delimiter: str = ",") -> None:
        export_tabular_file(sheet.frame, path, delimiter=delimiter)

    def export_plot(self, plot: SavedPlot, path: str | Path) -> None:
        """Use the application's renderer so saved appearance is preserved."""
        import os
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is None:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])
        self._application = app
        from PySide6.QtCore import QCoreApplication, QEvent
        from ui.plot_tab import PlotTab
        from core.plot_comparison import is_comparison
        from ui.plot_comparison import PlotComparisonView
        view = PlotComparisonView(self.workspace, plot.state) if is_comparison(plot.state) else PlotTab(self.workspace)
        try:
            if is_comparison(plot.state):
                if Path(path).suffix.lower() != ".png":
                    raise ValueError("Comparison export currently requires a PNG path.")
                view.export_png(path)
            else:
                view.load_plot_state(plot.state)
                view._plot_canvas.export_figure(str(path))
        finally:
            view.close()
            view.deleteLater()
            app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def save_project(self, path: str | Path, **options: object) -> None:
        project_io.save_project(self.workspace, path, **options)


def main(arguments: Sequence[str] | None = None) -> int:
    """Replay the restricted recording language, never execute a Python module."""
    from core.script_cli import main as script_main
    return script_main(list(arguments) if arguments is not None else None)


def launch_recording(path: str | Path) -> None:
    """Generated-file convenience launcher; the run body is still interpreted."""
    import sys
    raise SystemExit(main([str(path), *sys.argv[1:]]))


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
