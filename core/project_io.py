"""Project file save/load for workspace persistence.

Projects are saved as ZIP archives (.jasc) containing CSV worksheets,
optional disk-backed Parquet tables, and a JSON metadata document.
"""

from __future__ import annotations

import binascii
import hashlib
import json
import os
import secrets
import struct
import tempfile
import uuid
import zipfile
from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import datetime, timezone
from io import TextIOWrapper
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

from core.workspace import (
    ColumnMetadata,
    FigureExtractionSession,
    WorksheetMetadata,
    Workspace,
)
from core.spectral_analysis import SpectralAnalysisSession
from core.large_data import restore_large_dataset
from models.fit_functions import CustomFitModel

PROJECT_EXTENSION = ".jasc"
ENCRYPTED_PROJECT_EXTENSION = ".jascx"
PRIVATE_KEY_EXTENSION = ".jasc-key"
PUBLIC_KEY_EXTENSION = ".jasc-pub"
_META_FILENAME = "project.json"
_DATASETS_DIR = "datasets"
_FIGURE_SESSIONS_DIR = "figure_sessions"
_ANALYSES_DIR = "analyses"
_INTEGRITY_FILENAME = "integrity.json"
_PROJECT_VERSION = 9
_HASH_CHUNK_SIZE = 1024 * 1024
_PACKAGE_SEAL_SCHEMA = "jasc-package-seal-v1"
_PACKAGE_SEAL_DOMAIN = b"JASC-SEAL-v1"
_PACKAGE_NONCE_SIZE = 32
_SIGNATURE_ALGORITHM = "ed25519"
_SIGNATURE_DOMAIN = b"JASC-SIGNATURE-v1"
_PUBLIC_KEY_FORMAT = "jasc-ed25519-public-key-v1"
_ENCRYPTION_MAGIC = b"JASCENC\x00"
_ENCRYPTION_VERSION = 1
_ENCRYPTION_TAG_SIZE = 16
_ENCRYPTION_MAX_HEADER_SIZE = 16 * 1024
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1


@dataclass(frozen=True, slots=True)
class ProjectIntegrityReport:
    """Result of checking an optional project manifest/package seal."""

    has_manifest: bool
    verified: bool
    problems: tuple[str, ...] = ()
    signature_status: str = "unsigned"
    signer_fingerprint: str | None = None
    signer_name: str | None = None


@dataclass(frozen=True, slots=True)
class SigningPublicIdentity:
    """Shareable Ed25519 public identity used to establish signer trust."""

    name: str
    fingerprint: str
    public_key: bytes


@dataclass(frozen=True, slots=True)
class SigningPrivateIdentity:
    """Unlocked Ed25519 private identity retained only for the active session."""

    name: str
    fingerprint: str
    public_key: bytes
    private_key: Any


class ProjectIntegrityError(ValueError):
    """Raised when a hashed project package no longer matches its manifest."""

    def __init__(self, report: ProjectIntegrityReport) -> None:
        self.report = report
        detail = "; ".join(report.problems[:5]) or "unknown integrity mismatch"
        super().__init__(
            "The data package may have been forged or damaged. "
            f"Its saved integrity checks do not match: {detail}"
        )


class ProjectPasswordRequiredError(ValueError):
    """Raised when an encrypted project is opened without a password."""


class ProjectDecryptionError(ValueError):
    """Raised when an encrypted project cannot be authenticated/decrypted."""


class SigningKeyError(ValueError):
    """Raised when a JASC signing identity cannot be created or unlocked."""


def save_project(
    workspace: Workspace,
    path: str | Path,
    *,
    password: str | None = None,
    signing_identity: SigningPrivateIdentity | None = None,
) -> None:
    """Atomically save a workspace, optionally using password encryption.

    Plain projects remain normal ZIP/CSV ``.jasc`` packages. When ``password``
    is supplied, that complete package is encrypted and authenticated as a
    versioned ``.jascx`` container using Scrypt and AES-256-GCM.
    """
    file_path = Path(path)
    if not file_path.parent.exists():
        raise FileNotFoundError(f"Folder does not exist: {file_path.parent}")
    if password == "":
        raise ValueError("The encryption password cannot be empty.")

    output_temp = _new_temporary_path(file_path.parent, ".jasc-save-")
    try:
        if password is None:
            _write_project_archive(workspace, output_temp, signing_identity)
        else:
            with tempfile.TemporaryFile(
                prefix=".jasc-plain-",
                suffix=".tmp",
            ) as plain_stream:
                _write_project_archive(workspace, plain_stream, signing_identity)
                _encrypt_project_archive(plain_stream, output_temp, password)
        os.replace(output_temp, file_path)
    finally:
        output_temp.unlink(missing_ok=True)


