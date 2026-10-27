"""A read-only, asynchronously replaced row/column window for large tables."""

from __future__ import annotations

import csv
from io import StringIO

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableView, QVBoxLayout, QWidget,
)

from core.large_data import DISPLAY_COLUMNS, DISPLAY_ROWS, LargeDataset, TablePage
from ui.background_jobs import BackgroundJobController


class PagedTableModel(QAbstractTableModel):
    """Keep exactly one bounded page; cell callbacks never do I/O."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.page: TablePage | None = None

    def set_page(self, page: TablePage | None) -> None:
        self.beginResetModel()
        self.page = page
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() or self.page is None else self.page.frame.height

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() or self.page is None else self.page.frame.width

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> str | None:
        if not index.isValid() or self.page is None or role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        value = self.page.frame.item(index.row(), index.column())
        return "" if value is None else str(value)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> str | None:
        if self.page is None or role != Qt.DisplayRole:
            return None
        if orientation == Qt.Vertical:
            return str(self.page.row_start + section + 1)
        return self.page.frame.columns[section]


class LargeDataView(QWidget):
    """Coalesce window requests and reject obsolete worker results by generation."""

    worksheet_requested = Signal(object, object)
    idle = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.source: LargeDataset | None = None
        self.model = PagedTableModel(self)
        self.jobs = BackgroundJobController(self)
        self.jobs.finished.connect(self._finished)
        self._generation = 0
        self._desired: tuple[int, int, int] | None = None
        self._loaded: tuple[int, int, int] | None = None
        self._stopping = False
        self._bottom_after_load = False
        self._request_timer = QTimer(self)
        self._request_timer.setSingleShot(True)
        self._request_timer.setInterval(40)
        self._request_timer.timeout.connect(self._start_pending)
        self.summary = QLabel("No large dataset selected")
        self.summary.setWordWrap(True)
        self.table = QTableView(self)
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.viewport().installEventFilter(self)
        self.table.horizontalHeader().setDefaultSectionSize(140)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.row_input = QLineEdit("1")
        self.row_input.setMaximumWidth(150)
        self.row_input.returnPressed.connect(self._go_to_row)
        self.previous = QPushButton("Previous rows")
        self.next = QPushButton("Next rows")
        self.previous.clicked.connect(lambda: self._move_rows(-1))
        self.next.clicked.connect(lambda: self._move_rows(1))
        self.previous_columns = QPushButton("Previous columns")
        self.next_columns = QPushButton("Next columns")
        self.previous_columns.clicked.connect(lambda: self._move_columns(-1))
        self.next_columns.clicked.connect(lambda: self._move_columns(1))
        self.extract = QPushButton("Create worksheet from this window")
        self.extract.clicked.connect(self._extract)
        self.retry = QPushButton("Retry")
        self.retry.clicked.connect(self._retry)
        self.retry.hide()
        go = QPushButton("Go to row")
        go.clicked.connect(self._go_to_row)
        navigation = QHBoxLayout()
        for widget in (self.previous, self.next, self.row_input, go, self.previous_columns, self.next_columns):
            navigation.addWidget(widget)
        navigation.addStretch()
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addLayout(navigation)
        layout.addWidget(self.table)
        layout.addWidget(self.retry)
        layout.addWidget(self.extract)
        note = QLabel("Read-only large dataset. Scroll past a window edge to load adjacent rows, or jump to a row. Create a worksheet to analyse or edit the displayed rows and columns.")
        note.setWordWrap(True)
        layout.addWidget(note)
        copy = QShortcut(QKeySequence.Copy, self.table)
        copy.setContext(Qt.WidgetWithChildrenShortcut)
        copy.activated.connect(self._copy_selection)
        self._set_ready(False)

    def set_source(self, source: LargeDataset | None) -> None:
        self._generation += 1
        self.jobs.cancel()
        self.source = source
        self._bottom_after_load = False
        self._desired = self._loaded = None
        self.model.set_page(None)
        self._set_ready(False)
        self.retry.hide()
        if source is None:
            self.summary.setText("No large dataset selected")
        else:
            self.request_window(0, 0)

    def request_window(self, row: int, column: int = 0) -> None:
        """Navigation holds just the latest desired window, not a queue of pages."""
        if self.source is None or self._stopping:
            return
        row = max(0, min(row, max(0, self.source.row_count - 1)))
        column = max(0, min(column, max(0, len(self.source.columns) - 1)))
        key = (self._generation, row, column)
        if key == self._desired and self._loaded == key:
            return
        self._desired = key
        self.model.set_page(None)  # Evict the previous window immediately.
        self._loaded = None
        self._set_ready(False)
        self.retry.hide()
        self.summary.setText(f"{self.source.name}: loading rows from {row + 1:,} of {self.source.row_count:,}...")
        self._request_timer.start()

    def _start_pending(self) -> None:
        if self._stopping or self.jobs.is_running or self.source is None:
            return
        key, source = self._desired, self.source
        if key is None or key == self._loaded:
            return

        def received(page: TablePage) -> None:
            if key != self._desired or source is not self.source or self._stopping:
                return
            self.model.set_page(page)
            if self._bottom_after_load:
                self.table.scrollToBottom()
            self._bottom_after_load = False
            self._loaded = key
            self.row_input.setText(str(page.row_start + 1))
            end = page.row_start + page.frame.height
            start = page.row_start + 1 if page.frame.height else 0
            self.summary.setText(
                f"{source.name}: rows {start:,}-{end:,} of {source.row_count:,}; "
                f"columns {page.column_start + 1}-{page.column_start + page.frame.width} of {len(source.columns):,}"
            )
            self._set_ready(True)

        def failed(message: str) -> None:
            if key == self._desired and source is self.source and not self._stopping:
                self.summary.setText(f"Could not load window: {message}")
                self.retry.show()
                # Mark this request handled, avoiding an automatic error loop.
                self._loaded = key

        self.jobs.start(
            lambda context: source.read_page(key[1], key[2], context=context),
            on_success=received, on_error=failed, on_cancelled=lambda: None,
        )

    def _finished(self) -> None:
        if not self._stopping and self._desired != self._loaded:
            self._request_timer.start()
        self.idle.emit()

    def _retry(self) -> None:
        self._loaded = None
        self.retry.hide()
        self._start_pending()

    def _set_ready(self, ready: bool) -> None:
        page = self.model.page
        self.extract.setEnabled(ready and page is not None and bool(page.frame.height))
        # Row/column navigation can coalesce requests while another page loads.
        source = self.source
        row = self._desired[1] if self._desired else 0
        column = self._desired[2] if self._desired else 0
        height = page.frame.height if page is not None else DISPLAY_ROWS
        self.previous.setEnabled(source is not None and row > 0)
        self.next.setEnabled(source is not None and row + height < source.row_count)
        self.previous_columns.setEnabled(source is not None and column > 0)
        self.next_columns.setEnabled(source is not None and column + DISPLAY_COLUMNS < len(source.columns))

    def _move_rows(self, direction: int) -> None:
        if self._desired:
            page = self.model.page
            step = max(1, page.frame.height) if page is not None else DISPLAY_ROWS
            self.request_window(self._desired[1] + direction * step, self._desired[2])

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Wheel past an edge replaces the window instead of growing a cache."""
        if watched is self.table.viewport() and event.type() == QEvent.Wheel and self.model.page is not None:
            delta = event.angleDelta().y() or event.pixelDelta().y()
            bar = self.table.verticalScrollBar()
            if delta < 0 and bar.value() == bar.maximum() and self.next.isEnabled():
                self._bottom_after_load = False
                self._move_rows(1)
                return True
            if delta > 0 and bar.value() == bar.minimum() and self.previous.isEnabled():
                self._bottom_after_load = True
                self._move_rows(-1)
                return True
        return super().eventFilter(watched, event)

    def _move_columns(self, direction: int) -> None:
        if self._desired:
            self.request_window(self._desired[1], self._desired[2] + direction * DISPLAY_COLUMNS)

    def _go_to_row(self) -> None:
        try:
            row = int(self.row_input.text().replace(",", "")) - 1
            if self.source is None or row < 0 or row >= self.source.row_count:
                raise ValueError
        except ValueError:
            self.summary.setText("Enter a row number within the dataset.")
            return
        self.request_window(row, self._desired[2] if self._desired else 0)

    def _extract(self) -> None:
        if self.source is not None and self.model.page is not None:
            self.worksheet_requested.emit(self.source, self.model.page)

    def _copy_selection(self) -> None:
        indexes = self.table.selectionModel().selectedIndexes()
        if not indexes:
            return
        selected = {(index.row(), index.column()) for index in indexes}
        rows = [index.row() for index in indexes]
        columns = [index.column() for index in indexes]
        stream = StringIO(newline="")
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        for row in range(min(rows), max(rows) + 1):
            writer.writerow([
                self.model.data(self.model.index(row, column)) if (row, column) in selected else ""
                for column in range(min(columns), max(columns) + 1)
            ])
        QApplication.clipboard().setText(stream.getvalue())

    def shutdown(self) -> None:
        """Stop scheduling; the parent must retain us until jobs has stopped."""
        self._stopping = True
        self._desired = None
        self._request_timer.stop()
        self.jobs.cancel()
