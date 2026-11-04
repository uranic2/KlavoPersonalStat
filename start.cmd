@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if not errorlevel 1 goto run_py
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if not errorlevel 1 goto run_python
echo Python 3.10+ is required. Install it from https://www.python.org/downloads/
echo Then run start.cmd again.
pause
exit /b 1

:run_py
py -3 server.py %*
goto finish

:run_python
python server.py %*

:finish
if errorlevel 1 pause
