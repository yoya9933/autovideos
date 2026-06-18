# VideoTurn - YouTube Shorts 全自動發布系統
## 專案簡報（2026-06-11）

---

## 一、專案目標

每天自動生成並上傳 2 支繁體中文 YouTube Shorts 科技資訊影片，主題以台灣科技、AI、半導體、資安與科學新聞為核心。

目前主發布平台是 YouTube Shorts，長期目標是累積公開觀看數與頻道表現，達到 YouTube 合作夥伴計畫（YPP）資格並開始廣告變現。

系統已預留多平台發布架構，後續可從同一支短影音擴展到 Instagram Reels 與 Facebook Reels。

---

## 二、專案位置

```text
D:\coding_202605051504_XY_Propose_Minutes\videoturn_202606011405_XY\
├── MoneyPrinterTurbo-Portable-Windows-1.2.6\MoneyPrinterTurbo\   ← 主程式
│   ├── auto_publish_youtube.py        ← 每日自動發布入口腳本
│   ├── config.toml                    ← 執行設定、RSS、模型、素材、通知、發布平台
│   ├── app/services/
│   │   ├── rss_ingest.py              ← RSS 抓取、候選過濾、全文抓取、AI 選題、腳本/標題 Prompt
│   │   ├── thumbnail.py               ← Pillow 自動縮圖生成
│   │   ├── youtube_upload.py          ← YouTube OAuth、影片上傳、縮圖上傳
│   │   ├── platform_publish.py        ← 共用發布請求、發布結果、平台名稱正規化、狀態儲存
│   │   ├── instagram_reels_publish.py ← Instagram Reels 發布器（已實作，預設未啟用）
│   │   ├── facebook_reels_publish.py  ← Facebook Reels 發布器（已實作，預設未啟用）
│   │   ├── notification.py            ← Email / Telegram 成功、警告、失敗通知
│   │   ├── material.py                ← Pexels / Pixabay 素材搜尋下載
│   │   └── task.py                    ← 影片合成流水線（TTS → 字幕 → FFmpeg）
│   ├── test/services/                 ← RSS、通知、平台發布等單元測試
│   └── storage/auto_publish/
│       ├── seen.json                  ← 已處理 entry 記錄，含時間戳與 90 天保留
│       ├── jobs/                      ← 每次生成/發布的結果 JSON
│       ├── publish_status/            ← 各平台發布結果狀態
│       └── logs/                      ← 排程執行日誌
├── run_daily_auto_publish.bat         ← Windows 執行入口（排程器呼叫）
├── install_scheduler.bat              ← 一鍵安裝工作排程器（需管理員）
├── run_daily_auto_publish.sh          ← Linux / WSL 執行入口
├── update_and_run.sh                  ← Linux / WSL 更新依賴後執行
├── install_cron.sh                    ← Linux / WSL 安裝 12:00 / 20:00 cron
├── LINUX_SETUP.md                     ← Linux / WSL 使用指南
├── task_morning.xml                   ← 12:00 排程定義
└── task_afternoon.xml                 ← 20:00 排程定義
```

---

## 二之一、Linux / WSL 使用方式

此專案核心是 Python，原本外層包成 Windows portable 版本。Linux / WSL 不需要使用內附的 Windows `python.exe`、`ffmpeg.exe` 或 `.bat`，改用系統 Python、虛擬環境、系統 ffmpeg，以及 cron。

快速流程：

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip ffmpeg imagemagick cron

cd /home/yoya9933/code/autovideos/MoneyPrinterTurbo-Portable-Windows-1.2.6/MoneyPrinterTurbo
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp -n config.example.toml config.toml
```

接著編輯 `MoneyPrinterTurbo-Portable-Windows-1.2.6/MoneyPrinterTurbo/config.toml`，至少設定 Gemini、Pexels，以及之後 YouTube 上傳需要的 OAuth 資訊。

先測選題，不產片也不上傳：

```bash
cd /home/yoya9933/code/autovideos
./run_daily_auto_publish.sh --dry-run
```

再測產片但不上傳：

```bash
./run_daily_auto_publish.sh --no-upload
```

正式跑一次：

```bash
./run_daily_auto_publish.sh
```

安裝每天 12:00 / 20:00 自動執行：

```bash
./install_cron.sh
```

完整 Linux / WSL 步驟請看 `LINUX_SETUP.md`。

---

## 三、完整技術流程

```text
Windows 工作排程器（每天 12:00 / 20:00）
或 Linux cron（每天 12:00 / 20:00）
        ↓
