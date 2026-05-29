"use strict";

let CUSTOMERS = [];
let PRODUCTS = [];

const $ = (s) => document.querySelector(s);
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  if (r.status === 401) { window.location = "/login"; throw new Error("請先登入"); }
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).error || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
};
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), 2200);
}

// ---------- 初始化 ----------
async function init() {
  const data = await api("/api/lists");
  CUSTOMERS = data.customers; PRODUCTS = data.products;
  $("#custText").value = CUSTOMERS.map(c => [c.name, ...(c.aliases || [])].join(",")).join("\n");
  $("#prodText").value = PRODUCTS.map(p => [p.name, p.code, ...(p.aliases || [])].filter(Boolean).join(",")).join("\n");
  $("#llmTag").textContent = data.llm_available ? "（AI 已就緒）" : "（未設定 AI 金鑰，僅用規則）";
  await refreshPivot();
  await refreshRecords();
}

// ---------- 解析 ----------
$("#parseBtn").onclick = doParse;
$("#input").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) doParse(); });
document.querySelectorAll(".ex").forEach(a => a.onclick = (e) => {
  e.preventDefault(); $("#input").value = a.textContent.trim(); doParse();
});

async function doParse() {
  const text = $("#input").value.trim();
  if (!text) return;
  $("#parseBtn").disabled = true; $("#parseBtn").textContent = "解析中…";
  try {
    const res = await api("/api/parse", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, use_llm: $("#useLlm").checked }),
    });
    renderPreview(res);
  } catch (e) {
    toast("解析失敗：" + e.message);
  } finally {
    $("#parseBtn").disabled = false; $("#parseBtn").textContent = "解析";
  }
}

function customerOptions(selected) {
  const opts = ['<option value="">（未指定）</option>'];
  for (const c of CUSTOMERS) {
    const sel = c.name === selected ? " selected" : "";
    opts.push(`<option value="${esc(c.name)}"${sel}>${esc(c.name)}</option>`);
  }
  if (selected && !CUSTOMERS.some(c => c.name === selected))
    opts.push(`<option value="${esc(selected)}" selected>${esc(selected)}（新）</option>`);
  return opts.join("");
}

function renderPreview(res) {
  $("#previewCard").classList.remove("hidden");
  $("#pvDate").value = res.date || "";
  $("#pvCustomer").innerHTML = customerOptions(res.customer_name);
  const tag = $("#srcTag");
  tag.className = "tag " + (res.source === "llm" ? "llm" : "rule");
  tag.textContent = res.source === "llm" ? "AI 解析" : "規則解析";
  const tb = $("#itemsTable").querySelector("tbody");
  tb.innerHTML = "";
  (res.items || []).forEach(it => tb.appendChild(itemRow(it)));
  if (!res.items || !res.items.length) tb.appendChild(itemRow({}));
  $("#notes").innerHTML = (res.notes || []).map(n => "⚠ " + esc(n)).join("<br>");
  $("#previewCard").dataset.raw = res.raw || "";
}

function itemRow(it) {
  const tr = document.createElement("tr");
  const conf = it.score == null ? "" :
    `<span class="${it.score >= 0.8 ? "conf-hi" : it.score >= 0.5 ? "conf-mid" : "conf-lo"}">${Math.round((it.score || 0) * 100)}%</span>`;
  let prodOpts = '<option value="">（請選）</option>';
  for (const p of PRODUCTS) {
    const sel = p.name === it.product_name ? " selected" : "";
    prodOpts += `<option value="${esc(p.name)}" data-code="${esc(p.code)}"${sel}>${esc(p.name)}${p.code ? " (" + esc(p.code) + ")" : ""}</option>`;
  }
  if (it.product_name && !PRODUCTS.some(p => p.name === it.product_name))
    prodOpts += `<option value="${esc(it.product_name)}" selected>${esc(it.product_name)}（新）</option>`;
  tr.innerHTML = `
    <td><select class="p-name">${prodOpts}</select></td>
    <td><input class="p-code" value="${esc(it.product_code || "")}" size="6"></td>
    <td><input class="p-qty" type="number" step="any" value="${it.quantity ?? ""}" size="5"></td>
    <td><input class="p-unit" value="${esc(it.unit || "")}" size="4"></td>
    <td class="conf">${conf}</td>
    <td><button class="del">✕</button></td>`;
  const sel = tr.querySelector(".p-name");
  sel.onchange = () => {
    const o = sel.selectedOptions[0];
    if (o && o.dataset.code) tr.querySelector(".p-code").value = o.dataset.code;
  };
  tr.querySelector(".del").onclick = () => tr.remove();
  return tr;
}

$("#addItemBtn").onclick = () =>
  $("#itemsTable").querySelector("tbody").appendChild(itemRow({}));

$("#saveBtn").onclick = async () => {
  const items = [...$("#itemsTable").querySelectorAll("tbody tr")].map(tr => ({
    product_name: tr.querySelector(".p-name").value,
    product_code: tr.querySelector(".p-code").value,
    quantity: parseFloat(tr.querySelector(".p-qty").value) || 0,
    unit: tr.querySelector(".p-unit").value,
  })).filter(it => it.product_name && it.quantity);
  if (!items.length) return toast("沒有可存的品項（需有產品與數量）");
  try {
    const r = await api("/api/records", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date: $("#pvDate").value, customer_name: $("#pvCustomer").value,
        items, raw: $("#previewCard").dataset.raw,
      }),
    });
    toast(`已存 ${r.added} 筆`);
    $("#input").value = ""; $("#previewCard").classList.add("hidden");
    await refreshPivot(); await refreshRecords();
  } catch (e) { toast("存檔失敗：" + e.message); }
};

