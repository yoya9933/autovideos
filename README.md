# VideoTurn / MoneyPrinterTurbo 自動短影音工作區

這個工作區是以 `MoneyPrinterTurbo` 可攜版為核心的 Windows 自動短影音流程。主要用途是依 `tech` 或 `consumer_money` 內容線從 RSS 新聞源挑選題材，產生繁體中文 Shorts 旁白與 9:16 影片，並依設定發布到 YouTube Shorts；程式內也已放入 Instagram Reels 與 Facebook Reels 的發布介面。

本 README 依據目前的程式碼、設定範本、批次檔、排程 XML 與測試整理，不沿用舊 README 或 `PROJECT_MEMORY` 文件的描述。

## 專案邊界

```text
videoturn_202606011405_XY/
├─ README.md
├─ run_daily_auto_publish.bat
├─ install_scheduler.bat
├─ update_and_run.bat
├─ task_0900.xml
├─ task_1130.xml
├─ task_1400.xml
├─ task_1630.xml
├─ task_1900.xml
├─ task_2130.xml
└─ MoneyPrinterTurbo-Portable-Windows-1.2.6/
   ├─ lib/python/python.exe
   ├─ lib/ffmpeg/...
   ├─ lib/imagemagic/...
   └─ MoneyPrinterTurbo/
      ├─ auto_publish_youtube.py
      ├─ daily_job_report.py
      ├─ get_youtube_refresh_token.py
      ├─ config.example.toml
      ├─ app/
      ├─ test/
      ├─ resource/
      └─ storage/
```

重要邊界：

- Git 根目錄是外層 `videoturn_202606011405_XY`。
- 應用程式根目錄是 `MoneyPrinterTurbo-Portable-Windows-1.2.6/MoneyPrinterTurbo`。
- 可攜 Python 是 `MoneyPrinterTurbo-Portable-Windows-1.2.6/lib/python/python.exe`。
- `config.toml`、`.env`、OAuth token、`client_secret*.json`、`storage/`、`resource/songs/`、影片與音訊產物都屬於本機執行資料，不應提交。

## 主要入口

### 每日自動流程

```powershell
.\run_daily_auto_publish.bat
```

這個批次檔會：

- 設定可攜 FFmpeg 與 ImageMagick 路徑。
- 進入 `MoneyPrinterTurbo` 應用目錄。
- 用可攜 Python 執行 `auto_publish_youtube.py`。
- 把批次檔輸出寫到 `storage/auto_publish/logs/bat_YYYYMMDD.log`。

可把參數直接傳給 Python 腳本：

```powershell
.\run_daily_auto_publish.bat --dry-run
.\run_daily_auto_publish.bat --dry-run --topic-profile consumer_money
.\run_daily_auto_publish.bat --topic-profile tech
.\run_daily_auto_publish.bat --no-upload
.\run_daily_auto_publish.bat --privacy unlisted
.\run_daily_auto_publish.bat --publish-platforms youtube,facebook_reels
```

### 直接執行 Python

```powershell
cd .\MoneyPrinterTurbo-Portable-Windows-1.2.6\MoneyPrinterTurbo
..\lib\python\python.exe auto_publish_youtube.py --dry-run
```

`auto_publish_youtube.py` 支援：

- `--dry-run`: 抓 RSS、挑題、建立 prompt 後停止，不產生影片、不上傳。
- `--topic-profile tech|consumer_money`: 指定科技線或消費金錢線；未指定時讀取 `daily_default_topic_profile`，預設為 `tech`。
- `--no-upload`: 產生影片，但略過所有平台發布。
- `--privacy private|unlisted|public`: 覆蓋 YouTube 隱私狀態。
- `--publish-platforms` / `--platforms`: 指定 `youtube`、`instagram_reels`、`facebook_reels`。

### Web/API 模式

```powershell
cd .\MoneyPrinterTurbo-Portable-Windows-1.2.6\MoneyPrinterTurbo
..\lib\python\python.exe main.py
```

`main.py` 啟動 FastAPI，預設文件位置是 `http://127.0.0.1:8080/docs`。API 主要路由在 `app/controllers/v1/video.py` 與 `app/controllers/v1/llm.py`，包含影片、音訊、字幕、任務查詢、BGM、素材上傳與下載。

## 自動發布流程

目前 `auto_publish_youtube.py` 的流程如下：

