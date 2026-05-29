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

- **多帳號 + 團隊共享帳本**：註冊/登入；資料以「帳本」為單位。個人帳本只有自己看得到，
  也可建立**共享帳本**、把邀請碼給同事，大家共用同一份清單與銷貨資料（並記錄每筆的輸入者），
  隨時在右上角切換不同帳本。
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
6. **⑤ 團隊共享帳本（多人共用）**：在「團隊」卡片建立共享帳本 → 把**邀請碼**給同事；
   同事註冊登入後輸入邀請碼即可加入，之後大家看到/編輯的是同一份資料。右上角可切換帳本。

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

---

# 📦 庫存盤點系統（第二個 App）

以 **Google Sheet 為產品來源**、**程式 SQLite 為唯一正本**、再**同步寫回專屬 Google Sheet** 的庫存盤點系統。手機優先、支援多人同時盤點。

啟動：`python run_stocktake.py` → http://127.0.0.1:5001 （第一次請先「註冊」建立管理員）。
部署：`gunicorn run_stocktake:app`。

## 功能與頁面

- **登入 + 三種角色**：管理員(admin) / 盤點員(counter) / 覆核員(reviewer)。第一位註冊者為管理員，之後由管理員於「同步」頁建立帳號與指派角色。
- **儀表板**：啟用產品數、進行中/已結案批次、進行中批次進度。
- **建立批次**：盤點日期**必填**；可選類別範圍；建立時依目前產品與帳面庫存產生明細快照。
- **盤點作業**（手機優先）：頂部搜尋、狀態篩選、大數字輸入、**Enter 跳下一筆**、**自動儲存**；四種狀態 **未盤 / 已盤 / 差異 / 已覆核**。
- **多人同時盤點防覆寫**：每筆明細有 version，採**樂觀鎖**；他人已更新時回 409 並提示，可選擇覆蓋。
- **差異覆核**：勾選品項標記已覆核；管理員/覆核員可**結案**。
- **結案不可改**：結案後明細凍結，實盤數套用到庫存現況；要更正只能**新增調整紀錄**（保留稽核軌跡）。
- **歷史查詢**：依狀態查所有批次。
- **同步設定**：從來源匯入產品（更新產品主檔）、寫回專屬 Sheet、看同步日誌、管理帳號角色。

## 資料來源與專屬 Sheet

- 來源產品：`SOURCE_SHEET_ID` 的工作表 `產品名單`（欄位：商品編號、商品名稱、類別、規格）。
- 專屬盤點 Sheet（已建立於來源同目錄）：`庫存盤點系統（專屬）`
  - 工作表：產品主檔 / 盤點批次 / 盤點明細 / 庫存現況 / 同步日誌（缺的會由 App 用服務帳號自動建立）。
- **未設定 Google 憑證時**：「從來源匯入」會改讀本機 `stocktake/data/source_products.csv`（111 筆範例），其餘功能照常，唯「寫回專屬 Sheet」需先設定服務帳號。

## 設定 Google 服務帳號（部署後讀寫 Sheet）

1. 到 Google Cloud Console 建立專案 → 啟用 **Google Sheets API** 與 **Google Drive API**。
2. 建立**服務帳號**並下載 JSON 金鑰。
3. 把**來源 Sheet** 與**專屬 Sheet** 都「共用」給服務帳號的 email（`xxx@xxx.iam.gserviceaccount.com`），來源給「檢視者」、專屬給「編輯者」。
4. 設定環境變數後啟動：
   ```bash
   export GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/key.json   # 或直接貼 JSON 內容
   export SOURCE_SHEET_ID=1JOpCUfAS3YEHHGUq_NR8twxGzDh7C0_p7bZAdOc0tf0
   export DEDICATED_SHEET_ID=1-t5dPhduceaVwVk3vtoestXPOKR6_yk9xHKCtiS-Ipc
   export SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))")
   pip install -r requirements.txt   # 含 gspread、google-auth
   gunicorn run_stocktake:app
   ```
5. 進「同步」頁，先「⬇️ 從來源匯入產品」，再「⬆️ 寫回專屬 Sheet」（會自動補齊 5 個工作表）。

> 安全：服務帳號金鑰**切勿**進版控（`.gitignore` 已排除 `*service-account*.json`）。

## 結構

```
run_stocktake.py        啟動入口（gunicorn run_stocktake:app）
stocktake/
  db.py                 SQLite schema（產品/批次/明細/庫存/調整/同步/帳號）
  store.py              商業邏輯（樂觀鎖、結案凍結、調整紀錄、角色）
  sheets.py             Google Sheets 同步（服務帳號；可離線退化）
  app.py                Flask 後端與權限
  templates/            login/dashboard/batch_new/count/review/history/sync
  static/               手機優先 CSS / 共用 JS
  data/source_products.csv  來源產品範例（離線測試用）
tests/test_stocktake.py 核心邏輯測試
```

測試：`python tests/test_stocktake.py`
