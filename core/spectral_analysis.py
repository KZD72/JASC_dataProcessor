"""Persistent results for Raman and other spectrum/map analyses."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd


SPECTRAL_ANALYSIS_SCHEMA = "jasc-spectral-analysis-v1"


@dataclass(slots=True)
class SpectralAnalysisSession:
    """One reproducible analysis with compact metrics and linked fit curves.

    Frames remain separate from ordinary workspace datasets so intermediate
    baseline/fit tables do not crowd the Data navigator.  Project persistence
    still writes every frame as an ordinary UTF-8 CSV member for open-science
    access without JASC.
    """

    name: str
    source_dataset: str
    analysis_kind: str
    x_column: str
    y_column: str
    coordinate_columns: tuple[str, ...] = ()
    profile: dict[str, object] = field(default_factory=dict)
    metrics_frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    curves_frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    parameters_frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    peaks_frame: pd.DataFrame = field(default_factory=pd.DataFrame)
    session_id: str = field(default_factory=lambda: uuid4().hex)
    created_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def metadata(self) -> dict[str, object]:
        """Return the JSON-safe part of the session contract."""
        return {
            "schema": SPECTRAL_ANALYSIS_SCHEMA,
            "session_id": self.session_id,
            "name": self.name,
            "source_dataset": self.source_dataset,
            "analysis_kind": self.analysis_kind,
            "x_column": self.x_column,
            "y_column": self.y_column,
            "coordinate_columns": list(self.coordinate_columns),
            "created_utc": self.created_utc,
            "profile": deepcopy(self.profile),
        }

    def copy(self, *, name: str | None = None) -> "SpectralAnalysisSession":
        """Return an independent duplicate with a new session identity."""
        return SpectralAnalysisSession(
            name=name or self.name,
            source_dataset=self.source_dataset,
            analysis_kind=self.analysis_kind,
            x_column=self.x_column,
            y_column=self.y_column,
            coordinate_columns=tuple(self.coordinate_columns),
            profile=deepcopy(self.profile),
            metrics_frame=self.metrics_frame.copy(deep=True),
            curves_frame=self.curves_frame.copy(deep=True),
            parameters_frame=self.parameters_frame.copy(deep=True),
            peaks_frame=self.peaks_frame.copy(deep=True),
        )