// ---------- 統計表 ----------
async function refreshPivot() {
  const p = await api("/api/pivot");
  const t = $("#pivotTable");
  if (!p.products.length) { t.innerHTML = ""; $("#pivotEmpty").style.display = "block"; return; }
  $("#pivotEmpty").style.display = "none";
  let html = "<thead><tr><th>產品名稱</th>";
  for (const d of p.dates) html += `<th>${esc(d)}</th>`;
  html += "<th>合計</th></tr></thead><tbody>";
  for (const prod of p.products) {
    const label = prod.code ? `${esc(prod.name)}（${esc(prod.code)}）` : esc(prod.name);
    html += `<tr><td>${label}</td>`;
    for (const d of p.dates) {
      const v = p.matrix[prod.name][d] || 0;
      html += `<td>${v || ""}</td>`;
    }
    html += `<td class="total">${p.row_totals[prod.name] || 0}</td></tr>`;
  }
  html += "<tr><td>合計</td>";
  for (const d of p.dates) html += `<td>${p.col_totals[d] || 0}</td>`;
  html += `<td>${p.grand_total || 0}</td></tr></tbody>`;
  t.innerHTML = html;
}

$("#xlsxBtn").onclick = () => (window.location = "/api/export/xlsx");
$("#csvBtn").onclick = () => (window.location = "/api/export/csv");

// ---------- 明細 ----------
async function refreshRecords() {
  const { records } = await api("/api/records");
  const t = $("#recTable");
  if (!records.length) { t.innerHTML = "<tbody><tr><td class='muted'>尚無紀錄</td></tr></tbody>"; return; }
  let html = "<thead><tr><th>日期</th><th>顧客</th><th>產品</th><th>編號</th><th>數量</th><th>單位</th><th></th></tr></thead><tbody>";
  for (const r of records.slice().reverse()) {
    html += `<tr><td>${esc(r.date)}</td><td>${esc(r.customer_name || "")}</td><td>${esc(r.product_name)}</td>` +
      `<td>${esc(r.product_code || "")}</td><td>${r.quantity}</td><td>${esc(r.unit || "")}</td>` +
      `<td><button class="del" data-id="${r.id}">✕</button></td></tr>`;
  }
  t.innerHTML = html + "</tbody>";
  t.querySelectorAll(".del").forEach(b => b.onclick = async () => {
    await api("/api/records/" + b.dataset.id, { method: "DELETE" });
    await refreshPivot(); await refreshRecords();
  });
}

$("#clearBtn").onclick = async () => {
  if (!confirm("確定清空所有銷貨紀錄？此動作無法復原。")) return;
  await api("/api/records/clear", { method: "POST" });
  await refreshPivot(); await refreshRecords();
};

// ---------- 清單儲存 ----------
document.querySelectorAll("[data-save]").forEach(btn => btn.onclick = async () => {
  const which = btn.dataset.save;
  const text = which === "customers" ? $("#custText").value : $("#prodText").value;
  try {
    await api(`/api/lists/${which}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    await init();
    toast("清單已更新");
  } catch (e) { toast("儲存失敗：" + e.message); }
});

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- 登出 ----------
$("#logoutBtn").onclick = async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location = "/login";
};

// ---------- 語音輸入（瀏覽器 Web Speech API，繁中）----------
(function setupVoice() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const micBtn = $("#micBtn");
  const hint = $("#micHint");
  if (!SR) {
    micBtn.disabled = true;
    micBtn.title = "此瀏覽器不支援語音輸入";
    hint.textContent = "（此瀏覽器不支援語音，建議用 Chrome / Edge）";
    return;
  }
  const rec = new SR();
  rec.lang = "zh-TW";
  rec.interimResults = true;
  rec.continuous = false;
  let listening = false;
  let base = "";

  rec.onresult = (e) => {
    let txt = "";
    for (let i = 0; i < e.results.length; i++) txt += e.results[i][0].transcript;
    $("#input").value = (base + txt).trim();
  };
  rec.onerror = (e) => {
    hint.textContent = e.error === "not-allowed"
      ? "（麥克風權限被拒，請在瀏覽器允許）" : "（語音錯誤：" + e.error + "）";
    stop();
  };
  rec.onend = () => { if (listening) stop(); };

  function start() {
    base = $("#input").value ? $("#input").value + " " : "";
    listening = true;
    micBtn.classList.add("recording");
    hint.textContent = "🔴 聆聽中…講完會自動停止，或再按一次麥克風";
    try { rec.start(); } catch (e) {}
  }
  function stop() {
    listening = false;
    micBtn.classList.remove("recording");
    hint.textContent = "";
    try { rec.stop(); } catch (e) {}
  }
  micBtn.onclick = () => (listening ? stop() : start());
})();

init().catch(e => toast("初始化失敗：" + e.message));
