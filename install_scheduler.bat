@echo off
setlocal
chcp 65001 >nul
echo ========================================
echo   VideoTurn Task Scheduler Installer
echo   Run as Administrator!
echo ========================================
echo.

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%.") do set "TASK_WORKDIR=%%~fI"
set "TASK_COMMAND=%SCRIPT_DIR%run_daily_auto_publish.bat"
set "MORNING_XML=%SCRIPT_DIR%task_morning.xml"
set "AFTERNOON_XML=%SCRIPT_DIR%task_afternoon.xml"

echo [1/3] Refreshing task XML for current folder...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference = 'Stop';" ^
    "$ns = 'http://schemas.microsoft.com/windows/2004/02/mit/task';" ^
    "function Set-TaskXml($path, $description, $startBoundary) { [xml]$xml = Get-Content -Raw -Path $path; $nsm = New-Object System.Xml.XmlNamespaceManager($xml.NameTable); $nsm.AddNamespace('t', $ns); $xml.SelectSingleNode('/t:Task/t:RegistrationInfo/t:Description', $nsm).InnerText = $description; $xml.SelectSingleNode('/t:Task/t:Triggers/t:CalendarTrigger/t:StartBoundary', $nsm).InnerText = $startBoundary; $xml.SelectSingleNode('/t:Task/t:Actions/t:Exec/t:Command', $nsm).InnerText = $env:TASK_COMMAND; $xml.SelectSingleNode('/t:Task/t:Actions/t:Exec/t:WorkingDirectory', $nsm).InnerText = $env:TASK_WORKDIR; $settings = New-Object System.Xml.XmlWriterSettings; $settings.Encoding = [System.Text.Encoding]::Unicode; $settings.Indent = $true; $writer = [System.Xml.XmlWriter]::Create($path, $settings); try { $xml.Save($writer) } finally { $writer.Close() } }" ^
    "Set-TaskXml $env:MORNING_XML 'Auto publish YouTube Shorts - Noon run (12:00)' '2026-06-06T12:00:00';" ^
    "Set-TaskXml $env:AFTERNOON_XML 'Auto publish YouTube Shorts - Evening run (20:00)' '2026-06-06T20:00:00';"
if errorlevel 1 (
    echo     [FAIL] Failed to refresh task XML.
    pause
    exit /b 1
)
echo     [OK] Task XML refreshed.
if /I "%~1"=="--xml-only" (
    echo     XML refresh only; scheduler tasks were not created.
    endlocal
    exit /b 0
)

echo [2/3] Creating noon 12:00 task...
schtasks /Create /TN "VideoTurn\AutoPublish_Morning" /XML "%SCRIPT_DIR%task_morning.xml" /F
if errorlevel 1 (
    echo     [FAIL] Please run as Administrator!
    pause
    exit /b 1
)
echo     [OK] 12:00 task created.

echo [3/3] Creating evening 20:00 task...
schtasks /Create /TN "VideoTurn\AutoPublish_Afternoon" /XML "%SCRIPT_DIR%task_afternoon.xml" /F
if errorlevel 1 (
    echo     [FAIL] Failed!
    pause
    exit /b 1
)
echo     [OK] 20:00 task created.

echo.
echo ========================================
echo   Done!
echo   - Daily 12:00 auto upload (video 1)
echo   - Daily 20:00 auto upload (video 2)
echo.
echo   Check: Task Scheduler > VideoTurn
echo ========================================
echo.
pause
endlocal
