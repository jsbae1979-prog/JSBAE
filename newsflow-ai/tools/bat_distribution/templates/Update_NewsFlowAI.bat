@echo off
setlocal DisableDelayedExpansion
rem DEVELOPMENT TEMPLATE ONLY: no live trust/installer; no update is applied.
if not exist "%~dp0app\runtime\python.exe" (
  echo BLOCKED: bundled Python runtime is missing.
  exit /b 2
)
if not exist "%~dp0app\controller\bat_distribution\contract_entry.py" (
  echo BLOCKED: contract dispatcher is missing.
  exit /b 2
)
"%~dp0app\runtime\python.exe" -I -B "%~dp0app\controller\bat_distribution\contract_entry.py" update "%~dp0."
exit /b %errorlevel%
