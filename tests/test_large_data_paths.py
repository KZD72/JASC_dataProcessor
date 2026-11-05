"""Regression tests for optimized clipboard, editor refresh, and project I/O paths."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from core import project_io
from core.clipboard_io import parse_tabular_clipboard
from core.workspace import Workspace
from ui.dataframe_model import DataFrameTableModel
from ui.main_window import MainWindow


class ClipboardBlockTests(unittest.TestCase):
    """Protect clipboard token semantics and block-oriented model updates."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_parser_preserves_text_columns_quotes_and_embedded_newlines(self) -> None:
        block = parse_tabular_clipboard(
            '001\t"a\tb"\n002\t"line 1\nline 2"\n',
            text_columns={0},
        )

        self.assertEqual(block.shape, (2, 2))
        self.assertEqual(block.iloc[0, 0], "001")
        self.assertEqual(block.iloc[0, 1], "a\tb")
        self.assertEqual(block.iloc[1, 1], "line 1\nline 2")

    def test_block_paste_grows_once_and_round_trips_through_undo(self) -> None:
        workspace = Workspace()
        dataset = workspace.add_dataset(
            "sheet",
            pd.DataFrame(
                {
                    "x": pd.Series([float("nan")] * 25, dtype="float64"),
                    "label": pd.Series([pd.NA] * 25, dtype="object"),
                }
            ),
        )
        dataset.formulas["x"] = "col1 * 2"
        model = DataFrameTableModel()
        model.set_dataset(dataset)
        block = parse_tabular_clipboard(
            "\n".join(f"{index}\titem-{index}\t{index + 1}" for index in range(1_000)),
            text_columns={1},
        )

        pasted_shape = model.paste_block(0, 0, block)

        self.assertEqual(pasted_shape, (1_000, 3))
        self.assertEqual(dataset.frame.shape, (1_000, 3))
        self.assertEqual(dataset.frame.iloc[999, 0], 999.0)
        self.assertEqual(dataset.frame.iloc[999, 1], "item-999")
        self.assertEqual(dataset.frame.iloc[999, 2], 1000.0)
        self.assertNotIn("x", dataset.formulas)

        self.assertTrue(model.undo())
        self.assertEqual(dataset.frame.shape, (25, 2))
        self.assertEqual(dataset.formulas["x"], "col1 * 2")
        self.assertTrue(model.redo())
        self.assertEqual(dataset.frame.shape, (1_000, 3))

    def test_numeric_metadata_rejects_invalid_clipboard_without_history_entry(self) -> None:
        workspace = Workspace()
        dataset = workspace.add_dataset("sheet", pd.DataFrame({"x": [1.0, 2.0]}))
        dataset.metadata_for_column("x").value_type = "numeric"
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        with self.assertRaisesRegex(ValueError, "not numeric"):
            model.paste_block(0, 0, pd.DataFrame([["bad"]]))

        self.assertFalse(model.can_undo())
        self.assertEqual(dataset.frame["x"].tolist(), [1.0, 2.0])

    def test_whole_column_paste_bulk_grows_and_infers_numeric_values(self) -> None:
        dataset = Workspace().add_dataset("sheet", pd.DataFrame({"existing": [1, 2]}))
        model = DataFrameTableModel()
        model.set_dataset(dataset)
        block = parse_tabular_clipboard("1\ta\n2\tb\n3\tc")

        inserted = model.insert_columns(0, ["number", "label"], block)

        self.assertEqual(inserted, ["number", "label"])
        self.assertEqual(dataset.frame.shape, (3, 3))
        self.assertEqual(dataset.frame["number"].tolist(), [1, 2, 3])
        self.assertEqual(dataset.frame["label"].tolist(), ["a", "b", "c"])
        self.assertTrue(model.undo())
        self.assertEqual(dataset.frame.shape, (2, 1))

    def test_clear_cells_preserves_shape_and_is_one_undoable_edit(self) -> None:
        dataset = Workspace().add_dataset(
            "sheet",
            pd.DataFrame({"x": [1, 2, 3], "y": [4.0, 5.0, 6.0]}),
        )
        dataset.formulas = {"x": "col1 * 2", "y": "col2 + 1"}
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        cleared = model.clear_cells([(0, 0, 1, 0), (2, 1, 2, 1)])

        self.assertEqual(cleared, 3)
        self.assertEqual(dataset.frame.shape, (3, 2))
        self.assertTrue(dataset.frame.iloc[:2, 0].isna().all())
        self.assertTrue(pd.isna(dataset.frame.iloc[2, 1]))
        self.assertEqual(dataset.frame.iloc[2, 0], 3.0)
        self.assertNotIn("x", dataset.formulas)
        self.assertNotIn("y", dataset.formulas)
        self.assertTrue(model.undo())
        pd.testing.assert_frame_equal(
            dataset.frame,
            pd.DataFrame({"x": [1, 2, 3], "y": [4.0, 5.0, 6.0]}),
        )

    def test_resize_sheet_changes_both_dimensions_and_restores_metadata_on_undo(self) -> None:
        dataset = Workspace().add_dataset(
            "sheet",
            pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [4.0, 5.0, 6.0]}),
        )
        dataset.formulas["y"] = "col1 * 2"
        dataset.metadata_for_column("y").unit = "V"
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        self.assertEqual(model.resize_sheet(2, 1), (2, 1))
        self.assertEqual(dataset.frame.shape, (2, 1))
        self.assertNotIn("y", dataset.formulas)
        self.assertNotIn("y", dataset.column_metadata)
        self.assertTrue(model.undo())
        self.assertEqual(dataset.frame.shape, (3, 2))
        self.assertEqual(dataset.formulas["y"], "col1 * 2")
        self.assertEqual(dataset.column_metadata["y"].unit, "V")

        self.assertEqual(model.resize_sheet(5, 4), (5, 4))
        self.assertEqual(dataset.frame.shape, (5, 4))
        self.assertEqual(list(dataset.frame.columns[:2]), ["x", "y"])
        self.assertTrue(dataset.frame.iloc[3:, :].isna().all().all())

    def test_large_fill_range_uses_bulk_growth_and_assignment(self) -> None:
        dataset = Workspace().add_dataset("sheet", pd.DataFrame({"x": [float("nan")]}))
        model = DataFrameTableModel()
        model.set_dataset(dataset)

        result_column = model.fill_range("x", 1, 10_000, 0.0, 0.5)

        self.assertEqual(result_column, "x")
        self.assertEqual(dataset.frame.shape, (10_000, 1))
        self.assertEqual(dataset.frame.iloc[-1, 0], 4_999.5)

    def test_history_is_bounded_by_entry_count(self) -> None:
        dataset = Workspace().add_dataset("sheet", pd.DataFrame({"x": [0.0]}))
        model = DataFrameTableModel()
        model._max_history_entries = 3
        model.set_dataset(dataset)

        index = model.index(0, 0)
        for value in range(1, 7):
            self.assertTrue(model.setData(index, str(value), Qt.EditRole))

        self.assertEqual(len(model._undo_stack), 3)

    def test_oversized_history_snapshot_is_not_copied_or_retained(self) -> None:
        dataset = Workspace().add_dataset("sheet", pd.DataFrame({"x": [0.0]}))
        model = DataFrameTableModel()
        model._max_history_bytes = 1
        model.set_dataset(dataset)

        with patch.object(model, "_snapshot", side_effect=AssertionError("snapshot copied")):
            self.assertTrue(model.setData(model.index(0, 0), "1", Qt.EditRole))

        self.assertFalse(model.can_undo())


