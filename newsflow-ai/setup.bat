@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 goto location_error
rem Preserve an existing supported environment; never replace it silently.
if exist ".venv\Scripts\python.exe" goto existing_venv
where py >nul 2>&1
if errorlevel 1 goto try_python
py -3.14 -c "import sys; sys.exit(0 if sys.version_info[:2] == (3,14) else 1)" >nul 2>&1
if errorlevel 1 goto try_py312
py -3.14 "tools\windows_launcher.py" --setup-only
set "NF_EXIT=%ERRORLEVEL%"
goto finished
:try_py312
py -3.12 -c "import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)" >nul 2>&1
if errorlevel 1 goto try_python
py -3.12 "tools\windows_launcher.py" --setup-only
set "NF_EXIT=%ERRORLEVEL%"
goto finished
:existing_venv
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2] in ((3,12),(3,14)) else 1)" >nul 2>&1
if errorlevel 1 goto python_error
".venv\Scripts\python.exe" "tools\windows_launcher.py" --setup-only
set "NF_EXIT=%ERRORLEVEL%"
goto finished
:try_python
where python >nul 2>&1
if errorlevel 1 goto python_error
python -c "import sys; sys.exit(0 if sys.version_info[:2] in ((3,12),(3,14)) else 1)" >nul 2>&1
if errorlevel 1 goto python_error
python "tools\windows_launcher.py" --setup-only
set "NF_EXIT=%ERRORLEVEL%"
goto finished
:python_error
echo Python 3.12 or 3.14 is required. Python 3.13 is not supported.
echo Open START_HERE.html for setup guidance.
set "NF_EXIT=1"
goto finished
:location_error
echo Cannot open the project folder. Check its path and permissions.
set "NF_EXIT=1"
:finished
if "%NF_EXIT%"=="0" goto setup_done
echo NewsFlow AI did not start or stopped with an error. See README troubleshooting.
pause
goto done
:setup_done
echo Required preparation checks passed. Open run.bat to start.
pause
:done
exit /b %NF_EXIT%
