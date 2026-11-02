"""公開ページをパスコードで保護する。

GitHub Pages は静的ファイルしか配れないため、ページ全体を AES-256-GCM で暗号化し、
ブラウザ側(Web Crypto)でパスコードから鍵を作って復号する方式にしている。
公開されるのは暗号文とロック画面だけで、パスコードを知らない人には中身が読めない。

注意: 暗号文は誰でも取得できるため、短いパスコードは手元のPCで総当たりされうる。
そのため MIN_LEN 文字未満のパスコードはビルドを失敗させる。
"""
from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERATIONS = 600_000  # PBKDF2-SHA256(OWASP推奨値)。iPhoneでも1秒未満
MIN_LEN = 10


class PasscodeError(Exception):
    pass


def check_passcode(passcode: str | None) -> str:
    if not passcode:
        raise PasscodeError("パスコード(環境変数 BOARD_PASSCODE)が設定されていません")
    if len(passcode) < MIN_LEN:
        raise PasscodeError(f"パスコードは{MIN_LEN}文字以上にしてください(現在{len(passcode)}文字)")
    return passcode


def encrypt(plain: str, passcode: str) -> dict:
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(hashes.SHA256(), 32, salt, ITERATIONS).derive(passcode.encode("utf-8"))
    ct = AESGCM(key).encrypt(iv, plain.encode("utf-8"), None)
    b = lambda x: base64.b64encode(x).decode("ascii")
    return {"salt": b(salt), "iv": b(iv), "ct": b(ct), "iter": ITERATIONS}


def decrypt(payload: dict, passcode: str) -> str:
    """検証用(本番はブラウザ側で復号する)。"""
    d = lambda k: base64.b64decode(payload[k])
    key = PBKDF2HMAC(hashes.SHA256(), 32, d("salt"), payload["iter"]).derive(passcode.encode("utf-8"))
    return AESGCM(key).decrypt(d("iv"), d("ct"), None).decode("utf-8")


LOCK_PAGE = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="color-scheme" content="light dark">
<title>ボード</title>
<style>
:root{--bg:#f6f7f9;--fg:#1a1d21;--card:#fff;--line:#dde1e6;--mut:#667085;--acc:#0b5fff;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#101215;--fg:#e8eaed;--card:#1a1d22;--line:#2c3138;--mut:#9aa3ad;--acc:#6ea0ff;--bad:#ff7b72}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Hiragino Sans","Yu Gothic",sans-serif}
form{width:min(92vw,360px);background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px}
h1{font-size:1.1rem;margin:0 0 14px}
input[type=password]{width:100%;font-size:1rem;padding:12px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)}
button{width:100%;margin-top:12px;padding:12px;font-size:1rem;font-weight:700;border:0;border-radius:8px;background:var(--acc);color:#fff}
button[disabled]{opacity:.6}label{display:block;margin-top:10px;font-size:.85rem;color:var(--mut)}
#msg{min-height:1.4em;margin:10px 0 0;font-size:.9rem;color:var(--bad)}
noscript{color:var(--bad)}
</style></head><body>
<form id="f" autocomplete="on">
<h1>パスコードを入力してください</h1>
<input type="text" name="username" autocomplete="username" value="board" hidden>
<input id="p" type="password" name="password" autocomplete="current-password" autofocus required>
<label><input id="r" type="checkbox" checked> この端末で記憶する</label>
<button id="b" type="submit">開く</button>
<p id="msg" role="alert"></p>
<noscript>JavaScriptを有効にしてください。</noscript>
</form>
<script>
const D=__PAYLOAD__;
const KEY="board_passcode";
const b64=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
async function open(pass){
  const base=await crypto.subtle.importKey("raw",new TextEncoder().encode(pass),"PBKDF2",false,["deriveKey"]);
  const key=await crypto.subtle.deriveKey({name:"PBKDF2",salt:b64(D.salt),iterations:D.iter,hash:"SHA-256"},base,{name:"AES-GCM",length:256},false,["decrypt"]);
  const buf=await crypto.subtle.decrypt({name:"AES-GCM",iv:b64(D.iv)},key,b64(D.ct));
  return new TextDecoder().decode(buf);
}
function show(html){document.open();document.write(html);document.close();}
function store(op,v){try{if(op==="get")return localStorage.getItem(KEY);if(op==="set")localStorage.setItem(KEY,v);else localStorage.removeItem(KEY);}catch(e){}return null;}
const f=document.getElementById("f"),p=document.getElementById("p"),m=document.getElementById("msg"),btn=document.getElementById("b");
f.addEventListener("submit",async e=>{
  e.preventDefault();m.textContent="";btn.disabled=true;btn.textContent="確認中…";
  try{
    const html=await open(p.value);
    if(document.getElementById("r").checked)store("set",p.value);else store("del");
    show(html);
  }catch(err){
    m.textContent=window.crypto&&crypto.subtle?"パスコードが違います":"この環境では開けません(https でアクセスしてください)";
    btn.disabled=false;btn.textContent="開く";p.select();
  }
});
(async()=>{
  const saved=store("get");
  if(!saved||!window.crypto||!crypto.subtle)return;
  try{show(await open(saved));}catch(e){store("del");}
})();
</script></body></html>
"""


def build_lock_page(plain_html: str, passcode: str) -> str:
    payload = json.dumps(encrypt(plain_html, passcode), separators=(",", ":"))
    return LOCK_PAGE.replace("__PAYLOAD__", payload)


def lock_site(out_dir: str, passcode: str) -> None:
    """out_dir/index.html を暗号化したロック画面に置き換え、平文のデータは削除する。"""
    passcode = check_passcode(passcode)
    path = os.path.join(out_dir, "index.html")
    with open(path, encoding="utf-8") as f:
        plain = f.read()
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_lock_page(plain, passcode))
    for leftover in ("data.json",):
        fp = os.path.join(out_dir, leftover)
        if os.path.exists(fp):
            os.remove(fp)
