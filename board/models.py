from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Event:
    venue: str
    title: str
    day: date
    open: str | None = None
    start: str | None = None
    end: str | None = None
    note: str = ""
    url: str = ""
    span_end: date | None = None  # 複数日開催の最終日

    def on(self, d: date) -> bool:
        return self.day <= d <= (self.span_end or self.day)


@dataclass
class Ship:
    berth: str
    name: str
    arrive_day: date | None
    arrive_time: str | None
    depart_day: date | None
    depart_time: str | None
    note: str = ""
    cancelled: bool = False

    def describe_on(self, d: date) -> str | None:
        """その日の状況を1行で返す。関係ない日は None。"""
        if self.cancelled:
            return None

        def tm(t):
            return t or "時刻非公開"

        a, dp = self.arrive_day, self.depart_day
        if a == d and dp == d:
            return f"入港 {tm(self.arrive_time)} → 出港 {tm(self.depart_time)}"
        if a == d:
            tail = f"(出港 {dp.month}/{dp.day} {tm(self.depart_time)})" if dp else ""
            return f"入港 {tm(self.arrive_time)}{tail}"
        if dp == d:
            return f"出港 {tm(self.depart_time)}"
        if a and dp and a < d < dp:
            return "停泊中"
        return None

    def sort_key(self, d: date) -> str:
        if self.arrive_day == d and self.arrive_time:
            return self.arrive_time
        if self.depart_day == d and self.depart_time:
            return self.depart_time
        return "99:99"


@dataclass
class Result:
    key: str
    name: str
    url: str
    events: list[Event] = field(default_factory=list)
    ships: list[Ship] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # 取りこぼしの可能性(あると「なし」を信用できない)
    notes: list[str] = field(default_factory=list)  # 常に表示する補足
    error: str | None = None
    manual: bool = False  # 自動取得未対応(公式サイトを手動で確認)
