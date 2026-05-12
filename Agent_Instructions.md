# System Instructions for AI Assistant (Codex)

## 1. Project Overview
**Role**: You are an expert Python developer specialized in PySide6, Pandas, Matplotlib, and SciPy.
**Goal**: Build a lightweight, performant data processing and visualization application, conceptually similar to SciDAVis or Origin.
**Tech Stack**:
- **GUI Framework**: PySide6 (Targeting standalone `.exe` deployment via PyInstaller)
- **Data Handling**: Pandas, NumPy
- **Math & Fitting Engine**: SciPy (`scipy.optimize`, `scipy.special`, `scipy.integrate`, `scipy.fft`)
- **Plotting**: Matplotlib (embedded in PySide6 using `FigureCanvasQTAgg` and `NavigationToolbar2QT`)

## 2. Core Functional Requirements

### A. Data Management & Workspace
- Maintain a central "Workspace" or "Project" state capable of holding multiple Pandas DataFrames simultaneously.
- Allow users to select columns from different loaded datasets to plot them together on the same canvas.

### B. Data Import & Entry
- **File Import**: Support `.csv` and `.txt`. Include smart parsing: allow the user to select delimiters (comma, semicolon, space, tab) and toggle header detection.
- **Manual Entry**: Implement a spreadsheet-like widget (`QTableWidget` or a custom `QAbstractTableModel` with `QTableView`) allowing users to create new sheets, name columns, and manually enter/edit data.

### C. Visualization & Plotting
- **Mapping**: UI elements (e.g., dropdowns/list widgets) to assign specific columns to X and Y axes.
- **Customization**: Controls for plot title, X/Y labels, line styles, marker styles, colors, and canvas dimensions.
- **Interactivity**: Integrate standard Matplotlib Navigation Toolbar (zoom, pan, save figure).

### D. Mathematical Operations
- **Calculus**: Numerical differentiation (derivative) and integration of selected data columns.
- **Signal Processing**: Fast Fourier Transform (FFT) and Inverse Fast Fourier Transform (iFFT) capabilities. Results should be displayable as new data columns or instant plots.

### E. Curve Fitting Engine
Implement a robust fitting module using `scipy.optimize.curve_fit`. The UI must allow users to select data, choose a model, guess initial parameters, and visualize the fit line against raw data. 
**Required Predefined Analytical Models**:
1. **Polynomial & Linear**: Linear, Quadratic, Cubic, Arbitrary n-th degree.
2. **Exponential & Power**: Single Exponential Growth/Decay, Double Exponential Decay, Stretched Exponential (Kohlrausch), Power Law.
3. **Peak Functions**: Gaussian, Lorentzian (Cauchy), Voigt / Pseudo-Voigt, Asymmetric Gaussian (Skewed).
4. **Sigmoidal & Step**: Logistic Curve, Gompertz Model, Error Function (erf).
5. **Oscillatory**: Sine/Cosine Wave, Damped Sine Wave.
6. **Specialized**: Heidler Function, Bessel Functions (1st & 2nd kind), Weibull Distribution, Log-Normal.

## 3. Coding Guidelines & AI Directives
- **Modularity**: DO NOT write monolithic code. Separate concerns (UI, Data Logic, Math Operations, Plotting) into different modules/files.
- **Type Hinting**: Use Python type hints for all function signatures.
- **Error Handling**: Use `try/except` blocks to handle malformed data, failed curve fits (`OptimizeWarning`), or unreadable files gracefully. Use PySide6 `QMessageBox` to inform the user of errors without crashing.
- **Documentation**: Write clear docstrings for complex math operations.
- **Session Continuity**: Always refer to `ChangeLog_Session.md` before starting new tasks, and update it before ending your response.