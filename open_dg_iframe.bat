@echo off
cd /d "%~dp0"
echo ============================================
echo  BUOC 1: Dong tat ca cua so Chrome hien co
echo ============================================
taskkill /f /im chrome.exe >nul 2>&1
timeout /t 3 >nul

echo.
echo ============================================
echo  BUOC 2: Mo Chrome voi CDP port 9222
echo ============================================
set "CHROME=E:\Tools\Google Chrome\App\Chrome-bin\chrome.exe"
if not exist "%CHROME%" set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

if not exist "%CHROME%" (
    echo [LOI] Khong tim thay chrome.exe
    pause
    exit /b 1
)

echo [.] Dang mo Chrome tai cd p 9222 voi profile: %~dp0chrome_profile
start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%~dp0chrome_profile" --no-first-run --no-default-browser-check "https://www.neo179.com/gamelobby/live"

echo.
echo [.] Dang cho 5 giay de CDP sang...
timeout /t 5 >nul

echo.
echo ============================================
echo  BUOC 3: Chay script lay URL iframe DG
echo ============================================
python tools\open_dg_iframe.py

echo.
pause
