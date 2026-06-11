@echo off
setlocal
chcp 65001 >nul

echo ==== 1. Pulling latest code from git ====
cd /d "%~dp0MoneyPrinterTurbo-Portable-Windows-1.2.6\MoneyPrinterTurbo"
git pull origin main

echo ==== 2. Updating dependencies ====
set "PYTHON_EXE=%~dp0MoneyPrinterTurbo-Portable-Windows-1.2.6\lib\python\python.exe"
"%PYTHON_EXE%" -m pip install --upgrade pip
"%PYTHON_EXE%" -m pip install -r requirements.txt

echo ==== 3. Running auto publish script ====
cd /d "%~dp0"
call run_daily_auto_publish.bat

echo ==== Done ====
pause
