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
set "XML_0900=%SCRIPT_DIR%task_0900.xml"
set "XML_1130=%SCRIPT_DIR%task_1130.xml"
set "XML_1400=%SCRIPT_DIR%task_1400.xml"
set "XML_1630=%SCRIPT_DIR%task_1630.xml"
set "XML_1900=%SCRIPT_DIR%task_1900.xml"
set "XML_2130=%SCRIPT_DIR%task_2130.xml"

echo [1/8] Refreshing task XML for current folder...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference = 'Stop';" ^
    "$ns = 'http://schemas.microsoft.com/windows/2004/02/mit/task';" ^
    "function Set-TaskXml($path, $description, $startBoundary) { [xml]$xml = Get-Content -Raw -Path $path; $nsm = New-Object System.Xml.XmlNamespaceManager($xml.NameTable); $nsm.AddNamespace('t', $ns); $xml.SelectSingleNode('/t:Task/t:RegistrationInfo/t:Description', $nsm).InnerText = $description; $xml.SelectSingleNode('/t:Task/t:Triggers/t:CalendarTrigger/t:StartBoundary', $nsm).InnerText = $startBoundary; $xml.SelectSingleNode('/t:Task/t:Actions/t:Exec/t:Command', $nsm).InnerText = $env:TASK_COMMAND; $xml.SelectSingleNode('/t:Task/t:Actions/t:Exec/t:WorkingDirectory', $nsm).InnerText = $env:TASK_WORKDIR; $settings = New-Object System.Xml.XmlWriterSettings; $settings.Encoding = [System.Text.Encoding]::Unicode; $settings.Indent = $true; $writer = [System.Xml.XmlWriter]::Create($path, $settings); try { $xml.Save($writer) } finally { $writer.Close() } }" ^
    "Set-TaskXml $env:XML_0900 'Auto publish YouTube Shorts - Run 1 (09:00)' '2026-06-06T09:00:00';" ^
    "Set-TaskXml $env:XML_1130 'Auto publish YouTube Shorts - Run 2 (11:30)' '2026-06-06T11:30:00';" ^
    "Set-TaskXml $env:XML_1400 'Auto publish YouTube Shorts - Run 3 (14:00)' '2026-06-06T14:00:00';" ^
    "Set-TaskXml $env:XML_1630 'Auto publish YouTube Shorts - Run 4 (16:30)' '2026-06-06T16:30:00';" ^
    "Set-TaskXml $env:XML_1900 'Auto publish YouTube Shorts - Run 5 (19:00)' '2026-06-06T19:00:00';" ^
    "Set-TaskXml $env:XML_2130 'Auto publish YouTube Shorts - Run 6 (21:30)' '2026-06-06T21:30:00';"
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

call :CreateTask "2/8" "09:00" "VideoTurn\AutoPublish_0900" "%XML_0900%" || exit /b 1
call :CreateTask "3/8" "11:30" "VideoTurn\AutoPublish_1130" "%XML_1130%" || exit /b 1
call :CreateTask "4/8" "14:00" "VideoTurn\AutoPublish_1400" "%XML_1400%" || exit /b 1
call :CreateTask "5/8" "16:30" "VideoTurn\AutoPublish_1630" "%XML_1630%" || exit /b 1
call :CreateTask "6/8" "19:00" "VideoTurn\AutoPublish_1900" "%XML_1900%" || exit /b 1
call :CreateTask "7/8" "21:30" "VideoTurn\AutoPublish_2130" "%XML_2130%" || exit /b 1

echo [8/8] Disabling old scheduler tasks if present...
for %%T in ("VideoTurn\AutoPublish_Morning" "VideoTurn\AutoPublish_Afternoon" "\MoneyPrinterTurbo Daily Auto Publish") do (
    schtasks /Query /TN "%%~T" >nul 2>&1
    if errorlevel 1 (
        echo     [SKIP] %%~T not found.
    ) else (
        schtasks /Change /TN "%%~T" /DISABLE
        if errorlevel 1 (
            echo     [FAIL] Failed to disable %%~T.
            pause
            exit /b 1
        )
        echo     [OK] %%~T disabled.
    )
)

echo.
echo ========================================
echo   Done!
echo   - Daily 09:00 auto upload (video 1)
echo   - Daily 11:30 auto upload (video 2)
echo   - Daily 14:00 auto upload (video 3)
echo   - Daily 16:30 auto upload (video 4)
echo   - Daily 19:00 auto upload (video 5)
echo   - Daily 21:30 auto upload (video 6)
echo.
echo   Check: Task Scheduler > VideoTurn
echo ========================================
echo.
pause
endlocal
exit /b 0

:CreateTask
echo [%~1] Creating %~2 task...
schtasks /Create /TN "%~3" /XML "%~4" /F
if errorlevel 1 (
    echo     [FAIL] Please run as Administrator!
    pause
    exit /b 1
)
echo     [OK] %~2 task created.
exit /b 0
