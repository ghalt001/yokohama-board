"""パスコード保護のテスト。実行: python tests/test_protect.py"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from board import protect  # noqa: E402

PASS = "correct-horse-battery"
PLAIN = "<html><body>秘密の本文 三井オーシャンサクラ</body></html>"


def test_roundtrip_and_no_plaintext():
    page = protect.build_lock_page(PLAIN, PASS)
    assert "三井オーシャンサクラ" not in page and "秘密の本文" not in page, "平文が漏れている"
    import json, re

    payload = json.loads(re.search(r"const D=(\{.*?\});", page).group(1))
    assert protect.decrypt(payload, PASS) == PLAIN
    try:
        protect.decrypt(payload, "wrong-passcode-x")
        raise AssertionError("誤ったパスコードで復号できてしまった")
    except Exception as e:  # noqa: BLE001
        assert not isinstance(e, AssertionError), e


def test_salt_changes_each_time():
    a, b = protect.encrypt(PLAIN, PASS), protect.encrypt(PLAIN, PASS)
    assert a["salt"] != b["salt"] and a["ct"] != b["ct"]


def test_short_or_missing_passcode_rejected():
    for bad in (None, "", "1234", "123456789"):
        try:
            protect.check_passcode(bad)
            raise AssertionError(f"通ってしまった: {bad!r}")
        except protect.PasscodeError:
            pass
    assert protect.check_passcode("1234567890")


def test_lock_site_removes_plain_files():
    d = tempfile.mkdtemp()
    try:
        open(os.path.join(d, "index.html"), "w", encoding="utf-8").write(PLAIN)
        open(os.path.join(d, "data.json"), "w", encoding="utf-8").write('{"x":"秘密の本文"}')
        protect.lock_site(d, PASS)
        assert not os.path.exists(os.path.join(d, "data.json"))
        assert "秘密の本文" not in open(os.path.join(d, "index.html"), encoding="utf-8").read()
    finally:
        shutil.rmtree(d)


def test_main_fails_closed_without_passcode():
    env = {k: v for k, v in os.environ.items() if k != "BOARD_PASSCODE"}
    out = tempfile.mkdtemp()
    try:
        r = subprocess.run(
            [sys.executable, "-m", "board.main", "--out", out, "--require-passcode"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 2, (r.returncode, r.stderr)
        assert not os.path.exists(os.path.join(out, "index.html")), "保護なしでページが作られた"
        env["BOARD_PASSCODE"] = "short"
        r = subprocess.run(
            [sys.executable, "-m", "board.main", "--out", out, "--require-passcode"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 2 and not os.path.exists(os.path.join(out, "index.html"))
    finally:
        shutil.rmtree(out)


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, repr(e))
    sys.exit(1 if fails else 0)
