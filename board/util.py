from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (compatible; yokohama-taxi-board/1.0; personal use)"

TIME_PAT = r"(\d{1,2}\s*(?:[:：]|時)\s*\d{2})"


class FetchError(Exception):
    pass


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("　", " ")).strip()


def lines_of(soup) -> list[str]:
    """ページ全体を1行ずつのテキストに分解する(HTML構造に依存しない解析用)。"""
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    out = []
    for ln in soup.get_text("\n").splitlines():
        ln = clean(ln)
        if ln:
            out.append(ln)
    return out


def dedupe_repeat(s: str) -> str:
    """「A A B」のように同じ語句が連続して重複しているものを1つにまとめる。"""
    toks = s.split(" ")
    changed = True
    while changed:
        changed = False
        n = len(toks)
        for k in range(1, n // 2 + 1):
            for i in range(0, n - 2 * k + 1):
                if toks[i : i + k] == toks[i + k : i + 2 * k]:
                    toks = toks[: i + k] + toks[i + 2 * k :]
                    changed = True
                    break
            if changed:
                break
    return " ".join(toks)


def norm_time(s: str | None) -> str | None:
    """「17:00」「17時」「10時30分」などを HH:MM にそろえる。読めなければ None。"""
    if not s:
        return None
    m = re.search(r"(\d{1,2})\s*[:：]\s*(\d{2})", s)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = re.search(r"(\d{1,2})\s*時\s*(?:(\d{1,2})\s*分?)?", s)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}"
    return None


def infer_date(month: int, day: int, today: date) -> date:
    """年が書かれていない月日から、今日に最も近い年を選ぶ。"""
    cands = []
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            cands.append(date(y, month, day))
        except ValueError:
            pass
    return min(cands, key=lambda x: abs((x - today).days))


_OPEN = r"(?:開場|OPEN|Open|open)\s*[:：/／]?\s*" + TIME_PAT
_START = r"(?<![付売場])(?:開演|開始|キックオフ|KICK\s*OFF|試合開始|START|Start|start)\s*[:：/／]?\s*" + TIME_PAT
_END = r"(?:終演|終了|END)\s*(?:予定)?\s*[:：/／]?\s*" + TIME_PAT


def times_from_text(text: str):
    def first(pat):
        m = re.search(pat, text)
        return norm_time(m.group(1)) if m else None

    return first(_OPEN), first(_START), first(_END)


@dataclass
class Ctx:
    today: date
    targets: list
    fetch: object
    detail_budget: int = 25

    @property
    def months(self):
        return sorted({(d.year, d.month) for d in self.targets})


def enrich(ctx: Ctx, event, tag: str) -> None:
    """一覧に時刻がない場合、詳細ページから開場・開演・終演を補う。"""
    if not event.url or ctx.detail_budget <= 0:
        return
    ctx.detail_budget -= 1
    try:
        soup = ctx.fetch.get_soup(event.url, tag)
    except FetchError:
        return
    o, s, e = times_from_text(" ".join(lines_of(soup)))
    event.open = event.open or o
    event.start = event.start or s
    event.end = event.end or e


class Fetcher:
    def __init__(self, raw_dir: str | None = None, delay: float = 1.0):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "ja,en;q=0.5"})
        self.raw_dir = raw_dir
        self.delay = delay
        self._last = 0.0
        self._robots: dict[str, RobotFileParser] = {}
        if raw_dir:
            os.makedirs(raw_dir, exist_ok=True)

    def _allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = RobotFileParser()
            try:
                r = self.s.get(base + "/robots.txt", timeout=15)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except requests.RequestException:
                rp.parse([])
            self._robots[base] = rp
        return rp.can_fetch(UA, url)

    def get_soup(self, url: str, tag: str) -> BeautifulSoup:
        if not self._allowed(url):
            raise FetchError("robots.txt により取得が許可されていません")
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        last: Exception | None = None
        r = None
        for attempt in range(3):
            try:
                r = self.s.get(url, timeout=30)
                self._last = time.time()
                if r.status_code == 200:
                    break
                last = FetchError(f"HTTP {r.status_code}")
            except requests.RequestException as e:
                last = FetchError(str(e)[:120])
            r = None
            time.sleep(2 * (attempt + 1))
        if r is None:
            raise last or FetchError("取得失敗")
        if self.raw_dir:
            fn = re.sub(r"[^\w.-]", "_", tag) + ".html"
            with open(os.path.join(self.raw_dir, fn), "wb") as f:
                f.write(r.content)
        return BeautifulSoup(r.content, "lxml")
