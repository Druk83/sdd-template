@echo off
REM Windows wrapper for the exported agent-logic tool

set "SCRIPT_DIR=%~dp0"
if not defined PYTHON set "PYTHON=python"

"%PYTHON%" "%SCRIPT_DIR%agent-logic.py" %*
