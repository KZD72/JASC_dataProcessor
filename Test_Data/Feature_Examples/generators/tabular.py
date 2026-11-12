"""Tabular import, editing, preparation, formula, statistics and storage fixtures."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
import re
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

import numpy as np
import pandas as pd
from openpyxl import Workbook

from .common import csv, inputs, truth


def workbook(path: Path) -> None:
    """Normalize ZIP and document timestamps so regeneration is byte-identical."""
    book = Workbook()
    book.properties.created = book.properties.modified = datetime(2026, 1, 1)
    values = book.active
    values.title = "Measurements"
    values.append(["x", "y"])
    for x in range(6):
        values.append([x, 2*x + 1])
    groups = book.create_sheet("Groups")
    groups.append(["group", "label"])
    groups.append(["A", "Control"])
    groups.append(["B", "Treatment"])
    # Value-only Excel import intentionally does not execute formulas or VBA.
    buffer = BytesIO()
    book.save(buffer)
    with ZipFile(buffer) as source, ZipFile(path, "w", ZIP_DEFLATED) as target:
        for name in sorted(source.namelist()):
            data = source.read(name)
            if name == "docProps/core.xml":
                data = re.sub(rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
                              b"2026-01-01T00:00:00Z", data)
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            target.writestr(info, data)


def generate_tabular(root: Path) -> None:
    directory = inputs(root, "01_Import")
    frame = pd.DataFrame({"x": range(6), "y": np.arange(6)*2 + 1})
    csv(directory/"comma.csv", frame)
    frame.to_csv(directory/"tab.txt", sep="\t", index=False, lineterminator="\n")
    frame.to_csv(directory/"headerless.dat", sep=" ", index=False, header=False, lineterminator="\n")
    (directory/"preamble.txt").write_text(
        "Experiment: Synthetic import\nOperator: Example\nx;y\n" +
        "".join(f"{x};{2*x+1}\n" for x in range(6)), encoding="utf-8")
    (directory/"decimal_comma.txt").write_text(
        "x;y\n0,0;1,0\n0,5;2,0\n1,0;3,0\n", encoding="utf-8")
    (directory/"cp1252.txt").write_bytes("label;value\ncaf\u00e9;1\ncr\u00e8me;2\n".encode("cp1252"))
    frame.to_csv(directory/"utf16.txt", sep="\t", index=False, encoding="utf-16", lineterminator="\n")
    workbook(directory/"two_sheets.xlsx")
    truth(directory, {"standard_rows": 6, "slope": 2, "intercept": 1,
                      "decimal_comma_x": [0, .5, 1], "workbook_tabs": ["Measurements", "Groups"]})

    directory = inputs(root, "02_Worksheet_Editing")
    csv(directory/"numeric_seeds.csv", pd.DataFrame({"x": [1., 2., np.nan, np.nan, np.nan, np.nan],
                                                    "y": [10., 20., np.nan, np.nan, np.nan, np.nan]}))
    csv(directory/"date_category_seeds.csv", pd.DataFrame({
        "month": ["2026-01-31", "2026-02-28", "", "", "", ""],
        "category": ["A", "B", "A", "B", "", ""]}))
    truth(directory, {"filled_x": [1, 2, 3, 4, 5, 6], "filled_y": [10, 20, 30, 40, 50, 60],
                      "date_last": "2026-06-30", "categories": ["A", "B", "A", "B", "A", "B"]})

    directory = inputs(root, "03_Data_Preparation")
    frame = pd.DataFrame({"id": range(1, 9), "group": ["A"]*4 + ["B"]*4,
                          "measurement": np.arange(1, 9, dtype=float)*10,
                          "repeat_value": np.arange(1, 9, dtype=float)*20})
    frame.loc[3, "measurement"] = np.nan
    frame = pd.concat([frame, frame.iloc[[1, 1]]], ignore_index=True).sample(frac=1, random_state=37)
    csv(directory/"dirty.csv", frame)
    csv(directory/"labels.csv", pd.DataFrame({"group": ["A", "B"], "label": ["Control", "Treatment"]}))
    truth(directory, {"raw_rows": 10, "clean_ids": [1, 2, 3, 5, 6, 7, 8],
                      "group_means": {"A": 20., "B": 65.}, "sum": 320., "melt_rows": 14})

    directory = inputs(root, "04_Formulas")
    x = np.arange(11, dtype=float)
    csv(directory/"measurements.csv", pd.DataFrame({"x": x, "signal": 3*x + 5}))
    csv(directory/"reference.csv", pd.DataFrame({"background": .5*x + 1}))
    truth(directory, {"corrected_slope": 2.5, "corrected_intercept": 4, "rows": 11})

    directory = inputs(root, "07_Statistics")
    rng = np.random.default_rng(703)
    group = np.repeat(["A", "B", "C"], 20)
    value = np.repeat([2., 4., 6.], 20) + rng.normal(0, .35, 60)
    index = np.arange(60, dtype=float)
    csv(directory/"study.csv", pd.DataFrame({"index": index, "value": value,
        "paired": value + .4 + rng.normal(0, .1, 60), "linear": 3*index + 2, "group": group}))
    truth(directory, {"count": 60, "group_count": 3, "group_size": 20,
                      "regression_slope": 3., "regression_intercept": 2., "value_mean": float(value.mean())})

    directory = inputs(root, "13_Projects_and_Export")
    csv(directory/"measurements.csv", pd.DataFrame({"x": np.arange(21), "y": np.arange(21)*2 + 1}))
    truth(directory, {"rows": 21, "slope": 2., "intercept": 1.})

    directory = inputs(root, "14_Large_Data")
    row = np.arange(12000)
    csv(directory/"sensor_log.csv", pd.DataFrame({"row_id": row, "time_s": row*.01,
                                                  "signal": 1 + .002*row, "channel": row % 4}))
    truth(directory, {"source_rows": 12000, "window_start_zero_based": 2500, "window_rows": 400,
                      "first_id": 2500, "last_id": 2899, "signal_mean": 6.399})
