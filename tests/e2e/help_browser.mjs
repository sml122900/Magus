// 도움말 대화 보관(2026-10-09) 브라우저 시험: 헤드리스 Chrome(CDP). tests/test_help_browser.py가 부른다.
// 사용: node help_browser.mjs <chrome> <base> <앨리스 세션 쿠키> <밥 세션 쿠키> <Chrome 프로필 폴더(pytest tmp_path)>
// 페이지 이동 뒤 유지, 접기(✕), 20턴 넘음, 24시간(저장된 시각을 앞당김), 새 대화, 다른 사용자, 로그아웃. 실패하면 종료 코드 1.
import { spawn } from "node:child_process";
import { rmSync } from "node:fs";

const [chromePath, base, cookieA, cookieB, profile] = process.argv.slice(2);
const port = 9600 + Math.floor(Math.random() * 300);
const chrome = spawn(chromePath, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--lang=ko-KR", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
function check(name, cond) { console.log(`${cond ? "ok  " : "FAIL"} ${name}`); if (!cond) failed += 1; }

let target;
for (let i = 0; i < 100 && !target; i++) {
  try { target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page"); } catch { /* 아직 */ }
  if (!target) await sleep(200);
}
if (!target) { console.log("FAIL chrome did not start"); process.exit(1); }
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let seq = 0;
const pending = new Map(), waiters = [];
ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) { const p = pending.get(msg.id); pending.delete(msg.id); msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result); }
  else if (msg.method) { for (const w of waiters.splice(0)) (w.method === msg.method ? w.resolve(msg.params) : waiters.push(w)); }
});
const send = (method, params = {}) => new Promise((resolve, reject) => { const id = ++seq; pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method, params })); });
const once = (method) => new Promise((resolve) => waiters.push({ method, resolve }));
const js = async (expression) => (await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;
async function go(path) { const loaded = once("Page.loadEventFired"); await send("Page.navigate", { url: base + path }); await loaded; await sleep(150); }
async function until(expr, ms = 15000) { for (let t = 0; t < ms; t += 100) { try { if (await js(expr)) return true; } catch { /* 넘어가는 중 */ } await sleep(100); } return false; }
async function login(value) { await send("Network.setCookie", { name: "magus_session", value, url: base, path: "/" }); }
const KEY = `"magus-help:" + document.querySelector(".help").getAttribute("data-user")`;
const stored = `JSON.parse(localStorage.getItem(${KEY}) || "null")`;
async function ask(text) {
  const before = await js("document.querySelectorAll('.help-log li.bot:not(.wait)').length");
  await js(`(function(){var b=document.querySelector('.help-box'); if (b.hidden) document.querySelector('.help-btn').click();
    document.querySelector('.help-form textarea').value=${JSON.stringify(text)}; document.querySelector('.help-form button').click();})()`);
  return until(`document.querySelectorAll('.help-log li.bot:not(.wait)').length > ${before}`);
}

await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable");
await login(cookieA);
await go("/shelf");
check("도움말 단추가 있다", await js("!!document.querySelector('.help-btn')"));
check("첫 질문에 답이 온다", await ask("노드는 어떻게 지우나요?"));
await go("/me");
check("페이지를 옮겨도 대화가 남고 펼친 채", await js("document.querySelectorAll('.help-log li').length === 2 && !document.querySelector('.help-box').hidden"));
await js("document.querySelector('.help-close').click()");
await go("/shelf");
check("✕는 접기: 대화는 남고, 접힌 '?'에 표시", await js(
  "document.querySelector('.help-box').hidden && document.querySelectorAll('.help-log li').length === 2 && document.querySelector('.help-btn').classList.contains('has-talk')"));
await js(`localStorage.setItem(${KEY}, JSON.stringify({turns: Array.from({length: 20}, (_, i) => ({q: "질문" + i, a: "답" + i})), last: Date.now(), open: true}))`);
await go("/shelf");
check("저장된 20턴이 보인다", await js("document.querySelectorAll('.help-log li').length === 40"));
check("21번째 질문", await ask("하나 더"));
check("20턴을 넘으면 가장 오래된 것부터 지운다", await js(`${stored}.turns.length === 20 && ${stored}.turns[0].q === "질문1" && ${stored}.turns[19].q === "하나 더"`));
await js(`(function(){var d=${stored}; d.last = Date.now() - 25*3600*1000; localStorage.setItem(${KEY}, JSON.stringify(d));})()`);
await go("/shelf");
check("마지막 질문 뒤 24시간이 지나면 지운다", await js(`document.querySelectorAll('.help-log li').length === 0 && localStorage.getItem(${KEY}) === null`));
check("다시 묻기", await ask("휴지통은 어디에 있나요?"));
await js("document.querySelector('.help-new').click()");
check("새 대화를 누르면 지운다", await js(`document.querySelectorAll('.help-log li').length === 0 && ${stored}.turns.length === 0`));
check("앨리스가 질문", await ask("앨리스의 질문"));
await login(cookieB);
await go("/shelf");
check("다른 사용자(밥)로 로그인하면 앞 사용자의 대화가 보이지 않는다", await js(
  "document.querySelectorAll('.help-log li').length === 0 && !document.querySelector('.help-btn').classList.contains('has-talk')"));
check("밥이 질문", await ask("밥의 질문"));
await js("document.querySelector('form[action=\"/logout\"] button').click()");
await until("location.pathname === '/logout' && document.readyState === 'complete'");
check("로그아웃하면 이 브라우저의 도움말 대화를 모두 지운다", await js(
  "Object.keys(localStorage).filter(function (k) { return k.indexOf('magus-help:') === 0; }).length === 0"));
ws.close(); chrome.kill();
try { rmSync(profile, { recursive: true, force: true }); } catch { /* Chrome이 아직 붙잡고 있을 수 있다 */ }
process.exit(failed ? 1 : 0);
