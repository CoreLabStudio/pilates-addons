@echo off
REM mōva demo tunnel — starts ngrok on port 8069
REM Usage: double-click or run from any terminal
REM Requires ngrok installed and authenticated (ngrok config add-authtoken <token>)
REM
REM STATIC DOMAIN: claim one free static domain at https://dashboard.ngrok.com/domains
REM Then set STATIC_DOMAIN below (e.g. "lucky-bear-obviously.ngrok-free.app")
REM Leave blank to use a random temporary URL instead.

set PORT=8069
set STATIC_DOMAIN=unwired-sermon-grape.ngrok-free.dev

echo.
echo  mova demo tunnel
echo  ================

where ngrok >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: ngrok not found in PATH.
    echo  Download from https://ngrok.com/download and add to PATH.
    pause
    exit /b 1
)

if defined STATIC_DOMAIN (
    echo  Forwarding localhost:%PORT% to https://%STATIC_DOMAIN%
    echo  This URL is stable across restarts.
    echo  Press Ctrl+C to stop.
    echo.
    ngrok http --url=%STATIC_DOMAIN% %PORT%
) else (
    echo  Forwarding localhost:%PORT% via ngrok ^(random URL^)
    echo  Set STATIC_DOMAIN in this file for a stable URL.
    echo  Press Ctrl+C to stop.
    echo.
    ngrok http %PORT%
)

echo.
echo  Tunnel stopped. Press any key to close this window.
pause >nul
