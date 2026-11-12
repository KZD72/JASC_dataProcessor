WORKSHEETS, EDITS AND METADATA
=============================
Replay run_example.py with this directory as input; start an empty project.

GUI: import input/numeric_seeds.csv, select the complete two-column six-row area,
then Data > Smart Fill Selection, Numeric. Expect x=1..6 and y=10,20,..60.
Undo and Redo should restore missing cells and then the completed sequence.
Double-click a column header: assign x role X/unit s/long name Time and y role
Y/unit V/long name Signal. Metadata changes affect labels, not stored values.
Create a new worksheet; paste the rows 0,1 / 1,3 / 2,5 / 3,7. Fill Range can add
sequence=100,105,110,115. Try inserting/deleting a row or column, clearing a
selection and undoing it. Duplicate, rename and delete the duplicate worksheet.

Manual date/category variant: import input/date_category_seeds.csv. Select all six
month cells and choose Date-Time Smart Fill; the last month is 2026-06-30, retaining
month-end behavior. Select all category cells and use Category Cycle to finish
A,B,A,B,A,B. This variant is guided rather than included in the supplied macro.
Clipboard copy/paste and column renames can also be tried on disposable copies.

Replay exports filled.csv and manual.csv. The filled metadata remains in the
result project; ordinary CSV does not retain JASC's metadata layer.
