"""Public analysis operations shared by Python recordings and numerical engines."""

from __future__ import annotations

from copy import deepcopy
from threading import Event
from types import SimpleNamespace

import pandas as pd

from core import data_prep
from core.jobs import JobContext
from core.workspace import Dataset, Workspace, set_dataset_operation_comments
from math_engine.calculus import validate_numeric_column_metadata


class AnalysisApi:
    workspace: Workspace

    def map_analysis(self, series_state: dict, *, operation: str, name: str,
                     parameters: list | None = None) -> Dataset:
        """Recompute grids, axis/line cuts, ROI summaries and contour vertices."""
        import os
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
        from ui.plot_canvas import PlotCanvas, PlotSeries
        from ui.plot_tab import PlotTab
        if QApplication.instance() is None:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self._application = QApplication.instance() or QApplication([])
        canvas = PlotCanvas()
        source = PlotSeries(**series_state)
        args = parameters or []
        try:
            if operation == "grid":
                frame = canvas.surface_grid_frame(self.workspace, source)
            elif operation in {"horizontal", "vertical"}:
                frame = canvas.surface_profile_frame(self.workspace, source, operation, *args)
            elif operation == "line":
                frame = canvas.surface_line_profile_frame(self.workspace, source, *args)
            elif operation == "roi":
                frame = canvas.surface_roi_summary_frame(self.workspace, source, *args)
            elif operation == "contours":
                frame = canvas.surface_contours_frame(self.workspace, source)
            else:
                raise ValueError(f"Unknown map analysis: {operation}")
            output = self.workspace.add_dataset(name, frame, copy_frame=False)
            PlotTab._annotate_surface_analysis_dataset(output, operation, source)
            return output
        finally:
            canvas.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def _analysis_sheet(self, name: str, frame: pd.DataFrame, sources: list[Dataset], operation: str) -> Dataset:
        output = self.workspace.add_dataset(name, frame, copy_frame=False)
        metadata = {}
        for source in sources:
            for column, entry in source.column_metadata.items():
                if column in frame.columns and column not in metadata:
                    metadata[column] = entry
        output.set_column_metadata(metadata)
        set_dataset_operation_comments(output, operation)
        return output

    def prepare(self, sheet: Dataset, *, operation: str, name: str,
                other: Dataset | None = None, operation_comment: str | None = None, **settings: object) -> Dataset:
        """Run the same filter/subset/sort/cleanup/group/merge/reshape/bin engines."""
        sheet.sync_column_metadata_attrs()
        if operation == "filter":
            frame = data_prep.apply_filter_condition(sheet.frame, data_prep.FilterCondition(**settings["condition"]))
        elif operation == "subset":
            frame = data_prep.extract_positional_subset(sheet.frame, **settings)
        elif operation == "sort":
            frame = data_prep.sort_dataframe(sheet.frame, **settings)
        elif operation == "duplicates":
            frame = data_prep.remove_duplicate_rows(sheet.frame, **settings)
        elif operation == "missing":
            frame = data_prep.clean_missing_values(sheet.frame, **settings)
        elif operation == "group":
            frame = data_prep.group_aggregate_dataframe(sheet.frame, **settings)
        elif operation == "merge":
            if other is None:
                raise ValueError("Merge requires another worksheet.")
            other.sync_column_metadata_attrs()
            frame = data_prep.merge_join_dataframes(sheet.frame, other.frame, **settings)
        elif operation == "reshape":
            frame = data_prep.reshape_dataframe(sheet.frame, **settings)
        elif operation == "bin":
            frame = data_prep.bin_dataframe(sheet.frame, **settings)
        else:
            raise ValueError(f"Unknown Data Prep operation: {operation}")
        return self._analysis_sheet(name, frame, [sheet]+([other] if other else []), operation_comment or f"Data Prep: {operation}")

    def statistics(self, sheet: Dataset, *, operation_key: str, name: str,
                   primary_column: str = "", columns: list[str] | None = None,
                   secondary: Dataset | None = None, secondary_column: str = "",
                   operation_comment: str | None = None) -> Dataset:
        from math_engine.statistics import STATISTIC_OPERATIONS, run_statistical_analysis, run_multicolumn_statistical_analysis
        def label(column: str) -> str:
            metadata = sheet.column_metadata.get(column)
            text = metadata.long_name if metadata and metadata.long_name else column
            if metadata and metadata.unit:
                text += f" ({metadata.unit})"
            return f"{sheet.name}: {text}"
        sheet.sync_column_metadata_attrs()
        scope = STATISTIC_OPERATIONS[operation_key].scope
        if scope == "multi":
            selected = sheet.frame[columns].copy()
            selected.attrs.update(sheet.frame.attrs)
            frame = run_multicolumn_statistical_analysis(selected, {column: label(column) for column in columns}, operation_key)
        else:
            validate_numeric_column_metadata(sheet.frame, primary_column, pd.to_numeric(sheet.frame[primary_column], errors="coerce"))
            values = None
            if secondary is not None:
                secondary.sync_column_metadata_attrs()
                values = secondary.frame[secondary_column]
                if scope != "group":
                    validate_numeric_column_metadata(secondary.frame, secondary_column, pd.to_numeric(values, errors="coerce"))
            frame = run_statistical_analysis(sheet.frame[primary_column], f"{sheet.name}: {primary_column}", operation_key,
                                             values, f"{secondary.name}: {secondary_column}" if secondary else "")
        return self._analysis_sheet(name, frame, [], operation_comment or f"Statistics: {operation_key}")

    def interpolate(self, sheet: Dataset, *, coordinate_columns: list[str], value_column: str,
                    name: str, method: str, query_columns: list[str] | None = None,
                    ranges: list[tuple[float, float, int]] | None = None, mesh: bool = False,
                    manual_points: str | None = None, fill_policy: str = "nan", smoothing: float = 0.,
                    epsilon: float | None = None, operation_comment: str | None = None) -> Dataset:
        from math_engine.interpolation import generated_query_points, query_points_from_columns, query_points_from_text, interpolate_dataset
        sheet.sync_column_metadata_attrs()
        if sum(value is not None for value in (query_columns, ranges, manual_points)) != 1:
            raise ValueError("Select exactly one interpolation query source.")
        if query_columns is not None:
            query = query_points_from_columns(sheet.frame, query_columns)
        elif ranges is not None:
            query = generated_query_points(ranges, mesh)
        else:
            query = query_points_from_text(manual_points, len(coordinate_columns))
        frame = interpolate_dataset(sheet.frame, coordinate_columns, value_column, query, method, fill_policy, smoothing, epsilon)
        output = self.workspace.add_dataset(name, frame, copy_frame=False)
        from core.import_metadata import apply_interpolation_metadata
        apply_interpolation_metadata(sheet, output, coordinate_columns, value_column)
        query_kind = "columns" if query_columns is not None else "generated" if ranges is not None else "manual"
        operation = operation_comment or (f"Interpolation: value={value_column}, coordinates={', '.join(coordinate_columns)}, "
                                          f"method={method}, query={query_kind}, outside={fill_policy}, binding=exact_column_name")
        set_dataset_operation_comments(output, operation, (f"{value_column}_interpolated",))
        output.prune_column_metadata()
        return output

    def statistics_plot_data(self, sheet: Dataset, *, kind: str, name: str,
                             column: str = "", secondary: Dataset | None = None,
                             secondary_column: str = "", columns: list[str] | None = None,
                             result: Dataset | None = None, result_name: str = "statistics") -> Dataset:
        from core.api_statistics_plots import StatisticsPlotData
        builder = StatisticsPlotData(self.workspace)
        if kind == "normal":
            output = builder._statistics_normal_curve_dataset(sheet, column)
        elif kind == "comparison":
            output = builder._statistics_comparison_dataset(sheet, column, secondary, secondary_column, result_name)
        elif kind == "groups":
            output = builder._statistics_group_distribution_dataset(sheet, column, secondary, secondary_column, result_name)
        elif kind == "correlation":
            output = builder._statistics_correlation_heatmap_dataset(sheet, columns, result_name)
        elif kind == "pca":
            output = builder._statistics_pca_variance_dataset(sheet)
        elif kind == "bland_altman":
            output = builder._statistics_bland_altman_dataset(sheet, column, secondary, secondary_column, result_name)
        elif kind == "regression":
            output = builder._statistics_regression_line_dataset(sheet, column, secondary, secondary_column, result)
        else:
            raise ValueError(f"Unknown statistics companion data: {kind}")
        if output is None:
            raise ValueError("The requested companion data are unavailable.")
        if output.name != name:
            self.workspace.rename_dataset(output.name, name)
        return output

    def baseline_map(self, sheet: Dataset, *, x_column: str, y_column: str, name: str,
                     parameters: dict[str, object], analysis_range: tuple[float, float] | None = None,
                     detail: dict[str, str] | None = None) -> Dataset:
        from core.baseline_jobs import BaselineMapRequest, prepare_baseline_map
        from core.spectral_jobs import SpectralSource
        from math_engine.baseline import BaselineParameters
        sheet.sync_column_metadata_attrs()
        request = BaselineMapRequest(SpectralSource(sheet.name, sheet.frame.copy()), x_column, y_column,
                                     BaselineParameters(**parameters), analysis_range, name, detail or {})
        prepared = prepare_baseline_map(JobContext(Event(), lambda _: None), request).worksheet
        output = self.workspace.add_dataset(prepared.name, prepared.frame, copy_frame=False)
        output.set_column_metadata(prepared.column_metadata)
        output.worksheet_metadata = prepared.worksheet_metadata
        return output

    def spectral_batch(self, sheets: list[Dataset], *, settings: dict[str, object]) -> SimpleNamespace:
        from core.peak_fit_jobs import PeakFitRequest, prepare_peak_fit
        from core.spectral_jobs import SpectralSource
        from math_engine.baseline import BaselineParameters
        from math_engine.peak_detection import PeakDetectionParameters, PeakRecord
        from math_engine.composite_peak_fit import CompositeFitParameters, PeakComponentSpec
        options = deepcopy(settings)
        for sheet in sheets:
            sheet.sync_column_metadata_attrs()
        options["sources"] = tuple(SpectralSource(sheet.name, sheet.frame.copy()) for sheet in sheets)
        options["components"] = tuple(PeakComponentSpec(**{**item, "peak": PeakRecord(**item["peak"])}) for item in options["components"])
        options["baseline"] = BaselineParameters(**options["baseline"])
        options["detection"] = PeakDetectionParameters(**options["detection"])
        options["fit"] = CompositeFitParameters(**options["fit"])
        prepared = prepare_peak_fit(JobContext(Event(), lambda _: None), PeakFitRequest(**options))
        outputs = []
        before = set(self.workspace.dataset_names())
        try:
            for item in prepared.worksheets:
                output = self.workspace.add_dataset(item.name, item.frame, copy_frame=False)
                output.set_column_metadata(item.column_metadata)
                output.worksheet_metadata = item.worksheet_metadata
                outputs.append(output)
            analysis = self.workspace.add_spectral_analysis(prepared.analysis)
        except Exception:
            for name in set(self.workspace.dataset_names())-before:
                self.workspace.remove_dataset(name)
            raise
        return SimpleNamespace(analysis=analysis, sheets=outputs)