def _write_project_archive(
    workspace: Workspace,
    file_path: Path | BinaryIO,
    signing_identity: SigningPrivateIdentity | None = None,
) -> None:
    """Write the ordinary open ZIP/CSV representation to ``file_path``."""

    datasets = workspace.list_datasets()
    metadata = {
        "version": _PROJECT_VERSION if workspace.large_dataset_names() else 8,
        "datasets": [],
        "figure_sessions": [],
        "plots": [],
        "custom_fit_models": [],
        "spectral_analyses": [],
        "large_datasets": [],
    }
    if signing_identity is not None:
        metadata["security"] = {
            "signature_required": True,
            "signature_algorithm": _SIGNATURE_ALGORITHM,
            "signer_fingerprint": signing_identity.fingerprint,
            "signer_name": signing_identity.name,
        }

    with zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, dataset in enumerate(workspace.list_large_datasets()):
            member = f"large_datasets/{index:04d}.parquet"
            # Already compressed Parquet; stream from disk without a bytes copy.
            archive.write(dataset.path, member, compress_type=zipfile.ZIP_STORED)
            metadata["large_datasets"].append({
                "name": dataset.name, "parquet_file": member,
                "source_path": dataset.source_path, "details": dataset.details,
            })
        figure_sessions: dict[str, FigureExtractionSession] = {}
        for index, dataset in enumerate(datasets):
            csv_name = f"{_DATASETS_DIR}/{index:04d}_{_sanitise_filename(dataset.name)}.csv"
            with archive.open(csv_name, "w") as raw_csv:
                with TextIOWrapper(raw_csv, encoding="utf-8", newline="") as csv_stream:
                    dataset.frame.to_csv(csv_stream, index=False)

            if dataset.figure_session is not None:
                figure_sessions[dataset.figure_session.session_id] = dataset.figure_session

            metadata["datasets"].append({
                "name": dataset.name,
                "csv_file": csv_name,
                "backend": dataset.backend,
                "source_path": str(dataset.source_path) if dataset.source_path else None,
                "formulas": dict(dataset.formulas),
                "figure_session_id": (
                    dataset.figure_session.session_id
                    if dataset.figure_session is not None
                    else None
                ),
                "column_metadata": {
                    str(column): entry.to_metadata()
                    for column, entry in dataset.column_metadata.items()
                    if not entry.is_empty()
                },
                "worksheet_metadata": dataset.worksheet_metadata.to_metadata(),
            })

        for index, session in enumerate(figure_sessions.values()):
            image_name = (
                f"{_FIGURE_SESSIONS_DIR}/{index:04d}_"
                f"{_sanitise_filename(session.session_id)}.png"
            )
            archive.writestr(image_name, session.image_png)
            metadata["figure_sessions"].append({
                "session_id": session.session_id,
                "extraction_kind": session.extraction_kind,
                "source_path": session.source_path,
                "image_file": image_name,
                "state": session.state,
            })

        for plot in workspace.list_plots():
            metadata["plots"].append({
                "name": plot.name,
                "state": plot.state,
                "plot_id": plot.plot_id,
                "editor_state": plot.editor_state,
            })

        for model in workspace.list_custom_fit_models():
            metadata["custom_fit_models"].append(model.to_metadata())

        for index, analysis in enumerate(workspace.list_spectral_analyses()):
            base = f"{_ANALYSES_DIR}/{index:04d}_{_sanitise_filename(analysis.name)}"
            entry = analysis.metadata()
            frame_files: dict[str, str] = {}
            for frame_name, frame in (
                ("metrics", analysis.metrics_frame),
                ("curves", analysis.curves_frame),
                ("parameters", analysis.parameters_frame),
                ("peaks", analysis.peaks_frame),
            ):
                csv_name = f"{base}_{frame_name}.csv"
                with archive.open(csv_name, "w") as raw_csv:
                    with TextIOWrapper(raw_csv, encoding="utf-8", newline="") as csv_stream:
                        frame.to_csv(csv_stream, index=False)
                frame_files[frame_name] = csv_name
            entry["frame_files"] = frame_files
            metadata["spectral_analyses"].append(entry)

        archive.writestr(_META_FILENAME, json.dumps(metadata, indent=2, ensure_ascii=False))

    _append_integrity_manifest(file_path, signing_identity)


