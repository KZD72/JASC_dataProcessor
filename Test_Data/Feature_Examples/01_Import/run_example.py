# Allowed input folder: this 01_Import directory. Start with an empty project.
from jasc_api import Session, series, launch_recording


def run(session):
    comma = session.load("input/comma.csv", name="Comma")
    tab = session.load("input/tab.txt", name="Tab")
    metadata = session.load("input/preamble.txt", name="Preamble", delimiter=";", skip_rows=2, has_header=True)
    no_header = session.load("input/headerless.dat", name="Headerless", delimiter=" ", has_header=False)
    decimal = session.load("input/decimal_comma.txt", name="Decimal comma", delimiter=";", number_format="comma_decimal")
    ansi = session.load("input/cp1252.txt", name="ANSI", delimiter=";", encoding="cp1252")
    utf16 = session.load("input/utf16.txt", name="UTF16")
    excel = session.load_excel("input/two_sheets.xlsx", worksheet="Measurements", name="Excel measurements")
    groups = session.load_excel("input/two_sheets.xlsx", worksheet="Groups", name="Excel groups")
    for sheet in [comma, tab, metadata, no_header, decimal, ansi, utf16, excel, groups]:
        session.export_data(sheet, "tables/" + sheet.name + ".csv")


if __name__ == "__main__":
    launch_recording(__file__)
