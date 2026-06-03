# 會議記錄小幫手（會議逐字稿 / 摘要 / 待辦）

仿 Chat Everywhere V2「會議記錄小幫手」設計的**純前端**單頁應用：
打開麥克風即可即時轉錄，自動萃取重點摘要與待辦事項，一鍵匯出 Word／txt。

## 功能

- 🎧 **即時逐字轉錄** — 使用瀏覽器原生 Web Speech API，邊講邊出字，逐字稿可手動修正
- 🧠 **重點摘要與決策** — 內建規則自動萃取（可選填 OpenAI API Key 走 AI 強化）
- ✅ **待辦事項自動標註** — 偵測行動／指派語氣的句子，整理成可勾選清單
- 📤 **多格式匯出** — 一鍵下載 Word（.doc）或純文字（.txt）
- 🔎 **歷史與搜尋** — 會議存於瀏覽器 `localStorage`，支援關鍵字搜尋
- 📱 **響應式** — 電腦、平板、手機皆可使用

## 使用方式

純靜態網站，**不需後端**。直接用瀏覽器打開即可：

```bash
# 方式一：直接開檔
open index.html        # macOS
# 或在檔案總管中雙擊 index.html

# 方式二：起一個本機伺服器（建議，麥克風在 http://localhost 才會放行）
python3 -m http.server 8000
# 然後瀏覽 http://localhost:8000/
```

> ⚠️ 語音辨識需在 **HTTPS 或 localhost** 環境才能取得麥克風權限。
> 建議使用桌機版 **Chrome** 或 **Edge**（Web Speech API 支援度最佳）。

## 檔案結構

| 檔案 | 說明 |
|------|------|
| `index.html` | 頁面結構（Hero／功能／流程／工作台／方案／頁尾） |
| `style.css` | 簡約現代風格、響應式版型 |
| `app.js` | 語音辨識、摘要與待辦萃取、匯出、歷史紀錄 |

## 部署

任何靜態主機皆可：GitHub Pages、Netlify、Vercel、Cloudflare Pages，或直接放進現有
Flask 專案的 `static/` 下以路由提供。

## 隱私

語音與逐字稿皆在**瀏覽器本機**處理；歷史存於 `localStorage`。
若填入 OpenAI API Key，僅在你按下「產生摘要」時由瀏覽器直接呼叫 OpenAI，
金鑰存在本機 `localStorage`，不會上傳到任何中介伺服器。
