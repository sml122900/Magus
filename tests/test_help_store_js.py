"""도움말 대화 보관(2026-10-09): 브라우저 localStorage 로직(MagusHelpStore)을 node로 돌려 본다. node가 없으면 건너뛴다.
20턴 넘음(오래된 것부터), 마지막 질문 뒤 24시간, 새 대화, 로그아웃(모두 지움), 사용자별 열쇠, 망가진 값."""

from __future__ import annotations

import shutil
import subprocess

from conftest import needs_tools

from magus.helpbot import HELP_STORE_JS, user_key

NODE = shutil.which("node")

CHECKS = r"""
function Storage() { this.m = {}; }
Storage.prototype.getItem = function (k) { return k in this.m ? this.m[k] : null; };
Storage.prototype.setItem = function (k, v) { this.m[k] = String(v); };
Storage.prototype.removeItem = function (k) { delete this.m[k]; };
Storage.prototype.key = function (i) { return Object.keys(this.m)[i] || null; };
Object.defineProperty(Storage.prototype, "length", {get: function () { return Object.keys(this.m).length; }});
function ok(cond, what) { if (!cond) { console.error("FAIL " + what); process.exit(1); } }
var S = MagusHelpStore, st = new Storage(), A = "magus-help:alice", B = "magus-help:bob", now = 1000000000000;
var d = S.read(st, A, now);
ok(d.turns.length === 0 && d.open === false, "빈 시작");
for (var i = 0; i < 25; i++) d = S.add(st, A, d, "질문" + i, "답" + i, now + i);
ok(d.turns.length === 20 && d.turns[0].q === "질문5" && d.turns[19].q === "질문24", "20턴 넘으면 오래된 것부터");
ok(S.read(st, A, now + 100).turns.length === 20, "다시 읽어도 20턴");
ok(S.read(st, B, now).turns.length === 0, "다른 사용자 열쇠에는 없다");
ok(S.read(st, A, now + 24 + S.TTL - 1).turns.length === 20, "24시간 안이면 그대로");
ok(S.read(st, A, now + 24 + S.TTL + 1).turns.length === 0 && st.getItem(A) === null, "마지막 질문 뒤 24시간이 지나면 지운다");
d = S.add(st, A, S.read(st, A, now), "q", "a", now);
d.open = true; S.write(st, A, d);
ok(S.read(st, A, now).open === true, "펼친 상태도 남는다");
ok(S.clear(st, A).turns.length === 0 && st.getItem(A) === null, "새 대화는 지운다");
S.add(st, A, S.read(st, A, now), "q", "a", now); S.add(st, B, S.read(st, B, now), "q", "a", now); st.setItem("other-app", "x");
S.clearAll(st);
ok(st.getItem(A) === null && st.getItem(B) === null && st.getItem("other-app") === "x", "로그아웃은 도움말 열쇠만 모두 지운다");
st.setItem(A, "{망가진"); ok(S.read(st, A, now).turns.length === 0, "망가진 값은 빈 대화");
st.setItem(A, JSON.stringify({turns: [{q: 1, a: "x"}, {q: "질문", a: "답"}], last: now}));
ok(S.read(st, A, now).turns.length === 1, "형식이 틀린 턴은 뺀다");
var broken = {getItem: function () { throw new Error("막힘"); }, setItem: function () { throw new Error("막힘"); },
              removeItem: function () { throw new Error("막힘"); }, key: function () { return null; }, length: 0};
ok(S.read(broken, A, now).turns.length === 0 && S.add(broken, A, S.read(broken, A, now), "q", "a", now).turns.length === 1, "막힌 저장소에서도 죽지 않는다");
console.log("ok");
"""


@needs_tools("node가 없다", NODE)
def test_help_store_logic_in_node():
    done = subprocess.run([NODE, "-e", HELP_STORE_JS + "\n" + CHECKS], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"


def test_user_key_differs_per_user_and_hides_the_name():
    assert user_key("alice") != user_key("bob") and len(user_key("alice")) == 16 and "alice" not in user_key("alice")
