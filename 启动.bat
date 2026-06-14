@echo off
chcp 65001 > nul
title 言語景観ツール ランチャー

echo ================================
echo  言語景観ツール 起動中...
echo ================================
echo.

:: カレントディレクトリをbatファイルの場所に設定
cd /d "%~dp0"

:: Pythonの場所を探す
set PYTHON=
for %%p in (
    "python"
    "%LOCALAPPDATA%\Microsoft\WindowsApps\python3.11.exe"
    "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Python39\python.exe"
) do (
    if not defined PYTHON (
        %%p --version >nul 2>&1 && set PYTHON=%%~p
    )
)

if not defined PYTHON (
    echo [エラー] Python が見つかりません。
    echo Python をインストールしてください。
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Python: %PYTHON%
echo フォルダ: %~dp0
echo.

:: ランチャーがあれば優先して起動する
if exist "%~dp0ランチャー.py" (
    echo ランチャーを起動しています...
    start "" "%PYTHON%" "%~dp0ランチャー.py"
    exit /b 0
)

echo [警告] ランチャー.py が見つかりません。地図サーバーを直接起動します。
echo.

:: ポート8080が使用中かチェック
netstat -ano | findstr /R /C:":8080 .*LISTENING" > nul 2>&1
if %errorlevel% == 0 (
    echo ポート8080はすでに使用中です。
    echo ブラウザで開きます...
    timeout /t 1 > nul
    start "" "http://localhost:8080/index.html"
    exit /b 0
)

:: サーバー起動
echo サーバーを起動しています...
start /b "" "%PYTHON%" -m http.server 8080

:: 起動待機
timeout /t 2 > nul

:: ブラウザを開く
echo ブラウザを開いています...
start "" "http://localhost:8080/index.html"

echo.
echo ================================
echo  サーバー起動中
echo  http://localhost:8080
echo.
echo  このウィンドウを閉じるとサーバーは停止しません。
echo ================================
echo.

pause
