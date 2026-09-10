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
