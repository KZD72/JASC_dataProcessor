from jasc_api import Session, series, launch_recording


def run(session):
    data = session.load("input/measurements.csv", name="Measurements")
    plot = session.plot([series(x=(data, "x"), y=(data, "y"), plot_type="line_marker", marker="o")], name="Saved plot", settings={"title": "Project round-trip: y = 2x + 1"})
    session.export_data(data, "tables/measurements.csv")
    session.export_data(data, "tables/measurements.tsv", delimiter="\t")
    session.export_plot(plot, "figures/measurement.png")
    session.export_plot(plot, "figures/measurement.svg")
    session.export_plot(plot, "figures/measurement.pdf")
    session.save_project("example.jasc")


if __name__ == "__main__":
    launch_recording(__file__)