run_daily_auto_publish.bat / run_daily_auto_publish.sh
        ↓
MoneyPrinterTurbo\auto_publish_youtube.py
        ↓
[1] 載入設定與狀態
    → 讀取 config.toml
    → 讀取 storage/auto_publish/seen.json
    → 解析 daily_publish_platforms，目前預設為 ["youtube"]
        ↓
[2] rss_ingest.collect_candidate_entries()
    → 從 5 個 RSS 來源抓取最多 12 篇候選
    → 過濾低資訊量、缺少文章連結、摘要過短、已看過的 entry
    → 對同事件標題做去重與主題加權
        ↓
[3] rss_ingest.select_best_entry_for_video()
    → Gemini 從候選中選出最適合做 Shorts 的題目（LLM 呼叫 #1）
        ↓
[4] rss_ingest.fetch_article_text()
    → 抓取文章原始頁全文
    → Google News 連結會嘗試跟隨到原始網站
    → 全文不足時改用 RSS 摘要或跳過低資訊題目
        ↓
[5] rss_ingest.build_script_prompt()
    → 優先使用全文
    → 來源較薄時縮短成 35-50 秒腳本，不硬湊 45-75 秒
        ↓
[6] rss_ingest.generate_video_title()
    → Gemini 生成真實但高點擊率的繁體中文標題（LLM 呼叫 #2）
    → 失敗時退回 RSS 標題
        ↓
[7] _build_daily_material_terms()
    → 產生或映射英文素材搜尋詞
    → Pexels / Pixabay 避免使用中文關鍵字搜尋
        ↓
[8] task.start(stop_at="video")
    → Gemini 生成旁白腳本（LLM 呼叫 #3）
    → Edge TTS 合成語音
    → 依英文關鍵字下載 Pexels 素材
    → FFmpeg 合成 9:16 直式短影音
        ↓
[9] 品質門檢查（目前 config 預設關閉）
    → 可檢查影片檔、時長、字幕、腳本文字量、結尾完整性等
        ↓
[10] 平台發布
    → YouTube：OAuth2 refresh token → resumable upload → public Shorts
    → Instagram Reels / Facebook Reels：已實作 publisher，需設定平台與環境變數後啟用
        ↓
[11] thumbnail.generate_thumbnail()
    → Pillow 生成 1280×720 YouTube 縮圖
    → youtube_upload.upload_thumbnail() 上傳自訂縮圖
        ↓
[12] 儲存執行結果
    → 成功後寫入 seen.json
    → 儲存 job JSON 到 storage/auto_publish/jobs/
    → 儲存平台發布狀態到 storage/auto_publish/publish_status/
    → 發送 Email / Telegram 通知（依設定）
```

---

## 四、config.toml 重要設定（現況）

```toml
# 影片素材來源
video_source = "pexels"
daily_video_source = "pexels"
daily_allow_local_material_fallback = false
daily_material_term_count = 5
daily_material_fallback_terms = [
  "technology news",
  "digital technology",
  "computer chip",
  "data center",
  "city skyline"
]

# AI 模型
llm_provider = "gemini"
gemini_model_name = "gemini-2.5-flash"
gemini_max_output_tokens = 8192

# RSS 來源（5 個）
daily_rss_feeds = [
  "https://trends.google.com/trending/rss?geo=TW",
  "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
  "https://technews.tw/feed/",
  "https://pansci.asia/feed/",
  "https://www.ithome.com.tw/rss"
]
daily_candidate_count = 12
daily_min_summary_length = 80
daily_min_full_text_length = 300

# 聲音
daily_voice_name = "zh-CN-XiaoyiNeural-Female"
daily_voice_names = [
  "zh-TW-HsiaoChenNeural-Female",
  "zh-TW-HsiaoYuNeural-Female",
  "zh-CN-XiaoyiNeural-Female"
]
daily_voice_rate = 1.15

# 品質門
daily_quality_gate_enabled = false
daily_quality_gate_min_duration_seconds = 35
daily_quality_gate_max_duration_seconds = 180
daily_quality_gate_require_subtitle = true

# 發布平台
daily_publish_platforms = ["youtube"]
daily_publish_hashtags = ["shorts", "台灣", "科技", "AI", "人工智慧", "新聞", "知識", "科學", "短影音"]

