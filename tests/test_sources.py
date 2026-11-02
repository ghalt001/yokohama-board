"""解析処理の動作確認(実サイトには接続せず、想定したHTMLの断片で検証する)。

実行: python tests/test_sources.py
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup  # noqa: E402

from board import sources as S  # noqa: E402
from board.main import SOURCES, run  # noqa: E402
from board.models import Result  # noqa: E402
from board.util import Ctx, FetchError, dedupe_repeat  # noqa: E402

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


def lines_html(lines):
    return "<html><body>" + "".join(f"<p>{x}</p>" for x in lines) + "</body></html>"


def ctx_for(pages):
    return Ctx(today=TODAY, targets=[TODAY, TODAY + timedelta(days=1)], fetch=FakeFetcher(pages))


SHIPS = """<h2>11月</h2><table>
<tr><th>月</th><th>入港</th><th>出港</th><th>着岸場所</th><th>船名</th><th>前港</th><th>次港</th></tr>
<tr><td>11</td><td>2日(月)<br>9:00</td><td>2日（月）<br>17：00</td><td>新港</td><td>三井オーシャンサクラ</td><td>八丈島</td><td>串本</td></tr>
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


KARENA = """<a href="https://k-arena.com/schedule/20261103-1/">Shout Out to Jesus -ENCORE- in K-Arena - background Shout Out to Jesus -ENCORE- in K-Arena KviBaba OPEN 15:30 / START 17:00</a>
<a href="/schedule/20261111-1/">米津玄師 2026 TOUR / GHOST - background 米津玄師 米津玄師</a>"""


def test_karena():
    res = Result("karena", "Kアリーナ横浜", "https://k-arena.com/schedule/")
    S.karena(ctx_for({"karena": KARENA}), res)
    e = res.events[0]
    assert (e.day, e.open, e.start) == (date(2026, 11, 3), "15:30", "17:00")
    assert e.title == "Shout Out to Jesus -ENCORE- in K-Arena"
    assert res.events[1].start is None and "公式" in res.events[1].note


BUDOKAN = [
    "2026年11月のイベント", "アリーナ", "日程 行事名 区分 来場者数 開始 終了 駐車場※ 営業予定",
    "1日", "B.LEAGUE ONE 2026-27 SEASON 横浜エクセレンス vs 新潟", "横浜エクセレンス", "有料 2500", "15:05", "17:05", "×",
    "2月", "非公開", "関係者のみ", "〇",
    "3火", "Super Big Bang 2026", "スーパースターエンターテインメント", "有料 3000", "13:00", "19:00", "×",
    "4水", "K2リーグ", "関係者のみ 450", "未定", "未定", "〇",
    "26木", "第24回支部交流・研修会", "関係者のみ 300", "未定", "未定", "〇",
    "27金", "B.LEAGUE ONE 横浜エクセレンス vs 岐阜", "有料 2500", "27日19:05", "28日15:05", "27日 21:05", "28日 17:05", "×",
    "28土", "29日", "日本整形外科学会100周年記念イベントin横浜", "無料 700", "13:00", "16:00", "〇",
    "※駐車場営業予定〇：通常営業", "武道場", "1日", "第48回関東・東北空手道選手権大会", "関係者のみ 300 未定", "未定", "×",
    "※駐車場営業予定〇：通常営業",
]


def test_budokan():
    evs = S.parse_budokan_lines(BUDOKAN, 2026, 11)
    pick = lambda d: [e for e in evs if e.day == date(2026, 11, d)]
    assert [(e.start, e.end) for e in pick(1) if e.venue == "横浜武道館"] == [("15:05", "17:05")]
    assert pick(2) == [], "非公開は除外"
    assert [(e.title[:5], e.start, e.end) for e in pick(3)] == [("Super", "13:00", "19:00")]
    assert pick(4)[0].start is None and "450" in pick(4)[0].note
    assert [(e.start, e.end) for e in pick(27)] == [("19:05", "21:05")]
    assert [(e.start, e.end) for e in pick(28)] == [("15:05", "17:05")], pick(28)
    assert [e.venue for e in pick(1)].count("横浜武道館(武道場)") == 1


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