1. 讀取 `config.toml`；如果不存在，`app/config/config.py` 會從 `config.example.toml` 複製一份。
2. 解析發布平台。預設讀 `daily_publish_platforms`，空值時回到 `youtube`。
3. 先檢查 `storage/auto_publish/pending_upload.json`。如果上一輪已產生影片但上傳失敗，會先嘗試重傳，不重新生成影片。
4. 依 `--topic-profile` 或 `daily_default_topic_profile` 載入該內容線的 feeds、偏好字詞、排除字詞與編輯規則；若沒有 profile 設定，`tech` 會相容使用舊的 `daily_rss_*` 設定。
5. 用 `daily_rss_state_file` 記錄已處理條目，避免重複發布。
6. 跨各 feed 輪流取樣，過濾低資訊量、profile 排除字詞與重複事件，收集 profile 指定數量的候選。
7. 由 LLM 按 profile 編輯規則挑選最適合 Shorts 的題材；LLM 失敗時用 profile 關鍵字加權的本機評分退回。
8. 嘗試抓取全文，若全文不足則使用 RSS 摘要；來源資訊太少時會跳過。
9. 產生長標題、短標題、旁白 prompt、素材搜尋詞與發布描述。
10. `--dry-run` 到此停止，並寫 job/publish state。
11. `app/services/task.py` 執行影片任務：腳本、素材詞、TTS、字幕、素材下載或本機素材、合成影片。
12. `--no-upload` 會保留影片與狀態紀錄，但不發布。
13. 發布前寫入 `pending_upload.json`，讓下一輪能恢復上傳。
14. 依序呼叫平台 publisher。YouTube 成功後會產生並上傳縮圖。
15. 寫入 job JSON、publish status JSON，並透過 Email/Telegram 發送成功、失敗或警告通知。

## 設定重點

主要設定位於 `MoneyPrinterTurbo/config.toml`。這個檔案可能含有 API key、OAuth refresh token、SMTP 密碼等祕密，已由 `.gitignore` 排除。

常用欄位：

```toml
[app]
llm_provider = "openai"
daily_default_topic_profile = "tech"
daily_rss_feeds = [
  "https://trends.google.com/trending/rss?geo=TW",
  "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
  "https://technews.tw/feed/",
  "https://pansci.asia/feed/",
  "https://www.ithome.com.tw/rss"
]
daily_candidate_count = 12
daily_video_source = "auto"
daily_material_term_count = 5
daily_voice_names = ["zh-TW-HsiaoChenNeural-Female", "zh-TW-HsiaoYuNeural-Female", "zh-CN-XiaoyiNeural-Female"]
daily_bgm_type = "random"
daily_bgm_volume = 0.15
daily_publish_platforms = ["youtube"]
daily_publish_hashtags = ["shorts"]

youtube_upload_enabled = false
youtube_upload_privacy_status = "public"
youtube_upload_category_id = "22"
youtube_upload_tags = ["shorts"]

[app.daily_topic_profiles.tech]
candidate_count = 24
focus_keywords = ["AI", "人工智慧", "半導體", "晶片", "資安"]
focus_keyword_bonus = 8
excluded_keywords = []
editorial_brief = "優先選擇具有明確衝突、數字或一般人影響的科技題。"

[app.daily_topic_profiles.consumer_money]
candidate_count = 24
focus_keywords = ["漲價", "訂閱", "手續費", "退款", "物價", "信用卡", "詐騙", "會員", "定價"]
focus_keyword_bonus = 4
excluded_keywords = ["目標價", "基金申購", "信用卡推薦", "開戶禮", "限時優惠"]
editorial_brief = "先說明一般人會多付、少拿或承擔什麼風險；不得提供個股買賣建議。"
```

上方只節錄 profile 結構；完整 feeds 與排除字詞請以 `config.example.toml` 為準。`consumer_money` 目前分成價格／訂閱／費用、消費糾紛／詐騙，以及物價／薪資／品牌定價三組 Google News RSS 查詢。兩個 profile 共用 `seen.json`，避免同一事件跨內容線重複發布。

程式支援的重點行為：

- `daily_video_source = "auto"` 時會優先用 Pexels，其次 Pixabay；兩者沒有 API key 時自動回到 `storage/local_videos` 或測試資源。
- `daily_bgm_type = "topic"` 時會依題材選 `resource/songs/ai_tools`、`resource/songs/semiconductor_stock`、`resource/songs/security_fraud` 底下的 MP3；找不到就退回一般隨機 BGM。
- `daily_publish_platforms` 可用 `youtube`、`instagram_reels`、`facebook_reels`，也接受 `yt`、`ig`、`fb` 等別名。
- YouTube OAuth 可用 `get_youtube_refresh_token.py` 取得 refresh token；`--write-config` 只更新 client id、client secret、refresh token，不會改 `youtube_upload_privacy_status`。
- Instagram Reels 需要 Graph API 可公開讀取的影片 URL template。
- Facebook Reels 支援本機檔案上傳，也支援 CDN URL template。
- Email 與 Telegram 通知可用 config 或環境變數覆蓋。

注意：`config.example.toml` 目前含有 `daily_quality_gate_*` 欄位，但 `auto_publish_youtube.py` 尚未呼叫品質門檻檢查。不要把這些欄位視為已生效的發布阻擋機制。

