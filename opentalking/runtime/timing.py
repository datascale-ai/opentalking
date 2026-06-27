from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from typing import Any


@dataclass
class SpeechTiming:
    session_id: str
    model_type: str
    text_preview: str
    started_at: float = field(default_factory=time.perf_counter)
    marks: dict[str, float] = field(default_factory=dict)
    counters: dict[str, float] = field(default_factory=dict)

    def mark_once(self, name: str) -> float:
        now = time.perf_counter() - self.started_at
        self.marks.setdefault(name, now)
        return self.marks[name]

    def add_duration(self, name: str, seconds: float) -> None:
        self.counters[name] = self.counters.get(name, 0.0) + max(0.0, float(seconds))

    def add_count(self, name: str, value: int | float = 1) -> None:
        self.counters[name] = self.counters.get(name, 0.0) + float(value)

    def set_value(self, name: str, value: int | float) -> None:
        self.counters[name] = float(value)

    def payload(
        self,
        *,
        mark_order: list[str] | tuple[str, ...] | None = None,
        counter_order: list[str] | tuple[str, ...] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "session_id": self.session_id,
            "model_type": self.model_type,
            "text_preview": self.text_preview[:80],
            "total_ms": round((time.perf_counter() - self.started_at) * 1000.0, 1),
        }

        mark_keys = list(mark_order) if mark_order is not None else sorted(self.marks.keys())
        for key in mark_keys:
            if key in self.marks:
                out[f"{key}_ms"] = round(self.marks[key] * 1000.0, 1)

        counter_keys = list(counter_order) if counter_order is not None else sorted(self.counters.keys())
        for key in counter_keys:
            if key not in self.counters:
                continue
            value = self.counters[key]
            if key.endswith("_s"):
                out[key[:-2] + "_ms"] = round(value * 1000.0, 1)
            elif float(value).is_integer():
                out[key] = int(value)
            else:
                out[key] = round(value, 3)

        if extra:
            out.update(extra)
        return out

    def to_json(
        self,
        *,
        mark_order: list[str] | tuple[str, ...] | None = None,
        counter_order: list[str] | tuple[str, ...] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        return json.dumps(
            self.payload(mark_order=mark_order, counter_order=counter_order, extra=extra),
            ensure_ascii=False,
            sort_keys=False,
        )