NISSAN = """<h3>2026年11月</h3><a href="?m=x">2026年12月</a>
<table><tr><td>icon</td><td>スタジアムツアー</td></tr></table>
<table>
<tr><td>1</td><td>日</td><td><img alt="x"><a href="detail.php?id1">マリノス vs 川崎</a></td><td>日産スタジアム</td></tr>
<tr><td>2</td><td>月</td><td></td><td></td></tr>
<tr><td>3</td><td>火祝</td><td><img alt="y"><a href="detail.php?id2">高校駅伝</a></td><td>日産フィールド小机</td></tr>
<tr><td></td><td></td><td><a href="detail.php?id3">同日の別イベント</a></td><td>草地広場</td></tr>
<tr><td>8</td><td>日</td><td><a href="/tour"><img alt="ツアー"></a></td><td></td></tr>
</table>"""
NISSAN_DETAIL = "<p>試合情報</p><p>開場 11:00</p><p>キックオフ 14:00</p><p>受付開始 08:00</p>"


def test_nissan():
    res = Result("nissan", "日産スタジアム", "https://www.nissan-stadium.jp/calendar/")
    S.nissan(ctx_for({"nissan-base": NISSAN, "nissan-detail": NISSAN_DETAIL}), res)
    d3 = [e for e in res.events if e.day == date(2026, 11, 3)]
    assert [e.title for e in d3] == ["高校駅伝", "同日の別イベント"], d3
    assert (d3[0].open, d3[0].start) == ("11:00", "14:00"), (d3[0].open, d3[0].start)
    assert not [e for e in res.events if e.day == date(2026, 11, 8)], "画像だけのリンクは除外"


PIA = """<a href="/event/6683.html">11.01 SUN コブクロ LIVE TOUR</a>
<a href="/event/7098.html">11.02 MON PRIVATE</a><a href="/event/7096.html">11.03 TUE ガールズバンドクライ Special LIVE</a>"""


def test_pia():
    res = Result("pia", "ぴあアリーナMM", "")
    S.pia(ctx_for({"pia-202611": PIA, "pia-detail": "<p>OPEN 16:00</p><p>START 17:00</p>"}), res)
    assert [e.title for e in res.events if e.day.day in (2, 3)] == ["ガールズバンドクライ Special LIVE"]
    e = [e for e in res.events if e.day.day == 3][0]
    assert (e.open, e.start) == ("16:00", "17:00")


AKARENGA = """<ul><li><a href="/event/aaa/">全国ふるさとフェア２０２６ 全国ふるさとフェア２０２６</a><p>詳細は「イベントの詳細を見る」をご確認ください。</p>
<ul><li>2026年10月31日(土) ～ 2026年11月3日(火)</li><li>イベント広場</li></ul><a href="/event/aaa/">イベントの詳細を見る</a></li>
<li><a href="/event/bbb/">ハンバーガーフェス</a><ul><li>2026年11月14日(土) ～ 2026年11月15日(日)</li><li>イベント広場</li></ul></li></ul>"""


def test_akarenga():
    res = Result("akarenga", "横浜赤レンガ倉庫", "https://www.yokohama-akarenga.jp/event/")
    S.akarenga(ctx_for({"akarenga": AKARENGA}), res)
    e = res.events[0]
    assert e.title == "全国ふるさとフェア２０２６" and e.on(date(2026, 11, 2)) and not e.on(date(2026, 11, 4)), e
    assert "イベント広場" in e.note


def test_arena_empty_table_warns():
    html = "<h2>横浜アリーナで開催されるイベント情報</h2><p>2026.11.01 　コンサート</p><p>U-KNOW PROJECT</p><p>開場：15:00 開演：16:00</p><table><tr><td>日付</td><td>イベント名</td></tr></table>"
    res = Result("arena", "横浜アリーナ", "https://www.yokohama-arena.co.jp/event/")
    S.arena(ctx_for({"arena-202611": html}), res)
    assert res.warnings, "一覧が空なら警告を出す"
    assert res.events and res.events[0].start == "16:00"


def test_dedupe():
    assert dedupe_repeat("A A B") == "A B"
    assert dedupe_repeat("来栖りん 来栖りん 来栖りん ワン") == "来栖りん ワン"


def test_full_run_with_failures(tmp_path_str="/tmp/board_test_out"):
    pages = {"ships-2026": SHIPS, "zepp-202611": ZEPP, "karena": KARENA}  # 他は取得失敗扱い
    now = datetime(2026, 11, 2, 4, 0, tzinfo=JST)
    results = run(tmp_path_str, None, fetcher=FakeFetcher(pages), now=now)
    html = open(os.path.join(tmp_path_str, "index.html"), encoding="utf-8").read()
    assert "三井オーシャンサクラ" in html and "18:15" in html
    assert "⚠取得失敗" in html, "失敗した施設は「なし」ではなく失敗と表示"
    assert "自動取得未対応" in html
    assert "終演目安" in html
    assert sum(1 for r in results if r.error) >= 6


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
