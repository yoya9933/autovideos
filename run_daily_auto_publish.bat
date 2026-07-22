@echo off
setlocal
chcp 65001 >nul

set "CURRENT_DIR=%~dp0MoneyPrinterTurbo-Portable-Windows-1.2.6\"

rem --- FFmpeg / ImageMagick (same as start.bat) ---
set "FFMPEG_BINARY=%CURRENT_DIR%lib\ffmpeg\ffmpeg-7.0-essentials_build\ffmpeg.exe"
set "IMAGEMAGICK_BINARY=%CURRENT_DIR%lib\imagemagic\ImageMagick-7.1.1-29-portable-Q16-x64\magick.exe"
set "IMAGEIO_FFMPEG_EXE=%FFMPEG_BINARY%"
set "LOG_DIR=%CURRENT_DIR%MoneyPrinterTurbo\storage\auto_publish\logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

rem --- 以日期命名 bat 啟停 log，與 Python loguru 的 daily_YYYY-MM-DD.log 並列 ---
for /f "tokens=1-3 delims=/-" %%a in ("%DATE%") do (
    set "TODAY=%%a%%b%%c"
)
set "BAT_LOG=%LOG_DIR%\bat_%TODAY%.log"

rem --- 清理 30 天前的舊 bat log（forfiles 找不到符合檔案時會輸出錯誤，重定向至 nul）---
forfiles /p "%LOG_DIR%" /m "bat_*.log" /d -30 /c "cmd /c del @path" >nul 2>&1

cd /d "%CURRENT_DIR%MoneyPrinterTurbo"
echo ==== %DATE% %TIME% run_daily_auto_publish start ==== >> "%BAT_LOG%"
"%CURRENT_DIR%lib\python\python.exe" auto_publish_youtube.py %* >> "%BAT_LOG%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
echo ==== %DATE% %TIME% run_daily_auto_publish exit %EXIT_CODE% ==== >> "%BAT_LOG%"
echo ==== %DATE% %TIME% daily_job_report --send-email-on-complete start ==== >> "%BAT_LOG%"
"%CURRENT_DIR%lib\python\python.exe" daily_job_report.py --send-email --send-email-on-complete --expected-jobs 24 >> "%BAT_LOG%" 2>&1
set "REPORT_EXIT_CODE=%ERRORLEVEL%"
echo ==== %DATE% %TIME% daily_job_report --send-email exit %REPORT_EXIT_CODE% ==== >> "%BAT_LOG%"

endlocal & exit /b %EXIT_CODE%
