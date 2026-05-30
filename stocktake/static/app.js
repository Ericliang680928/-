"use strict";
// 共用工具
window.$ = (s, r) => (r || document).querySelector(s);
window.$$ = (s, r) => [...(r || document).querySelectorAll(s)];

window.api = async (url, opts) => {
  const r = await fetch(url, opts);
  if (r.status === 401) { window.location = "/login"; throw new Error("請先登入"); }
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (!r.ok) { const e = new Error(data.error || r.statusText); e.status = r.status; e.data = data; throw e; }
  return data;
};
window.post = (url, body) => api(url, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
});

let _toastT;
window.toast = (msg) => {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; document.body.appendChild(t); }
  t.textContent = msg; t.style.display = "block";
  clearTimeout(_toastT); _toastT = setTimeout(() => (t.style.display = "none"), 2400);
};

window.esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

window.logout = async () => { await fetch("/api/auth/logout", { method: "POST" }); window.location = "/login"; };
