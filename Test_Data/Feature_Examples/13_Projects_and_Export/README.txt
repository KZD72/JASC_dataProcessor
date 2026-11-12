PROJECTS, EXPORT AND PROTECTION
===============================
Replay run_example.py with this directory as input; start an empty project.
The macro creates a line plot and ordinary example.jasc plus the runner's final
_jasc_result.jasc. Tables export as CSV/TSV, the individual plot as PNG/SVG/PDF.
Comparisons currently export PNG only; vector exports here are individual figures.

GUI: open example.jasc from the new output run folder. Expect 21 rows of y=2*x+1
and Saved plot. Change its title/axis labels, close/reopen the plot tab and save
under a NEW project name. Reopen it and verify both numeric data and plot changes.
CSV/TSV exports do not retain all project metadata, formulas and plot definitions;
use .jasc for a complete editable workspace.

PROTECTION IS MANUAL, NOT RECORDED:
1. Save an encrypted .jascx COPY through the project Save options using your own
   temporary test password. Close/reopen: wrong password must fail, correct one
   restores data. Do not overwrite the ordinary example or use a real password.
2. If testing signatures, choose File > Create Signing Identity; keep its private
   key/password local. Export/import only its public identity
   and inspect trusted/unknown signature status. Save signed copies separately.
3. Reopen the unsigned .jasc and distinguish its Package Seal from an author
   signature. A seal is an integrity check, not independent proof of authorship.
No private keys, passwords or encrypted projects are supplied by these examples.
Restricted replay excludes signing/key management and encrypted/signed saves.
Existing executable bundles and their manuals are snapshots; no bundle is rebuilt.
