@echo off
setlocal EnableDelayedExpansion
rem ------------------------------------------------------------------
rem  moneydj-fund-nav-high-report : install into %USERPROFILE%\.claude\skills
rem  Double-click, or run from a terminal:  install.bat
rem ------------------------------------------------------------------
set "NAME=moneydj-fund-nav-high-report"
set "SRC=%~dp0"
if "%SRC:~-1%"=="\" set "SRC=%SRC:~0,-1%"
set "DST=%USERPROFILE%\.claude\skills\%NAME%"

echo.
echo [1/3] Copy skill to %DST%
if /I "%SRC%"=="%DST%" (
  echo       already in place, nothing to copy
) else (
  if not exist "%DST%" mkdir "%DST%"
  xcopy "%SRC%\*" "%DST%\" /E /I /Y /Q >nul
  if errorlevel 1 ( echo       COPY FAILED & goto :fail )
  echo       done
)

echo.
echo [2/3] Find Python 3.8 or newer
set "PY="
for %%C in ("py -3" "python3" "python") do (
  if not defined PY (
    %%~C -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
    if !errorlevel! equ 0 (
      for /f "delims=" %%P in ('%%~C -c "import sys; print(sys.executable)"') do set "PY=%%P"
    )
  )
)
if not defined PY (
  echo       Python 3.8+ not found.
  echo       Install it from https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  echo       then run install.bat again.
  goto :fail
)
echo       using !PY!
> "%DST%\python_path.txt" echo !PY!

echo.
echo [3/3] Test run: 3 funds from MoneyDJ category 47
set "PYTHONIOENCODING=utf-8"
set "TEST=%TEMP%\%NAME%-test"
"!PY!" "%DST%\scripts\fund_nav_high_report.py" --category 47 --limit 3 --no-cache --out "%TEST%\report.html"
if errorlevel 1 (
  echo       TEST FAILED - check the internet connection, or whether moneydj.com is reachable.
  goto :fail
)
echo.
echo Installed. Test report: %TEST%\report.html
echo In Claude Code type  /%NAME%  or paste a MoneyDJ iQuoteFundCatFund URL.
echo Optional data check needs Node.js + Playwright, see README.md.
echo.
pause
exit /b 0

:fail
echo.
pause
exit /b 1
