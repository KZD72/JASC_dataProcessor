JASC EXAMPLE DATA AND FEATURE WALKTHROUGHS
=========================================

Start with Feature_Examples/README.txt and its catalog.json. The numbered
directories cover every current application feature family with small synthetic
inputs, independent expected results, GUI instructions, and restricted API macros
where supported. Image digitization and protected project saves have manual steps.

For a complete folder-processing macro, use Macro_Example/README.txt. It loads
three spectra, cleans them, fits them, and exports synchronized comparison plots.

SurfaceMap_README.txt describes the earlier regular/irregular surface examples.
The other existing files and saved projects are retained as legacy samples;
their original contents and any existing credentials have not been changed.

No Python installation is needed to use supplied data and macros in a packaged
JASC application that supports restricted playback. Python plus JASC dependencies
is needed only for source execution, input regeneration, or automated tests.
These examples do not rebuild the executable.
