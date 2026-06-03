/* ============================================================
   會議記錄小幫手 — 前端邏輯
   - 即時語音辨識：Web Speech API（瀏覽器原生，純前端）
   - 摘要 / 待辦：內建規則萃取，或選填 OpenAI API 強化
   - 匯出：txt / Word（前端 Blob）
   - 歷史：localStorage + 關鍵字搜尋
   ============================================================ */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const STORE_KEY = 'mt_history_v1';
  const KEY_KEY = 'mt_openai_key';

  // ---- DOM ----
  const recBtn = $('recBtn'), recLabel = $('recLabel'), status = $('status'),
        timer = $('timer'), transcript = $('transcript'), interim = $('interim'),
        meetingTitle = $('meetingTitle'), langSel = $('lang'), clearBtn = $('clearBtn'),
        summaryBtn = $('summaryBtn'), summaryList = $('summaryList'), todoList = $('todoList'),
        exportWord = $('exportWord'), exportTxt = $('exportTxt'), saveBtn = $('saveBtn'),
        search = $('search'), historyList = $('historyList'), apiKey = $('apiKey'),
        unsupported = $('unsupported'), audioFile = $('audioFile'), uploadHint = $('uploadHint');

  // ---- 語音辨識初始化 ----
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recog = null, recording = false, seconds = 0, timerId = null;

  if (!SR) {
    unsupported.hidden = false;
    recBtn.disabled = true;
    recBtn.title = '此瀏覽器不支援語音辨識';
  }

  function buildRecognizer() {
    const r = new SR();
    r.lang = langSel.value;
    r.continuous = true;
    r.interimResults = true;

    r.onresult = (e) => {
      let finalChunk = '', interimChunk = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalChunk += t;
        else interimChunk += t;
      }
      if (finalChunk) {
        const stamp = fmtClock(new Date());
        const sep = transcript.value && !transcript.value.endsWith('\n') ? '\n' : '';
        transcript.value += `${sep}[${stamp}] ${finalChunk.trim()}\n`;
        transcript.scrollTop = transcript.scrollHeight;
      }
      interim.textContent = interimChunk;
    };

    r.onerror = (e) => {
      if (e.error === 'no-speech') return; // 忽略短暫無聲
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        status.textContent = '⚠️ 麥克風權限被拒，請允許麥克風存取';
        stopRecording();
      } else {
        status.textContent = '辨識錯誤：' + e.error;
      }
    };

    // continuous 模式下瀏覽器仍可能自動結束 → 若仍在錄音則自動續接
    r.onend = () => {
      if (recording) { try { r.start(); } catch (_) {} }
    };
    return r;
  }

  // ---- 錄音控制 ----
  function startRecording() {
    recog = buildRecognizer();
    try { recog.start(); } catch (_) {}
    recording = true;
    recBtn.classList.add('is-rec');
    recLabel.textContent = '停止錄音';
    status.textContent = '🔴 錄音中…';
    langSel.disabled = true;
    timerId = setInterval(() => { seconds++; timer.textContent = fmtDur(seconds); }, 1000);
  }

  function stopRecording() {
    recording = false;
    if (recog) { try { recog.stop(); } catch (_) {} }
    clearInterval(timerId);
    recBtn.classList.remove('is-rec');
    recLabel.textContent = seconds ? '繼續錄音' : '開始錄音';
    status.textContent = seconds ? '⏸ 已停止（可繼續或產生摘要）' : '尚未開始';
    interim.textContent = '';
    langSel.disabled = false;
  }

  recBtn.addEventListener('click', () => recording ? stopRecording() : startRecording());

  clearBtn.addEventListener('click', () => {
    if (transcript.value && !confirm('確定要清空目前的逐字稿與計時？')) return;
    transcript.value = ''; interim.textContent = ''; seconds = 0;
    timer.textContent = '00:00'; recLabel.textContent = '開始錄音';
    status.textContent = '尚未開始';
    summaryList.innerHTML = '<li class="muted">尚未產生摘要</li>';
    todoList.innerHTML = '<li class="muted">尚未產生待辦</li>';
  });

  // ---- 上傳音檔轉錄（選配後端 server.py） ----
  const LANG_TO_ISO = { 'zh-TW': 'zh', 'zh-CN': 'zh', 'en-US': 'en', 'ja-JP': 'ja' };

  audioFile.addEventListener('change', async () => {
    const file = audioFile.files[0];
    if (!file) return;
    const uploadBtn = audioFile.closest('.upload__btn');
    uploadBtn.classList.add('is-busy');
    uploadHint.textContent = `⏳ 上傳並轉錄中：${file.name}（檔案越長越久，請稍候）`;

    const fd = new FormData();
    fd.append('audio', file);
    fd.append('language', LANG_TO_ISO[langSel.value] || '');

    try {
      const res = await fetch('/api/transcribe', { method: 'POST', body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      const text = (data.text || '').trim();
      if (text) {
        const sep = transcript.value && !transcript.value.endsWith('\n') ? '\n' : '';
        transcript.value += `${sep}[音檔：${file.name}] ${text}\n`;
        transcript.scrollTop = transcript.scrollHeight;
        uploadHint.textContent = `✅ 已轉錄並附加到逐字稿：${file.name}`;
      } else {
        uploadHint.textContent = '⚠️ 轉錄結果為空，請確認音檔內容';
      }
    } catch (err) {
      const noServer = err instanceof TypeError; // fetch 失敗 → 多半沒啟動後端
      uploadHint.textContent = noServer
        ? '⚠️ 找不到後端服務。請依 README 啟動 server.py 後再上傳音檔。'
        : '⚠️ 轉錄失敗：' + err.message;
    } finally {
      uploadBtn.classList.remove('is-busy');
      audioFile.value = '';
    }
  });

  // ---- 摘要與待辦：內建規則 ----
  // 待辦：含行動／指派語氣的句子
  const TODO_HINTS = ['要', '需要', '請', '負責', '追蹤', '完成', '提出', '準備', '安排',
    '確認', '聯絡', '寄', '提交', '截止', '下週', '下周', '明天', '本週', '本周',
    '預計', '規劃', '處理', 'todo', 'action', 'deadline', '前完成', '製作', '撰寫'];
  // 重點：含決策／結論語氣的句子
  const KEY_HINTS = ['決定', '決議', '結論', '共識', '通過', '同意', '預算', '目標',
    '重點', '問題', '風險', '方向', '確定', '結果', '建議'];

  function splitSentences(text) {
    return text
      .replace(/\[\d{1,2}:\d{2}(:\d{2})?\]/g, ' ')      // 去掉時間戳
      .split(/[。！？!?\n;；]+/)
      .map(s => s.trim())
      .filter(s => s.length >= 4);
  }

  function ruleExtract(text) {
    const sents = splitSentences(text);
    const score = (s, hints) => hints.reduce((n, h) => n + (s.includes(h) ? 1 : 0), 0);

    const todos = [];
    const seenTodo = new Set();
    sents.forEach(s => {
      if (score(s, TODO_HINTS) > 0) {
        const k = s.slice(0, 30);
        if (!seenTodo.has(k)) { seenTodo.add(k); todos.push(s); }
      }
    });

    let keys = sents
      .map(s => ({ s, n: score(s, KEY_HINTS) }))
      .filter(o => o.n > 0)
      .sort((a, b) => b.n - a.n)
      .map(o => o.s);
    // 去重 + 若太少則補上較長的句子作為重點
    keys = [...new Set(keys)];
    if (keys.length < 3) {
      const extra = sents.filter(s => !keys.includes(s)).sort((a, b) => b.length - a.length);
      keys = keys.concat(extra.slice(0, 3 - keys.length));
    }

    return { summary: keys.slice(0, 6), todos: todos.slice(0, 10) };
  }

  function renderResults({ summary, todos }) {
    summaryList.innerHTML = summary.length
      ? summary.map(s => `<li>${esc(s)}</li>`).join('')
      : '<li class="muted">內容不足，無法萃取重點</li>';
    todoList.innerHTML = todos.length
      ? todos.map(s => `<li><input type="checkbox"><span>${esc(s)}</span></li>`).join('')
      : '<li class="muted">未偵測到明確待辦事項</li>';
  }

  summaryBtn.addEventListener('click', async () => {
    const text = transcript.value.trim();
    if (!text) { alert('逐字稿是空的，請先錄音或輸入文字。'); return; }
    const key = apiKey.value.trim();
    if (key) {
      summaryBtn.textContent = '🧠 AI 分析中…';
      try {
        const r = await aiExtract(text, key);
        renderResults(r);
        localStorage.setItem(KEY_KEY, key);
      } catch (err) {
        alert('AI 摘要失敗，改用內建規則。\n' + err.message);
        renderResults(ruleExtract(text));
      } finally {
        summaryBtn.textContent = '🧠 產生摘要與待辦';
      }
    } else {
      renderResults(ruleExtract(text));
    }
  });

  // ---- OpenAI 強化摘要（選填） ----
  async function aiExtract(text, key) {
    const prompt = `你是專業的會議記錄助理。請閱讀以下會議逐字稿，輸出 JSON：
{"summary":["重點1","重點2"...],"todos":["待辦1","待辦2"...]}
summary 為重要決策、討論重點與結論（3-6 點），todos 為需要後續執行的行動項目（可標註負責人與期限）。只輸出 JSON。

逐字稿：
${text.slice(0, 8000)}`;

    const res = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key },
      body: JSON.stringify({
        model: 'gpt-4o-mini',
        messages: [{ role: 'user', content: prompt }],
        temperature: 0.2,
        response_format: { type: 'json_object' }
      })
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    const obj = JSON.parse(data.choices[0].message.content);
    return { summary: obj.summary || [], todos: obj.todos || [] };
  }

  // ---- 匯出 ----
  function currentTitle() {
    return (meetingTitle.value.trim() || '會議記錄') ;
  }
  function buildReport() {
    const sums = [...summaryList.querySelectorAll('li:not(.muted)')].map(li => li.textContent);
    const todos = [...todoList.querySelectorAll('li:not(.muted) span')].map(li => li.textContent);
    return { title: currentTitle(), date: fmtDate(new Date()),
             transcript: transcript.value.trim(), summary: sums, todos };
  }

  exportTxt.addEventListener('click', () => {
    const r = buildReport();
    let out = `${r.title}\n日期：${r.date}\n${'='.repeat(40)}\n\n`;
    out += `【重點摘要】\n${r.summary.length ? r.summary.map((s,i)=>`${i+1}. ${s}`).join('\n') : '（無）'}\n\n`;
    out += `【待辦事項】\n${r.todos.length ? r.todos.map(s=>`☐ ${s}`).join('\n') : '（無）'}\n\n`;
    out += `【逐字稿】\n${r.transcript || '（無）'}\n`;
    download(out, `${r.title}.txt`, 'text/plain;charset=utf-8');
  });

  exportWord.addEventListener('click', () => {
    const r = buildReport();
    const html = `<html xmlns:o="urn:schemas-microsoft-com:office:office"
      xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">
      <head><meta charset="utf-8"></head><body style="font-family:'Microsoft JhengHei',sans-serif">
      <h1>${esc(r.title)}</h1><p>日期：${r.date}</p>
      <h2>重點摘要</h2><ul>${r.summary.map(s=>`<li>${esc(s)}</li>`).join('')||'<li>（無）</li>'}</ul>
      <h2>待辦事項</h2><ul>${r.todos.map(s=>`<li>☐ ${esc(s)}</li>`).join('')||'<li>（無）</li>'}</ul>
      <h2>逐字稿</h2><p style="white-space:pre-wrap">${esc(r.transcript)||'（無）'}</p>
      </body></html>`;
    download('﻿' + html, `${r.title}.doc`, 'application/msword');
  });

  // ---- 歷史（localStorage） ----
  function loadHistory() { try { return JSON.parse(localStorage.getItem(STORE_KEY)) || []; } catch { return []; } }
  function saveHistory(arr) { localStorage.setItem(STORE_KEY, JSON.stringify(arr)); }

  saveBtn.addEventListener('click', () => {
    const r = buildReport();
    if (!r.transcript) { alert('沒有可儲存的內容。'); return; }
    const arr = loadHistory();
    arr.unshift({ id: Date.now(), ...r });
    saveHistory(arr);
    renderHistory();
    status.textContent = '✅ 已存入歷史';
  });

  function renderHistory(filter = '') {
    const arr = loadHistory();
    const f = filter.trim().toLowerCase();
    const shown = f ? arr.filter(x =>
      (x.title + x.transcript + x.summary.join('') + x.todos.join('')).toLowerCase().includes(f)
    ) : arr;

    if (!shown.length) {
      historyList.innerHTML = `<p class="muted" style="grid-column:1/-1;padding:18px">${
        arr.length ? '找不到符合的會議。' : '尚無歷史紀錄，按「存入歷史」即可保存。'}</p>`;
      return;
    }
    historyList.innerHTML = shown.map(x => `
      <div class="hist-card" data-id="${x.id}">
        <h4>${esc(x.title)}</h4>
        <div class="meta">${x.date} · ${x.summary.length} 重點 · ${x.todos.length} 待辦</div>
        <div class="excerpt">${esc(x.transcript).slice(0, 160)}</div>
        <div class="hist-card__btns">
          <button class="btn btn--ghost btn--sm" data-act="load">載入</button>
          <button class="btn btn--ghost btn--sm" data-act="del">刪除</button>
        </div>
      </div>`).join('');
  }

  historyList.addEventListener('click', (e) => {
    const btn = e.target.closest('button'); if (!btn) return;
    const id = Number(btn.closest('.hist-card').dataset.id);
    const arr = loadHistory();
    const item = arr.find(x => x.id === id);
    if (btn.dataset.act === 'del') {
      if (!confirm('刪除這筆會議紀錄？')) return;
      saveHistory(arr.filter(x => x.id !== id));
      renderHistory(search.value);
    } else if (btn.dataset.act === 'load' && item) {
      meetingTitle.value = item.title;
      transcript.value = item.transcript;
      renderResults({ summary: item.summary, todos: item.todos });
      window.scrollTo({ top: $('app').offsetTop - 60, behavior: 'smooth' });
    }
  });

  search.addEventListener('input', () => renderHistory(search.value));

  // ---- 小工具 ----
  function fmtDur(s) { const m = String(Math.floor(s/60)).padStart(2,'0'); const ss = String(s%60).padStart(2,'0'); return `${m}:${ss}`; }
  function fmtClock(d) { return d.toTimeString().slice(0,8); }
  function fmtDate(d) { return d.toLocaleString('zh-TW', { hour12:false }); }
  function esc(s='') { return s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
  function download(content, name, type) {
    const blob = new Blob([content], { type });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ---- 啟動 ----
  apiKey.value = localStorage.getItem(KEY_KEY) || '';
  renderHistory();
})();
