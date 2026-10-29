@echo off
setlocal DisableDelayedExpansion
rem Owned private session only; never taskkill or stop host processes.
if not exist "%~dp0app\runtime\python.exe" (
  echo BLOCKED: bundled Python runtime is missing.
  exit /b 2
)
if not exist "%~dp0app\controller\bat_distribution\contract_entry.py" (
  echo BLOCKED: contract dispatcher is missing.
  exit /b 2
)
"%~dp0app\runtime\python.exe" -I -B "%~dp0app\controller\bat_distribution\contract_entry.py" stop "%~dp0."
exit /b %errorlevel%
