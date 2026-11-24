"""Bounded, process-local storage for fresh token data."""

from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from time import monotonic
from typing import TypeVar

from pydantic import BaseModel

SourceKey = tuple[str, str, str]  # Network, token address, source
Result = TypeVar("Result", bound=BaseModel)


class SourceCache:
    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._entries: OrderedDict[SourceKey, tuple[float, BaseModel]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: SourceKey, model: type[Result]) -> Result | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= self._clock():
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
        return value.model_copy(deep=True) if isinstance(value, model) else None

    def store(self, key: SourceKey, value: BaseModel, *, ttl: float) -> None:
        snapshot = value.model_copy(deep=True)
        with self._lock:
            self._entries[key] = (self._clock() + ttl, snapshot)
            self._entries.move_to_end(key)
            if len(self._entries) > 512:
                self._entries.popitem(last=False)
