# VideoTurn SOP

## Daily Job Report

Use this before manually reading daily logs when checking auto-publish output.

1. Open the app directory:
   `D:\coding_202605051504_XY_Propose_Minutes\videoturn_202606011405_XY\MoneyPrinterTurbo-Portable-Windows-1.2.6\MoneyPrinterTurbo`
2. Print today's report:
   `..\lib\python\python.exe daily_job_report.py`
3. Print a specific local Taiwan date:
   `..\lib\python\python.exe daily_job_report.py --date YYYY-MM-DD`
4. Send the report through the existing Email notifier:
   `..\lib\python\python.exe daily_job_report.py --send-email`
5. Save a text copy only when local Python writes are allowed:
   `..\lib\python\python.exe daily_job_report.py --save`
6. Read the report in this order:
   jobs total, failed jobs, public video ids, error-like titles, sources, material terms.
7. If the report shows an error-like title or failed stage, inspect the matching job JSON and publish-status JSON before rerunning.

## Manual Public Publish Trigger

1. Before launching a manual public publish, check whether a scheduled portable-Python publish process is already running.
2. If a scheduled run is active, monitor its job/log/publish_status evidence instead of starting a second public upload.
3. Treat a successful scheduled run as the requested full-flow trigger when it is already producing/uploading at the time of the request.
4. After completion, verify with job JSON, publish_status JSON, daily report, and the uploaded YouTube video id.

## Review / 診斷順序

1. 讀全域工作台文件與本 `PROJECT_MEMORY`。
2. 先看 `storage\auto_publish\jobs\*.json`。
3. 再看 `storage\auto_publish\publish_status\*.json`。
4. 再看 `storage\auto_publish\logs\*.log`。
5. 解析 active `config.toml`，不要只看 `config.example.toml` 或簡報。
6. 查 `auto_publish_youtube.py` 主流程是否真的執行文件所說的 gate。
7. 查 `rss_ingest.py` 與 `llm.py` 的 LLM 輸出防線。
8. 最後再看排程 XML 與 batch wrapper。

## 公開發布前 checklist

1. `youtube_upload_privacy_status` 是否應該暫時改成 `private` 或 `unlisted`。
2. quality gate 是否存在且 active config 明確啟用。
3. LLM error string 是否會中止，不會進入 title/script/description。
4. 最新 job 是否有 `Error:`, `429`, `quota`, `rate limit` 進入 title 或 prompt。
5. 最新影片是否有 subtitle、audio、final mp4、合理時長。
6. 通知是否真的設定完成。
7. job/publish_status 是否能追蹤每個平台結果。

## 建議驗證命令

使用 portable Python，並先避免讓測試寫入正式 daily log。
正式修復後再跑 targeted unittest。
