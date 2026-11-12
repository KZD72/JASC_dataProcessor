from jasc_api import Session, series, launch_recording


def run(session):
    spectrum = session.load("input/spectrum.csv", name="Spectrum", data_kind="table")
    spatial = session.load("input/raman_map.csv", name="Raman map", data_kind="table")
    # Explicit reviewed seeds. The numerical fit is recomputed from the input.
    first = {"model_key": "gaussian", "peak": {
        "source_sheet": "Spectrum", "channel": "signal", "row_index": 100,
        "center": 200., "polarity": "positive", "raw_height": 7., "corrected_height": 5.,
        "prominence": 5., "fwhm": 14.13, "left_boundary": 180., "right_boundary": 220.,
        "left_base": 160., "right_base": 240., "area": 75.2, "local_snr": 100., "plateau_size": 1., "asymmetry": 1.},
        "initial_parameters": [5., 200., 6., 0.], "lower_bounds": [0., 190., 1., 0.],
        "upper_bounds": [20., 210., 20., 0.], "fixed_parameters": [False, False, False, True]}
    second = {"model_key": "gaussian", "peak": {
        "source_sheet": "Spectrum", "channel": "signal", "row_index": 200,
        "center": 300., "polarity": "positive", "raw_height": 5., "corrected_height": 3.,
        "prominence": 3., "fwhm": 23.55, "left_boundary": 270., "right_boundary": 330.,
        "left_base": 250., "right_base": 350., "area": 75.2, "local_snr": 100., "plateau_size": 1., "asymmetry": 1.},
        "initial_parameters": [3., 300., 10., 0.], "lower_bounds": [0., 290., 1., 0.],
        "upper_bounds": [20., 310., 30., 0.], "fixed_parameters": [False, False, False, True]}
    single = session.spectrum(spectrum, settings={
        "x_column": "shift", "y_column": "signal", "baseline": {"method": "constant", "constant_value": 2.},
        "detection": {"prominence": 1.}, "fit": {"data_mode": "corrected", "baseline_model": "zero"},
        "components": [first, second], "analysis_name": "Two Gaussian peaks", "signal_name": "Corrected spectrum",
        "peak_name": "Detected peaks", "fit_name": "Single fit", "parameter_name": "Single parameters"})
    component = {"model_key": "gaussian", "peak": {
        "source_sheet": "Raman map", "channel": "signal", "row_index": 140,
        "center": 240., "polarity": "positive", "raw_height": 7., "corrected_height": 5.,
        "prominence": 5., "fwhm": 14.13, "left_boundary": 220., "right_boundary": 260.,
        "left_base": 200., "right_base": 280., "area": 75.2, "local_snr": 100., "plateau_size": 1., "asymmetry": 1.},
        "initial_parameters": [5., 240., 6., 0.], "lower_bounds": [0., 225., 1., 0.],
        "upper_bounds": [20., 260., 20., 0.], "fixed_parameters": [False, False, False, True]}
    mapped = session.spectral_batch([spatial], settings={
        "scope": "map", "source_dataset": "Raman map", "components": [component],
        "baseline": {"method": "constant", "constant_value": 2.}, "detection": {"prominence": 1.},
        "fit": {"data_mode": "corrected", "baseline_model": "zero"}, "x_column": "shift", "y_column": "signal",
        "analysis_range": None, "tolerance": 15., "analysis_name": "Six pixel Raman fit", "profile": {}, "detail": {}})
    baseline = session.baseline_map(spatial, x_column="shift", y_column="signal", name="Map baseline corrected", parameters={"method": "constant", "constant_value": 2.})
    single_parameters = session.export_analysis_table(single.analysis, table="parameters", name="Single analysis parameters")
    metrics = session.export_analysis_table(mapped.analysis, table="metrics", name="Map metrics")
    parameters = session.export_analysis_table(mapped.analysis, table="parameters", name="Map parameters")
    for sheet in [single_parameters, metrics, parameters, baseline]:
        session.export_data(sheet, "tables/" + sheet.name + ".csv")


if __name__ == "__main__":
    launch_recording(__file__)
