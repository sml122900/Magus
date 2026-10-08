// 첨부 고르기(2026-10-09) 브라우저 시험: 헤드리스 Chrome(CDP). tests/test_attach_browser.py가 부른다.
// 사용: node attach_browser.mjs <chrome> <base> <세션 쿠키> <Chrome 프로필 폴더> <파일 폴더> <글쓰기 주소> <고치기 주소>
// 두 번 나눠 고르기 → 둘 다 남음 / ✕ → 하나만 빠짐 / 끌어다 놓기 더하기 / 11개째 거절 / 크기·형식 거절 / 같은 파일 한 번 / 저장 후 첨부 수.
// 고치기 화면도 같은 동작(기존 첨부 ✕ + 새 첨부). 끝에 "SAVED <글 주소>" 줄을 찍는다. 실패하면 종료 코드 1.
import { spawn } from "node:child_process";
import { join } from "node:path";

const [chromePath, base, cookie, profile, folder, writePath, editPath] = process.argv.slice(2);
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
// 파일 고르기: CDP로 input에 실제 파일을 넣고 change를 일으킨다(사람이 대화 상자에서 고른 것과 같다)
async function pick(names) {
  const { root } = await send("DOM.getDocument", { depth: -1 });
  const { nodeId } = await send("DOM.querySelector", { nodeId: root.nodeId, selector: "input[name=files][multiple]" });
  await send("DOM.setFileInputFiles", { nodeId, files: names.map((n) => join(folder, n)) });
  await sleep(100);
}
const NAMES = "Array.prototype.map.call(document.querySelectorAll('ul.chosen .fname'), function (s) { return s.textContent; }).join('|')";
// 끌어다 놓기: 페이지 안에서 File을 만들어 drop 이벤트로(브라우저가 놓은 파일과 같은 dataTransfer.files)
async function drop(name, type, bytes) {
  await js(`(function(){var dt=new DataTransfer(); dt.items.add(new File([new Uint8Array(${bytes})], ${JSON.stringify(name)}, {type: ${JSON.stringify(type)}}));
    var z=document.querySelector('[data-dropzone]'); z.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true}));
    z.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));})()`);
  await sleep(100);
}

await send("Page.enable"); await send("Runtime.enable"); await send("DOM.enable"); await send("Network.enable");
await send("Network.setCookie", { name: "magus_session", value: cookie, url: base, path: "/" });
await go(writePath);
await pick(["a.png", "b.pdf"]);
await pick(["c.txt"]);
check("두 번 나눠 고르면 둘 다 남는다", (await js(NAMES)) === "a.png|b.pdf|c.txt");
await pick(["a.png"]);
check("같은 파일(이름·크기)은 한 번만", (await js(NAMES)) === "a.png|b.pdf|c.txt");
await js("document.querySelectorAll('ul.chosen button.unpick')[1].click()");
check("✕를 누르면 그 파일만 빠진다", (await js(NAMES)) === "a.png|c.txt");
check("빠진 뒤 안내", (await js("document.querySelector('.pick-note').textContent")).includes("b.pdf"));
await drop("d.png", "image/png", 10);
check("끌어다 놓으면 더해진다", (await js(NAMES)) === "a.png|c.txt|d.png");
await pick(["bad.exe", "big.pdf"]);
const note = await js("document.querySelector('.pick-note').textContent");
check("허용 안 되는 형식은 담는 순간 빼고 안내", note.includes("bad.exe") && note.includes("형식"));
check("한도를 넘는 파일은 담는 순간 빼고 안내", note.includes("big.pdf") && note.includes("넘어"));
check("거절된 파일은 목록에 없다", (await js(NAMES)) === "a.png|c.txt|d.png");
await pick(["e1.txt", "e2.txt", "e3.txt", "e4.txt", "e5.txt", "e6.txt", "e7.txt", "e8.txt"]);
check("11개째는 거절", (await js("document.querySelectorAll('ul.chosen li').length")) === 10
  && (await js("document.querySelector('.pick-note').textContent")).includes("10개까지"));
check("✕는 누르기 쉬운 크기(44px)", await js("document.querySelector('ul.chosen button.unpick').getBoundingClientRect().height >= 44"));
await js("document.querySelector('input[name=title]').value = '첨부 시험'");
const saved = once("Page.loadEventFired");
await js("document.querySelector('form.write-form button.primary').click()");
await saved;
await until("location.pathname.split('/').length === 4 && document.readyState === 'complete'");
check("저장하면 글 보기", (await js("document.querySelector('h1').textContent")) === "첨부 시험");
check("저장 후 첨부 10개(그림 2 + 파일 8)", (await js("document.querySelectorAll('.pics img').length + document.querySelectorAll('ul.files li').length")) === 10);
const post = await js("location.pathname");

// 고치기 화면: 기존 첨부 ✕ + 새 첨부 두 번 나눠 고르기
await go(editPath);
check("고치기: 기존 첨부가 보인다", (await js("document.querySelectorAll('ul.current li').length")) === 1);
await js("document.querySelector('ul.current input[name=drop]').click()");
check("고치기: 기존 첨부 ✕ → 빼기 표시", await js("document.querySelector('ul.current input[name=drop]').checked"));
await pick(["a.png"]);
await pick(["c.txt"]);
check("고치기: 두 번 나눠 골라도 둘 다", (await js(NAMES)) === "a.png|c.txt");
const edited = once("Page.loadEventFired");
await js("document.querySelector('form.write-form button.primary').click()");
await edited;
await until("location.search.indexOf('done=edited') >= 0 && document.readyState === 'complete'");
check("고치기 저장 → 고쳤습니다", (await js("document.querySelector('p.msg') && document.querySelector('p.msg').textContent")) === "고쳤습니다.");
check("고치기 저장 후 첨부 2개(뺀 것은 휴지통)", (await js("document.querySelectorAll('.pics img').length + document.querySelectorAll('ul.files li').length")) === 2);
console.log(`SAVED ${post}`);
ws.close(); chrome.kill();
process.exit(failed ? 1 : 0);
