# 🚀 部署指南（免費方案）

把兩個 App 部署成公開網址、資料永久保存。全程約 10–15 分鐘。
所有要貼的值都已幫你準備好。

> 為什麼要你自己點：建立 Neon / Google Cloud / Render 帳號與服務，都需要登入**你自己的帳號**。
> 開發沙箱沒有你的登入，也被防火牆限制無法連到這些網站，因此這幾步只能由你操作。

---

## 步驟 1：建立免費 Postgres（Neon）

1. 到 https://neon.tech → 用 Google 登入 → 建立一個免費專案（區域選離你近的，如 Singapore）。
2. 進專案的 **SQL Editor**，貼上並執行：
   ```sql
   CREATE DATABASE sales;
   CREATE DATABASE stocktake;
   ```
3. 點 **Connect / Connection string**，複製連線字串（建議勾 **Pooled connection**）。它長這樣：
   ```
   postgresql://<user>:<password>@<host>-pooler.<region>.aws.neon.tech/neondb?sslmode=require
   ```
4. 由它做出**兩條**字串，只把結尾的資料庫名 `neondb` 換掉：
   - 銷貨單用： `...aws.neon.tech/sales?sslmode=require`
   - 盤點用：   `...aws.neon.tech/stocktake?sslmode=require`

> 這兩條等一下要分別貼到兩個服務的 `DATABASE_URL`。兩個 App 有同名資料表，**務必各用各的資料庫**。

---

## 步驟 2：部署到 Render（一次建立兩個服務）

1. 先讓 Render 讀得到設定檔：把分支 `claude/conversational-sales-invoice-HXUIq` 合併到 `main`
   （或在下一步選這個分支也可以）。
2. 到 https://render.com → 用 GitHub 登入 → **New** → **Blueprint**。
3. 選這個 repo（`Ericliang680928/-`）→ Render 會自動讀 `render.yaml`，建立兩個服務：
   `sales-invoice` 與 `stocktake`。`SECRET_KEY` 會自動產生，不用管。
4. 它會提示你填 `sync:false` 的環境變數，逐一貼上：

   **sales-invoice 服務**
   | 變數 | 值 |
   |------|----|
   | `DATABASE_URL` | 步驟 1 的 **/sales** 那條 |

   **stocktake 服務**
   | 變數 | 值 |
   |------|----|
   | `DATABASE_URL` | 步驟 1 的 **/stocktake** 那條 |
   | `GOOGLE_SERVICE_ACCOUNT_JSON` | 先留空，見步驟 3（不影響上線，只是暫時不能寫回 Google Sheet） |

   > `SOURCE_SHEET_ID`、`DEDICATED_SHEET_ID` 已寫在 `render.yaml`，不用填。
5. 按 **Apply / Deploy**，等兩個服務都變綠（Live）。各自會給一個 `https://xxx.onrender.com` 網址。
6. 開網址 → 第一次先「**註冊**」建立管理員帳號即可使用。

> 免費服務閒置約 15 分鐘會休眠，下次開啟需等幾秒冷啟動；資料存在 Neon，**不會**因休眠而消失。

---

## 步驟 3（選配）：接 Google Sheet 同步

盤點 App 不接 Google 也能完整使用（「從來源匯入」會讀內建的 111 筆範例 CSV）。
要真正讀寫你的 Google Sheet，再做這步：

1. 到 https://console.cloud.google.com → 建專案 → **APIs & Services → Enable APIs**：
   啟用 **Google Sheets API** 與 **Google Drive API**。
2. **Credentials → Create credentials → Service account** → 建立後到該帳號的 **Keys → Add key → JSON**，下載金鑰檔。
3. 記下服務帳號 email（`xxx@xxx.iam.gserviceaccount.com`），把兩份 Sheet 都「共用」給它：
   - 來源 `庫存盤點系統` 來源表 → **檢視者**
   - 專屬 `庫存盤點系統（專屬）` → **編輯者**
4. 回 Render 的 **stocktake** 服務 → Environment → `GOOGLE_SERVICE_ACCOUNT_JSON` 貼上**整段 JSON 內容** → 存檔會自動重部署。
5. 進 App 的「同步」頁 → 先「⬇️ 從來源匯入產品」→ 再「⬆️ 寫回專屬 Sheet」（會自動補齊 5 個工作表）。

---

## 已幫你準備好的值

| 項目 | 值 |
|------|----|
| 分支 | `claude/conversational-sales-invoice-HXUIq` |
| 來源 Sheet ID | `1JOpCUfAS3YEHHGUq_NR8twxGzDh7C0_p7bZAdOc0tf0` |
| 專屬 Sheet ID | `1-t5dPhduceaVwVk3vtoestXPOKR6_yk9xHKCtiS-Ipc` |
| `SECRET_KEY` | Render 會自動產生（也可自填：`python -c "import secrets;print(secrets.token_hex(32))"`） |

## 卡住時

- 服務 build 失敗 → 把 Render 的 **Logs** 貼給我，我幫你看。
- 連不上資料庫 → 多半是 `DATABASE_URL` 結尾資料庫名沒換，或少了 `?sslmode=require`。
- 寫回 Sheet 失敗 → 多半是忘了把 Sheet 共用給服務帳號 email（編輯者）。
