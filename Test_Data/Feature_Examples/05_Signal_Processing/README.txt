CALCULUS, SMOOTHING AND FOURIER TRANSFORMS
========================================
Replay run_example.py with this directory as input; start an empty project.
Input: signals.csv, 512 evenly spaced samples at 128 Hz.
signal = 2*sin(2*pi*5*t) + 0.5*cos(2*pi*13*t); noisy adds seeded noise (sigma 0.15).

GUI: Analysis > Derivative, X=time_s, Y=quadratic, NumPy gradient. Interior values
equal 2*t; endpoint one-sided differences have finite-difference error. Integral,
cumulative trapezoid, starts at zero and approximates t^3/3 within 0.00005.
Try Smoothing on noisy: adjacent average (5), median (5), Savitzky-Golay (9,3),
LOWESS (fraction 0.025), FFT low-pass (fraction 0.25), derivative smoothing plus
integration (window 9). Smoothers have different biases/edge behavior; the same
settings are not claimed optimal for every method. The raw signal is retained.

FFT: signal versus time_s, no window/rectangular. The full two-sided transform has
peaks at +/-5 and +/-13 Hz; raw magnitudes at positive peaks are 512 and 128.
These are unnormalized FFT coefficients, not physical one-sided amplitudes.
Inverse FFT: select FFT real and imaginary, expect the original signal to roundoff.
The inverse output sample column is an index, not an automatically recovered time.

Replay exports Signals, FFT, Inverse FFT and a frequency plot. For a cleaner
display, restrict the plot's X limits to 0..20 Hz after opening the result.
