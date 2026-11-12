from jasc_api import Session, series, launch_recording


def run(session):
    data = session.load("input/measurements.csv", name="Measurements")
    reference = session.load("input/reference.csv", name="Reference")
    session.formula(data, output_column="corrected", expression='col("signal") - sheet("Reference", "background")')
    session.formula(data, output_column="squared", expression='np.square(col("corrected"))')
    session.formula(data, output_column="selected", expression='col("corrected")')
    session.formula(data, output_column="selected", expression='-col("corrected")', row_positions=[0, 2])
    session.export_data(data, "tables/formulas.csv")


if __name__ == "__main__":
    launch_recording(__file__)
