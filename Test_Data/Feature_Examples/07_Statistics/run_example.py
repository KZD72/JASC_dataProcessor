from jasc_api import Session, series, launch_recording


def run(session):
    data = session.load("input/study.csv", name="Study")
    single = session.statistics(data, operation_key="single_complete", primary_column="value", name="Single report")
    pair = session.statistics(data, operation_key="pair_complete", primary_column="value", secondary=data, secondary_column="paired", name="Pair report")
    regression = session.statistics(data, operation_key="pair_linear_regression", primary_column="index", secondary=data, secondary_column="linear", name="Regression")
    multi = session.statistics(data, operation_key="multi_complete", columns=["value", "paired", "index"], name="Multi report")
    grouped = session.statistics(data, operation_key="group_complete", primary_column="value", secondary=data, secondary_column="group", name="Group report")
    normal = session.statistics_plot_data(data, kind="normal", column="value", name="Normal companion")
    groups = session.statistics_plot_data(data, kind="groups", column="value", secondary=data, secondary_column="group", name="Group companion")
    histogram = session.plot([series(x=(data, "index"), y=(data, "value"), plot_type="histogram", histogram_bins=12)], name="Distribution")
    for sheet in [single, pair, regression, multi, grouped, normal, groups]:
        session.export_data(sheet, "tables/" + sheet.name + ".csv")
    session.export_plot(histogram, "figures/distribution.png")


if __name__ == "__main__":
    launch_recording(__file__)
