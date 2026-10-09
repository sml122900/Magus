// 휴대폰 폭(2026-10-09 구조·버그 점검 11번) 잼: 헤드리스 Chrome(CDP)으로 화면마다 머리 줄 수, 누르는 것의 크기, '?'가 덮는 것.
// 사용: node mobile_measure.mjs <chrome> <base> <세션 쿠키> <프로필 폴더> <폭> <주소…>
// 한 줄에 JSON 하나: {path, width, headerLines, small: [[글자, 높이, 너비]...], covered: [글자...]}. 시험(test_mobile_browser.py)이 기준을 본다.
import { spawn } from "node:child_process";

const [chromePath, base, cookie, profile, widthText, ...paths] = process.argv.slice(2);
const width = Number(widthText);
const port = 9000 + Math.floor(Math.random() * 300);
const chrome = spawn(chromePath, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--lang=ko-KR", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
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
await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable");
await send("Network.setCookie", { name: "magus_session", value: cookie, url: base, path: "/" });
await send("Emulation.setDeviceMetricsOverride", { width, height: 844, deviceScaleFactor: 1, mobile: width < 600 });
const MEASURE = `(function () {
  var site = document.querySelector('.site-in'), kids = site ? Array.from(site.querySelectorAll('.brand, nav > a, nav > form')) : [];
  var tops = []; kids.forEach(function (k) { var t = Math.round(k.getBoundingClientRect().top); if (!tops.some(function (x) { return Math.abs(x - t) < 8; })) tops.push(t); });
  var sel = 'main a, main button, main summary, main label.drop, main input[type=checkbox], main input[type=radio], main select';
  var small = [];
  document.querySelectorAll(sel).forEach(function (el) {
    var r = el.getBoundingClientRect(), s = getComputedStyle(el);
    if (!r.width || !r.height || s.visibility === 'hidden' || el.closest('[hidden]') || el.closest('.world') || el.closest('.del-box') || el.closest('details:not([open]) > :not(summary)')) return;
    var box = el.closest('label') || el;  // 체크 상자는 그것을 감싼 label이 누르는 곳이다
    var b = box.getBoundingClientRect();
    if (Math.min(b.height, b.width) < ${width < 600 ? 44 : 32}) small.push([(box.textContent || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 16), Math.round(b.height), Math.round(b.width), box.tagName + '.' + (box.className || '') + ' < ' + (box.parentElement ? box.parentElement.tagName + '.' + box.parentElement.className : '')]);
  });
  var covered = [], help = document.querySelector('.help-btn');
  if (help) {
    window.scrollTo(0, document.documentElement.scrollHeight);
    var h = help.getBoundingClientRect();
    document.querySelectorAll(sel).forEach(function (el) {
      var r = el.getBoundingClientRect();
      if (r.width && r.right > h.left && r.left < h.right && r.bottom > h.top && r.top < h.bottom) covered.push((el.textContent || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 24));
    });
  }
  return {headerLines: tops.length, headerHeight: site ? Math.round(site.getBoundingClientRect().height) : 0, small: small, covered: covered};
})()`;
for (const path of paths) {
  const loaded = once("Page.loadEventFired");
  await send("Page.navigate", { url: base + path });
  await loaded; await sleep(300);
  console.log(JSON.stringify({ path, width, ...(await js(MEASURE)) }));
}
ws.close(); chrome.kill();
process.exit(0);
