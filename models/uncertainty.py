"""Serializable measurement percentile bounds shared by plots and fitting."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True, slots=True)
class PercentileBounds:
    lower_column: str
    upper_column: str
    lower_probability: float = .16
    upper_probability: float = .84
    centre: str = "median"
    origin: str = "measurement"
    distribution: str = "quantile_normal"
    model_version: int = 1

    def __post_init__(self) -> None:
        if not self.lower_column or not self.upper_column or self.lower_column == self.upper_column:
            raise ValueError("Choose different lower and upper percentile columns.")
        if not 0 < self.lower_probability < .5 < self.upper_probability < 1:
            raise ValueError("Percentile levels must satisfy 0 < lower < 50% < upper < 100%.")
        if self.centre not in {"median", "mean", "mode", "estimate"}:
            raise ValueError("Choose the meaning of the central values.")
        if self.distribution != "quantile_normal" or self.model_version != 1:
            raise ValueError("Unsupported percentile model.")
        if self.origin not in {"measurement", "posterior"}:
            raise ValueError("Choose measurement or posterior percentile bounds.")

    def to_state(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_state(cls, state: object) -> PercentileBounds | None:
        if state is None:
            return None
        if isinstance(state, cls):
            return state
        if not isinstance(state, dict):
            raise ValueError("Malformed percentile-bound definition.")
        return cls(**{key: value for key, value in state.items() if key in cls.__dataclass_fields__})

    def renamed(self, names: dict[str, str]) -> PercentileBounds:
        return replace(self, lower_column=names.get(self.lower_column, self.lower_column),
                       upper_column=names.get(self.upper_column, self.upper_column))
