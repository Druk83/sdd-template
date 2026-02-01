@echo off
REM Wrapper for pdd_scan.py (Windows)

set "SCRIPT_DIR=%~dp0"
if not defined PYTHON set "PYTHON=python"

"%PYTHON%" "%SCRIPT_DIR%pdd_scan.py" %*
