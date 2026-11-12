# JASC macro example: folder import -> cleanup -> correction -> fit -> plots/export.
# Run with Macros > Run Python API Script, or the JASC command-line runner.
# Allowed input folder: Test_Data/Macro_Example (the folder containing this file).
from jasc_api import Session, series, launch_recording


def run(session):
    # 1. Import every CSV in the input subfolder with explicit parsing settings.
    measurements = session.load_folder("input", delimiter=",", has_header=True)

    for raw in measurements:
        # 2. Remove missing measurements, remove repeated X samples, and sort X.
        valid = session.prepare(
            raw, operation="missing", name=raw.name+"_valid",
            columns=["x", "signal", "signal_sigma", "background"], strategy="drop_rows",
        )
        unique = session.prepare(
            valid, operation="duplicates", name=raw.name+"_unique",
            columns=["x"], keep="first",
        )
        processed = session.prepare(
            unique, operation="sort", name=raw.name+"_processed",
            columns=["x"], ascending=True,
        )
        session.delete_sheet(valid)
        session.delete_sheet(unique)

        # 3. Subtract the exact reference background included in this synthetic data.
        # This reference has no uncertainty; the measurement sigma remains valid.
        session.formula(
            processed, output_column="corrected",
            expression='col("signal") - col("background")',
        )

        # 4. LOWESS handles gaps left by missing samples. Display smoothing only;
        # the fit below uses the unsmoothed values.
        session.smooth(
            processed, x_column="x", y_column="corrected", method="lowess",
            output_column="smoothed", lowess_fraction=0.08, lowess_iterations=2,
        )

        # 5. Weighted Gaussian fit: amplitude, center, peak width sigma, offset.
        # signal_sigma is measurement noise in Y; peak sigma is a width in X.
        fit = session.fit(
            processed, x_column="x", y_column="corrected",
            model_key="gaussian", method="trf",
            weight_column="signal_sigma", weight_mode="sigma", absolute_sigma=True,
            initial_parameters=[8.0, 0.0, 0.85, 0.0],
            lower_bounds=[0.0, -3.0, 0.15, -1.0],
            upper_bounds=[20.0, 3.0, 2.0, 1.0],
            fixed_parameters=[False, False, False, False],
            fit_points=501, include_confidence_band=True, confidence_level=0.95,
            curve_name=raw.name+"_fit", residual_name=raw.name+"_residuals",
            create_residuals=True,
        )

        # 6. Create a readable parameter/quality table from the current fit result.
        fit_row = session.result_row(
            "fit", source_dataset=processed, result=fit,
            requested_x_column="x", x_column="x",
            requested_y_column="corrected", y_column="corrected",
            requested_x_weight_column=None, x_weight_column=None,
            requested_weight_column="signal_sigma", weight_column="signal_sigma",
            column_binding_mode="name",
            requested_fit_sheet=raw.name+"_fit", output_fit_sheet=fit.curve.name,
            requested_residual_sheet=raw.name+"_residuals", output_residual_sheet=fit.residuals.name,
            status="ok", error="", elapsed_seconds=0.0,
        )
        parameters = session.collect_rows(
            name=raw.name+"_fit_parameters", rows=[fit_row],
            operation="Weighted Gaussian fit of the unsmoothed, background-corrected measurements",
        )
        statistics = session.statistics(
            processed, operation_key="single_summary", primary_column="corrected",
            name=raw.name+"_statistics",
        )

        # 7. Preserve independent plots: measurements, visual smoothing, fit + 95% band.
        plot = session.plot(
            [
                series(
                    x=(processed, "x"), y=(processed, "corrected"),
                    plot_type="errorbar", y_err_column="signal_sigma",
                    marker=".", marker_size=2.5, line_style="none", line_width=0.6,
                    color="#7f8c8d", custom_label="Measured (1 sigma)",
                ),
                series(
                    x=(processed, "x"), y=(processed, "smoothed"),
                    color="#e67e22", line_width=1.5, custom_label="LOWESS (display only)",
                ),
                series(
                    x=(fit.curve, "fit_x"), y=(fit.curve, "fit_y"),
                    color="#1565c0", line_width=1.8, line_style="--", custom_label="Weighted Gaussian fit",
                    lower_column="fit_lower", upper_column="fit_upper", fill_alpha=0.18,
                ),
            ],
            name=raw.name+"_analysis",
            settings={
                "title": raw.name+": background-corrected Gaussian peak",
                "axes": {"x": {"label": "X (arbitrary units)"}, "left_y": {"label": "Corrected signal (a.u.)"}},
                "grid": {"enabled": True},
                "legend": {"enabled": True, "location": "upper right"},
                "figure": {"width": 8.0, "height": 5.0},
            },
        )

        # 8. Export all useful tables and each independent plot.
        session.export_data(processed, "tables/"+raw.name+"_processed.csv")
        session.export_data(fit.curve, "tables/"+raw.name+"_fit.csv")
        session.export_data(fit.residuals, "tables/"+raw.name+"_residuals.csv")
        session.export_data(parameters, "tables/"+raw.name+"_fit_parameters.csv")
        session.export_data(statistics, "tables/"+raw.name+"_statistics.csv")
        session.export_plot(plot, "figures/"+raw.name+"_analysis.png")

    # 9. Compare the three supplied examples in equal cells with synchronized axes.
    comparison = session.compare(
        [session.plot_by_name("spectrum_01_analysis"),
         session.plot_by_name("spectrum_02_analysis"),
         session.plot_by_name("spectrum_03_analysis")],
        name="Synthetic spectra comparison", rows=1, columns=3,
        match_x=True, match_y=True, panel_labels=True,
    )
    session.export_plot(comparison, "figures/comparison.png")


if __name__ == "__main__":
    launch_recording(__file__)