## 執行產物

每日流程會主要寫入：

```text
MoneyPrinterTurbo/storage/auto_publish/
├─ seen.json
├─ pending_upload.json
├─ jobs/
├─ publish_status/
├─ reports/
└─ logs/
```

用途：

- `seen.json`: 已處理的 RSS entry id，保留期由程式管理。
- `pending_upload.json`: 上傳失敗後的恢復資料。若存在，下一輪會先嘗試重傳。
- `jobs/*.json`: 每次執行的題材、標題、影片路徑、成功狀態、錯誤階段與警告；另含 `topic_profile`、`source_title`、`source_url`、`source_feed` 供內容稽核。
- `publish_status/*.json`: 各平台發布結果、遠端 ID、錯誤與原始回應摘要。
- `logs/daily_YYYY-MM-DD.log`: loguru 寫入的每日應用 log，保留 30 天。
- `logs/bat_YYYYMMDD.log`: 外層批次檔 stdout/stderr。
- `reports/daily_YYYY-MM-DD.txt`: `daily_job_report.py --save` 產生的報告。

## 每日報告

```powershell
cd .\MoneyPrinterTurbo-Portable-Windows-1.2.6\MoneyPrinterTurbo
..\lib\python\python.exe daily_job_report.py --date 2026-06-21 --save
..\lib\python\python.exe daily_job_report.py --date 2026-06-21 --send-email
```

報告會從 `jobs/` 與 `publish_status/` 彙整：

- 總 job 數、成功數、失敗數。
- 成功公開上傳的 YouTube video id。
- 失敗階段與錯誤摘要。
- 疑似錯誤標題。
- 實際發布的 `tech`、`consumer_money` 與舊格式 `unknown` 數量，以及是否達到 3:3。
- 來源與素材搜尋詞統計。

## Windows 排程

```powershell
.\install_scheduler.bat --xml-only
```

`--xml-only` 只刷新 XML 中的路徑與時間，不建立 Windows 工作。實際建立排程需要系統管理員權限：

```powershell
.\install_scheduler.bat
```

目前批次檔會建立：

| 工作 | 時間 | Topic profile |
|---|---:|---|
| `VideoTurn\AutoPublish_0900` | 09:00 | `tech` |
| `VideoTurn\AutoPublish_1130` | 11:30 | `consumer_money` |
| `VideoTurn\AutoPublish_1400` | 14:00 | `tech` |
| `VideoTurn\AutoPublish_1630` | 16:30 | `consumer_money` |
| `VideoTurn\AutoPublish_1900` | 19:00 | `tech` |
| `VideoTurn\AutoPublish_2130` | 21:30 | `consumer_money` |

排程分配嚴格維持 3:3。某個 profile 沒有合格候選時會跳過，不會拿另一條內容線補位；若時段失敗，需要用相同 `--topic-profile` 補跑，當日成功發布數才可能恢復 3:3。

它也會嘗試停用舊的 `VideoTurn\AutoPublish_Morning`、`VideoTurn\AutoPublish_Afternoon`，以及 `\MoneyPrinterTurbo Daily Auto Publish` 根層工作。

## 測試與檢查

測試放在 `MoneyPrinterTurbo/test/` 與 `MoneyPrinterTurbo/test/services/`。目前測試涵蓋 RSS 挑題、LLM provider 設定、素材下載、BGM 路徑安全、任務流程、通知、Facebook Reels、每日報告等。

可用可攜 Python 執行：

```powershell
cd .\MoneyPrinterTurbo-Portable-Windows-1.2.6\MoneyPrinterTurbo
$env:PYTHONIOENCODING = "utf-8"
..\lib\python\python.exe -m unittest discover -s test
```

若本機有 `pytest`，也可以跑：

```powershell
..\lib\python\python.exe -m pytest test
```

提交前至少檢查：

```powershell
git status --short
git diff --check
```

## 維護注意事項

- 不要提交 `config.toml`、`.env`、OAuth client secret、refresh token、生成影片、log、`storage/` 或可攜 `lib/`。
- 修改發布平台時，同步檢查 `platform_publish.py`、對應 publisher、`auto_publish_youtube.py` 與 `test/services/`。
- 修改 RSS 題材挑選時，先看 `rss_ingest.py` 和 `test/services/test_rss_ingest.py`。
- 修改 YouTube 上傳或 OAuth 時，先確認 `pending_upload.json` 是否存在；已有影片時應優先修復上傳，不要直接重生影片。
- 修改排程腳本時，先跑 `install_scheduler.bat --xml-only`，再檢查 XML 是否只更新預期欄位。
- PowerShell 顯示中文亂碼不一定代表檔案內容壞掉；必要時用 UTF-8 讀取或用 Python/TOML parser 驗證。
