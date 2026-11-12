SAFE FORMULAS AND CROSS-SHEET DATA
=================================
Replay run_example.py with this directory as input; start an empty project.
GUI: import measurements.csv as Measurements and reference.csv as Reference.
Analysis > Apply Formula: target Measurements, new column corrected, whole column:
  col("signal") - sheet("Reference", "background")
Then create squared with np.square(col("corrected")). Expected corrected=2.5*x+4.

Create selected as col("corrected"). Select only visible rows 1 and 3 of selected;
apply -col("corrected") in selected-cells scope to update those two cells. Other
rows remain positive. Macro row positions [0,2] express those same visible rows.
Cross-sheet values align by row position, not by matching x; this example has
identical row counts/order deliberately. Formula text/provenance persists in .jasc.
The safe expression language does not permit Python imports or system commands.

Expected: eleven rows. corrected starts at 4 and ends at 29. selected is negative
only in rows 1 and 3. formulas.csv contains all source and computed columns.
For batch Sequential/Parallel choices, repeat this on multiple imported copies
through the formula dialog; the supplied replay demonstrates the numerical result.
