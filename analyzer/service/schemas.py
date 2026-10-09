"""Request and response models for the engine service, matching `docs/06` section 3.

These models **check** the wire format; they do not define it a second time. The
shape is owned by `pare.engine` (`AnalyzeRequest.from_api_dict` and
`AnalyzeResult.to_api_dict`, decision 52), so a request is validated here, then
handed to the library as plain JSON. That keeps one implementation of the
contract, which matters because the Java side cannot notice if two of them drift.

What validation adds over the library, and why each is here:

* Every row of `normal` and `recent` must have exactly one value per column. A
  short row would otherwise be misaligned silently with the column map.
* `null` is the only spelling of a missing number. pydantic rejects the strings
  "NaN" and "Infinity" because the fields are typed `float | None`.
* Unknown `params` keys are rejected (`docs/06`: "a request that says `topk`
  instead of `topK` is a mistake worth reporting").
* Enum-like strings are UPPERCASE (`docs/06` general rules) and anything else is a
  clear 422, never a quiet default.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

GraphSource = Literal[
    "TRACES", "STATIC_ARCHITECTURE", "CORRELATION", "SYNTHETIC_TRUE", "USER", "NONE"
]


def _no_strings(value: Any) -> Any:
    """Refuse a number written as a string.

    pydantic would otherwise read "NaN", "Infinity" or "3.5" into a float in its
    default lax mode - found by a test - and `docs/06` says a missing number is
    `null`, never the string "NaN". A JSON number, int or float, passes untouched.
    """
    if isinstance(value, str):
        raise ValueError(f"a number must be a JSON number or null, got the string {value!r}")
    return value


# One reading in a window: a JSON number, or null for "missing".
Reading = Annotated[float | None, BeforeValidator(_no_strings)]
TimeValue = Annotated[float, BeforeValidator(_no_strings)]


class _Camel(BaseModel):
    """Field names are camelCase on the wire; unknown top-level fields are refused."""

    model_config = ConfigDict(extra="forbid")


class ColumnModel(_Camel):
    name: str = Field(min_length=1)
    service: str = Field(min_length=1)
    metric: str = Field(min_length=1)


class WindowModel(_Camel):
    timeSec: list[TimeValue]
    values: list[list[Reading]]

    @model_validator(mode="after")
    def _same_length(self) -> WindowModel:
        if len(self.timeSec) != len(self.values):
            raise ValueError(
                f"timeSec has {len(self.timeSec)} entries but values has {len(self.values)} rows"
            )
        return self


class EdgeModel(_Camel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from", min_length=1)
    to: str = Field(min_length=1)


class GraphModel(_Camel):
    source: GraphSource = "NONE"
    edges: list[EdgeModel] = Field(default_factory=list)


class AnalyzeRequestModel(_Camel):
    """POST /v1/analyze. Ground truth is never part of it (hard rule 4)."""

    requestId: str | None = None
    engine: str = "PARE"
    alarmTimeSec: TimeValue
    columns: list[ColumnModel] = Field(min_length=1)
    normal: WindowModel
    recent: WindowModel
    graph: GraphModel | None = None
    params: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _rows_match_columns(self) -> AnalyzeRequestModel:
        width = len(self.columns)
        for window_name in ("normal", "recent"):
            window: WindowModel = getattr(self, window_name)
            for index, row in enumerate(window.values):
                if len(row) != width:
                    raise ValueError(
                        f"{window_name}.values row {index} has {len(row)} values "
                        f"but there are {width} columns"
                    )
        if not self.normal.values:
            raise ValueError("normal has no rows; a baseline cannot be learned from nothing")
        if not self.recent.values:
            raise ValueError("recent has no rows; there is nothing to analyse")
        return self

    def to_library_dict(self) -> dict[str, Any]:
        """The plain JSON form `pare.engine.AnalyzeRequest.from_api_dict` reads."""
        data = self.model_dump(by_alias=True, exclude_none=False)
        if data["graph"] is None:
            data["graph"] = {"source": "NONE", "edges": []}
        return data


FaultType = Literal["LATENCY", "CPU", "MEM", "ERROR"]
NoiseLevel = Literal["LOW", "MEDIUM", "HIGH"]

# The one place the API noise names meet the library's float (docs/05 section 5).
NOISE_LEVELS: dict[str, float] = {"LOW": 0.5, "MEDIUM": 1.0, "HIGH": 2.0}


class SyntheticRequestModel(_Camel):
    """POST /v1/synthetic. Ranges keep a request from asking for an absurd case."""

    nServices: int = Field(default=8, ge=3, le=60)
    faultType: FaultType = "LATENCY"
    rootService: str | None = None
    propagation: float = Field(default=0.8, ge=0.0, le=1.5)
    amplification: float = Field(default=0.0, ge=0.0, le=5.0)
    noise: NoiseLevel = "MEDIUM"
    nNormal: int = Field(default=600, ge=60, le=20_000)
    nAbnormal: int = Field(default=120, ge=10, le=5_000)
    seed: int = Field(default=7, ge=0)

    @field_validator("rootService")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value or None


class ErrorBody(BaseModel):
    """`docs/06` section 4: every 4xx/5xx has this body."""

    error: str
    details: str | None = None
