# Replays semantic edits, rather than keyboard/mouse coordinates.
from jasc_api import Session, series, launch_recording


def run(session):
    seeds = session.load("input/numeric_seeds.csv", name="Seeds")
    session.edit(seeds, operation="smart_fill_selection", parameters={
        "start_row": 0, "end_row": 5, "start_column": 0, "end_column": 1, "mode": "numeric"})
    session.edit(seeds, operation="undo", parameters={})
    session.edit(seeds, operation="redo", parameters={})
    session.edit(seeds, operation="set_column_metadata", parameters={"metadata": {
        "x": {"__metadata__": {"role": "x", "unit": "s", "long_name": "Time", "value_type": "numeric"}},
        "y": {"__metadata__": {"role": "y", "unit": "V", "long_name": "Signal", "value_type": "numeric"}}}})
    manual = session.new_sheet("Manual", rows=4)
    session.edit(manual, operation="paste_block", parameters={
        "start_row": 0, "start_column": 0, "rows": [[0, 1], [1, 3], [2, 5], [3, 7]]})
    session.edit(manual, operation="fill_range", parameters={
        "target_column": "sequence", "start_row": 0, "count": 4, "start_value": 100., "step": 5.})
    duplicate = session.duplicate_sheet(manual)
    session.rename_sheet(duplicate, "Temporary copy")
    session.delete_sheet(duplicate)
    session.export_data(seeds, "tables/filled.csv")
    session.export_data(manual, "tables/manual.csv")


if __name__ == "__main__":
    launch_recording(__file__)
