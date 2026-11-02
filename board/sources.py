"""各施設・港のページから情報を取り出す処理。

どの関数も fn(ctx, res) の形で、取れた分を res に追加していく。
途中で例外が起きても、それまでに取れた分は残る(main.py 側で error として表示)。
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin

from .models import Event, Result, Ship
from .util import (
    FetchError,
    TIME_PAT,
    clean,
    dedupe_repeat,
    enrich,
    infer_date,
    lines_of,
    norm_time,
)

WD = "月火水木金土日"


def _in_targets(ctx, e: Event) -> bool:
    return any(e.on(d) for d in ctx.targets)


# ---------------------------------------------------------------- 客船入港
def _parse_dt(cell: str, default_month: int, year: int):
    dm = re.search(r"(?:(\d{1,2})月)?\s*(\d{1,2})日", cell)
    if not dm:
        return None, None
    month = int(dm.group(1)) if dm.group(1) else default_month
    y = year + 1 if month < default_month else year
    try:
        d = date(y, month, int(dm.group(2)))
    except ValueError:
        return None, None
    return d, norm_time(cell[dm.end():])


def _berth(s: str) -> str:
    for b in ("大さん橋", "新港", "大黒"):
        if b in s:
            return b + ("ふ頭" if b == "大黒" else "")
    return s


def ships(ctx, res: Result):
    for year in sorted({d.year for d in ctx.targets}):
        url = f"https://www.city.yokohama.lg.jp/kanko-bunka/minato/kyakusen/nyuko/{year}.html"
        soup = ctx.fetch.get_soup(url, f"ships-{year}")
        n = 0
        for tr in soup.find_all("tr"):
            tds = tr.find_all(["td", "th"])
            if len(tds) < 6:
                continue
            mon = clean(tds[0].get_text())
            if not mon.isdigit():
                continue
            mon = int(mon)
            arr = tds[1].get_text(" ", strip=True)
            dep = tds[2].get_text(" ", strip=True)
            berth = _berth(clean(tds[3].get_text()))
            name_lines = [clean(x) for x in tds[4].get_text("\n", strip=True).split("\n") if clean(x)]
            raw_name = " ".join(name_lines)
            cancelled = "中止" in raw_name
            name = name_lines[-1] if name_lines else raw_name
            note = ""
            if "初入港" in name:
                name = name.replace("【初入港】", "").strip()
                note = "初入港"
            a_day, a_t = _parse_dt(arr, mon, year)
            d_day, d_t = _parse_dt(dep, mon, year)
            res.ships.append(Ship(berth, name, a_day, a_t, d_day, d_t, note, cancelled))
            n += 1
        if n == 0:
            res.warnings.append(f"{year}年の入港予定表が読み取れませんでした")


# ---------------------------------------------------------------- Zepp
def zepp(ctx, res: Result):
    for y, m in ctx.months:
        soup = ctx.fetch.get_soup(f"{res.url}?_y={y}&_m={m}", f"zepp-{y}{m:02d}")
        found = 0
        for a in soup.find_all("a", href=re.compile(r"schedule/single/")):
            txt = clean(a.get_text(" "))
            dm = re.search(r"(\d{4})\s+(\d{1,2})\.(\d{1,2})", txt)
            if not dm:
                continue
            found += 1
            day = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
            h = a.find(re.compile(r"^h[1-6]$"))
            if h:
                title = clean(h.get_text(" "))
            else:
                rest = re.sub(r"^\s*(SUN|MON|TUE|WED|THU|FRI|SAT)\b", "", txt[dm.end():])
                title = dedupe_repeat(clean(rest.split("[OPEN]")[0].split("[PRICE]")[0]))
            url = urljoin(res.url, a["href"])
            sessions = re.findall(r"\[OPEN\]\s*" + TIME_PAT + r"\s*\[START\]\s*" + TIME_PAT, txt)
            if sessions:
                for i, (o, s) in enumerate(sessions):
                    note = f"{i + 1}回目の公演" if len(sessions) > 1 else ""
                    res.events.append(Event("Zepp Yokohama", title, day, norm_time(o), norm_time(s), note=note, url=url))
            else:
                res.events.append(Event("Zepp Yokohama", title, day, url=url))
        if not found:
            res.warnings.append(f"{y}年{m}月: 公演が1件も取得できませんでした")


# ---------------------------------------------------------------- Kアリーナ横浜
def karena(ctx, res: Result):
    soup = ctx.fetch.get_soup(res.url, "karena")
    found = 0
    for a in soup.find_all("a", href=re.compile(r"/schedule/\d{8}-\d+")):
        dm = re.search(r"/schedule/(\d{4})(\d{2})(\d{2})-\d+", a["href"])
        day = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
        t = a.select_one(".schedule-list-item__title")
        ot = a.select_one(".schedule-list-item__open-start")
        artist = a.select_one(".schedule-list-item__artist")
        if t:
            title = clean(t.get_text(" "))
            timetxt = clean(ot.get_text(" ")) if ot else ""
        else:  # 構造が変わった場合の保険(題名に時刻が混ざるのを防ぐ)
            txt = clean(a.get_text(" "))
            timetxt = txt
            title = re.sub(r"\s*OPEN\s*\d.*$", "", txt.split(" - background ")[0])
        om = re.search(r"OPEN\s*" + TIME_PAT + r"\s*/\s*START\s*" + TIME_PAT, timetxt)
        o, s_ = (norm_time(om.group(1)), norm_time(om.group(2))) if om else (None, None)
        note = clean(artist.get_text(" ")) if artist else ""
        if len(note) > 50:
            note = note[:50] + "…"
        if not s_:
            note = (note + " " if note else "") + "時刻は公式サイトで確認"
        res.events.append(Event("Kアリーナ横浜", title, day, o, s_, note=note, url=urljoin(res.url, a["href"])))
        found += 1
    if not found:
        res.warnings.append("公演が1件も取得できませんでした")


# ---------------------------------------------------------------- 横浜武道館
_SKIP_TITLES = {"非公開", "設営", "撤去", "休館日"}
_TOKEN = re.compile(r"^(?:(\d{1,2})日\s*)?(\d{1,2}:\d{2})$")


def _cell_lines(td) -> list[str]:
    return [clean(x) for x in td.get_text("\n").split("\n") if clean(x)]


def _tokens(td) -> list[tuple[int | None, str]]:
    out = []
    for ln in _cell_lines(td):
        m = _TOKEN.match(ln)
        if m:
            out.append((int(m.group(1)) if m.group(1) else None, norm_time(m.group(2))))
    return out


def parse_budokan(soup, y: int, m: int):
    """戻り値: (イベント一覧, 日付の行数)。日付の行が0なら表を読めていない。"""
    events: list[Event] = []
    nrows = 0
    for ti, table in enumerate(soup.select("table.event__main__item__table")):
        label = table.get("aria-labelledby")
        head = soup.find(id=label) if label else None
        section = clean(head.get_text()) if head else ""
        is_dojo = "武道" in section or (not section and ti == 1)
        venue = "横浜武道館(武道場)" if is_dojo else "横浜武道館"
        for tr in table.find_all("tr"):
            d = tr.find("span", class_="_date")
            if not d or not clean(d.get_text()).isdigit():
                continue
            nrows += 1
            tds = tr.find_all("td", recursive=False)
            if not tds or "_close" in (tr.get("class") or []):
                continue
            u = tds[0].select_one("._user")
            title = clean(u.get_text(" ")) if u else clean(tds[0].get_text(" "))
            if not title or title in _SKIP_TITLES or "休館" in title or title.startswith("横浜武道館 教室"):
                continue
            row_day = int(clean(d.get_text()))
            kubun = clean(tds[1].get_text()) if len(tds) > 1 else ""
            count = clean(tds[2].get_text()) if len(tds) > 2 else ""
            note = (kubun + (f" 来場{count}人" if count.isdigit() else "")).strip()
            starts = _tokens(tds[3]) if len(tds) > 3 else []
            ends = _tokens(tds[4]) if len(tds) > 4 else []
            if not starts:
                events.append(Event(venue, title, date(y, m, row_day), note=note))
                continue
            for i, (dd, t) in enumerate(starts):
                end = ends[i][1] if i < len(ends) else None
                events.append(Event(venue, title, date(y, m, dd or row_day), start=t, end=end, note=note))
    return events, nrows


def budokan(ctx, res: Result):
    for y, m in ctx.months:
        page = f"{res.url}?year={y}&month={m}"
        soup = ctx.fetch.get_soup(page, f"budokan-{y}{m:02d}")
        evs, nrows = parse_budokan(soup, y, m)
        for e in evs:
            e.url = page
        res.events.extend(evs)
        if nrows == 0:
            res.warnings.append(f"{y}年{m}月: 表を読み取れませんでした(ページの作りが変わった可能性)")


# ---------------------------------------------------------------- 横浜BUNTAI
_DATE_LINE = re.compile(r"^(\d{1,2})\.(\d{1,2})$")


def _is_stop(line: str) -> bool:
    return bool(re.fullmatch(r"20\d\d", line) or re.match(r"^1月\s+2月", line) or line in ("カレンダーから選ぶ", "HOME EVENT"))


def _times_for(text: str, m: int, d: int):
    seg = text
    mm = re.search(rf"{m}月\s*{d}日", text)
    if mm:
        nxt = re.search(r"\d{1,2}月\s*\d{1,2}日", text[mm.end():])
        seg = text[mm.end(): mm.end() + nxt.start()] if nxt else text[mm.end():]
    om = re.search(r"(?:開場|[Oo][Pp][Ee][Nn])\s*[:：]?\s*" + TIME_PAT, seg)
    sm = re.search(r"(?:開演|[Ss][Tt][Aa][Rr][Tt])\s*[:：]?\s*" + TIME_PAT, seg)
    tm = re.search(TIME_PAT + r"\s*TIP\s*OFF", seg, re.I)
    start = norm_time(sm.group(1)) if sm else (norm_time(tm.group(1)) if tm else None)
    return (norm_time(om.group(1)) if om else None), start


def parse_buntai(lines: list[str], today: date) -> list[Event]:
    out = []
    i, n = 0, len(lines)
    while i < n:
        if not _DATE_LINE.match(lines[i]):
            i += 1
            continue
        dates = []
        while i < n and _DATE_LINE.match(lines[i]):
            g = _DATE_LINE.match(lines[i]).groups()
            dates.append((int(g[0]), int(g[1])))
            i += 1
        j = i
        while j < n and not _DATE_LINE.match(lines[j]) and not _is_stop(lines[j]):
            j += 1
        block, i = lines[i:j], j
        if not block:
            continue
        idx = block.index("公演時間") if "公演時間" in block else min(2, len(block))
        title = clean(" ".join(block[:idx]))
        end_idx = block.index("料金") if "料金" in block else min(len(block), idx + 8)
        text = " ".join(block[idx + 1 : end_idx])
        for m, d in dates:
            try:
                day = infer_date(m, d, today)
            except ValueError:
                continue
            o, s = _times_for(text, m, d)
            out.append(Event("横浜BUNTAI", title, day, o, s))
    return out


def buntai(ctx, res: Result):
    soup = ctx.fetch.get_soup(res.url, "buntai")
    evs = parse_buntai(lines_of(soup), ctx.today)
    for e in evs:
        e.url = res.url
    res.events.extend(evs)
    if not evs:
        res.warnings.append("イベントが1件も取得できませんでした")
    if any(d.month != ctx.today.month for d in ctx.targets):
        res.warnings.append("翌月にまたがる日は、翌月分を取得していません")


# ---------------------------------------------------------------- 日産スタジアム
def nissan(ctx, res: Result):
    base = res.url
    for y, m in ctx.months:
        soup = ctx.fetch.get_soup(base, "nissan-base")
        head = soup.find(["h2", "h3"], string=re.compile(r"\d{4}年\s*\d{1,2}月"))
        shown = re.search(r"(\d{4})年\s*(\d{1,2})月", head.get_text()) if head else None
        if not shown or (int(shown.group(1)), int(shown.group(2))) != (y, m):
            link = soup.find("a", string=re.compile(rf"{y}年\s*{m}月"))
            if not link:
                res.warnings.append(f"{y}年{m}月のカレンダーへのリンクが見つかりません")
                continue
            soup = ctx.fetch.get_soup(urljoin(base, link["href"]), f"nissan-{y}{m:02d}")
        cur = None
        count = 0
        for tr in soup.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) >= 4:
                dtxt = clean(cells[0].get_text())
                content, venue = cells[2], cells[3]
            elif len(cells) == 2:
                dtxt, content, venue = "", cells[0], cells[1]
            else:
                continue
            if dtxt.isdigit():
                cur = int(dtxt)
            if cur is None:
                continue
            a = content.find("a", href=re.compile(r"detail"))
            title = clean(a.get_text(" ")) if a else ""
            if not title:
                continue
            try:
                day = date(y, m, cur)
            except ValueError:
                continue
            e = Event("日産スタジアム", title, day, note=clean(venue.get_text(" ")), url=urljoin(base, a["href"]))
            res.events.append(e)
            count += 1
        if not count:
            res.warnings.append(f"{y}年{m}月: カレンダーが読み取れませんでした")
    for e in res.events:
        if _in_targets(ctx, e):
            _nissan_detail(ctx, e)


def _nissan_detail(ctx, e: Event) -> None:
    """詳細ページの表(行事名/期日/開場/開始/終了/…)から時刻を補う。"""
    if not e.url or ctx.detail_budget <= 0:
        return
    ctx.detail_budget -= 1
    try:
        soup = ctx.fetch.get_soup(e.url, f"nissan-detail-{e.day:%m%d}-{e.url[-6:]}")
    except FetchError:
        return
    vals = {}
    for tr in soup.select("table.cal_table tr"):
        th, td = tr.find("th"), tr.find("td")
        if th and td:
            vals[clean(th.get_text())] = clean(td.get_text(" "))
    e.open = e.open or norm_time(vals.get("開場"))
    e.start = e.start or norm_time(vals.get("開始"))
    e.end = e.end or norm_time(vals.get("終了"))


# ---------------------------------------------------------------- ぴあアリーナMM
def pia(ctx, res: Result):
    for y, m in ctx.months:
        page = f"https://pia-arena-mm.jp/event@p1={y}&p2={m:02d}.html"
        soup = ctx.fetch.get_soup(page, f"pia-{y}{m:02d}")
        found = 0
        for a in soup.select("a.event-list"):
            dt = a.select_one(".event-list__date p")
            h = a.select_one(".event-list__detail h3") or a.select_one("h3")
            dm = re.match(r"\s*(\d{1,2})\.(\d{1,2})", dt.get_text()) if dt else None
            if not dm or not h:
                continue
            found += 1
            title = clean(h.get_text(" "))
            if title.upper() == "PRIVATE":
                continue
            try:
                day = date(y, int(dm.group(1)), int(dm.group(2)))
            except ValueError:
                continue
            res.events.append(Event("ぴあアリーナMM", title, day, url=urljoin(page, a.get("href", ""))))
        if not found:
            res.warnings.append(f"{y}年{m}月: 公演が1件も取得できませんでした")
    for e in res.events:
        if _in_targets(ctx, e):
            enrich(ctx, e, f"pia-detail-{e.day:%m%d}")


# ---------------------------------------------------------------- 横浜アリーナ
def _first_time(v):
    """['20:00予定'] や ['17：00'] の先頭を HH:MM に。空なら None。"""
    return norm_time(v[0]) if isinstance(v, list) and v else None


def parse_arena_json(data, base_url: str) -> list[Event]:
    out = []
    for it in data:
        try:
            d1 = date.fromisoformat(it["date1"])
            d2 = date.fromisoformat(it.get("date2") or it["date1"])
        except (KeyError, ValueError):
            continue
        title = clean(it.get("title") or "")
        artist = clean(it.get("artist") or "")
        if artist and artist not in title:
            title = f"{title}({artist})" if title else artist
        if not title:
            continue
        link = it.get("url") or ""
        if not link and it.get("path"):
            link = urljoin(base_url, it["path"])
        out.append(
            Event(
                "横浜アリーナ", title, d1,
                _first_time(it.get("ev_open")), _first_time(it.get("ev_start")), _first_time(it.get("ev_end")),
                url=link, span_end=d2 if d2 > d1 else None,
            )
        )
    return out


def arena(ctx, res: Result):
    for y, m in ctx.months:
        data = ctx.fetch.get_json(f"https://www.yokohama-arena.co.jp/event/{y}{m:02d}?_format=json", f"arena-{y}{m:02d}")
        if not isinstance(data, list):
            res.warnings.append(f"{y}年{m}月: 予想外の形式のデータでした。「なし」とは限りません")
            continue
        res.events.extend(parse_arena_json(data, "https://www.yokohama-arena.co.jp/"))


# ---------------------------------------------------------------- 横浜スタジアム
_HAMASTA_SKIP = ("保全日", "貸切利用", "予備日")


def parse_hamasta(data) -> list[Event]:
    out = []
    for it in data:
        title = clean(it.get("title") or "")
        if not title or any(k in title for k in _HAMASTA_SKIP):
            continue
        try:
            day = date.fromisoformat(it["date"])
        except (KeyError, ValueError):
            continue
        tg = clean(it.get("target") or "")
        if tg and tg not in title:
            title = f"{title} vs {tg}"
        out.append(
            Event(
                "横浜スタジアム", title, day,
                norm_time(it.get("open_time")), norm_time(it.get("start_time")), norm_time(it.get("end_time")),
                note=clean(it.get("pro_category_1") or ""), url=it.get("title_link") or "",
            )
        )
    return out


def hamasta(ctx, res: Result):
    for y, m in ctx.months:
        data = ctx.fetch.get_json(
            f"https://www.yokohama-stadium.co.jp/_nuxt/_db/event-chunks__{y}-{m:02d}.json", f"hamasta-{y}{m:02d}", ok_404=True
        )
        if data is None:
            res.notes.append(f"{y}年{m}月の日程は公式サイトでまだ公開されていません")
            continue
        if not isinstance(data, list):
            res.warnings.append(f"{y}年{m}月: 予想外の形式のデータでした。「なし」とは限りません")
            continue
        res.events.extend(parse_hamasta(data))


# ---------------------------------------------------------------- パシフィコ横浜
PACIFICO_CALENDARS = [
    "78a66c66587ef8c39d987a3eb014082df0eff54f2445e9f837f94404fa0304e6",
    "n1d7858363ffb40c9c82e272fc18b92528e0db30df3d6e159dfc503eeee6464a5",
    "n9e043fe7408716fce55f5f54f484074002eb939a192acdb50237cfb3ffac54fb",
    "n230f1639b8d54499f15caa874711a36b626933721072c1f9182d1282e4ddc586",
    "n6804e72a022c5b213349f94093988a11b91248a693afc0a30328b839ea2ed120",
    "n737b19946fd8b839a17aaaa8ddc15f64af59045e36622b78fb50dcc31959992e",
]


def _ics_unescape(s: str) -> str:
    return s.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def parse_ics(text: str):
    """(カレンダー名, [{start,end,summary,desc}]) 。終日予定は date、時刻付きは datetime(時刻は文字列)。"""
    lines = []
    for ln in text.replace("\r\n", "\n").split("\n"):
        if ln[:1] in (" ", "\t") and lines:
            lines[-1] += ln[1:]
        else:
            lines.append(ln)
    name, evs, cur = "", [], None
    for ln in lines:
        if ln == "BEGIN:VEVENT":
            cur = {}
        elif ln == "END:VEVENT":
            if cur is not None:
                evs.append(cur)
            cur = None
        elif ":" in ln:
            k, v = ln.split(":", 1)
            base = k.split(";")[0]
            if cur is None:
                if base == "X-WR-CALNAME":
                    name = _ics_unescape(v)
            elif base in ("DTSTART", "DTEND"):
                cur[base] = (v.strip(), "VALUE=DATE" in k.upper())
            elif base == "SUMMARY":
                cur["summary"] = _ics_unescape(v)
            elif base == "DESCRIPTION":
                cur["desc"] = _ics_unescape(v)
            elif base == "RRULE":
                cur["rrule"] = v
    return name, evs


def parse_pacifico(text: str) -> tuple[list[Event], int]:
    from datetime import timedelta

    name, raw = parse_ics(text)
    out, skipped = [], 0
    for e in raw:
        if "DTSTART" not in e:
            continue
        sv, allday = e["DTSTART"]
        try:
            d1 = date(int(sv[0:4]), int(sv[4:6]), int(sv[6:8]))
        except ValueError:
            continue
        start = None
        if not allday and len(sv) >= 13:
            start = f"{sv[9:11]}:{sv[11:13]}"
        d2 = None
        if "DTEND" in e:
            ev, _ = e["DTEND"]
            try:
                d2 = date(int(ev[0:4]), int(ev[4:6]), int(ev[6:8]))
            except ValueError:
                d2 = None
            if d2 and allday:
                d2 -= timedelta(days=1)  # 終日予定の DTEND は翌日(排他的)
        if d2 and d2 <= d1:
            d2 = None
        if e.get("rrule"):
            skipped += 1  # 繰り返し予定は未展開(過去の調査では存在せず)
        m = re.search(r'href="([^"]+)"', e.get("desc", "")) or re.search(r"(https?://\S+)", e.get("desc", ""))
        out.append(
            Event(
                "パシフィコ横浜", clean(e.get("summary", "")), d1, start=start,
                note=(name + " / " if name else "") + ("" if start else "時刻は公式で確認"),
                url=m.group(1) if m else "", span_end=d2,
            )
        )
    return out, skipped


def pacifico(ctx, res: Result):
    ok = 0
    for cid in PACIFICO_CALENDARS:
        url = f"https://calendar.google.com/calendar/ical/{cid}%40group.calendar.google.com/public/basic.ics"
        try:
            # 公式サイトが公開しているカレンダー購読用の公開フィード(robots.txt は Google のもの。個人利用の範囲で取得)
            text = ctx.fetch.get_text(url, f"pacifico-{cid[:6]}", ext="ics", robots=False)
        except FetchError as e:
            res.warnings.append(f"カレンダー{cid[:6]}の取得に失敗: {e}")
            continue
        if "BEGIN:VCALENDAR" not in (text or ""):
            res.warnings.append(f"カレンダー{cid[:6]}が予想外の形式でした")
            continue
        ok += 1
        evs, skipped = parse_pacifico(text)
        if skipped:
            res.warnings.append(f"カレンダー{cid[:6]}に繰り返し予定が{skipped}件あり、未展開です")
        res.events.extend(e for e in evs if _in_targets(ctx, e))
    if not ok:
        raise FetchError("カレンダーを1つも取得できませんでした")
    res.notes.append("パシフィコ横浜は公式カレンダーの日付のみ(開場・開演時刻は未掲載)。時刻は公式サイトで確認してください")


# ---------------------------------------------------------------- 横浜赤レンガ倉庫
_D = r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:[（(][^）)]*[）)])?"
_RANGE = re.compile(_D + r"(?:\s*[～~〜]\s*" + _D + r")?")


def akarenga(ctx, res: Result):
    soup = ctx.fetch.get_soup(res.url, "akarenga")
    seen = set()
    count = 0
    for li in soup.find_all("li"):
        a = li.find("a", href=re.compile(r"/(event|christmas)/"))
        if not a or a["href"] in seen:
            continue
        txt = clean(li.get_text(" "))
        dm = _RANGE.search(txt)
        if not dm:
            continue
        seen.add(a["href"])
        start = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
        end = date(int(dm.group(4)), int(dm.group(5)), int(dm.group(6))) if dm.group(4) else None
        title = dedupe_repeat(clean(a.get_text(" ")))
        rest = clean(txt[dm.end():].replace("イベントの詳細を見る", ""))
        res.events.append(
            Event("横浜赤レンガ倉庫", title, start, note=rest, url=urljoin(res.url, a["href"]), span_end=end)
        )
        count += 1
    if not count:
        res.warnings.append("イベントが1件も取得できませんでした")
    res.notes.append("1号館ホールの公演は別サイト(akarenga.yafjp.org)のため未対応です")


# ---------------------------------------------------------------- 未対応(手動確認)
def manual(ctx, res: Result):
    res.manual = True
