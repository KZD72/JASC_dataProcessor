from jasc_api import Session, series, launch_recording


def run(session):
    source = session.load_large("input/sensor_log.csv", delimiter=",", has_header=True)
    window = session.extract_window(source, name="Explicit window", row_start=2500, row_count=400, column_start=0, column_count=4)
    summary = session.statistics(window, operation_key="single_summary", primary_column="signal", name="Window statistics")
    session.export_data(window, "tables/window.csv")
    session.export_data(summary, "tables/window_statistics.csv")
    # _jasc_result.jasc retains the disk-backed source as well as this small window.


if __name__ == "__main__":
    launch_recording(__file__)
