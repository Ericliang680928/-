# 🚀 部署指南（3 步完成，免費）

Supabase 資料庫 ✅ 已建好（兩個 App 的 schema 都已建立）。
剩下只需要拿到連線字串 → 貼到 Render。

---

## 步驟 1：拿 Supabase 連線字串（約 1 分鐘）

1. 到 https://supabase.com/dashboard/project/kxgbnrbedmmgfxuevuzq/settings/database
2. 找 **Connection string** 區塊 → 選 **Transaction** 模式（Port 6543）
3. 按 **Copy** 複製 URI（格式如下，把 `[YOUR-PASSWORD]` 換成你的真實密碼）：
   ```
   postgresql://postgres.kxgbnrbedmmgfxuevuzq:[YOUR-PASSWORD]@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres
   ```

> 💡 忘記密碼？同一頁往下找 **Reset database password**。

---

## 步驟 2：Render 一鍵部署（約 5 分鐘）

1. 到 https://render.com → 用 GitHub 登入
2. **New → Blueprint** → 選這個 repo（`Ericliang680928/-`）→ 選 `main` 分支
3. Render 讀 `render.yaml` 會建立 **sales-invoice** 和 **stocktake** 兩個服務
4. 它會要你填 `sync: false` 的變數，都填**同一條**連線字串：

   | 服務 | 變數 | 值 |
   |------|------|----|
   | sales-invoice | `DATABASE_URL` | 步驟 1 複製的 URI |
   | stocktake | `DATABASE_URL` | 步驟 1 複製的 URI（一模一樣） |
   | stocktake | `GOOGLE_SERVICE_ACCOUNT_JSON` | 先留空（不影響部署，選配） |

   > `DB_SCHEMA`、`SECRET_KEY`、`SOURCE_SHEET_ID`、`DEDICATED_SHEET_ID` 都已寫在設定檔，不用填。

5. 按 **Apply** → 等兩個服務都變綠（Live）→ 各拿到一個 `https://xxx.onrender.com`

6. 開網址 → 按「**註冊**」建立管理員帳號即可使用。

> ⚠️ Render 免費服務閒置 ~15 分鐘會休眠、首次開啟稍慢（冷啟動）。**資料存在 Supabase，不受休眠影響。**

---

## 步驟 3（選配）：接 Google Sheet 同步

> **不接 Google 也能完整使用盤點 App。** 「從來源匯入」會讀內建 111 筆範例。
> 要真正讀寫 Google Sheet 再做這步：

1. [Google Cloud Console](https://console.cloud.google.com) → 建專案 → 啟用 **Google Sheets API** + **Google Drive API**
2. **Credentials → Service account** → 建立 → **Keys → Add key → JSON** → 下載
3. 把服務帳號 email 加為兩份 Sheet 的共用者：
   - [來源 Sheet](https://docs.google.com/spreadsheets/d/1JOpCUfAS3YEHHGUq_NR8twxGzDh7C0_p7bZAdOc0tf0) → **檢視者**
   - [專屬 Sheet](https://docs.google.com/spreadsheets/d/1-t5dPhduceaVwVk3vtoestXPOKR6_yk9xHKCtiS-Ipc) → **編輯者**
4. Render → stocktake 服務 → Environment → `GOOGLE_SERVICE_ACCOUNT_JSON` 貼整段 JSON → 儲存（自動重部署）
5. 進 App「同步」頁 → ⬇️ 從來源匯入 → ⬆️ 寫回專屬 Sheet

---

## 已幫你做好的事

| 項目 | 狀態 |
|------|------|
| Supabase `salesapp` schema（6 張表 + 索引）| ✅ 已建立 |
| Supabase `stocktake` schema（7 張表 + 索引）| ✅ 已建立 |
| `render.yaml` 設定兩個服務 | ✅ 含 DB_SCHEMA、SECRET_KEY 自動產生 |
| 規格欄位、差異報表匯出 | ✅ |
| SQLite↔Postgres 相容層（本機/測試用 SQLite）| ✅ 本機 PG16 實測通過 |

## 卡住時

把 Render 的 **Logs** 貼給我，我幫你看。常見問題：
- Build 失敗 → 多半 Python 版本或 pip 依賴問題
- 連不上資料庫 → `DATABASE_URL` 複製時有沒有帶密碼？有沒有 `?` 後面的部分？
- 寫回 Sheet 失敗 → Sheet 有沒有共用給服務帳號 email（編輯者）？
