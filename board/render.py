from __future__ import annotations

import html
import re
from datetime import date, datetime

WDJ = "月火水木金土日"

VENUE_ORDER = [
    "横浜アリーナ",
    "日産スタジアム",
    "横浜スタジアム",
    "横浜武道館",
    "横浜BUNTAI",
    "ぴあアリーナMM",
    "Kアリーナ横浜",
    "パシフィコ横浜",
    "Zepp Yokohama",
    "横浜赤レンガ倉庫",
]


def esc(s) -> str:
    return html.escape(s or "")


def fmt_day(d: date) -> str:
    return f"{d.month}/{d.day}({WDJ[d.weekday()]})"


def _mins(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _hhmm(mins: int) -> str:
    mins %= 1440
    return f"{mins // 60:02d}:{mins % 60:02d}"


def est_end(e):
    """終演時刻。公式に載っていればそのまま、なければ開演から推定(推定は True)。"""
    if e.end:
        return e.end, False
    base = e.start or (_hhmm(_mins(e.open) + 60) if e.open else None)
    if not base:
        return None, True
    dur = 120 if re.search(r"\bvs\b|ＶＳ|リーグ|LEAGUE|TIPOFF", e.title, re.I) else 150
    return _hhmm(_mins(base) + dur), True


def events_on(results, day):
    evs = [e for r in results for e in r.events if e.on(day)]
    evs.sort(key=lambda e: (e.start or e.open or "99:99", e.venue))
    return evs


def ships_on(results, day):
    out = []
    for r in results:
        for s in r.ships:
            d = s.describe_on(day)
            if d:
                out.append((s, d))
    out.sort(key=lambda x: x[0].sort_key(day))
    return out


def event_card(e) -> str:
    main = e.start or e.open or "終日/未定"
    end, est = est_end(e)
    bits = []
    if e.open:
        bits.append(f"開場 {e.open}")
    if e.start:
        bits.append(f"開演 {e.start}")
    if end:
        bits.append(f"<b>終演{'目安' if est else ''} {end}</b>")
    note = e.note
    if e.span_end and e.span_end != e.day:
        note = f"{fmt_day(e.day)}〜{fmt_day(e.span_end)} " + note
    title = esc(e.title)
    if e.url:
        title = f'<a href="{esc(e.url)}" target="_blank" rel="noopener">{title}</a>'
    return (
        '<li class="card">'
        f'<div class="time">{esc(main)}</div>'
        '<div class="body">'
        f'<span class="venue">{esc(e.venue)}</span>'
        f'<div class="title">{title}</div>'
        f'<div class="sub">{" / ".join(bits)}</div>'
        + (f'<div class="note">{esc(note.strip())}</div>' if note.strip() else "")
        + "</div></li>"
    )


def day_section(results, day) -> str:
    evs = events_on(results, day)
    ships = ships_on(results, day)
    out = []

    # 終演時刻の近い順(タクシー需要の目安)
    ends = []
    for e in evs:
        end, est = est_end(e)
        if end and e.start:
            ends.append((end, est, e))
    ends.sort(key=lambda x: x[0])
    if ends:
        out.append("<h3>終演の目安(早い順)</h3><ul class='ends'>")
        for end, est, e in ends:
            out.append(f"<li><b>{end}</b>{'<small>推定</small>' if est else ''} {esc(e.venue)} — {esc(e.title)}</li>")
        out.append("</ul>")

    out.append("<h3>イベント(開始順)</h3>")
    if evs:
        out.append("<ul class='cards'>" + "".join(event_card(e) for e in evs) + "</ul>")
    else:
        out.append("<p class='empty'>取得できたイベントはありません</p>")

    out.append("<h3>客船</h3>")
    if ships:
        out.append("<ul class='ships'>")
        for s, d in ships:
            note = f" <small>{esc(s.note)}</small>" if s.note else ""
            out.append(f"<li><span class='venue'>{esc(s.berth)}</span> <b>{esc(s.name)}</b>{note}<div class='sub'>{esc(d)}</div></li>")
        out.append("</ul>")
    else:
        out.append("<p class='empty'>入港・出港の予定なし</p>")
    return "".join(out)


def status_chips(results, day) -> str:
    chips = []
    by_name = {r.name: r for r in results}
    names = [n for n in VENUE_ORDER if n in by_name]
    for n in names:
        r = by_name[n]
        link = f' <a href="{esc(r.url)}" target="_blank" rel="noopener">公式</a>'
        if r.manual:
            chips.append(f'<li class="chip warn">{esc(n)}: 自動取得未対応{link}</li>')
        elif r.error:
            chips.append(f'<li class="chip bad">{esc(n)}: ⚠取得失敗{link}</li>')
        else:
            cnt = sum(1 for e in r.events if e.on(day))
            if cnt:
                chips.append(f'<li class="chip ok">{esc(n)}: {cnt}件{link}</li>')
            elif r.warnings:
                chips.append(f'<li class="chip warn">{esc(n)}: ⚠要確認(取りこぼしの可能性){link}</li>')
            else:
                chips.append(f'<li class="chip none">{esc(n)}: なし{link}</li>')
    ship = by_name.get("客船入港")
    if ship:
        if ship.error:
            chips.append('<li class="chip bad">客船入港: ⚠取得失敗</li>')
        elif ship.warnings:
            chips.append('<li class="chip warn">客船入港: ⚠要確認</li>')
    return "<ul class='chips'>" + "".join(chips) + "</ul>"


CSS = """
:root{--bg:#f6f7f9;--fg:#1a1d21;--card:#fff;--line:#dde1e6;--mut:#667085;--acc:#0b5fff;--ok:#0a7d3b;--warn:#a15c00;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#101215;--fg:#e8eaed;--card:#1a1d22;--line:#2c3138;--mut:#9aa3ad;--acc:#6ea0ff;--ok:#4cc77a;--warn:#f0b24a;--bad:#ff7b72}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Hiragino Sans","Yu Gothic",sans-serif}
main{max-width:760px;margin:0 auto;padding:16px}
h1{font-size:1.35rem;margin:.2em 0}h2{font-size:1.15rem;margin:1.6em 0 .4em;border-bottom:2px solid var(--line);padding-bottom:.2em}
h3{font-size:.95rem;color:var(--mut);margin:1.2em 0 .4em}
.meta{color:var(--mut);font-size:.85rem;margin:0}
ul{list-style:none;margin:0;padding:0}a{color:var(--acc)}
.cards .card{display:flex;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-bottom:8px}
.time{min-width:64px;font-weight:700;font-size:1.1rem;font-variant-numeric:tabular-nums}
.body{flex:1;min-width:0}.venue{display:inline-block;font-size:.75rem;background:var(--line);border-radius:4px;padding:0 6px;margin-right:4px}
.title{font-weight:600;word-break:break-word}.sub{color:var(--mut);font-size:.85rem}.sub b{color:var(--fg)}.note{font-size:.8rem;color:var(--mut)}
.ends li{padding:3px 0;border-bottom:1px dashed var(--line)}.ends small{color:var(--mut);margin:0 4px}
.ships li{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin-bottom:8px}
.empty{color:var(--mut);margin:.3em 0}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{font-size:.8rem;border:1px solid var(--line);border-radius:999px;padding:2px 10px;background:var(--card)}
.chip.ok{border-color:var(--ok)}.chip.warn{border-color:var(--warn);color:var(--warn)}.chip.bad{border-color:var(--bad);color:var(--bad)}.chip.none{color:var(--mut)}
.alert{background:var(--card);border-left:4px solid var(--bad);padding:8px 12px;border-radius:6px;font-size:.85rem;margin:12px 0}
details{margin-top:1.5em}summary{cursor:pointer;font-weight:700;font-size:1.05rem}
footer{margin-top:2em;color:var(--mut);font-size:.8rem}footer li{margin:2px 0}
"""


def render(results, now: datetime, targets: list[date]) -> str:
    today = targets[0]
    problems = []
    for r in results:
        if r.error:
            problems.append(f"{r.name}: 取得に失敗しました({r.error})")
        for w in r.warnings:
            problems.append(f"{r.name}: {w}")

    parts = [
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<meta name='robots' content='noindex,nofollow'><meta name='color-scheme' content='light dark'>",
        "<title>横浜 イベント・入港ボード</title>",
        f"<style>{CSS}</style></head><body><main>",
        f"<h1>横浜 イベント・入港ボード</h1>",
        f"<p class='meta'>{fmt_day(today)} 版 / 更新 {now:%H:%M} JST(毎朝自動更新)</p>",
    ]
    if problems:
        parts.append("<div class='alert'><b>取得できなかった/要確認の項目</b><ul>")
        parts += [f"<li>{esc(p)}</li>" for p in problems]
        parts.append("</ul></div>")

    parts.append(f"<h2>今日 {fmt_day(today)}</h2>")
    parts.append(status_chips(results, today))
    parts.append(day_section(results, today))

    if len(targets) > 1:
        t = targets[1]
        parts.append(f"<details><summary>明日 {fmt_day(t)}</summary>")
        parts.append(status_chips(results, t))
        parts.append(day_section(results, t))
        parts.append("</details>")

    parts.append("<footer><p>※公式サイトの情報を自動で集めたものです。時刻の変更・中止は各公式サイトで確認してください。「終演目安」と書かれたものは開演からの推定です。</p><ul>")
    for r in results:
        parts.append(f"<li><a href='{esc(r.url)}' target='_blank' rel='noopener'>{esc(r.name)}</a>")
        for n in r.notes:
            parts.append(f" — {esc(n)}")
        parts.append("</li>")
    parts.append("</ul></footer></main></body></html>")
    return "".join(parts)
