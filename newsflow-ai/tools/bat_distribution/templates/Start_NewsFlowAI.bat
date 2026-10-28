@echo off
setlocal DisableDelayedExpansion
rem DEVELOPMENT TEMPLATE ONLY: dispatcher refuses live application execution.
if not exist "%~dp0app\runtime\python.exe" (
  echo BLOCKED: bundled Python runtime is missing.
  exit /b 2
)
if not exist "%~dp0app\controller\bat_distribution\contract_entry.py" (
  echo BLOCKED: contract dispatcher is missing.
  exit /b 2
)
"%~dp0app\runtime\python.exe" -I -B "%~dp0app\controller\bat_distribution\contract_entry.py" start "%~dp0."
exit /b %errorlevel%
