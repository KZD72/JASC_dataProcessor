# JASC Data Processor v0.1.0 — Windows release and Linux installer

JASC is a desktop application for importing, processing, plotting and fitting scientific data. This release adds recorded workflows, persistent fit reports, custom plot colours and packaged downloads for Windows and Linux.

## Highlights

- **Recorded workflows:** capture supported operations as readable Python API calls and replay them through the GUI or command line. Process compatible files from a folder or worksheets in the workspace, with plots and exports. A red window border and recording badge show when recording is active.
- **Restricted macro playback:** recordings use approved JASC commands, validated before execution. Playback uses a separate worker, selected input/output folders, cancellation and staged results. Arbitrary Python programs are not supported by the runner.
- **Improved fitting:** choose the input worksheet directly in Curve Fit, plot and fit asymmetric percentile bounds, and retain successful fit reports as workspace tables. Reports include full text, numeric parameters, errors and fit metrics, with copy/export controls and project persistence.
- **Better plot workflows:** independent plot tabs, equal-cell comparison grids, optional synchronized axes, pop-out windows and mouse zoom/pan. Choose from 20 colour presets or use custom RGB/hex colours for series and locators; applied colours and pending edits persist with the project.
- **Ready-to-use examples:** synthetic data and walkthroughs cover 14 feature families, including 13 replay macros and an additional whole-folder processing example. The updated PDF manual and curated examples are included in both downloads.

## Downloads

| Asset | Description |
| --- | --- |
| `JASC-Windows-x86_64-0.1.0.zip` | Windows 64-bit application with bundled Python and dependencies. |
| `JASC-Linux-0.1.0.sh` | Python-based Linux installer that downloads dependencies into an isolated environment. |
| `SHA256SUMS.txt` | SHA-256 checksums for both downloads. |

### Windows

Extract the **entire ZIP**, then run `JASC.exe` inside the `JASC` folder. Keep `_internal` beside the executables. A separate Python installation is not required.

`JASC-cli.exe` supports command-line macro playback. Start with `Test_Data/README.txt` for the included examples.

### Linux

Download the installer and run:

```sh
sh JASC-Linux-0.1.0.sh
```

Requirements: **Python 3.10–3.12 with venv/pip**, internet access, compatible binary wheels for the target CPU/libc, and Qt desktop libraries. The installer does not require root or modify the system Python.

After installation, launch:

```sh
~/.local/opt/JASC-0.1.0/JASC
```

Use `--install-dir PATH` to choose a new installation directory, `--verify` to check the embedded archive, or `--extract-only PATH` to extract sources without downloading dependencies. Existing directories are not overwritten. See `LINUX_INSTALL.txt` for troubleshooting and interpreter selection.

## Verification and current limits

- Three Windows standalone checks passed without external Python. The extracted release ZIP also passed GUI startup, and the bundled CLI completed the asymmetric-fit example and exported all 19 plot subtypes.
- Ten Linux packaging tests passed, including real shell verification/extraction, quoted paths and arguments, checksum checks, overwrite protection and failed-install diagnostics.
- **Native Linux installation and GUI startup have not yet been tested on a Linux machine.** The `.sh` is a Python-based installer, not a frozen Linux executable; compatibility with every distribution, CPU or libc is not guaranteed.
- Windows code signing and validation on a fresh Windows VM remain pending.
- Some interactive workflows, including image digitization, are not yet macro-replayable. Encrypted/signed project saves and key management are excluded from recordings. Fit errors and confidence bands remain local approximations rather than bootstrap intervals.
