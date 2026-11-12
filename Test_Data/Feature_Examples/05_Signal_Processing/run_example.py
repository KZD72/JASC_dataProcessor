from jasc_api import Session, series, launch_recording


def run(session):
    data = session.load("input/signals.csv", name="Signals")
    session.derivative(data, x_column="time_s", y_column="quadratic", method="gradient", output_column="derivative")
    session.integral(data, x_column="time_s", y_column="quadratic", method="trapezoid", output_column="integral")
    session.smooth(data, x_column="time_s", y_column="noisy", method="adjacent_average", output_column="average", window_length=5)
    session.smooth(data, x_column="time_s", y_column="noisy", method="moving_median", output_column="median", window_length=5)
    session.smooth(data, x_column="time_s", y_column="noisy", method="savgol", output_column="savgol", window_length=9, polynomial_order=3)
    session.smooth(data, x_column="time_s", y_column="noisy", method="lowess", output_column="lowess", lowess_fraction=.025)
    session.smooth(data, x_column="time_s", y_column="noisy", method="fft", output_column="lowpass", fft_cutoff_fraction=.25)
    session.smooth(data, x_column="time_s", y_column="noisy", method="derivative_integral", output_column="reconstructed_smooth", window_length=9)
    fft = session.fft(data, signal_column="signal", x_column="time_s", window_method="boxcar", name="FFT")
    inverse = session.ifft(fft, real_column="real", imaginary_column="imaginary", name="Inverse FFT")
    plot = session.plot([series(x=(fft, "frequency"), y=(fft, "magnitude"))], name="Frequency spectrum", settings={"title": "FFT: peaks at +/-5 and +/-13 Hz"})
    for sheet in [data, fft, inverse]:
        session.export_data(sheet, "tables/" + sheet.name + ".csv")
    session.export_plot(plot, "figures/fft.png")


if __name__ == "__main__":
    launch_recording(__file__)