class EditorRefreshTests(unittest.TestCase):
    """Ensure dataset attachment and history changes avoid redundant table scans."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()

    def tearDown(self) -> None:
        with patch.object(self.window, "_confirm_project_plot_changes", return_value=True):
            self.window.close()

    def test_dataset_list_refresh_attaches_and_sizes_once(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "sheet",
            pd.DataFrame({"x": range(1_000), "y": range(1_000)}),
        )
        with (
            patch.object(
                self.window,
                "_show_dataset_editor",
                wraps=self.window._show_dataset_editor,
            ) as show_editor,
            patch.object(
                self.window,
                "_resize_dataset_columns_to_contents",
                wraps=self.window._resize_dataset_columns_to_contents,
            ) as resize_columns,
        ):
            self.window._refresh_dataset_list(dataset.name)

        self.assertEqual(show_editor.call_count, 1)
        self.assertEqual(resize_columns.call_count, 1)

    def test_cell_edit_does_not_trigger_column_resizing(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "sheet",
            pd.DataFrame({"x": [1.0], "y": [2.0]}),
        )
        self.window._show_dataset_editor(dataset.name)

        with patch.object(self.window, "_resize_dataset_columns_to_contents") as resize_columns:
            changed = self.window._dataset_model.setData(
                self.window._dataset_model.index(0, 0),
                "3",
                Qt.EditRole,
            )

        self.assertTrue(changed)
        resize_columns.assert_not_called()

    def test_clipboard_availability_check_does_not_parse_contents(self) -> None:
        QApplication.clipboard().setText("1\t2\n3\t4")

        with (
            patch.object(
                self.window,
                "_parse_clipboard_text",
                side_effect=AssertionError("clipboard was parsed eagerly"),
            ),
            patch.object(
                self.window,
                "_clipboard_dataset_columns",
                side_effect=AssertionError("clipboard columns were decoded eagerly"),
            ),
        ):
            self.assertTrue(self.window._clipboard_has_dataset_columns())

    def test_large_selection_context_menu_does_not_enumerate_selected_cells(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "large",
            pd.DataFrame({f"c{column}": range(20_000) for column in range(12)}),
        )
        self.window._refresh_dataset_list(dataset.name)
        self.window._dataset_table.selectAll()

        with (
            patch.object(
                self.window,
                "_selected_dataset_indexes",
                side_effect=AssertionError("context menu enumerated selected cells"),
            ),
            patch.object(
                self.window,
                "_selected_dataset_columns",
                side_effect=AssertionError("context menu expanded selected columns"),
            ),
            patch("ui.main_window.QMenu") as menu_class,
        ):
            menu_class.return_value.exec.return_value = None
            self.window._show_dataset_editor_context_menu(QPoint(0, 0), context_column=0)

        action_labels = [
            call.args[0]
            for call in menu_class.return_value.addAction.call_args_list
            if call.args
        ]
        self.assertIn("Copy Row(s)", action_labels)
        self.assertIn("Paste Values Transposed", action_labels)
        self.assertIn("Clear Selected Cell Values", action_labels)
        self.assertIn("Resize Sheet...", action_labels)

    def test_delete_clears_cells_and_modified_delete_removes_structure(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "sheet",
            pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [4.0, 5.0, 6.0]}),
        )
        self.window._refresh_dataset_list(dataset.name)
        self.window.show()
        self.window._dataset_table.setFocus()
        self.window._dataset_table.selectRow(1)
        self.app.processEvents()

        QTest.keyClick(self.window._dataset_table, Qt.Key_Delete)
        self.app.processEvents()
        self.assertEqual(len(dataset.frame), 3)
        self.assertEqual(list(dataset.frame.columns), ["x", "y"])
        self.assertTrue(dataset.frame.iloc[1].isna().all())

        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as question,
            patch.object(QMessageBox, "information") as information,
        ):
            QTest.keyClick(
                self.window._dataset_table,
                Qt.Key_Delete,
                Qt.ShiftModifier,
            )
            self.app.processEvents()
        self.assertTrue(question.called)
        information.assert_not_called()
        self.assertEqual(len(dataset.frame), 2)

        self.window._select_dataset_column_range(0, 1)
        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as question,
            patch.object(QMessageBox, "information") as information,
        ):
            QTest.keyClick(
                self.window._dataset_table,
                Qt.Key_Delete,
                Qt.ControlModifier,
            )
            self.app.processEvents()
        self.assertTrue(question.called)
        information.assert_not_called()
        self.assertEqual(list(dataset.frame.columns), ["y"])
        self.assertEqual(self.window._delete_cells_action.shortcut().toString(), "Del")
        self.assertEqual(self.window._delete_rows_action.shortcut().toString(), "Shift+Del")
        self.assertEqual(self.window._delete_columns_action.shortcut().toString(), "Ctrl+Del")

    def test_transposed_paste_rotates_the_complete_clipboard_matrix(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "sheet",
            pd.DataFrame({"a": [0.0, 0.0, 0.0], "b": [0.0, 0.0, 0.0]}),
        )
        self.window._refresh_dataset_list(dataset.name)
        self.window._dataset_table.setCurrentIndex(self.window._dataset_model.index(0, 0))
        QApplication.clipboard().setText("1\t2\t3\n4\t5\t6")

        self.window._paste_dataset_clipboard(transpose=True)

        self.assertEqual(dataset.frame.iloc[:3, :2].values.tolist(), [[1, 4], [2, 5], [3, 6]])
        self.assertEqual(
            self.window._dataset_table.selectionModel().selection()[0].bottom(),
            2,
        )

    def test_row_header_context_selects_rows_and_body_menu_remains_available(self) -> None:
        dataset = self.window._workspace.add_dataset(
            "sheet",
            pd.DataFrame({"a": [1, 2], "b": [3, 4]}),
        )
        self.window._refresh_dataset_list(dataset.name)
        header = self.window._dataset_table.verticalHeader()
        row_position = QPoint(2, header.sectionViewportPosition(1) + 2)

        with patch.object(self.window, "_show_dataset_editor_context_menu") as show_menu:
            self.window._show_dataset_row_header_context_menu(row_position)

        self.assertEqual(self.window._selected_dataset_rows(), [1])
        self.assertEqual(self.window._selected_dataset_columns(), [0, 1])
        self.assertEqual(show_menu.call_args.kwargs["context_row"], 1)
        self.window._copy_dataset_rows()
        self.assertEqual(QApplication.clipboard().text(), "2\t4")
        self.assertEqual(
            self.window._dataset_table.viewport().contextMenuPolicy(),
            Qt.CustomContextMenu,
        )
        self.assertEqual(header.contextMenuPolicy(), Qt.CustomContextMenu)


class ProjectStreamingTests(unittest.TestCase):
    """Protect streamed project persistence and ownership-transfer behavior."""

    def test_project_round_trip_uses_streamed_dataset_members(self) -> None:
        workspace = Workspace()
        dataset = workspace.add_dataset(
            "sheet",
            pd.DataFrame({"x": [1.0, 2.0], "label": ["a", "b"]}),
        )
        dataset.metadata_for_column("x").role = "x"
        dataset.sync_column_metadata_attrs()
        dataset.worksheet_metadata.fields = [("Instrument", "Raman")]
        dataset.worksheet_metadata.raw_lines = ["#Instrument=Raman"]
        dataset.worksheet_metadata.import_details = {"Format": "Delimited text"}

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "streamed.jasc"
            project_io.save_project(workspace, path)
            integrity = project_io.verify_project_integrity(path)
            with zipfile.ZipFile(path, "r") as archive:
                project_metadata = json.loads(archive.read("project.json"))
                manifest = json.loads(archive.read("integrity.json"))
            loaded = project_io.load_project(path)

        self.assertTrue(integrity.has_manifest)
        self.assertTrue(integrity.verified)
        self.assertEqual(integrity.problems, ())
        self.assertEqual(project_metadata["version"], 8)
        self.assertEqual(manifest["schema"], "jasc-package-seal-v1")
        self.assertEqual(manifest["algorithm"], "sha256")
        self.assertEqual(len(manifest["seal"]), 64)
        self.assertEqual(len(manifest["nonce"]), 44)
        self.assertTrue(manifest["created_utc"].endswith("Z"))
        self.assertEqual(set(manifest["files"]["project.json"]), {"size", "sha256"})
        loaded_dataset = loaded.get_dataset("sheet")
        pd.testing.assert_frame_equal(loaded_dataset.frame, dataset.frame)
        self.assertEqual(loaded_dataset.column_metadata["x"].role, "x")
        self.assertEqual(
            loaded_dataset.worksheet_metadata.fields,
            [("Instrument", "Raman")],
        )
        self.assertEqual(
            loaded_dataset.worksheet_metadata.raw_lines,
            ["#Instrument=Raman"],
        )

    def test_changed_project_member_fails_integrity_check(self) -> None:
        workspace = Workspace()
        workspace.add_dataset("sheet", pd.DataFrame({"x": [1.0, 2.0]}))

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tampered.jasc"
            project_io.save_project(workspace, path)
            with zipfile.ZipFile(path, "r") as archive:
                members = {
                    entry.filename: archive.read(entry.filename)
                    for entry in archive.infolist()
                    if not entry.is_dir()
                }
            dataset_name = next(name for name in members if name.startswith("datasets/"))
            members[dataset_name] = b"x\n999\n"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, payload in members.items():
                    archive.writestr(name, payload)

            report = project_io.verify_project_integrity(path)
            with self.assertRaises(project_io.ProjectIntegrityError):
                project_io.load_project(path)
            loaded = project_io.load_project(path, allow_integrity_mismatch=True)

        self.assertTrue(report.has_manifest)
        self.assertFalse(report.verified)
        self.assertTrue(any(dataset_name in problem for problem in report.problems))
        self.assertEqual(loaded.get_dataset("sheet").frame["x"].tolist(), [999])

    def test_package_seal_rejects_recalculated_member_hash_and_size(self) -> None:
        workspace = Workspace()
        workspace.add_dataset("sheet", pd.DataFrame({"x": [1.0, 2.0]}))

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "resealed-member.jasc"
            project_io.save_project(workspace, path)
            with zipfile.ZipFile(path, "r") as archive:
                members = {
                    entry.filename: archive.read(entry.filename)
                    for entry in archive.infolist()
                    if not entry.is_dir()
                }
            dataset_name = next(name for name in members if name.startswith("datasets/"))
            forged_data = b"x\n999\n"
            members[dataset_name] = forged_data
            manifest = json.loads(members["integrity.json"])
            manifest["files"][dataset_name] = {
                "size": len(forged_data),
                "sha256": hashlib.sha256(forged_data).hexdigest(),
            }
            members["integrity.json"] = json.dumps(manifest).encode("utf-8")
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, payload in members.items():
                    archive.writestr(name, payload)

            report = project_io.verify_project_integrity(path)
            with self.assertRaises(project_io.ProjectIntegrityError):
                project_io.load_project(path)

        self.assertFalse(report.verified)
        self.assertIn("package seal mismatch", report.problems)
        self.assertFalse(any(problem == f"changed '{dataset_name}'" for problem in report.problems))

    def test_each_save_has_a_unique_package_identity_and_seal(self) -> None:
        workspace = Workspace()
        workspace.add_dataset("sheet", pd.DataFrame({"x": [1.0]}))

        with tempfile.TemporaryDirectory() as folder:
            manifests = []
            for filename in ("first.jasc", "second.jasc"):
                path = Path(folder) / filename
                project_io.save_project(workspace, path)
                with zipfile.ZipFile(path, "r") as archive:
                    manifests.append(json.loads(archive.read("integrity.json")))

        self.assertNotEqual(manifests[0]["package_uuid"], manifests[1]["package_uuid"])
        self.assertNotEqual(manifests[0]["nonce"], manifests[1]["nonce"])
        self.assertNotEqual(manifests[0]["seal"], manifests[1]["seal"])

    def test_signing_identity_is_encrypted_and_public_identity_is_shareable(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            private_path = Path(folder) / "researcher.jasc-key"
            identity, public_path = project_io.create_signing_identity(
                private_path,
                name="Researcher Name",
                password="private key password",
            )
            private_bytes = private_path.read_bytes()
            public_identity = project_io.load_public_identity(public_path)
            unlocked = project_io.load_signing_identity(
                private_path,
                password="private key password",
            )
            with self.assertRaises(project_io.SigningKeyError):
                project_io.load_signing_identity(private_path, password="wrong")

        self.assertIn(b"ENCRYPTED PRIVATE KEY", private_bytes)
        self.assertNotIn(identity.public_key, private_bytes)
        self.assertEqual(public_identity.name, "Researcher Name")
        self.assertEqual(public_identity.fingerprint, identity.fingerprint)
        self.assertEqual(unlocked.fingerprint, identity.fingerprint)

    def test_signed_project_verifies_author_key_and_identity(self) -> None:
        workspace = Workspace()
        workspace.add_dataset("signed data", pd.DataFrame({"x": [1.0, 2.0]}))

        with tempfile.TemporaryDirectory() as folder:
            identity, _public_path = project_io.create_signing_identity(
                Path(folder) / "author.jasc-key",
                name="Test Author",
                password="key password",
            )
            path = Path(folder) / "signed.jasc"
            project_io.save_project(workspace, path, signing_identity=identity)
            report = project_io.verify_project_integrity(path)
            loaded = project_io.load_project(path)
            with zipfile.ZipFile(path, "r") as archive:
                manifest = json.loads(archive.read("integrity.json"))

        self.assertTrue(report.verified)
        self.assertEqual(report.signature_status, "valid")
        self.assertEqual(report.signer_fingerprint, identity.fingerprint)
        self.assertEqual(report.signer_name, "Test Author")
        self.assertEqual(loaded.project_signature_status, "valid")
        self.assertEqual(loaded.project_signer_fingerprint, identity.fingerprint)
        self.assertEqual(manifest["signature"]["algorithm"], "ed25519")
        self.assertEqual(manifest["signature"]["signed_object"], "package_seal")

    def test_signature_rejects_fully_resealed_forged_content(self) -> None:
        workspace = Workspace()
        workspace.add_dataset("signed data", pd.DataFrame({"x": [1.0, 2.0]}))

        with tempfile.TemporaryDirectory() as folder:
            identity, _public_path = project_io.create_signing_identity(
                Path(folder) / "author.jasc-key",
                name="Test Author",
                password="key password",
            )
            path = Path(folder) / "forged-signed.jasc"
            project_io.save_project(workspace, path, signing_identity=identity)
            with zipfile.ZipFile(path, "r") as archive:
                members = {
                    entry.filename: archive.read(entry.filename)
                    for entry in archive.infolist()
                    if not entry.is_dir()
                }
            dataset_name = next(name for name in members if name.startswith("datasets/"))
            forged_data = b"x\n999\n"
            members[dataset_name] = forged_data
            manifest = json.loads(members["integrity.json"])
            manifest["files"][dataset_name] = {
                "size": len(forged_data),
                "sha256": hashlib.sha256(forged_data).hexdigest(),
            }
            manifest_core = {
                key: value
                for key, value in manifest.items()
                if key not in {"seal", "signature"}
            }
            manifest["seal"] = project_io._package_seal_digest(manifest_core)
            members["integrity.json"] = json.dumps(manifest).encode("utf-8")
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, payload in members.items():
                    archive.writestr(name, payload)

            report = project_io.verify_project_integrity(path)
            with self.assertRaises(project_io.ProjectIntegrityError):
                project_io.load_project(path)

        self.assertFalse(report.verified)
        self.assertEqual(report.signature_status, "invalid")
        self.assertIn("invalid digital signature", report.problems)
        self.assertFalse(any(problem.startswith("changed '") for problem in report.problems))

    def test_required_signature_cannot_be_silently_removed(self) -> None:
        workspace = Workspace()
        workspace.add_dataset("signed data", pd.DataFrame({"x": [1.0]}))

        with tempfile.TemporaryDirectory() as folder:
            identity, _public_path = project_io.create_signing_identity(
                Path(folder) / "author.jasc-key",
                name="Test Author",
                password="key password",
            )
            path = Path(folder) / "stripped-signature.jasc"
            project_io.save_project(workspace, path, signing_identity=identity)
            with zipfile.ZipFile(path, "r") as archive:
                members = {
                    entry.filename: archive.read(entry.filename)
                    for entry in archive.infolist()
                    if not entry.is_dir()
                }
            manifest = json.loads(members["integrity.json"])
            manifest.pop("signature")
            members["integrity.json"] = json.dumps(manifest).encode("utf-8")
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, payload in members.items():
                    archive.writestr(name, payload)

            report = project_io.verify_project_integrity(path)

        self.assertFalse(report.verified)
        self.assertEqual(report.signature_status, "invalid")
        self.assertIn("required digital signature is missing", report.problems)

    def test_encrypted_project_round_trip_is_authenticated(self) -> None:
        workspace = Workspace()
        workspace.add_dataset(
            "private data",
            pd.DataFrame({"x": [1.0, 2.0], "note": ["alpha", "beta"]}),
        )

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "private.jascx"
            project_io.save_project(workspace, path, password="correct horse battery staple")
            encrypted_bytes = path.read_bytes()
            integrity = project_io.verify_project_integrity(
                path,
                password="correct horse battery staple",
            )
            self.assertTrue(project_io.is_encrypted_project(path))
            loaded = project_io.load_project(
                path,
                password="correct horse battery staple",
            )

        self.assertFalse(encrypted_bytes.startswith(b"PK"))
        self.assertNotIn(b"private data", encrypted_bytes)
        self.assertTrue(integrity.verified)
        pd.testing.assert_frame_equal(
            loaded.get_dataset("private data").frame,
            workspace.get_dataset("private data").frame,
        )

    def test_encrypted_project_rejects_missing_wrong_and_tampered_credentials(self) -> None:
        workspace = Workspace()
        workspace.add_dataset("sheet", pd.DataFrame({"x": [1.0]}))

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "private.jascx"
            project_io.save_project(workspace, path, password="right password")
            with self.assertRaises(project_io.ProjectPasswordRequiredError):
                project_io.load_project(path)
            with self.assertRaises(project_io.ProjectDecryptionError):
                project_io.load_project(path, password="wrong password")

            payload = bytearray(path.read_bytes())
            payload[-20] ^= 0x01
            path.write_bytes(payload)
            with self.assertRaises(project_io.ProjectDecryptionError):
                project_io.load_project(path, password="right password")

    def test_encrypted_project_preserves_and_verifies_author_signature(self) -> None:
        workspace = Workspace()
        workspace.add_dataset("private signed", pd.DataFrame({"x": [1.0]}))

        with tempfile.TemporaryDirectory() as folder:
            identity, _public_path = project_io.create_signing_identity(
                Path(folder) / "author.jasc-key",
                name="Private Author",
                password="key password",
            )
            path = Path(folder) / "private-signed.jascx"
            project_io.save_project(
                workspace,
                path,
                password="project password",
                signing_identity=identity,
            )
            report = project_io.verify_project_integrity(
                path,
                password="project password",
            )
            loaded = project_io.load_project(path, password="project password")

        self.assertTrue(report.verified)
        self.assertEqual(report.signature_status, "valid")
        self.assertEqual(report.signer_fingerprint, identity.fingerprint)
        self.assertEqual(loaded.project_signature_status, "valid")

    def test_encrypted_save_as_requests_and_confirms_password(self) -> None:
        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        window = MainWindow()
        window._workspace.add_dataset("sheet", pd.DataFrame({"x": [1.0]}))
        try:
            with (
                patch(
                    "ui.main_window.QFileDialog.getSaveFileName",
                    return_value=(
                        "protected",
                        "Encrypted JASC Project (*.jascx)",
                    ),
                ),
                patch(
                    "ui.main_window.QInputDialog.getText",
                    side_effect=[("secret", True), ("secret", True)],
                ) as password_prompt,
                patch("ui.main_window.project_io.save_project") as save_project,
            ):
                window._save_project_as()

            save_project.assert_called_once_with(
                window._workspace,
                Path("protected.jascx"),
                password="secret",
            )
            self.assertEqual(window._project_path, Path("protected.jascx"))
            self.assertEqual(password_prompt.call_args_list[0].args[2], "Encryption password:")
            self.assertEqual(
                password_prompt.call_args_list[1].args[2],
                "Confirm encryption password:",
            )
        finally:
            with patch.object(window, "_confirm_project_plot_changes", return_value=True):
                window.close()

    def test_file_menu_exposes_each_project_security_save_mode(self) -> None:
        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        window = MainWindow()
        try:
            file_action = next(
                action
                for action in window.menuBar().actions()
                if action.text() == "&File"
            )
            file_menu = file_action.menu()
            self.assertIsNotNone(file_menu)
            labels = {action.text().replace("&", "") for action in file_menu.actions()}
            self.assertIn("Save Open Project As...", labels)
            self.assertIn("Save Encrypted Project As...", labels)
            self.assertIn("Save Signed Open Project As...", labels)
            self.assertIn("Save Signed + Encrypted Project As...", labels)
            self.assertIn("Signing Identities", labels)
        finally:
            with patch.object(window, "_confirm_project_plot_changes", return_value=True):
                window.close()

    def test_signed_save_as_uses_selected_private_identity(self) -> None:
        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        window = MainWindow()
        window._workspace.add_dataset("sheet", pd.DataFrame({"x": [1.0]}))
        identity = project_io.SigningPrivateIdentity(
            "Researcher",
            "SHA256:" + "a" * 64,
            b"p" * 32,
            object(),
        )
        try:
            with (
                patch(
                    "ui.main_window.QFileDialog.getOpenFileName",
                    return_value=("researcher.jasc-key", ""),
                ),
                patch(
                    "ui.main_window.QFileDialog.getSaveFileName",
                    return_value=("signed-project", "Signed Open JASC Project (*.jasc)"),
                ),
                patch(
                    "ui.main_window.QInputDialog.getText",
                    return_value=("key password", True),
                ) as key_password_prompt,
                patch(
                    "ui.main_window.project_io.load_signing_identity",
                    return_value=identity,
                ),
                patch("ui.main_window.project_io.save_project") as save_project,
            ):
                window._save_signed_project_as()

            save_project.assert_called_once_with(
                window._workspace,
                Path("signed-project.jasc"),
                password=None,
                signing_identity=identity,
            )
            self.assertEqual(window._project_signature_fingerprint, identity.fingerprint)
            self.assertEqual(window._workspace.project_signature_status, "valid")
            self.assertEqual(
                key_password_prompt.call_args.args[2],
                "Private-key password:",
            )
        finally:
            with patch.object(window, "_confirm_project_plot_changes", return_value=True):
                window.close()

    def test_main_window_prompts_to_open_encrypted_project(self) -> None:
        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        window = MainWindow()
        loaded_workspace = Workspace()
        loaded_workspace.add_dataset("private", pd.DataFrame({"x": [1.0]}))
        try:
            with (
                patch(
                    "ui.main_window.QFileDialog.getOpenFileName",
                    return_value=("private.jascx", ""),
                ),
                patch(
                    "ui.main_window.QInputDialog.getText",
                    return_value=("secret", True),
                ),
                patch(
                    "ui.main_window.project_io.load_project",
                    side_effect=[
                        project_io.ProjectPasswordRequiredError("password needed"),
                        loaded_workspace,
                    ],
                ) as load_project,
            ):
                window._open_project()

            self.assertEqual(window._workspace.dataset_names(), ["private"])
            self.assertEqual(window._project_password, "secret")
            self.assertEqual(load_project.call_count, 2)
            self.assertEqual(load_project.call_args.kwargs["password"], "secret")
        finally:
            with patch.object(window, "_confirm_project_plot_changes", return_value=True):
                window.close()

    def test_failed_save_keeps_existing_project_file(self) -> None:
        workspace = Workspace()
        workspace.add_dataset("sheet", pd.DataFrame({"x": [1.0]}))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "existing.jasc"
            path.write_bytes(b"previous project bytes")
            with (
                patch(
                    "core.project_io._write_project_archive",
                    side_effect=RuntimeError("simulated write failure"),
                ),
                self.assertRaises(RuntimeError),
            ):
                project_io.save_project(workspace, path)

            self.assertEqual(path.read_bytes(), b"previous project bytes")

    def test_unsigned_version_four_project_remains_backward_compatible(self) -> None:
        workspace = Workspace()
        workspace.add_dataset("legacy", pd.DataFrame({"x": [1.0]}))

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.jasc"
            project_io.save_project(workspace, path)
            with zipfile.ZipFile(path, "r") as archive:
                members = {
                    entry.filename: archive.read(entry.filename)
                    for entry in archive.infolist()
                    if not entry.is_dir() and entry.filename != "integrity.json"
                }
            metadata = json.loads(members["project.json"].decode("utf-8"))
            metadata["version"] = 4
            members["project.json"] = json.dumps(metadata).encode("utf-8")
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, payload in members.items():
                    archive.writestr(name, payload)

            report = project_io.verify_project_integrity(path)
            loaded = project_io.load_project(path)

        self.assertFalse(report.has_manifest)
        self.assertFalse(report.verified)
        self.assertEqual(loaded.dataset_names(), ["legacy"])

    def test_version_five_hash_manifest_remains_backward_compatible(self) -> None:
        workspace = Workspace()
        workspace.add_dataset("version five", pd.DataFrame({"x": [1.0]}))

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "version-five.jasc"
            project_io.save_project(workspace, path)
            with zipfile.ZipFile(path, "r") as archive:
                members = {
                    entry.filename: archive.read(entry.filename)
                    for entry in archive.infolist()
                    if not entry.is_dir() and entry.filename != "integrity.json"
                }
            metadata = json.loads(members["project.json"])
            metadata["version"] = 5
            members["project.json"] = json.dumps(metadata).encode("utf-8")
            legacy_manifest = {
                "algorithm": "sha256",
                "files": {
                    name: hashlib.sha256(payload).hexdigest()
                    for name, payload in members.items()
                },
            }
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, payload in members.items():
                    archive.writestr(name, payload)
                archive.writestr("integrity.json", json.dumps(legacy_manifest))

            report = project_io.verify_project_integrity(path)
            loaded = project_io.load_project(path)

        self.assertTrue(report.has_manifest)
        self.assertTrue(report.verified)
        self.assertEqual(loaded.dataset_names(), ["version five"])

    def test_main_window_warns_before_opening_forged_package(self) -> None:
        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        window = MainWindow()
        integrity_error = project_io.ProjectIntegrityError(
            project_io.ProjectIntegrityReport(
                has_manifest=True,
                verified=False,
                problems=("changed 'datasets/sheet.csv'",),
            )
        )
        try:
            with (
                patch(
                    "ui.main_window.QFileDialog.getOpenFileName",
                    return_value=("forged.jasc", ""),
                ),
                patch(
                    "ui.main_window.project_io.load_project",
                    side_effect=integrity_error,
                ),
                patch.object(
                    QMessageBox,
                    "warning",
                    return_value=QMessageBox.Cancel,
                ) as warning,
            ):
                window._open_project()

            warning.assert_called_once()
            self.assertIn("may have been forged", warning.call_args.args[2])
            self.assertEqual(window._workspace.dataset_names(), [])
        finally:
            with patch.object(window, "_confirm_project_plot_changes", return_value=True):
                window.close()

    def test_workspace_can_adopt_a_freshly_parsed_frame(self) -> None:
        frame = pd.DataFrame({"x": [1, 2, 3]})
        dataset = Workspace().add_dataset("sheet", frame, copy_frame=False)
        self.assertIs(dataset.frame, frame)


if __name__ == "__main__":
    unittest.main()
