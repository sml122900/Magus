// 폼 상태·스크랩 초점(2026-10-09 구조·버그 점검 8·9번) 브라우저 시험: 헤드리스 Chrome(CDP). tests/test_forms_browser.py가 부른다.
// 사용: node forms_browser.mjs <chrome> <base> <세션 쿠키> <Chrome 프로필 폴더> <게시판 주소> <글쓰기 주소> <고치기 주소>
// ☆을 Space·Enter로 눌러도 초점이 그 단추에 남는다 / 글자 수 'n/한도', 넘치면 저장을 막는다 /
// 바꾼 채 떠나면 beforeunload로 묻는다(저장하면 묻지 않는다) / 저장 뒤 뒤로 가기는 폼·저장 단추가 처음 모습. 실패하면 종료 코드 1.
import { spawn } from "node:child_process";

const [chromePath, base, cookie, profile, boardPath, writePath, editPath] = process.argv.slice(2);
const port = 9300 + Math.floor(Math.random() * 300);
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
const pending = new Map(), waiters = [], dialogs = [];
ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) { const p = pending.get(msg.id); pending.delete(msg.id); msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result); }
  else if (msg.method) {
    if (msg.method === "Page.javascriptDialogOpening") dialogs.push(msg.params);
    for (const w of waiters.splice(0)) (w.method === msg.method ? w.resolve(msg.params) : waiters.push(w));
  }
});
const send = (method, params = {}) => new Promise((resolve, reject) => { const id = ++seq; pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method, params })); });
const once = (method) => new Promise((resolve) => waiters.push({ method, resolve }));
const js = async (expression) => (await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;
async function go(path) { const loaded = once("Page.loadEventFired"); await send("Page.navigate", { url: base + path }); await loaded; await sleep(200); }
async function until(expr, ms = 10000) { for (let t = 0; t < ms; t += 100) { try { if (await js(expr)) return true; } catch { /* 넘어가는 중 */ } await sleep(100); } return false; }
async function key(k, code, text) {  // 사람이 누른 것과 같은 키(사용자 활성화가 생긴다)
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: k, code, text, windowsVirtualKeyCode: k === "Enter" ? 13 : 32 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code, windowsVirtualKeyCode: k === "Enter" ? 13 : 32 });
}

await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable");
await send("Network.setCookie", { name: "magus_session", value: cookie, url: base, path: "/" });

// 9번: ☆ — Space·Enter로 눌러도 초점이 단추에 남는다
await go(boardPath);
await js("document.querySelector('form.star button').focus()");
await key(" ", "Space", " ");
check("Space로 ☆ → ★", await until("document.querySelector('form.star button').getAttribute('aria-pressed') === 'true'"));
check("Space 뒤 초점이 그 단추에", await js("document.activeElement === document.querySelector('form.star button')"));
await key("Enter", "Enter", "\r");
check("Enter로 ★ → ☆", await until("document.querySelector('form.star button').getAttribute('aria-pressed') === 'false'"));
check("Enter 뒤 초점이 그 단추에", await js("document.activeElement === document.querySelector('form.star button')"));

// 5번: 글자 수 표시와 넘치면 막기
await go(writePath);
check("제목 옆 0/80", (await js("document.querySelector('input[name=title] + .count').textContent")) === "0/80");
check("본문처럼 큰 칸은 한도에 가까울 때만 보인다", await js("getComputedStyle(document.querySelector('textarea[name=content] + .count')).display === 'none'"));
await js("var t=document.querySelector('input[name=title]'); t.focus(); t.value='가'.repeat(81); t.dispatchEvent(new Event('input', {bubbles: true}))");
check("넘치면 '81/80 · 1자 넘음'", (await js("document.querySelector('input[name=title] + .count').textContent")) === "81/80 · 1자 넘음");
await js("document.querySelector('textarea[name=content]').focus()");
await js("document.querySelector('form.write-form button.primary').click()");
await sleep(500);
check("넘친 채 저장하면 그 자리(넘친 칸에 초점)", (await js("location.pathname")) === writePath
  && await js("document.activeElement === document.querySelector('input[name=title]')"));

// 8번: 바꾼 채 떠나면 묻는다
await go(editPath);
await js("document.querySelector('textarea[name=content]').focus()");
await send("Input.insertText", { text: " 더 씀" });
const asked = once("Page.javascriptDialogOpening");
send("Page.navigate", { url: base + "/shelf" }).catch(() => {});
const dialog = await Promise.race([asked, sleep(5000).then(() => null)]);
check("바꾼 채 떠나면 브라우저가 묻는다(beforeunload)", dialog !== null && dialog.type === "beforeunload");
if (dialog) await send("Page.handleJavaScriptDialog", { accept: false });  // 머문다
await sleep(300);
check("머물면 적은 것 그대로", (await js("document.querySelector('textarea[name=content]').value")).includes("더 씀"));
// 저장하면 묻지 않는다 → 글 보기 → 뒤로 가기: 폼·저장 단추가 처음 모습
const saved = once("Page.loadEventFired");
await js("document.querySelector('form.write-form button.primary').click()");
await saved;
await until("location.search.indexOf('done=edited') >= 0 && document.readyState === 'complete'");
check("저장하면 묻지 않고 글 보기로", dialogs.filter((d) => d.type === "beforeunload").length === 1);
const back = once("Page.loadEventFired");
await js("history.back()");
await Promise.race([back, sleep(3000)]);
await sleep(500);
check("뒤로 가기: 저장 단추가 눌린 채 남지 않는다", await until("location.pathname.endsWith('/edit') && !document.querySelector('form.write-form button.primary').disabled"));
check("뒤로 가기: 저장 중 안내가 남지 않는다", (await js("document.querySelector('.pick-note').textContent")) === "");
ws.close(); chrome.kill();
process.exit(failed ? 1 : 0);
