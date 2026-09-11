@echo off
REM ---------------------------------------------------------------------------
REM CoreLab / Yoleyva -- run the module test suite.
REM
REM   tools\run-tests.bat -u fitness_portal --test-tags /fitness_portal
REM   tools\run-tests.bat -u fitness_core,fitness_packages,fitness_portal ^
REM                       --test-tags /fitness_core,/fitness_packages,/fitness_portal
REM
REM Override any of these from the shell before calling:
REM   ODOO_PYTHON  ODOO_BIN  ODOO_CONF  TEST_DATA_DIR  TESTDB  TESTPORT  TEST_LOG
REM
REM Read tools\README.md before changing the flags below. Three of them are
REM load-bearing and the suite goes nondeterministic without them.
REM ---------------------------------------------------------------------------

setlocal

if "%ODOO_PYTHON%"==""   set ODOO_PYTHON=C:\odoo-dev\venv\Scripts\python.exe
if "%ODOO_BIN%"==""      set ODOO_BIN=C:\odoo-dev\odoo-19e\odoo-bin
if "%ODOO_CONF%"==""     set ODOO_CONF=C:\odoo-dev\odoo-pilates.conf
if "%TEST_DATA_DIR%"=="" set TEST_DATA_DIR=C:\odoo-dev\testdata
if "%TESTDB%"==""        set TESTDB=fresh_main
if "%TESTPORT%"==""      set TESTPORT=8499
if "%TEST_LOG%"==""      set TEST_LOG=C:\odoo-dev\logs\tests.log

REM Refuse to run if something already owns the test port. The suite talks to
REM its own HTTP server on TESTPORT; if a stranger is there - a forgotten
REM background reproduction, another session's run - every request goes to it
REM instead. That server is a live Odoo in a different test context, so it
REM rejects them all with "400 ... does not contain the required cookie" and
REM ~80 page tests fail identically every run. That reads as a catastrophic
REM regression and is nothing of the kind; it cost an hour on 2026-09-11.
netstat -ano | findstr /R /C:":%TESTPORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo.
  echo   ABORTED: something is already listening on port %TESTPORT%.
  echo.
  echo   The suite would send its requests to that server instead of its own,
  echo   and every page-rendering test would fail with a 400.
  echo.
  echo   Find it:  netstat -ano ^| findstr ":%TESTPORT%"
  echo   Then stop it, or run with a free port:  set TESTPORT=8599
  echo.
  exit /b 1
)

for %%D in ("%TEST_LOG%") do if not exist "%%~dpD" mkdir "%%~dpD"

REM Clear the test session store before each run. Odoo's own HttpCase leaks one
REM session file per test (see README, "The session leak"), so this directory
REM grows every run until it reaches the state that causes the flakiness the
REM --data-dir flag below exists to avoid. Nothing here outlives a run.
if exist "%TEST_DATA_DIR%\sessions" rd /s /q "%TEST_DATA_DIR%\sessions"

"%ODOO_PYTHON%" "%ODOO_BIN%" ^
  -c "%ODOO_CONF%" ^
  -d %TESTDB% ^
  --db-filter=%TESTDB% ^
  --data-dir="%TEST_DATA_DIR%" ^
  --http-port=%TESTPORT% ^
  --max-cron-threads=0 ^
  --test-enable ^
  --stop-after-init ^
  --logfile="%TEST_LOG%" ^
  %*
