"""Retarget serialized plot-editor bindings alongside applied plot definitions."""

from __future__ import annotations


def rename_editor_dataset(editor: dict[str, object], old: str, new: str) -> None:
    for name, control in editor.get("controls", {}).items():
        if name.endswith("_dataset_combo") and isinstance(control, dict):
            if control.get("text") == old:
                control["text"] = new
            if control.get("data") == old:
                control["data"] = new


def rename_editor_columns(editor: dict[str, object], dataset: str, names: dict[str, str]) -> None:
    controls = editor.get("controls", {})
    bindings = {
        "_x_dataset_combo": ("_x_column_combo", "_x_err_column_combo", "_x_bounds_lower_combo", "_x_bounds_upper_combo"),
        "_y_dataset_combo": ("_y_column_combo", "_y_err_column_combo", "_y_bounds_lower_combo", "_y_bounds_upper_combo"),
        "_z_dataset_combo": ("_z_column_combo",),
        "_spectral_dataset_combo": ("_spectral_column_combo",),
    }
    for binding, columns in bindings.items():
        source = controls.get(binding, {})
        if source.get("text") != dataset and source.get("data") != dataset:
            continue
        for column in columns:
            control = controls.get(column, {})
            for key in ("text", "data"):
                value = control.get(key)
                if isinstance(value, str) and value in names:
                    control[key] = names[value]
        if binding == "_y_dataset_combo":
            editor["distribution_columns"] = [names.get(value, value)
                                               for value in editor.get("distribution_columns", [])]
