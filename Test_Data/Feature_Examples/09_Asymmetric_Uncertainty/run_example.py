from jasc_api import Session, series, launch_recording


def run(session):
    data = session.load("input/percentiles.csv", name="Percentile measurements")
    bounds = {"lower_column": "y_p16", "upper_column": "y_p84", "lower_probability": .16, "upper_probability": .84, "centre": "median", "origin": "measurement"}
    # X is exact in the synthetic experiment. Its endpoint columns demonstrate
    # plotting only; do not invent X noise in the fitted measurement model.
    fit = session.fit(data, x_column="x", y_column="y", model_key="linear", method="trf", initial_parameters=[1.5, 2.], y_bounds=bounds, curve_name="Percentile fit", residual_name="Percentile residuals")
    row = session.result_row("fit_report", source_sheet=data.name, requested_y_column="y", y_column="y", output_fit_sheet=fit.curve.name, result=fit)
    report = session.collect_rows(name="Percentile report", rows=[row])
    plot = session.plot([series(x=(data, "x"), y=(data, "y"), plot_type="errorbar", marker=".", line_style="none", y_bounds=bounds, x_bounds={"lower_column": "x_p16", "upper_column": "x_p84"}), series(x=(fit.curve, "fit_x"), y=(fit.curve, "fit_y"))], name="Asymmetric error bars")
    for sheet in [fit.curve, fit.residuals, report]:
        session.export_data(sheet, "tables/" + sheet.name + ".csv")
    session.export_plot(plot, "figures/percentiles.png")


if __name__ == "__main__":
    launch_recording(__file__)
