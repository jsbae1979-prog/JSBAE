@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 goto location_error
where py >nul 2>&1
if errorlevel 1 goto try_python
py -3.12 -c "import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)" >nul 2>&1
if errorlevel 1 goto try_python
py -3.12 "tools\windows_launcher.py"
set "NF_EXIT=%ERRORLEVEL%"
goto finished
:try_python
where python >nul 2>&1
if errorlevel 1 goto python_error
python -c "import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)" >nul 2>&1
if errorlevel 1 goto python_error
python "tools\windows_launcher.py"
set "NF_EXIT=%ERRORLEVEL%"
goto finished
:python_error
echo Python 3.12 is required. Install Python 3.12 from python.org, then retry.
set "NF_EXIT=1"
goto finished
:location_error
echo Cannot open the project folder. Check its path and permissions.
set "NF_EXIT=1"
:finished
if "%NF_EXIT%"=="0" goto done
echo NewsFlow AI did not start or stopped with an error. See README troubleshooting.
pause
:done
exit /b %NF_EXIT%
