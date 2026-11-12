CURVE FITTING, CONSTRAINTS AND CUSTOM MODELS
==========================================
Replay run_example.py with this directory as input; start an empty project.
models.csv has one common positive x grid and nine noise-free representative
responses spanning polynomial, exponential, peak, transition, oscillatory,
kinetic, power-law/rheology, probability-density and special-function use cases.

GUI: Analysis > Curve Fit. Choose Models (or your imported models worksheet) in
Source > Worksheet, X=x; choose exactly one response at a time. Switching worksheets
refreshes all column choices and clears response/error mappings. Batch targets
remain available separately. Each successful GUI fit stores <fit-sheet>_report;
the viewer can copy its text, export its table, or open the saved worksheet.
Replay fits linear, gaussian, decay and a custom model. Check these parameters:
- Linear: slope 2.5, intercept 1.2.
- Gaussian: amplitude 8, center 5, sigma 0.7, offset 0.5. Bounds and initial seeds
  are explicit in run_example.py; optional confidence/residual outputs are enabled.
- Exponential Decay: amplitude 6, tau 2, offset 0.4.
- Custom model "Example line": a*x+b, parameters a,b, seeds 2,1.
  The macro supplies its definition to the fit directly. To retain a selectable
  project model, create it through the GUI's Custom Models workflow and save .jasc;
  passing a model definition to one API fit does not register a project model.
Compare LM/TRF/Dogbox or fix a known Gaussian offset through the dialog. Bounds
and parameter order depend on the selected model; inspect the model equation.

Additional GUI responses and generating equations (not automated fit assertions):
logistic=5/(1+exp(-1.5*(x-5))); sine=2*sin(2*pi*0.3*x+0.2)+1;
kinetics=4*x/(2+x); power=3*x^0.6;
log_normal=exp(-0.5*((ln(x)-1)/0.4)^2)/(x*0.4*sqrt(2*pi)); bessel=J0(x).
Select the matching built-in equation and parameterization before fitting.

Replay exports curves, residuals and readable reports; all four RMSE values should
be near zero. Noise-free confidence bands may collapse: these inputs verify model
recovery, not realistic experimental uncertainty. See families 09 and Macro_Example
for uncertainty-aware fits. Global/shared-parameter fitting is not implied.
