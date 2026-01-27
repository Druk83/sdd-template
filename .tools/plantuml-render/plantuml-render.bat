@echo off
REM Wrapper for plantuml_render.py (Windows)

set "SCRIPT_DIR=%~dp0"
if not defined PYTHON set "PYTHON=python"

"%PYTHON%" "%SCRIPT_DIR%plantuml_render.py" %*
