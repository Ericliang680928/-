# 🗣️ 口語化銷貨單系統

用「講的 / 隨手打一句話」就能登錄銷貨，系統自動對應你的**顧客清單**與**產品清單（含產品編號）**，
並整理成你要的 **「產品 × 日期」交叉統計表**，可一鍵匯出 Excel。

> 例：輸入「今天王小明買了三箱可口可樂跟兩瓶礦泉水」
> → 日期 2026-05-29、顧客 王小明、可口可樂(A001) 3 箱、礦泉水(B001) 2 瓶。

---

## 為什麼提供清單能提高口語準確度？

口語常有**簡稱、同音字、口誤**（「可樂」↔「可口可樂」、「老王」↔「王老闆」）。
系統把你的清單當「字典」，用**字元層級的模糊比對**把講法校正回清單裡的正式名稱，
並自動帶出產品編號。清單越完整、別名給得越多，準確度越高。

---

## 功能

- **多帳號**：註冊/登入，每個帳號的清單與銷貨資料各自隔離，互看不到。
- **語音輸入**：可按 🎤 直接用講的（瀏覽器 Web Speech API，繁中；Chrome / Edge 支援最佳）。
- **口語輸入**：支援相對日期（今天/昨天/前天）、明確日期（5月20號、2026/05/20）、
  中文數字（三箱、一百二十）、阿拉伯數字、常見單位（箱/瓶/個/打…）。
- **一句多筆**：「可樂50個、水12瓶」會拆成兩筆，並自動判斷「數量在前」或「產品在前」的語序。
- **先規則、後 AI**：預設離線規則 + 模糊比對（免費、不外傳、夠快）；
  遇到規則信心不足的句子，且有設定金鑰時，才呼叫 Claude 補強。
- **確認再存檔**：解析結果以表格呈現，可手動下拉修正後再存。
- **交叉統計表**：A 欄=產品名稱、B 欄起=各日期、交叉格=當日銷售總量，含合計列/欄。
- **匯出**：Excel（.xlsx）與 CSV。

---

## 安裝與啟動

```bash
pip install -r requirements.txt   # anthropic 為選配
python app.py
# 開瀏覽器 http://127.0.0.1:5000 → 先「註冊新帳號」
```

> 資料存在 SQLite（預設 `data/app.db`，可用環境變數 `SALES_DB` 覆寫）。
> 設定 `SECRET_KEY` 環境變數可固定登入 session 的加密金鑰（正式環境務必設定）。

## 使用步驟

1. **註冊 / 登入**：第一次使用先註冊；新帳號會自動帶一份範例清單。
2. **④ 清單設定**：貼上你的顧客與產品清單（產品請附編號）。
3. **① 口語輸入**：打一句話、或按 🎤 用講的 → 按「解析」。
4. **② 確認與修正**：檢查日期/顧客/品項，需要時下拉修正 → 「確認存檔」。
5. **③ 統計表**：即時看到產品 × 日期交叉表 → 「匯出 Excel / CSV」。

---

## 清單格式

`data/customers.csv`
```
name,aliases
大同公司,大同|大同股份
王小明,小明|老王|王老闆
```

`data/products.csv`（`code` 為產品編號）
```
name,code,aliases
可口可樂,A001,可樂|coke
礦泉水,B001,水|瓶裝水
```
> 也可直接在網頁「④ 清單設定」貼上編輯，毋須手改檔案。

---

## 啟用 AI 補強（選配）

```bash
export ANTHROPIC_API_KEY=sk-...           # 你的金鑰
export SALES_LLM_MODEL=claude-sonnet-4-6  # 可省略
python app.py
```
未設定金鑰時，系統完全以離線規則運作（網頁會顯示「未設定 AI 金鑰，僅用規則」）。

---

## 分享給其他人 / 上線使用

系統已內建**多帳號登入**，可以安全地多人共用（每人資料隔離）。上線方式：

### Render（最簡單，附設定檔）

本專案已附 `render.yaml`，到 [render.com](https://render.com) → New → **Blueprint** → 連這個 repo，
它會自動：用 `gunicorn` 啟動、產生安全的 `SECRET_KEY`、掛一顆持久磁碟到 `/data`
並把資料庫指向 `/data/app.db`（重新部署資料不流失）。完成後就有一個公開網址。

### Railway / Fly.io 等

附了 `Procfile`（`web: gunicorn app:app ...`），多數平台會自動辨識。記得：
- 設環境變數 `SECRET_KEY`（隨機長字串）、`COOKIE_SECURE=1`（https）。
- 把 `SALES_DB` 指向一個**持久磁碟**路徑，否則重啟會清空資料。

### 其他

- **同一區網**：`python app.py` 已綁 `0.0.0.0`，同網路的人連 `http://你的IP:5000`。
- **臨時分享**：`ngrok http 5000` 開一個臨時公開網址。

> 啟用 AI 補強：在平台後台設 `ANTHROPIC_API_KEY`（切勿寫進程式或設定檔）。

---

## 測試

```bash
python tests/test_parser.py        # 或 python -m pytest -q
```

## 專案結構

```
app.py                 Flask 後端、登入與 API
Procfile / render.yaml 部署設定（gunicorn / Render）
sales/
  db.py                SQLite 連線與資料表結構
  store.py             帳號、清單、銷貨紀錄（依 user_id 隔離）
  matcher.py           中文模糊比對
  parser.py            離線規則解析（日期/數量/產品配對）
  llm.py               選配的 Claude 解析補強（含 prompt caching）
  pivot.py             產品×日期交叉表 + Excel/CSV 匯出
templates/
  login.html           登入 / 註冊頁
  index.html           主介面（含語音輸入）
static/                前端 JS / CSS
data/                  清單格式範例 CSV；執行時的 app.db 不進版控
tests/                 測試
```
