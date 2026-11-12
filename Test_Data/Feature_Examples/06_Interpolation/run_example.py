from jasc_api import Session, series, launch_recording


def run(session):
    line = session.load("input/line.csv", name="Line source")
    plane = session.load("input/plane.csv", name="Plane source")
    volume = session.load("input/volume.csv", name="Volume source")
    line_query = session.interpolate(line, coordinate_columns=["x"], value_column="value", name="Line query", method="pchip", ranges=[(0., 4., 17)])
    plane_query = session.interpolate(plane, coordinate_columns=["x", "y"], value_column="z", name="Plane query", method="linear", ranges=[(-1., 1., 9), (-1., 1., 9)], mesh=True)
    center = session.interpolate(volume, coordinate_columns=["x", "y", "z"], value_column="value", name="Volume center", method="linear", manual_points="0.5, 0.5, 0.5")
    outside = session.interpolate(line, coordinate_columns=["x"], value_column="value", name="Outside blank", method="linear", manual_points="-1\n0\n4\n5", fill_policy="nan")
    for sheet in [line_query, plane_query, center, outside]:
        session.export_data(sheet, "tables/" + sheet.name + ".csv")


if __name__ == "__main__":
    launch_recording(__file__)