def load_project(
    path: str | Path,
    *,
    allow_integrity_mismatch: bool = False,
    password: str | None = None,
) -> Workspace:
    """Load a plain or password-encrypted project file."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Project file does not exist: {file_path}")

    if is_encrypted_project(file_path):
        if password is None:
            raise ProjectPasswordRequiredError(
                "This project is encrypted. Enter its password to open it."
            )
        with tempfile.TemporaryFile(
            prefix=".jasc-open-",
            suffix=".tmp",
        ) as plain_stream:
            _decrypt_project_archive(file_path, plain_stream, password)
            plain_stream.seek(0)
            return _load_project_archive(
                plain_stream,
                allow_integrity_mismatch=allow_integrity_mismatch,
            )

    return _load_project_archive(
        file_path,
        allow_integrity_mismatch=allow_integrity_mismatch,
    )


def _load_project_archive(
    file_path: Path | BinaryIO,
    *,
    allow_integrity_mismatch: bool,
) -> Workspace:
    """Load an already decrypted ZIP/CSV project package."""

    try:
        integrity = _verify_project_archive(file_path)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise ProjectIntegrityError(
            ProjectIntegrityReport(
                has_manifest=True,
                verified=False,
                problems=(f"unreadable project package ({exc})",),
            )
        ) from exc
    if integrity.has_manifest and not integrity.verified and not allow_integrity_mismatch:
        raise ProjectIntegrityError(integrity)

    workspace = Workspace()
    workspace.project_signature_status = integrity.signature_status
    workspace.project_signer_fingerprint = integrity.signer_fingerprint
    workspace.project_signer_name = integrity.signer_name

    with zipfile.ZipFile(file_path, "r") as archive:
        raw_meta = archive.read(_META_FILENAME).decode("utf-8")
        metadata = json.loads(raw_meta)

        if metadata.get("version", 0) > _PROJECT_VERSION:
            raise ValueError(
                f"Project file version {metadata['version']} is newer than "
                f"this application supports (version {_PROJECT_VERSION})."
            )

        for entry in metadata.get("large_datasets", []):
            with archive.open(entry["parquet_file"], "r") as stream:
                workspace.add_large_dataset(restore_large_dataset(
                    stream, entry["name"], source_path=entry.get("source_path", ""),
                    details=entry.get("details", {}),
                ))

        figure_sessions: dict[str, FigureExtractionSession] = {}
        for entry in metadata.get("figure_sessions", []):
            try:
                session_id = str(entry["session_id"])
                image_png = archive.read(str(entry["image_file"]))
            except (KeyError, TypeError, zipfile.BadZipFile):
                continue
            state = entry.get("state")
            figure_sessions[session_id] = FigureExtractionSession(
                session_id=session_id,
                extraction_kind=str(entry.get("extraction_kind", "xy") or "xy"),
                image_png=image_png,
                source_path=str(entry.get("source_path", "") or ""),
                state=dict(state) if isinstance(state, dict) else {},
            )

        for entry in metadata.get("datasets", []):
            with archive.open(entry["csv_file"], "r") as raw_csv:
                with TextIOWrapper(raw_csv, encoding="utf-8", newline="") as csv_stream:
                    frame = pd.read_csv(csv_stream)
            source_path = entry.get("source_path")

            dataset = workspace.add_dataset(
                entry["name"],
                frame,
                source_path=source_path,
                backend=entry.get("backend", "pandas"),
                copy_frame=False,
            )

            formulas = entry.get("formulas")
            if isinstance(formulas, dict):
                dataset.formulas.update(formulas)

            session_id = entry.get("figure_session_id")
            if isinstance(session_id, str):
                dataset.figure_session = figure_sessions.get(session_id)

            column_metadata = entry.get("column_metadata")
            if isinstance(column_metadata, dict):
                dataset.set_column_metadata({
                    str(column): ColumnMetadata.from_metadata(metadata_entry)
                    for column, metadata_entry in column_metadata.items()
                })

            dataset.worksheet_metadata = WorksheetMetadata.from_metadata(
                entry.get("worksheet_metadata")
            )

        for entry in metadata.get("plots", []):
            name = entry.get("name")
            state = entry.get("state")
            if isinstance(name, str) and isinstance(state, dict):
                workspace.add_plot(
                    name, state,
                    plot_id=entry.get("plot_id") if isinstance(entry.get("plot_id"), str) else None,
                    editor_state=entry.get("editor_state") if isinstance(entry.get("editor_state"), dict) else None,
                )

        for entry in metadata.get("custom_fit_models", []):
            try:
                workspace.add_custom_fit_model(CustomFitModel.from_metadata(entry))
            except (TypeError, ValueError):
                continue

        for entry in metadata.get("spectral_analyses", []):
            if not isinstance(entry, dict):
                continue
            frame_files = entry.get("frame_files", {})
            if not isinstance(frame_files, dict):
                frame_files = {}

            def read_analysis_frame(frame_name: str) -> pd.DataFrame:
                member = frame_files.get(frame_name)
                if not isinstance(member, str):
                    return pd.DataFrame()
                with archive.open(member, "r") as raw_csv:
                    with TextIOWrapper(raw_csv, encoding="utf-8", newline="") as csv_stream:
                        try:
                            return pd.read_csv(csv_stream)
                        except pd.errors.EmptyDataError:
                            return pd.DataFrame()

            coordinate_columns = entry.get("coordinate_columns", [])
            profile = entry.get("profile", {})
            workspace.add_spectral_analysis(SpectralAnalysisSession(
                name=str(entry.get("name", "Spectral Analysis") or "Spectral Analysis"),
                source_dataset=str(entry.get("source_dataset", "") or ""),
                analysis_kind=str(entry.get("analysis_kind", "spectrum") or "spectrum"),
                x_column=str(entry.get("x_column", "x") or "x"),
                y_column=str(entry.get("y_column", "y") or "y"),
                coordinate_columns=tuple(
                    str(value) for value in coordinate_columns
                ) if isinstance(coordinate_columns, list) else (),
                profile=dict(profile) if isinstance(profile, dict) else {},
                metrics_frame=read_analysis_frame("metrics"),
                curves_frame=read_analysis_frame("curves"),
                parameters_frame=read_analysis_frame("parameters"),
                peaks_frame=read_analysis_frame("peaks"),
                session_id=str(entry.get("session_id", "") or uuid.uuid4().hex),
                created_utc=str(entry.get("created_utc", "") or ""),
            ))

    return workspace


def verify_project_integrity(
    path: str | Path,
    *,
    password: str | None = None,
) -> ProjectIntegrityReport:
    """Verify every package member covered by a saved SHA-256 manifest.

    Projects created before version 5 do not contain a manifest and remain
    loadable as unprotected, backward-compatible packages.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Project file does not exist: {file_path}")
    if is_encrypted_project(file_path):
        if password is None:
            raise ProjectPasswordRequiredError(
                "This project is encrypted. Enter its password to verify it."
            )
        with tempfile.TemporaryFile(
            prefix=".jasc-verify-",
            suffix=".tmp",
        ) as plain_stream:
            _decrypt_project_archive(file_path, plain_stream, password)
            plain_stream.seek(0)
            return _verify_project_archive(plain_stream)
    return _verify_project_archive(file_path)


