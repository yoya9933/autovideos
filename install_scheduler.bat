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
set "XML_TECH=%SCRIPT_DIR%task_tech_4h.xml"
set "XML_CONSUMER=%SCRIPT_DIR%task_consumer_4h.xml"
set "XML_CYBER=%SCRIPT_DIR%task_cybersecurity_4h.xml"
set "XML_SCIENCE=%SCRIPT_DIR%task_science_future_4h.xml"

echo [1/4] Refreshing task XML for current folder...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference = 'Stop';" ^
    "$ns = 'http://schemas.microsoft.com/windows/2004/02/mit/task';" ^
    "function Set-TaskXml($path, $description, $startBoundary, $arguments) { [xml]$xml = Get-Content -Raw -Path $path; $nsm = New-Object System.Xml.XmlNamespaceManager($xml.NameTable); $nsm.AddNamespace('t', $ns); $xml.SelectSingleNode('/t:Task/t:RegistrationInfo/t:Description', $nsm).InnerText = $description; $xml.SelectSingleNode('/t:Task/t:Triggers/t:CalendarTrigger/t:StartBoundary', $nsm).InnerText = $startBoundary; $commandNode = $xml.SelectSingleNode('/t:Task/t:Actions/t:Exec/t:Command', $nsm); $commandNode.InnerText = $env:TASK_COMMAND; $execNode = $xml.SelectSingleNode('/t:Task/t:Actions/t:Exec', $nsm); $argumentsNode = $xml.SelectSingleNode('/t:Task/t:Actions/t:Exec/t:Arguments', $nsm); if ($null -eq $argumentsNode) { $argumentsNode = $xml.CreateElement('Arguments', $ns); [void]$execNode.InsertAfter($argumentsNode, $commandNode) }; $argumentsNode.InnerText = $arguments; $xml.SelectSingleNode('/t:Task/t:Actions/t:Exec/t:WorkingDirectory', $nsm).InnerText = $env:TASK_WORKDIR; $settings = New-Object System.Xml.XmlWriterSettings; $settings.Encoding = [System.Text.Encoding]::Unicode; $settings.Indent = $true; $writer = [System.Xml.XmlWriter]::Create($path, $settings); try { $xml.Save($writer) } finally { $writer.Close() } }" ^
    "Set-TaskXml $env:XML_TECH 'Auto publish YouTube Shorts - Technology (every 2 hours)' '2026-06-06T00:00:00' '--topic-profile tech';" ^
    "Set-TaskXml $env:XML_CONSUMER 'Auto publish YouTube Shorts - Consumer Money (every 2 hours)' '2026-06-06T01:00:00' '--topic-profile consumer_money';"
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

call :CreateTask "2/6" "technology every 4 hours" "VideoTurn\AutoPublish_Tech_4h" "%XML_TECH%" || exit /b 1
call :CreateTask "3/6" "consumer money every 4 hours" "VideoTurn\AutoPublish_Consumer_4h" "%XML_CONSUMER%" || exit /b 1
call :CreateTask "4/6" "cybersecurity every 4 hours" "VideoTurn\AutoPublish_Cybersecurity_4h" "%XML_CYBER%" || exit /b 1
call :CreateTask "5/6" "science future every 4 hours" "VideoTurn\AutoPublish_ScienceFuture_4h" "%XML_SCIENCE%" || exit /b 1

echo [4/4] Disabling old scheduler tasks if present...
for %%T in ("VideoTurn\AutoPublish_0900" "VideoTurn\AutoPublish_1130" "VideoTurn\AutoPublish_1400" "VideoTurn\AutoPublish_1630" "VideoTurn\AutoPublish_1900" "VideoTurn\AutoPublish_2130" "VideoTurn\AutoPublish_Morning" "VideoTurn\AutoPublish_Afternoon" "\MoneyPrinterTurbo Daily Auto Publish") do (
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
echo   - Technology: every 2 hours from 00:00 (12 videos/day)
echo   - Consumer Money: every 2 hours from 01:00 (12 videos/day)
echo   - Total: 24 videos/day
echo.
echo   Check: Task Scheduler > VideoTurn
echo ========================================
echo.
if /I "%~1"=="--no-pause" (
    endlocal
    exit /b 0
)
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
