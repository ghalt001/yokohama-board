"""解析処理の動作確認(実サイトには接続せず、実際のHTMLを写した断片で検証する)。

武道館・ぴあアリーナMM・Kアリーナ・日産スタジアム(詳細)・客船入港は、実ページのHTMLの構造をそのまま写した断片を使っている。

実行: python tests/test_sources.py
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup  # noqa: E402

from board import sources as S  # noqa: E402
from board.main import SOURCES, run  # noqa: E402
from board.models import Result  # noqa: E402
from board.util import Ctx, FetchError, dedupe_repeat, norm_time, times_from_text  # noqa: E402

TODAY = date(2026, 11, 2)
JST = timezone(timedelta(hours=9))


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages  # tagの先頭一致 → HTML

    def get_soup(self, url, tag):
        for k, v in self.pages.items():
            if tag.startswith(k):
                return BeautifulSoup(v, "lxml")
        raise FetchError("fixture なし: " + tag)

    def get_text(self, url, tag, ext="txt", robots=True, ok_404=False):
        for k, v in self.pages.items():
            if tag.startswith(k):
                if v is None:
                    if ok_404:
                        return None
                    raise FetchError("HTTP 404")
                return v
        raise FetchError("fixture なし: " + tag)

    def get_json(self, url, tag, ok_404=False):
        import json as _j

        t = self.get_text(url, tag, ext="json", ok_404=ok_404)
        return None if t is None else _j.loads(t)


def lines_html(lines):
    return "<html><body>" + "".join(f"<p>{x}</p>" for x in lines) + "</body></html>"


def ctx_for(pages):
    return Ctx(today=TODAY, targets=[TODAY, TODAY + timedelta(days=1)], fetch=FakeFetcher(pages))


# ---------------------------------------------------------------- 共通
def test_norm_time():
    assert norm_time("17:00") == "17:00"
    assert norm_time("9:30") == "09:30"
    assert norm_time("13時") == "13:00"
    assert norm_time("10時30分") == "10:30"
    assert norm_time("16時00分") == "16:00"
    assert norm_time("未定") is None and norm_time("") is None and norm_time(None) is None
    o, s, e = times_from_text("公演時間 開場/17:00 開演/18:00 料金 受付開始 08:00")
    assert (o, s, e) == ("17:00", "18:00", None), (o, s, e)


# ---------------------------------------------------------------- 客船入港(実HTMLと同じ構造)
SHIPS = """<h2>11月</h2><table><caption>11月</caption>
<tr><th scope="col" class="center">月</th><th scope="col" class="center">入港（着岸）</th><th scope="col" class="center">出港（離岸）</th><th scope="col" class="center">着岸場所</th><th scope="col" class="center">船名</th><th scope="col" class="center">前港</th><th scope="col" class="center">次港</th></tr>
<tr><td class="center">11</td><td class="left">2日(月)<br>9:00</td><td class="left">2日(月)<br>17:00</td><td class="center">新港</td><td class="center">三井オーシャンサクラ</td><td class="center">八丈島</td><td class="center">串本</td></tr>
<tr><td>11</td><td>3日(火)<br>非公開</td><td>3日(火)<br>17:00</td><td>大黒</td><td>テスト号【初入港】</td><td>a</td><td>b</td></tr>
<tr><td>11</td><td>1日(日)<br>9:00</td><td>4日(水)<br>17:00</td><td>大さん橋</td><td>長期停泊船</td><td>a</td><td>b</td></tr>
<tr><td>11</td><td>2日(月)<br>9:00</td><td>2日(月)<br>17:00</td><td>新港</td><td>※荒天により、寄港中止<br>キャンセル船</td><td>a</td><td>b</td></tr>
</table>"""


def test_ships():
    res = Result("ships", "客船入港", "")
    S.ships(ctx_for({"ships-2026": SHIPS}), res)
    day = TODAY
    got = {s.name: s.describe_on(day) for s in res.ships}
    assert got["三井オーシャンサクラ"] == "入港 09:00 → 出港 17:00", got
    assert got["長期停泊船"] == "停泊中", got
    assert got["キャンセル船"] is None, got
    nxt = {s.name: s.describe_on(day + timedelta(days=1)) for s in res.ships}
    assert nxt["テスト号"] == "入港 時刻非公開 → 出港 17:00", nxt
    assert [s for s in res.ships if s.name == "テスト号"][0].berth == "大黒ふ頭"
    assert [s for s in res.ships if s.name == "テスト号"][0].note == "初入港"


ZEPP = """<a href="/hall/yokohama/schedule/single/?rid=1">TODAY 2026 11.2 MON T.C.R.横浜銀蝿R.S. T.C.R.横浜銀蝿R.S. 【振替公演】 Rock'n Roll 集会 [OPEN] 18:15 [START] 19:00 [PRICE] 全席指定/ ¥12,100</a>
<a href="/hall/yokohama/schedule/single/?rid=2">2026 11.3 TUE 来栖りん 来栖りん 来栖りん ワンマンライブ [OPEN] 13:00 [START] 14:00 [PRICE] x [OPEN] 17:30 [START] 18:30 [PRICE] y</a>
<a href="/hall/yokohama/schedule/single/?rid=3">2026 11.7 SAT 別の日 [OPEN] 17:00 [START] 18:00</a>"""


def test_zepp():
    res = Result("zepp", "Zepp Yokohama", "https://www.zepp.co.jp/hall/yokohama/schedule/")
    S.zepp(ctx_for({"zepp-202611": ZEPP}), res)
    by_day = {}
    for e in res.events:
        by_day.setdefault(e.day.day, []).append(e)
    assert len(by_day[2]) == 1 and by_day[2][0].open == "18:15" and by_day[2][0].start == "19:00"
    assert by_day[2][0].title.startswith("T.C.R.横浜銀蝿R.S. 【振替公演】"), by_day[2][0].title
    assert [(e.open, e.start) for e in by_day[3]] == [("13:00", "14:00"), ("17:30", "18:30")]
    assert by_day[3][0].title == "来栖りん ワンマンライブ", by_day[3][0].title


# ---------------------------------------------------------------- Kアリーナ(実HTMLと同じ構造)
KARENA = """<a href="https://k-arena.com/schedule/20261103-1/"><div class="schedule-list-item__container"><div class="schedule-list-item__image"><div class="schedule-list-item__image--blur"><img src="x.jpeg" alt="Shout Out to Jesus -ENCORE- in K-Arena - background"></div><img class="schedule-list-item__image--main" src="x.jpeg" alt="Shout Out to Jesus -ENCORE- in K-Arena"></div><div class="schedule-list-item__content"><h2 class="schedule-list-item__title">Shout Out to Jesus -ENCORE- in K-Arena</h2><p class="schedule-list-item__artist">KviBaba</p><div class="schedule-list-item__open-start"><p>OPEN 15:30 / START 17:00</p></div></div></div></a>
<a href="https://k-arena.com/schedule/20261111-1/"><div class="schedule-list-item__container"><div class="schedule-list-item__content"><h2 class="schedule-list-item__title">米津玄師 2026 TOUR / GHOST</h2><p class="schedule-list-item__artist">米津玄師</p><div class="schedule-list-item__open-start"><!-- <p>開演時間は調整中につき今後お知らせいたします。</p> --></div></div></div></a>"""

KARENA_OLD_LAYOUT = """<a href="/schedule/20261103-1/">Shout Out to Jesus -ENCORE- in K-Arena KviBaba OPEN 15:30 / START 17:00</a>"""


def test_karena():
    res = Result("karena", "Kアリーナ横浜", "https://k-arena.com/schedule/")
    S.karena(ctx_for({"karena": KARENA}), res)
    e = res.events[0]
    assert (e.day, e.open, e.start) == (date(2026, 11, 3), "15:30", "17:00")
    assert e.title == "Shout Out to Jesus -ENCORE- in K-Arena", e.title
    assert e.note == "KviBaba", e.note
    assert res.events[1].start is None and "公式" in res.events[1].note
    assert res.events[1].title == "米津玄師 2026 TOUR / GHOST"
    # 構造が変わっても、題名に時刻が混ざらない
    res2 = Result("karena", "Kアリーナ横浜", "https://k-arena.com/schedule/")
    S.karena(ctx_for({"karena": KARENA_OLD_LAYOUT}), res2)
    assert "OPEN" not in res2.events[0].title and res2.events[0].start == "17:00", res2.events[0]


# ---------------------------------------------------------------- 横浜武道館(実HTMLと同じ構造)
def bd_row(day, wd, title=None, host="", kubun="", count="", start=None, end=None, rowspan=1):
    th = f'<th class=" js-holiday" scope="row"><span class="_date">{day}</span><span class="_day">{wd}</span></th>'
    if title is None:
        return f"<tr>{th}</tr>"  # 複数日イベントの2日目以降(セルなし)

    def times(v):
        v = v or []
        return "".join(f"<div>{x}</div>" for x in (v + ["", "", ""])[:3])

    rs = f' rowspan="{rowspan}"'
    host_html = f'<a href="https://example.com/" target="_blank" rel="noopener"> {host} </a>' if host else ""
    return (
        f'<tr>{th}<td{rs}><div class="_user"><a href="detail.html?1">{title}</a></div><div class="_host">{host_html}</div></td>'
        f"<td{rs}>{kubun}</td><td{rs}>{count}</td><td{rs}>{times(start)}</td><td{rs}>{times(end)}</td><td{rs}>〇</td></tr>"
    )


def table(label_id, rows):
    return (
        f'<div class="event__main__item__table-wrapper"><table class="event__main__item__table" aria-labelledby="{label_id}">'
        '<thead><tr><th scope="col">日程</th><th class="_title" scope="col">行事名</th><th scope="col">区分</th>'
        '<th scope="col">来場者数</th><th scope="col">開始</th><th scope="col">終了</th><th scope="col">駐車場<sup>※</sup><br>営業予定</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )


CLOSED = (
    '<tr class="_close"><th class=" js-holiday" scope="row"><span class="_date">19</span><span class="_day">木</span></th>'
    '<td rowspan="1"><div class="_user"><span>休館日</span></div><div class="_host"></div></td><td rowspan="1"></td><td rowspan="1"></td>'
    '<td rowspan="1"><div></div><div></div><div></div></td><td rowspan="1"><div></div><div></div><div></div></td><td rowspan="1"></td></tr>'
)

BUDOKAN_ARENA = "".join(
    [
        bd_row(1, "日", "B.LEAGUE ONE 2026-27 SEASON 横浜エクセレンス vs 新潟", "横浜エクセレンス", "有料", "2500", ["15:05"], ["17:05"]),
        bd_row(2, "月", "非公開", kubun="関係者のみ"),
        bd_row(3, "火", "Super Big Bang 2026", "スーパースターエンターテインメント", "有料", "3000", ["13:00"], ["19:00"]),
        bd_row(4, "水", "第34回FOLTリーグ団体戦", "(一社)新日本ｽﾎﾟｰﾂ連盟", "関係者のみ", "450", ["9:30"], ["18:00"]),
        bd_row(6, "金", "設営"),
        CLOSED,
        bd_row(27, "金", "B.LEAGUE ONE 2026-27 SEASON 横浜エクセレンス vs 岐阜", "横浜エクセレンス", "有料", "2500", ["27日19:05", "28日15:05"], ["27日 21:05", "28日 17:05"], rowspan=2),
        bd_row(28, "土"),
        bd_row(29, "日", "日本整形外科学会100周年記念イベントin横浜", "神奈川県臨床整形外科医会", "無料", "700", ["13:00"], ["16:00"]),
    ]
)
BUDOKAN_DOJO = bd_row(1, "日", "第48回関東・東北空手道選手権大会", "", "関係者のみ", "300", ["未定"], ["未定"])
BUDOKAN = (
    '<h3 id="arena">アリーナ</h3>' + table("arena", BUDOKAN_ARENA) + '<h3 id="dojo">武道場</h3>' + table("dojo", BUDOKAN_DOJO)
)


def test_budokan():
    soup = BeautifulSoup(BUDOKAN, "lxml")
    evs, nrows = S.parse_budokan(soup, 2026, 11)
    assert nrows >= 9
    pick = lambda d, v="横浜武道館": [e for e in evs if e.day == date(2026, 11, d) and e.venue == v]
    assert [(e.start, e.end) for e in pick(1)] == [("15:05", "17:05")]
    assert pick(2) == [] and pick(6) == [] and pick(19) == [], "非公開・設営・休館日は除外"
    e3 = pick(3)
    assert [(e.title, e.start, e.end) for e in e3] == [("Super Big Bang 2026", "13:00", "19:00")], e3
    assert e3[0].note == "有料 来場3000人", e3[0].note
    assert [(e.start, e.end) for e in pick(4)] == [("09:30", "18:00")]
    assert [(e.start, e.end) for e in pick(27)] == [("19:05", "21:05")]
    assert [(e.start, e.end) for e in pick(28)] == [("15:05", "17:05")], pick(28)
    assert [(e.start, e.end) for e in pick(29)] == [("13:00", "16:00")]
    dojo = pick(1, "横浜武道館(武道場)")
    assert len(dojo) == 1 and dojo[0].start is None


def test_budokan_unreadable_page_warns():
    """表が読めなかったとき、「なし」ではなく警告が出ること(取りこぼしの見逃し防止)。"""
    res = Result("budokan", "横浜武道館", "https://www.yokohama-budokan.com/event/")
    S.budokan(ctx_for({"budokan-202611": "<html><body><p>全く違う作りのページ</p></body></html>"}), res)
    assert res.events == [] and res.warnings, res.warnings


BUNTAI = [
    "EVENT", "イベント", "2026", "2024", "1月 2月 3月", "カレンダーから選ぶ",
    "11.3", "Aimer Premium Concert 2026", "公演時間", "open 16:30 / start 17:30", "料金", "指定席 ￥9,500",
    "11.7", "B.LEAGUE 2026-27 SEASON 横浜ビー・コルセアーズ HOMEGAME", "vs神戸ストークス", "公演時間", "15:05 TIPOFF", "料金", "公式HPをご確認ください。",
    "11.21", "11.22", "B.LEAGUE B.ONE 横浜エクセレンス HOMEGAME vs熊本", "公演時間", "11月21日 17:35 TIPOFF", "11月22日 15:05 TIPOFF", "料金",
    "11.28", "11.29", "アイカツスターズ！10周年記念イベント", "公演時間", "11月28日(土)", "開場：16時00分", "開演：17時00分", "11月29日(日)", "開場：15時00分", "開演：16時00分", "料金", "x",
    "2024", "1月 2月 3月",
]


def test_buntai():
    evs = S.parse_buntai(BUNTAI, TODAY)
    f = lambda m, d: [e for e in evs if e.day == date(2026, m, d)]
    assert (f(11, 3)[0].open, f(11, 3)[0].start) == ("16:30", "17:30")
    assert f(11, 7)[0].start == "15:05" and "vs神戸" in f(11, 7)[0].title
    assert f(11, 21)[0].start == "17:35" and f(11, 22)[0].start == "15:05"
    assert (f(11, 28)[0].open, f(11, 28)[0].start) == ("16:00", "17:00")
    assert (f(11, 29)[0].open, f(11, 29)[0].start) == ("15:00", "16:00")


# ---------------------------------------------------------------- 日産スタジアム(一覧・詳細とも実HTMLと同じ構造)
NISSAN = """<h3>2026年11月</h3><a href="?m=x">2026年12月</a>
<table><tr><td>icon</td><td>スタジアムツアー</td></tr></table>
<table>
<tr class="bdnone01"><th>1</th><th class="th01"><span class="sun"><span>日</span></span></th><td><img src="img/icon_soccer.png" title="サッカー" alt="サッカー"><a href="detail.php?id1">マリノス vs 川崎</a><a><br></a></td><td class="sub2">日産スタジアム</td></tr>
<tr><th>2</th><th>月</th><td></td><td></td></tr>
<tr><th>3</th><th>火祝</th><td><img alt="y"><a href="detail.php?id2">高校駅伝</a></td><td>日産フィールド小机</td></tr>
<tr><td><a href="detail.php?id3">同日の別イベント</a></td><td>草地広場</td></tr>
<tr><th>8</th><th>日</th><td><a href="/tour"><img alt="ツアー"></a></td><td></td></tr>
</table>"""
NISSAN_DETAIL = """<section class="cont_right"><table class="cal_table"><tbody><tr><th>行事名</th><td>明治安田Ｊ１リーグ 横浜F・マリノス vs 川崎フロンターレ</td></tr><tr><th>期日</th><td>2026年11月1日</td></tr><tr><th>開場</th><td>10時30分</td></tr><tr><th>開始</th><td>13時</td></tr><tr><th>終了</th><td></td></tr><tr><th>主催</th><td></td></tr></tbody></table></section>"""
NISSAN_DETAIL_EMPTY = """<table class="cal_table"><tbody><tr><th>行事名</th><td>x</td></tr><tr><th>開場</th><td></td></tr><tr><th>開始</th><td></td></tr><tr><th>終了</th><td></td></tr></tbody></table>"""


def test_nissan():
    res = Result("nissan", "日産スタジアム", "https://www.nissan-stadium.jp/calendar/")
    S.nissan(ctx_for({"nissan-base": NISSAN, "nissan-detail": NISSAN_DETAIL}), res)
    d3 = [e for e in res.events if e.day == date(2026, 11, 3)]
    assert [e.title for e in d3] == ["高校駅伝", "同日の別イベント"], d3
    assert (d3[0].open, d3[0].start, d3[0].end) == ("10:30", "13:00", None), (d3[0].open, d3[0].start)
    assert not [e for e in res.events if e.day == date(2026, 11, 8)], "画像だけのリンクは除外"
    # 詳細に時刻が書かれていないときは、時刻なし(終日/未定)のまま
    res2 = Result("nissan", "日産スタジアム", "https://www.nissan-stadium.jp/calendar/")
    S.nissan(ctx_for({"nissan-base": NISSAN, "nissan-detail": NISSAN_DETAIL_EMPTY}), res2)
    assert all(e.open is None and e.start is None for e in res2.events if e.day == date(2026, 11, 3))


# ---------------------------------------------------------------- ぴあアリーナMM(実HTMLと同じ構造)
def pia_item(href, md, wd, title):
    return (
        f'<li><a class="event-list" href="{href}"><div class="event-list__date"><p>{md}</p><span class="nationalHoliday">{wd}</span></div>'
        '<div class="event-list__photo"><img class="event-list__photo__bg" src="a.jpg" alt=""><img class="event-list__photo__img" src="a.jpg" alt=""></div>'
        f'<div class="event-list__detail"><div class="title"><h3>{title}</h3><p></p></div></div></a></li>'
    )


PIA = "<ul>" + "".join(
    [
        pia_item("event/6683.html", "11.01", "SUN", "コブクロ KOBUKURO LIVE TOUR 2026 霞日和"),
        pia_item("event/7098.html", "11.02", "MON", "PRIVATE"),
        pia_item("event/7096.html", "11.03", "TUE", "ガールズバンドクライ Special LIVE“赤色の響祭”"),
    ]
) + "</ul>"
PIA_DETAIL = '<dl class="single-event__list"><dt>公演時間</dt><dd>開場/17:00 開演/18:00</dd></dl><dl class="single-event__list"><dt>料金</dt><dd>x</dd></dl>'


def test_pia():
    res = Result("pia", "ぴあアリーナMM", "")
    S.pia(ctx_for({"pia-202611": PIA, "pia-detail": PIA_DETAIL}), res)
    assert [e.title for e in res.events if e.day.day in (2, 3)] == ["ガールズバンドクライ Special LIVE“赤色の響祭”"]
    e = [e for e in res.events if e.day.day == 3][0]
    assert (e.open, e.start) == ("17:00", "18:00")
    assert e.url == "https://pia-arena-mm.jp/event/7096.html", e.url
    assert not res.warnings


def test_pia_unreadable_page_warns():
    res = Result("pia", "ぴあアリーナMM", "")
    S.pia(ctx_for({"pia-202611": "<html><body>違う作り</body></html>"}), res)
    assert res.warnings


AKARENGA = """<ul><li><a href="/event/aaa/">全国ふるさとフェア２０２６ 全国ふるさとフェア２０２６</a><p>詳細は「イベントの詳細を見る」をご確認ください。</p>
<ul><li>2026年10月31日(土) ～ 2026年11月3日(火)</li><li>イベント広場</li></ul><a href="/event/aaa/">イベントの詳細を見る</a></li>
<li><a href="/event/bbb/">ハンバーガーフェス</a><ul><li>2026年11月14日(土) ～ 2026年11月15日(日)</li><li>イベント広場</li></ul></li></ul>"""


def test_akarenga():
    res = Result("akarenga", "横浜赤レンガ倉庫", "https://www.yokohama-akarenga.jp/event/")
    S.akarenga(ctx_for({"akarenga": AKARENGA}), res)
    e = res.events[0]
    assert e.title == "全国ふるさとフェア２０２６" and e.on(date(2026, 11, 2)) and not e.on(date(2026, 11, 4)), e
    assert "イベント広場" in e.note


ARENA_JSON = json.dumps([
    {"date1": "2026-11-03", "date2": "2026-11-03", "category": "1", "title": "i☆Ris 14th Anniversary Live", "artist": "i☆Ris",
     "ev_open": ["17:00"], "ev_start": ["18:00"], "ev_end": [], "construction": ["2026-11-02"], "path": "/event/detail/iris", "url": False},
    {"date1": "2026-11-02", "date2": "2026-11-03", "category": "2", "title": "展示会", "artist": False,
     "ev_open": ["9：30"], "ev_start": [], "ev_end": ["17：00予定"], "path": "/event/detail/x", "url": "https://example.com/"},
])


def test_arena_json():
    res = Result("arena", "横浜アリーナ", "https://www.yokohama-arena.co.jp/event/")
    S.arena(ctx_for({"arena-202611": ARENA_JSON}), res)
    assert not res.warnings and len(res.events) == 2
    a = [e for e in res.events if "Ris" in e.title][0]
    assert (a.open, a.start, a.end) == ("17:00", "18:00", None) and a.url.endswith("/event/detail/iris")
    b = [e for e in res.events if e.title == "展示会"][0]
    assert (b.open, b.end) == ("09:30", "17:00") and b.span_end == date(2026, 11, 3) and b.url == "https://example.com/"


def test_arena_bad_json_is_error():
    res = Result("arena", "横浜アリーナ", "https://www.yokohama-arena.co.jp/event/")
    try:
        S.arena(ctx_for({"arena-202611": "{}"}), res)
    except Exception:
        return
    assert res.warnings, "想定外の形式は警告かエラーにする"


HAMASTA = json.dumps([
    {"title": "保全日", "title_link": "", "date": "2026-10-31", "open_time": "", "start_time": "", "end_time": "", "target": "", "pro_category_1": ""},
    {"title": "貸切利用", "title_link": "", "date": "2026-10-23", "open_time": "", "start_time": "", "end_time": "", "target": ""},
    {"title": "SMBC日本シリーズ2026", "title_link": "https://www.baystars.co.jp/game/result/1", "date": "2026-10-25",
     "open_time": "", "start_time": "18:00", "end_time": "", "target": "福岡ソフトバンクホークス", "pro_category_1": "日本シリーズ"},
    {"title": "「SMBC日本シリーズ2026」パブリックビューイング", "title_link": "", "date": "2026-10-25",
     "open_time": "16:30", "start_time": "18:00", "end_time": "", "target": "", "pro_category_1": ""},
])


def test_hamasta_october():
    today = date(2026, 10, 25)
    ctx = Ctx(today=today, targets=[today, today + timedelta(days=1)], fetch=FakeFetcher({"hamasta-202610": HAMASTA}))
    res = Result("hamasta", "横浜スタジアム", "https://www.yokohama-stadium.co.jp/events/")
    S.hamasta(ctx, res)
    assert [e.title for e in res.events if e.day == today] == [
        "SMBC日本シリーズ2026 vs 福岡ソフトバンクホークス", "「SMBC日本シリーズ2026」パブリックビューイング"], res.events
    assert not any("保全日" in e.title or "貸切" in e.title for e in res.events)
    assert res.events[0].start == "18:00" and res.events[0].url


def test_hamasta_unpublished_month_is_note_not_error():
    ctx = ctx_for({"hamasta-202611": None})
    res = Result("hamasta", "横浜スタジアム", "https://www.yokohama-stadium.co.jp/events/")
    S.hamasta(ctx, res)
    assert not res.events and not res.warnings and any("公開されていません" in n for n in res.notes)


ICS = (
    "BEGIN:VCALENDAR\r\nX-WR-CALNAME:国際会議\r\n"
    "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261102\r\nDTEND;VALUE=DATE:20261105\r\n"
    "SUMMARY:全国\\, 学会大会\r\nDESCRIPTION:<a href=\"https://example.com/ev1\">詳細</a>\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261120\r\nDTEND;VALUE=DATE:20261121\r\nSUMMARY:別の日\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261103\r\nSUMMARY:折り返し\r\n テストのタイトル\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


def test_pacifico_ics():
    pages = {"pacifico-": ICS}
    res = Result("pacifico", "パシフィコ横浜", "https://www.pacifico.co.jp/eventInfo")
    S.pacifico(ctx_for(pages), res)
    titles = sorted({e.title for e in res.events})
    assert titles == ["全国, 学会大会", "折り返しテストのタイトル"], titles
    e = [x for x in res.events if x.title.startswith("全国")][0]
    assert e.day == date(2026, 11, 2) and e.span_end == date(2026, 11, 4) and e.url == "https://example.com/ev1"
    assert "国際会議" in e.note and not res.warnings


def test_pacifico_all_fail_is_error():
    res = Result("pacifico", "パシフィコ横浜", "https://www.pacifico.co.jp/eventInfo")
    try:
        S.pacifico(ctx_for({}), res)
    except FetchError:
        return
    raise AssertionError("全カレンダー失敗はエラーにする")


def test_dedupe():
    assert dedupe_repeat("A A B") == "A B"
    assert dedupe_repeat("来栖りん 来栖りん 来栖りん ワン") == "来栖りん ワン"


def test_full_run_with_failures(tmp_path_str="/tmp/board_test_out"):
    pages = {"ships-2026": SHIPS, "zepp-202611": ZEPP, "karena": KARENA}  # 他は取得失敗扱い
    now = datetime(2026, 11, 2, 4, 0, tzinfo=JST)
    results = run(tmp_path_str, None, fetcher=FakeFetcher(pages), now=now)
    html = open(os.path.join(tmp_path_str, "index.html"), encoding="utf-8").read()
    assert "三井オーシャンサクラ" in html and "18:15" in html
    assert "取得に失敗しました" in html, "失敗した施設は「なし」ではなく失敗と表示"
    assert "終演目安" in html
    assert sum(1 for r in results if r.error) >= 6


def test_full_run_all_sources_with_real_shapes(tmp_path_str="/tmp/board_test_out2"):
    pages = {
        "ships-2026": SHIPS, "zepp-202611": ZEPP, "karena": KARENA,
        "budokan-202611": BUDOKAN, "buntai": lines_html(BUNTAI),
        "nissan-base": NISSAN, "nissan-detail": NISSAN_DETAIL,
        "pia-202611": PIA, "pia-detail": PIA_DETAIL, "akarenga": AKARENGA,
        "arena-202611": ARENA_JSON, "hamasta-202611": None, "pacifico-": ICS,
    }
    now = datetime(2026, 11, 2, 4, 0, tzinfo=JST)
    from board import render as R

    R.SHOW_TOMORROW = True  # 明日分の解析も確認するため一時的に有効化
    try:
        results = run(tmp_path_str, None, fetcher=FakeFetcher(pages), now=now)
    finally:
        R.SHOW_TOMORROW = False
    assert not [r.name for r in results if r.error], [(r.name, r.error) for r in results if r.error]
    html = open(os.path.join(tmp_path_str, "index.html"), encoding="utf-8").read()
    assert "ガールズバンドクライ" in html and "Super Big Bang 2026" in html


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                import traceback

                print("FAIL", name, repr(e))
                traceback.print_exc()
    sys.exit(1 if fails else 0)
