# Linux / WSL 使用指南

這個專案的核心是 Python，原本外層包成 Windows portable 版本。Linux / WSL 不需要使用內附的 Windows `python.exe`、`ffmpeg.exe` 或 `.bat`，改用系統 Python、虛擬環境、系統 ffmpeg，以及 cron 即可。

## 1. 安裝系統套件

Ubuntu / Debian / WSL:

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip ffmpeg imagemagick cron
```

如果系統沒有 `python3.11` 套件，也可以使用既有的 `python3`，但建議使用 Python 3.11。

## 2. 建立 Python 環境

```bash
cd /home/yoya9933/code/autovideos/MoneyPrinterTurbo-Portable-Windows-1.2.6/MoneyPrinterTurbo
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp -n config.example.toml config.toml
```

接著編輯 `config.toml`。至少需要設定：

```toml
llm_provider = "gemini"
gemini_api_key = "your-gemini-api-key"

pexels_api_keys = ["your-pexels-api-key"]

youtube_upload_enabled = false
youtube_upload_privacy_status = "private"
```

第一次建議先讓 `youtube_upload_enabled = false`，確認能選題和產片後再開上傳。

也可以改用環境變數放 secrets，避免把 key 寫進設定檔：

```bash
export GEMINI_API_KEY="your-gemini-api-key"
export PEXELS_API_KEYS="your-pexels-api-key"
export YOUTUBE_CLIENT_ID="your-youtube-client-id"
export YOUTUBE_CLIENT_SECRET="your-youtube-client-secret"
export YOUTUBE_REFRESH_TOKEN="your-youtube-refresh-token"
```

如果要讓 cron 排程也讀得到這些 secrets，請放在內層 `.env`：

```bash
cd /home/yoya9933/code/autovideos/MoneyPrinterTurbo-Portable-Windows-1.2.6/MoneyPrinterTurbo
cat > .env <<'EOF'
GEMINI_API_KEY=your-gemini-api-key
PEXELS_API_KEYS=your-pexels-api-key
YOUTUBE_CLIENT_ID=your-youtube-client-id
YOUTUBE_CLIENT_SECRET=your-youtube-client-secret
YOUTUBE_REFRESH_TOKEN=your-youtube-refresh-token
EOF
```

不要把真實 key commit 進 Git。`app/config/config.py` 會自動讀取這個 `.env`。

## 3. 先測 RSS / 選題

從專案根目錄執行：

```bash
cd /home/yoya9933/code/autovideos
./run_daily_auto_publish.sh --dry-run
```

`--dry-run` 會抓 RSS、選題、產生 prompt，然後停止；不會生成影片，也不會上傳。

## 4. 再測產片但不上傳

```bash
./run_daily_auto_publish.sh --no-upload
```

這會生成影片並寫入 job 狀態，但不會上傳 YouTube。輸出與紀錄會在：

```text
MoneyPrinterTurbo-Portable-Windows-1.2.6/MoneyPrinterTurbo/storage/auto_publish/
```

常看的路徑：

```text
logs/
jobs/
publish_status/
seen.json
```

## 5. 設定 YouTube 上傳

到 Google Cloud 建立 OAuth client，下載 `client_secret*.json`，放在專案根目錄或傳給 helper 指定路徑。

```bash
cd /home/yoya9933/code/autovideos/MoneyPrinterTurbo-Portable-Windows-1.2.6/MoneyPrinterTurbo
source .venv/bin/activate
python get_youtube_refresh_token.py --write-config --no-browser
```

指令會印出授權 URL。用瀏覽器打開並登入 YouTube 帳號授權，成功後 helper 會取得 refresh token 並寫回 `config.toml`。

確認後再把 `config.toml` 改成：

```toml
youtube_upload_enabled = true
youtube_upload_privacy_status = "private"
```

建議先用 `private` 測試，確認影片、標題、縮圖都沒問題後再改成 `public`。

## 6. 正式跑一次

```bash
cd /home/yoya9933/code/autovideos
./run_daily_auto_publish.sh
```

如果要更新程式、安裝依賴、然後跑一次：

```bash
./update_and_run.sh
```

## 7. 安裝每天 12:00 / 20:00 cron

```bash
cd /home/yoya9933/code/autovideos
./install_cron.sh
```

確認 cron:

```bash
crontab -l
```

cron 會用系統目前時區執行。如果是在 VPS 上，請先確認：

```bash
timedatectl
```

需要改成台北時區時：

```bash
sudo timedatectl set-timezone Asia/Taipei
```

## 8. 常見問題

- `Python 3.11/python3 not found`：先安裝 Python 或建立 `.venv`。
- `ffmpeg not found`：安裝 `ffmpeg`。
- `ImageMagick` 相關錯誤：安裝 `imagemagick`，或確認 `magick` / `convert` 在 PATH 裡。
- Gemini 429：代表 API rate limit，先等一段時間，或設定 `gemini_backup_api_key`。
- YouTube 上傳失敗：先改回 `youtube_upload_privacy_status = "private"` 測試，並檢查 OAuth refresh token 是否仍有效。
