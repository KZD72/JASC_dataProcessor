# Recommended System Architecture

> **Instructions for AI Agent**: Use this directory structure as a blueprint when creating the application files. Ensure modular separation of concerns.

```text
project_root/
│
├── main.py                 # Application entry point, initializes PySide6 QApplication
│
├── ui/                     # User Interface components
│   ├── main_window.py      # The main QMainWindow class
│   ├── data_table.py       # Spreadsheet widget for manual data entry
│   ├── plot_canvas.py      # Matplotlib figure canvas and toolbar integration
│   └── dialogs.py          # Custom dialogs (e.g., CSV import settings, Fit parameters)
│
├── core/                   # Business logic and data management
│   ├── workspace.py        # Manages multiple datasets/DataFrames
│   └── file_io.py          # Functions for parsing CSV/TXT files
│
├── math_engine/            # Calculations and transformations
│   ├── calculus.py         # Derivatives, Integrals, FFT, iFFT
│   └── curve_fitting.py    # SciPy curve fit logic and function library
│
├── models/                 # Predefined mathematical functions
│   └── fit_functions.py    # Python definitions of Gaussian, Heidler, Bessel, etc.
│
└── utils/                  # Helper functions
    └── helpers.py