@echo off
REM Wrapper for manifest-validator.py (Windows)

set "SCRIPT_DIR=%~dp0"
if not defined PYTHON set "PYTHON=python"

"%PYTHON%" "%SCRIPT_DIR%manifest-validator.py" %*