def _verify_project_archive(
    file_path: Path | BinaryIO,
) -> ProjectIntegrityReport:
    """Verify the integrity manifest in an already decrypted ZIP package."""
    signature_status = "unsigned"
    signer_fingerprint: str | None = None
    signer_name: str | None = None
    with zipfile.ZipFile(file_path, "r") as archive:
        names = [entry.filename for entry in archive.infolist() if not entry.is_dir()]
        if _INTEGRITY_FILENAME not in names:
            try:
                metadata = json.loads(archive.read(_META_FILENAME).decode("utf-8"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                return ProjectIntegrityReport(
                    has_manifest=True,
                    verified=False,
                    problems=(f"missing integrity manifest and invalid project metadata ({exc})",),
                )
            try:
                project_version = int(metadata.get("version", 0) or 0)
            except (TypeError, ValueError):
                return ProjectIntegrityReport(
                    has_manifest=True,
                    verified=False,
                    problems=("missing integrity manifest and invalid project version",),
                )
            if project_version >= 5:
                return ProjectIntegrityReport(
                    has_manifest=True,
                    verified=False,
                    problems=("missing integrity manifest",),
                )
            return ProjectIntegrityReport(has_manifest=False, verified=False)
        problems: list[str] = []
        if len(names) != len(set(names)):
            problems.append("duplicate package member names")
        try:
            manifest = json.loads(archive.read(_INTEGRITY_FILENAME).decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return ProjectIntegrityReport(
                has_manifest=True,
                verified=False,
                problems=(f"invalid integrity manifest ({exc})",),
            )
        if not isinstance(manifest, dict):
            problems.append("invalid integrity manifest structure")
        elif manifest.get("schema") == _PACKAGE_SEAL_SCHEMA:
            problems.extend(_sealed_manifest_problems(archive, names, manifest))
            (
                signature_status,
                signer_fingerprint,
                signer_name,
                signature_problems,
            ) = _manifest_signature_result(archive, manifest)
            problems.extend(signature_problems)
        else:
            if _archive_project_version(archive) >= 6:
                problems.append("missing version 6 package seal")
            problems.extend(_legacy_manifest_problems(archive, names, manifest))

    return ProjectIntegrityReport(
        has_manifest=True,
        verified=not problems,
        problems=tuple(problems),
        signature_status=signature_status,
        signer_fingerprint=signer_fingerprint,
        signer_name=signer_name,
    )


def _append_integrity_manifest(
    file_path: Path | BinaryIO,
    signing_identity: SigningPrivateIdentity | None = None,
) -> None:
    """Hash all members and append a uniquely salted, canonical package seal."""
    with zipfile.ZipFile(file_path, "r") as archive:
        files = {
            entry.filename: {
                "size": entry.file_size,
                "sha256": _sha256_archive_member(archive, entry.filename),
            }
            for entry in sorted(archive.infolist(), key=lambda item: item.filename)
            if not entry.is_dir() and entry.filename != _INTEGRITY_FILENAME
        }
    manifest_core = {
        "schema": _PACKAGE_SEAL_SCHEMA,
        "algorithm": "sha256",
        "created_utc": (
            datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        ),
        "package_uuid": str(uuid.uuid4()),
        "nonce": b64encode(secrets.token_bytes(_PACKAGE_NONCE_SIZE)).decode("ascii"),
        "files": files,
    }
    manifest = dict(manifest_core)
    manifest["seal"] = _package_seal_digest(manifest_core)
    if signing_identity is not None:
        signature = signing_identity.private_key.sign(
            _signature_message(manifest["seal"])
        )
        manifest["signature"] = {
            "algorithm": _SIGNATURE_ALGORITHM,
            "signed_object": "package_seal",
            "public_key": b64encode(signing_identity.public_key).decode("ascii"),
            "key_fingerprint": signing_identity.fingerprint,
            "value": b64encode(signature).decode("ascii"),
        }
    with zipfile.ZipFile(file_path, "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            _INTEGRITY_FILENAME,
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False),
        )


def _sealed_manifest_problems(
    archive: zipfile.ZipFile,
    names: list[str],
    manifest: dict[str, object],
) -> list[str]:
    """Return every detected problem in a version 6 JASC package seal."""
    problems: list[str] = []
    required_fields = {
        "schema",
        "algorithm",
        "created_utc",
        "package_uuid",
        "nonce",
        "files",
        "seal",
    }
    allowed_fields = (required_fields, required_fields | {"signature"})
    if set(manifest) not in allowed_fields or manifest.get("algorithm") != "sha256":
        return ["invalid package seal structure"]

    created_utc = manifest.get("created_utc")
    package_uuid = manifest.get("package_uuid")
    nonce = manifest.get("nonce")
    files = manifest.get("files")
    saved_seal = manifest.get("seal")
    if not _is_canonical_utc_timestamp(created_utc):
        problems.append("invalid package creation timestamp")
    if not _is_uuid4(package_uuid):
        problems.append("invalid package UUID")
    if not _is_package_nonce(nonce):
        problems.append("invalid package nonce")
    if not isinstance(files, dict):
        problems.append("invalid package file records")
    if not isinstance(saved_seal, str) or not _is_sha256_digest(saved_seal):
        problems.append("invalid package seal hash")
    if problems:
        return problems

    manifest_core = {key: manifest[key] for key in required_fields - {"seal"}}
    expected_seal = _package_seal_digest(manifest_core)
    if not secrets.compare_digest(saved_seal.lower(), expected_seal):
        problems.append("package seal mismatch")

    actual_names = set(names) - {_INTEGRITY_FILENAME}
    expected_names = set(files)
    for name in sorted(expected_names - actual_names):
        problems.append(f"missing '{name}'")
    for name in sorted(actual_names - expected_names):
        problems.append(f"unexpected '{name}'")
    for name in sorted(actual_names & expected_names):
        record = files.get(name)
        if not isinstance(record, dict) or set(record) != {"size", "sha256"}:
            problems.append(f"invalid saved file record for '{name}'")
            continue
        expected_size = record.get("size")
        expected_digest = record.get("sha256")
        if (
            not isinstance(expected_size, int)
            or isinstance(expected_size, bool)
            or expected_size < 0
        ):
            problems.append(f"invalid saved size for '{name}'")
        elif archive.getinfo(name).file_size != expected_size:
            problems.append(f"changed size for '{name}'")
        if not isinstance(expected_digest, str) or not _is_sha256_digest(expected_digest):
            problems.append(f"invalid saved hash for '{name}'")
            continue
        with archive.open(name, "r") as stream:
            actual_digest = _sha256_stream(stream)
        if not secrets.compare_digest(actual_digest, expected_digest.lower()):
            problems.append(f"changed '{name}'")
    return problems


def _manifest_signature_result(
    archive: zipfile.ZipFile,
    manifest: dict[str, object],
) -> tuple[str, str | None, str | None, list[str]]:
    """Verify an optional Ed25519 signature and its sealed signer declaration."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        project_metadata = json.loads(archive.read(_META_FILENAME).decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
        return "invalid", None, None, ["cannot read signed project metadata"]
    security = project_metadata.get("security") if isinstance(project_metadata, dict) else None
    signature_required = (
        isinstance(security, dict) and security.get("signature_required") is True
    )
    signer_name = (
        str(security.get("signer_name", "") or "").strip()
        if isinstance(security, dict)
        else ""
    ) or None
    declared_fingerprint = (
        str(security.get("signer_fingerprint", "") or "").strip()
        if isinstance(security, dict)
        else ""
    ) or None
    signature_record = manifest.get("signature")
    if signature_record is None:
        if signature_required:
            return (
                "invalid",
                declared_fingerprint,
                signer_name,
                ["required digital signature is missing"],
            )
        return "unsigned", None, None, []
    if not signature_required or not isinstance(security, dict):
        return "invalid", None, None, ["digital signature is not declared in project metadata"]
    if (
        not isinstance(signature_record, dict)
        or set(signature_record)
        != {"algorithm", "signed_object", "public_key", "key_fingerprint", "value"}
        or signature_record.get("algorithm") != _SIGNATURE_ALGORITHM
        or signature_record.get("signed_object") != "package_seal"
        or security.get("signature_algorithm") != _SIGNATURE_ALGORITHM
    ):
        return "invalid", declared_fingerprint, signer_name, ["invalid digital signature structure"]

    try:
        public_key_bytes = b64decode(str(signature_record["public_key"]), validate=True)
        signature_bytes = b64decode(str(signature_record["value"]), validate=True)
    except (ValueError, binascii.Error):
        return "invalid", declared_fingerprint, signer_name, ["invalid digital signature encoding"]
    if len(public_key_bytes) != 32 or len(signature_bytes) != 64:
        return "invalid", declared_fingerprint, signer_name, ["invalid digital signature length"]

    actual_fingerprint = _public_key_fingerprint(public_key_bytes)
    saved_fingerprint = str(signature_record.get("key_fingerprint", "") or "")
    if (
        saved_fingerprint != actual_fingerprint
        or declared_fingerprint != actual_fingerprint
    ):
        return "invalid", actual_fingerprint, signer_name, ["signer fingerprint mismatch"]
    saved_seal = manifest.get("seal")
    if not isinstance(saved_seal, str) or not _is_sha256_digest(saved_seal):
        return "invalid", actual_fingerprint, signer_name, ["cannot verify signature without a valid seal"]
    try:
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
            signature_bytes,
            _signature_message(saved_seal),
        )
    except (InvalidSignature, ValueError):
        return "invalid", actual_fingerprint, signer_name, ["invalid digital signature"]
    return "valid", actual_fingerprint, signer_name, []


def _legacy_manifest_problems(
    archive: zipfile.ZipFile,
    names: list[str],
    manifest: dict[str, object],
) -> list[str]:
    """Verify the per-member digest format written by version 5 projects."""
    expected = manifest.get("files")
    if manifest.get("algorithm") != "sha256" or not isinstance(expected, dict):
        return ["invalid integrity manifest structure"]

    problems: list[str] = []
    actual_names = set(names) - {_INTEGRITY_FILENAME}
    expected_names = set(expected)
    for name in sorted(expected_names - actual_names):
        problems.append(f"missing '{name}'")
    for name in sorted(actual_names - expected_names):
        problems.append(f"unexpected '{name}'")
    for name in sorted(actual_names & expected_names):
        expected_digest = expected.get(name)
        if not isinstance(expected_digest, str) or not _is_sha256_digest(expected_digest):
            problems.append(f"invalid saved hash for '{name}'")
            continue
        with archive.open(name, "r") as stream:
            actual_digest = _sha256_stream(stream)
        if not secrets.compare_digest(actual_digest, expected_digest.lower()):
            problems.append(f"changed '{name}'")
    return problems


def _archive_project_version(archive: zipfile.ZipFile) -> int:
    """Return the package project version, or zero when metadata is invalid."""
    try:
        metadata = json.loads(archive.read(_META_FILENAME).decode("utf-8"))
        return int(metadata.get("version", 0) or 0)
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return 0


def _package_seal_digest(manifest_core: dict[str, object]) -> str:
    """Hash the canonical manifest core with explicit domain separation."""
    canonical = json.dumps(
        manifest_core,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.sha256()
    digest.update(_PACKAGE_SEAL_DOMAIN)
    digest.update(b"\x00")
    digest.update(canonical)
    return digest.hexdigest()


def _signature_message(package_seal: str) -> bytes:
    """Return the domain-separated bytes covered by an Ed25519 signature."""
    return _SIGNATURE_DOMAIN + b"\x00" + bytes.fromhex(package_seal)


def _public_key_fingerprint(public_key: bytes) -> str:
    """Return the stable display fingerprint for an Ed25519 public key."""
    return f"SHA256:{hashlib.sha256(public_key).hexdigest()}"


def create_signing_identity(
    private_path: str | Path,
    *,
    name: str,
    password: str,
) -> tuple[SigningPrivateIdentity, Path]:
    """Create a password-encrypted Ed25519 identity and public sidecar file."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    clean_name = name.strip()
    if not clean_name:
        raise SigningKeyError("The signing identity name cannot be empty.")
    if not password:
        raise SigningKeyError("The signing-key password cannot be empty.")
    key_path = Path(private_path)
    if key_path.suffix.casefold() != PRIVATE_KEY_EXTENSION:
        key_path = key_path.with_suffix(PRIVATE_KEY_EXTENSION)
    if not key_path.parent.exists():
        raise FileNotFoundError(f"Folder does not exist: {key_path.parent}")

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    fingerprint = _public_key_fingerprint(public_key)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode("utf-8")),
    )
    public_path = key_path.with_suffix(PUBLIC_KEY_EXTENSION)
    public_document = {
        "format": _PUBLIC_KEY_FORMAT,
        "algorithm": _SIGNATURE_ALGORITHM,
        "name": clean_name,
        "fingerprint": fingerprint,
        "public_key": b64encode(public_key).decode("ascii"),
    }
    _atomic_write_bytes(key_path, private_pem, private=True)
    try:
        _atomic_write_bytes(
            public_path,
            json.dumps(
                public_document,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8"),
        )
    except Exception:
        key_path.unlink(missing_ok=True)
        raise
    return (
        SigningPrivateIdentity(clean_name, fingerprint, public_key, private_key),
        public_path,
    )


def load_signing_identity(
    private_path: str | Path,
    *,
    password: str,
) -> SigningPrivateIdentity:
    """Unlock a password-encrypted Ed25519 private identity."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key_path = Path(private_path)
    try:
        private_key = serialization.load_pem_private_key(
            key_path.read_bytes(),
            password=password.encode("utf-8"),
        )
    except (OSError, TypeError, ValueError) as exc:
        raise SigningKeyError(
            "The signing key could not be opened. Its password may be incorrect."
        ) from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise SigningKeyError("The selected file is not an Ed25519 private key.")
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    fingerprint = _public_key_fingerprint(public_key)
    name = key_path.stem
    public_path = key_path.with_suffix(PUBLIC_KEY_EXTENSION)
    if public_path.exists():
        try:
            public_identity = load_public_identity(public_path)
        except (OSError, SigningKeyError):
            public_identity = None
        if public_identity is not None and public_identity.fingerprint == fingerprint:
            name = public_identity.name
    return SigningPrivateIdentity(name, fingerprint, public_key, private_key)


def load_public_identity(path: str | Path) -> SigningPublicIdentity:
    """Load and validate a shareable JASC Ed25519 public identity file."""
    public_path = Path(path)
    try:
        document = json.loads(public_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SigningKeyError("The public signing identity is unreadable.") from exc
    if (
        not isinstance(document, dict)
        or document.get("format") != _PUBLIC_KEY_FORMAT
        or document.get("algorithm") != _SIGNATURE_ALGORITHM
    ):
        raise SigningKeyError("The selected file is not a JASC Ed25519 public identity.")
    try:
        public_key = b64decode(str(document["public_key"]), validate=True)
    except (KeyError, ValueError, binascii.Error) as exc:
        raise SigningKeyError("The public signing identity has invalid key data.") from exc
    fingerprint = _public_key_fingerprint(public_key)
    if len(public_key) != 32 or document.get("fingerprint") != fingerprint:
        raise SigningKeyError("The public signing identity fingerprint does not match.")
    name = str(document.get("name", "") or "").strip()
    if not name:
        raise SigningKeyError("The public signing identity has no display name.")
    return SigningPublicIdentity(name, fingerprint, public_key)


def _atomic_write_bytes(path: Path, payload: bytes, *, private: bool = False) -> None:
    """Atomically replace one small key/identity file."""
    temporary = _new_temporary_path(path.parent, f".{path.name}.")
    try:
        temporary.write_bytes(payload)
        if private:
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _is_canonical_utc_timestamp(value: object) -> bool:
    """Return whether a value is an ISO-8601 UTC timestamp ending in ``Z``."""
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError:
        return False
    return parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _is_uuid4(value: object) -> bool:
    """Return whether a value is a canonical random UUID string."""
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError):
        return False
    return parsed.version == 4 and str(parsed) == value


def _is_package_nonce(value: object) -> bool:
    """Return whether a value is the canonical 256-bit package nonce."""
    if not isinstance(value, str):
        return False
    try:
        decoded = b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        return False
    return (
        len(decoded) == _PACKAGE_NONCE_SIZE
        and b64encode(decoded).decode("ascii") == value
    )


def is_encrypted_project(path: str | Path) -> bool:
    """Return whether a file starts with the versioned JASC encryption marker."""
    file_path = Path(path)
    with file_path.open("rb") as stream:
        return stream.read(len(_ENCRYPTION_MAGIC)) == _ENCRYPTION_MAGIC


def _encrypt_project_archive(
    source: BinaryIO,
    destination: Path,
    password: str,
) -> None:
    """Stream-encrypt one ZIP project into an authenticated JASC container."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    salt = os.urandom(16)
    nonce = os.urandom(12)
    header = {
        "version": _ENCRYPTION_VERSION,
        "cipher": "AES-256-GCM",
        "kdf": {
            "name": "scrypt",
            "n": _SCRYPT_N,
            "r": _SCRYPT_R,
            "p": _SCRYPT_P,
        },
        "salt": b64encode(salt).decode("ascii"),
        "nonce": b64encode(nonce).decode("ascii"),
    }
    raw_header = json.dumps(
        header,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    prefix = _ENCRYPTION_MAGIC + struct.pack(">I", len(raw_header)) + raw_header
    key = _derive_encryption_key(password, salt)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(prefix)

    source.seek(0)
    with destination.open("wb") as output:
        output.write(prefix)
        while chunk := source.read(_HASH_CHUNK_SIZE):
            output.write(encryptor.update(chunk))
        output.write(encryptor.finalize())
        output.write(encryptor.tag)


def _decrypt_project_archive(
    source: Path,
    destination: BinaryIO,
    password: str,
) -> None:
    """Stream-decrypt and authenticate a JASC encrypted container."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    try:
        with source.open("rb") as encrypted:
            magic = encrypted.read(len(_ENCRYPTION_MAGIC))
            if magic != _ENCRYPTION_MAGIC:
                raise ProjectDecryptionError("This is not an encrypted JASC project.")
            raw_header_size = encrypted.read(4)
            if len(raw_header_size) != 4:
                raise ProjectDecryptionError("The encrypted project header is incomplete.")
            header_size = struct.unpack(">I", raw_header_size)[0]
            if not 0 < header_size <= _ENCRYPTION_MAX_HEADER_SIZE:
                raise ProjectDecryptionError("The encrypted project header is invalid.")
            raw_header = encrypted.read(header_size)
            if len(raw_header) != header_size:
                raise ProjectDecryptionError("The encrypted project header is incomplete.")
            header = json.loads(raw_header.decode("ascii"))
            salt, nonce = _validate_encryption_header(header)
            prefix = magic + raw_header_size + raw_header

            ciphertext_start = encrypted.tell()
            encrypted.seek(0, os.SEEK_END)
            ciphertext_size = encrypted.tell() - ciphertext_start - _ENCRYPTION_TAG_SIZE
            if ciphertext_size < 0:
                raise ProjectDecryptionError("The encrypted project payload is incomplete.")
            encrypted.seek(-_ENCRYPTION_TAG_SIZE, os.SEEK_END)
            tag = encrypted.read(_ENCRYPTION_TAG_SIZE)
            encrypted.seek(ciphertext_start)

            key = _derive_encryption_key(password, salt)
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(prefix)
            remaining = ciphertext_size
            destination.seek(0)
            destination.truncate()
            while remaining:
                chunk = encrypted.read(min(_HASH_CHUNK_SIZE, remaining))
                if not chunk:
                    raise ProjectDecryptionError(
                        "The encrypted project payload is incomplete."
                    )
                remaining -= len(chunk)
                destination.write(decryptor.update(chunk))
            destination.write(decryptor.finalize())
            destination.flush()
    except ProjectDecryptionError:
        destination.seek(0)
        destination.truncate()
        raise
    except (InvalidTag, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        destination.seek(0)
        destination.truncate()
        raise ProjectDecryptionError(
            "The password is incorrect, or the encrypted project was changed or damaged."
        ) from exc


def _validate_encryption_header(header: object) -> tuple[bytes, bytes]:
    """Validate a v1 encryption header and return decoded salt and nonce."""
    if not isinstance(header, dict):
        raise ValueError("invalid header")
    kdf = header.get("kdf")
    if (
        header.get("version") != _ENCRYPTION_VERSION
        or header.get("cipher") != "AES-256-GCM"
        or not isinstance(kdf, dict)
        or kdf.get("name") != "scrypt"
        or kdf.get("n") != _SCRYPT_N
        or kdf.get("r") != _SCRYPT_R
        or kdf.get("p") != _SCRYPT_P
    ):
        raise ValueError("unsupported encryption settings")
    salt = b64decode(str(header["salt"]), validate=True)
    nonce = b64decode(str(header["nonce"]), validate=True)
    if len(salt) != 16 or len(nonce) != 12:
        raise ValueError("invalid salt or nonce")
    return salt, nonce


def _derive_encryption_key(password: str, salt: bytes) -> bytes:
    """Derive a 256-bit encryption key from a user password using Scrypt."""
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    return Scrypt(
        salt=salt,
        length=32,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
    ).derive(password.encode("utf-8"))


def _new_temporary_path(parent: Path | None, prefix: str) -> Path:
    """Create and close a temporary file, returning its concrete path."""
    with tempfile.NamedTemporaryFile(
        prefix=prefix,
        suffix=".tmp",
        dir=parent,
        delete=False,
    ) as temporary:
        return Path(temporary.name)


def _sha256_archive_member(archive: zipfile.ZipFile, name: str) -> str:
    """Return the SHA-256 digest for one archive member without buffering it all."""
    with archive.open(name, "r") as stream:
        return _sha256_stream(stream)


def _sha256_stream(stream: object) -> str:
    """Return the SHA-256 digest of a binary readable stream."""
    digest = hashlib.sha256()
    while chunk := stream.read(_HASH_CHUNK_SIZE):
        digest.update(chunk)
    return digest.hexdigest()


def _is_sha256_digest(value: str) -> bool:
    """Return whether *value* is exactly one hexadecimal SHA-256 digest."""
    return len(value) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in value
    )


def _sanitise_filename(name: str) -> str:
    """Convert a dataset display name to a safe ZIP entry name."""
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)
    return safe.strip() or "dataset"
