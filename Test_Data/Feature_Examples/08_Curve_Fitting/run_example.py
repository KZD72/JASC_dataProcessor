from jasc_api import Session, series, launch_recording


def run(session):
    data = session.load("input/models.csv", name="Models")
    line = session.fit(data, x_column="x", y_column="linear", model_key="linear", method="trf", initial_parameters=[2., 1.], curve_name="Linear fit", residual_name="Linear residuals")
    peak = session.fit(data, x_column="x", y_column="gaussian", model_key="gaussian", method="trf", initial_parameters=[7., 4.8, .9, .4], lower_bounds=[0., 0., .1, 0.], upper_bounds=[20., 10., 3., 2.], fixed_parameters=[False, False, False, False], include_confidence_band=True, curve_name="Gaussian fit", residual_name="Gaussian residuals")
    decay = session.fit(data, x_column="x", y_column="decay", model_key="exponential_decay", method="trf", initial_parameters=[5., 1.5, .3], curve_name="Decay fit", residual_name="Decay residuals")
    custom = session.fit(data, x_column="x", y_column="linear", model_key="custom:Example line", method="trf", custom_models=[{"name": "Example line", "expression": "a*x+b", "parameter_names": ["a", "b"], "default_initial": [1., 0.]}], initial_parameters=[2., 1.], curve_name="Custom fit", residual_name="Custom residuals")
    line_row = session.result_row("fit_report", source_sheet=data.name, requested_y_column="linear", y_column="linear", output_fit_sheet=line.curve.name, result=line)
    peak_row = session.result_row("fit_report", source_sheet=data.name, requested_y_column="gaussian", y_column="gaussian", output_fit_sheet=peak.curve.name, result=peak)
    decay_row = session.result_row("fit_report", source_sheet=data.name, requested_y_column="decay", y_column="decay", output_fit_sheet=decay.curve.name, result=decay)
    custom_row = session.result_row("fit_report", source_sheet=data.name, requested_y_column="linear", y_column="linear", output_fit_sheet=custom.curve.name, result=custom)
    report = session.collect_rows(name="Fit reports", rows=[line_row, peak_row, decay_row, custom_row])
    for sheet in [line.curve, peak.curve, decay.curve, custom.curve, line.residuals, peak.residuals, report]:
        session.export_data(sheet, "tables/" + sheet.name + ".csv")
    plot = session.plot([series(x=(data, "x"), y=(data, "gaussian"), plot_type="scatter", marker="."), series(x=(peak.curve, "fit_x"), y=(peak.curve, "fit_y"), lower_column="fit_lower", upper_column="fit_upper")], name="Gaussian fit and band")
    session.export_plot(plot, "figures/gaussian.png")


if __name__ == "__main__":
    launch_recording(__file__)
