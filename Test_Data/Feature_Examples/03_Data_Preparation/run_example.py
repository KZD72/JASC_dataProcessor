from jasc_api import Session, series, launch_recording


def run(session):
    raw = session.load("input/dirty.csv", name="Raw")
    labels = session.load("input/labels.csv", name="Labels")
    valid = session.prepare(raw, operation="missing", name="Valid", columns=["measurement"], strategy="drop_rows")
    unique = session.prepare(valid, operation="duplicates", name="Unique", columns=["id"], keep="first")
    clean = session.prepare(unique, operation="sort", name="Clean", columns=["id"], ascending=True)
    filtered = session.prepare(clean, operation="filter", name="Filtered", condition={"column": "measurement", "operator": "gt", "value": "50"})
    subset = session.prepare(clean, operation="subset", name="Odd rows", row_mode="odd")
    grouped = session.prepare(clean, operation="group", name="Grouped", group_columns=["group"], value_columns=["measurement"], aggregations=["count", "mean", "sum"])
    joined = session.prepare(clean, operation="merge", name="Joined", other=labels, left_key="group", right_key="group", how="left")
    melted = session.prepare(clean, operation="reshape", name="Long form", mode="melt", id_columns=["id"], value_columns=["measurement", "repeat_value"])
    bins = session.prepare(clean, operation="bin", name="Binned", bin_column="id", value_columns=["measurement"], bin_count=2)
    for sheet in [clean, filtered, subset, grouped, joined, melted, bins]:
        session.export_data(sheet, "tables/" + sheet.name + ".csv")


if __name__ == "__main__":
    launch_recording(__file__)
