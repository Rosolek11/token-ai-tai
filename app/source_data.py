"""Common, additive source contract used by token security reports."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceValue(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    value: Any = None
    unit: str
    sourceId: str | None = None
    url: str | None = None
    timestamp: datetime | None = None


class NormalizedSourceData(BaseModel):
    price: dict[str, SourceValue] = Field(default_factory=dict)
    liquidity: dict[str, SourceValue] = Field(default_factory=dict)
    holders: dict[str, SourceValue] = Field(default_factory=dict)
    flags: dict[str, SourceValue] = Field(default_factory=dict)


class SourceRecorder:
    """Record provenance when an adapter supplies or replaces a selected value.

    Equal values retain the first observation that established them. Missing
    collections are null; actual numeric zero and boolean false are preserved.
    """

    def __init__(self) -> None:
        self.data = NormalizedSourceData()

    def capture(self, source: Any, *, activity: BaseModel, liquidity: BaseModel,
                holders: BaseModel, flags: list[BaseModel]) -> None:
        groups = {
            "price": {"price_usd": activity.price_usd,
                      "price_native_sol": activity.price_native_sol},
            "liquidity": liquidity.model_dump(),
            "holders": holders.model_dump(),
        }
        for group, values in groups.items():
            target = getattr(self.data, group)
            for key, value in values.items():
                if value == []:
                    value = None
                unit = self._unit(key)
                if key not in target:
                    target[key] = SourceValue(unit=unit)
                if value is not None and target[key].value != value:
                    target[key] = SourceValue(value=value, unit=unit,
                                             sourceId=source.source,
                                             url=source.source_url,
                                             timestamp=source.updated_at)
        for flag in flags:
            if flag.source == source.source:
                self.data.flags[f"{flag.source}:{flag.code}"] = SourceValue(
                    value=flag.value, unit="signal", sourceId=source.source,
                    url=source.source_url, timestamp=source.updated_at,
                )

    @staticmethod
    def _unit(key: str) -> str:
        if key.endswith("_usd"):
            return "USD"
        if key.endswith("_sol"):
            return "SOL"
        if key.endswith("_pct"):
            return "percent"
        if key.endswith("_count"):
            return "count"
        if key.endswith("_address"):
            return "address"
        if key == "creator_balance":
            return "token"
        return "records"
