# PyInstaller one-folder build: shared runtime, GUI and console entry points.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

root = Path(SPECPATH)
data = [(str(root / "JASC_Manual.pdf"), "."),
        (str(root / "resources" / "logo.png"), "resources")] + collect_data_files("scienceplots")
analysis = Analysis(
    [str(root / "main.py")], pathex=[str(root)],
    binaries=collect_dynamic_libs("odrpack"), datas=data,
    hiddenimports=["jasc_api", "matplotlib.backends.backend_qtagg"] + collect_submodules("polars", filter=lambda name: not name.startswith("polars.testing")),
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "tkinter", "IPython", "jupyter", "notebook",
              "pytest", "tests", "torch", "tensorflow", "numba", "cupy"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
gui = EXE(archive, analysis.scripts, [], exclude_binaries=True, name="JASC", console=False,
          icon=str(root / "resources" / "logo.png"),
          debug=False, strip=False, upx=False)
cli = EXE(archive, analysis.scripts, [], exclude_binaries=True, name="JASC-cli", console=True,
          debug=False, strip=False, upx=False)
bundle = COLLECT(gui, cli, analysis.binaries, analysis.datas, strip=False, upx=False, name="JASC")