# YouTube 上傳設定
youtube_upload_enabled = true
youtube_upload_privacy_status = "public"
youtube_upload_category_id = "28"
youtube_upload_tags = ["shorts", "台灣", "科技", "AI", "人工智慧", "新聞", "科學", "短影音"]
youtube_description_template = "來源：{source}\n連結：{url}\n\n{summary}\n\n#shorts #台灣 #科技 #AI #人工智慧 #新聞 #知識 #科學 #短影音 #每日資訊"

# Instagram Reels（已實作，預設未啟用）
instagram_reels_enabled = false
instagram_graph_api_version = "v23.0"
instagram_reels_share_to_feed = false

# 通知
email_notify_enabled = true
telegram_notify_enabled = false
```

---

## 五、目前已完成的主要改動

| # | 改動項目 | 檔案 | 狀態 |
|---|---|---|---|
| 1 | YouTube 預設發布狀態改為 public | config.toml | 已完成 |
| 2 | 影片素材改用 Pexels，並關閉 local fallback | config.toml / auto_publish_youtube.py | 已完成 |
| 3 | Pexels / Pixabay 搜尋改用英文素材詞 | auto_publish_youtube.py | 已完成 |
| 4 | Gemini 模型使用 gemini-2.5-flash | config.toml | 已完成 |
| 5 | YouTube 類別設定為 28（Science & Technology） | config.toml | 已完成 |
| 6 | YouTube Tags 與發布 Hashtags 擴充 | config.toml | 已完成 |
| 7 | 新增 RSS 全文抓取與 Google News 原站跟隨 | rss_ingest.py | 已完成 |
| 8 | 低資訊量 RSS 條目過濾與同事件去重 | rss_ingest.py | 已完成 |
| 9 | 腳本 Prompt 依來源厚度調整長度，避免硬湊內容 | rss_ingest.py | 已完成 |
| 10 | 新增 truthful high-CTR 標題生成與清理 | rss_ingest.py / auto_publish_youtube.py | 已完成 |
| 11 | seen.json 加入時間戳、90 天保留與新舊格式相容 | rss_ingest.py | 已完成 |
| 12 | 新增自動縮圖生成 | thumbnail.py | 已完成 |
| 13 | 新增 YouTube 自訂縮圖上傳 | youtube_upload.py / auto_publish_youtube.py | 已完成 |
| 14 | 建立共用多平台發布抽象 | platform_publish.py | 已完成 |
| 15 | 新增 Instagram Reels publisher | instagram_reels_publish.py | 已完成，預設未啟用 |
| 16 | 新增 Facebook Reels publisher | facebook_reels_publish.py | 已完成，預設未啟用 |
| 17 | 發布結果改存到 publish_status | platform_publish.py / auto_publish_youtube.py | 已完成 |
| 18 | 新增 Email / Telegram 通知服務 | notification.py | 已完成，Email 啟用，Telegram 預設關閉 |
| 19 | 批次執行時可使用 NullState，避免 WebUI 狀態依賴 | state.py / auto_publish_youtube.py | 已完成 |
| 20 | 建立 12:00 / 20:00 Windows 工作排程器腳本 | install_scheduler.bat / task_morning.xml / task_afternoon.xml | 已完成 |

---

## 六、已驗證的成功上傳

| 影片 ID | 標題 | 隱私狀態 | 備註 |
|---|---|---|---|
| `_XmZLfwzrrY` | 魏哲家抱怨AI爆發太突然 黃仁勳五字神回覆讓全場笑翻 | private | 早期本地素材驗證 |
| `d3LHiAzjj8M` | 黃仁勳直衝網咖見Faker？合簽顯卡送給粉絲！ | private | Pexels 素材，早期完整上傳 |
| `nfSHgxZb3OU` | 黃仁勳說台灣是家！最新影片點名這5家台廠 | public | 新流程公開上傳 |
| `lWwlOvppX0Y` | 酒駕公告出包？台南驚見AI人、美金檳榔攤！ | public | 新流程公開上傳 |
| `dtCFp2sYxss` | 黃仁勳被叫爸！親女兒聽到「這稱呼」後反應是？ | public | 新流程公開上傳 |
| `AtfB7oa0mp8` | 普亭嚇壞！以色列AI獵殺伊朗領袖 俄急關閉監視器 | public | 新流程公開上傳 |

補充：job 記錄中也有多支 private / unlisted 測試影片，以及部分因 Gemini 429 或設定缺失導致的失敗紀錄。

---

## 七、待完成的優化項目

### 緊急

- [ ] 重新啟用 `daily_quality_gate_enabled = true`
      → 目前品質門關閉，已有 job 記錄出現 Gemini 429 錯誤文字進入標題/輸出流程的情況；公開自動發布時風險偏高。

- [ ] Gemini 429 時停止發布，而不是使用錯誤訊息繼續產生標題或影片
      → 需要把 LLM 速率限制視為可重試失敗，不應讓錯誤文字進入 YouTube 標題。

### 重要

- [ ] 將 `daily_publish_platforms` 擴充為 `["youtube", "instagram_reels", "facebook_reels"]`
      → Instagram / Facebook publisher 已存在，但目前設定仍只發布 YouTube。

- [ ] 設定 Instagram Reels 需要的公開影片 URL 或 CDN URL template
      → Instagram Graph API 需要可公開抓取的 video_url，不能直接吃本機檔案。

- [ ] 設定 Facebook Reels 環境變數並做一次非排程測試
      → Facebook publisher 支援本機檔案上傳與 CDN URL 兩種模式。

- [ ] 開啟 Telegram 通知或補齊 Email App Password
      → 通知服務已實作，需確認憑證後才適合長期無人值守。

- [ ] 修正 config.toml 內部分中文欄位的終端顯示亂碼問題
      → Python TOML 解析正常，但 PowerShell 顯示會亂碼，後續人工維護容易誤判。

### 中期

- [ ] 升級 Gemini SDK（google.generativeai → google.genai）
- [ ] 新增更多高品質科技 RSS 來源，例如 inside.com.tw、techorange
- [ ] 移除或降低 Google Trends RSS 權重，因為它常只有關鍵字，缺少可改寫文章內容
- [ ] 日誌加入保留機制，例如 30 天後自動清除
- [ ] 縮圖依主題類型切換色系，例如 AI、半導體、資安、商業科技
- [ ] 建立每日/每週成效報表，追蹤公開 Shorts 的觀看數、曝光、點擊率與留存

---

## 八、已知問題

1. **Gemini 429 速率限制仍是最大穩定性風險**

   短時間密集測試或連續失敗重跑時，會碰到 Gemini 免費方案速率限制。新版流程已有備用 API key 欄位，但仍需要把 429 明確處理成「延後重試 / 不發布」。

2. **品質門目前關閉**

   `daily_quality_gate_enabled = false` 有利於測試不中斷，但不適合公開自動發布。公開排程應開啟品質門，避免短片、壞字幕、半句結尾或錯誤文字被發出去。

3. **Instagram Reels 尚未真正啟用**

   程式已完成，但 `instagram_reels_enabled = false`，且 Instagram 需要公開可抓取的影片 URL。若影片只存在本機，必須先上傳到可公開讀取的位置。

4. **Facebook Reels 尚未真正啟用**

   程式已完成並有測試覆蓋，但目前 `daily_publish_platforms` 未包含 `facebook_reels`，也尚未補齊 Page ID / Page Access Token 等設定。

5. **Telegram 預設關閉**

   Telegram notifier 已實作，但 `telegram_notify_enabled = false`，未設定 bot token 與 chat id 時不會發送。

6. **部分舊 job 是 private / unlisted**

   早期測試影片不會累積公開觀看表現。後續成效評估要以 `privacy_status = "public"` 的新 job 為主。

7. **工作排程器安裝仍需管理員權限**

   `install_scheduler.bat` 需要以系統管理員身份執行，才能建立或更新 Windows 工作排程器任務。

---

## 九、每支影片的成本

| 服務 | 費用 |
|---|---|
| Gemini API（選題 + 標題 + 腳本，約 3 次 LLM 呼叫） | 免費額度內為 0 |
| Pexels API（影片素材） | 免費額度內為 0 |
| Edge TTS（語音合成） | 0 |
| YouTube Data API（影片與縮圖上傳） | 免費額度內為 0 |
| Email / Telegram 通知 | 0 |
| 本機運算與電費（約數分鐘） | 約新台幣 0.1 元級別 |
| **每支影片總成本** | **約新台幣 0.1 元級別** |

---

*最後更新：2026-06-11 台灣時間*
