from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from . import sources as S
from .models import Result
from .protect import PasscodeError, check_passcode, lock_site
from .render import render
from .util import Ctx, Fetcher

JST = timezone(timedelta(hours=9))

# (key, 表示名, 代表URL, 取得関数)
SOURCES = [
    ("ships", "客船入港", "https://www.city.yokohama.lg.jp/kanko-bunka/minato/kyakusen/nyuko/2026.html", S.ships),
    ("arena", "横浜アリーナ", "https://www.yokohama-arena.co.jp/event/", S.arena),
    ("nissan", "日産スタジアム", "https://www.nissan-stadium.jp/calendar/", S.nissan),
    ("hamasta", "横浜スタジアム", "https://www.yokohama-stadium.co.jp/events/", S.manual),
    ("budokan", "横浜武道館", "https://www.yokohama-budokan.com/event/", S.budokan),
    ("buntai", "横浜BUNTAI", "https://yokohama-buntai.jp/event/", S.buntai),
    ("pia", "ぴあアリーナMM", "https://pia-arena-mm.jp/event/index.html", S.pia),
    ("karena", "Kアリーナ横浜", "https://k-arena.com/schedule/", S.karena),
    ("pacifico", "パシフィコ横浜", "https://www.pacifico.co.jp/eventInfo", S.manual),
    ("zepp", "Zepp Yokohama", "https://www.zepp.co.jp/hall/yokohama/schedule/", S.zepp),
    ("akarenga", "横浜赤レンガ倉庫", "https://www.yokohama-akarenga.jp/event/", S.akarenga),
]


def run(out_dir: str, raw_dir: str | None, fetcher=None, now: datetime | None = None) -> list[Result]:
    now = now or datetime.now(JST)
    today = now.date()
    ctx = Ctx(today=today, targets=[today, today + timedelta(days=1)], fetch=fetcher or Fetcher(raw_dir))
    results: list[Result] = []
    for key, name, url, fn in SOURCES:
        res = Result(key=key, name=name, url=url)
        try:
            fn(ctx, res)
        except Exception as e:  # 1か所の失敗で全体を止めない
            res.error = f"{type(e).__name__}: {e}"[:200]
            print(f"[NG] {name}: {res.error}", file=sys.stderr)
        else:
            print(f"[OK] {name}: events={len(res.events)} ships={len(res.ships)} warn={len(res.warnings)}")
        results.append(res)

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(render(results, now, ctx.targets))
    with open(os.path.join(out_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, ensure_ascii=False, indent=1, default=str)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    ap.add_argument("--raw", default=None, help="取得した生HTMLの保存先(デバッグ用)")
    ap.add_argument(
        "--require-passcode",
        action="store_true",
        help="環境変数 BOARD_PASSCODE が無い/短い場合は公開せずに失敗する(本番用)",
    )
    a = ap.parse_args()

    passcode = os.environ.get("BOARD_PASSCODE")
    if a.require_passcode or passcode:
        try:
            passcode = check_passcode(passcode)
        except PasscodeError as e:
            print(f"[STOP] {e}。保護なしでは公開しません。", file=sys.stderr)
            sys.exit(2)

    results = run(a.out, a.raw)
    if passcode:
        lock_site(a.out, passcode)
        print("[OK] ページをパスコードで暗号化しました")
    auto = [r for r in results if not r.manual]
    if auto and all(r.error for r in auto):
        sys.exit(1)  # 全滅したときだけ失敗扱い(GitHubからメールが届く)


if __name__ == "__main__":
    main()
