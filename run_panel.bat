@echo off
rem Open the tools panel (Qt desktop window) without leaving a console behind.
rem Prefers the tool venv (PySide6 lives there), falls back to PATH python.
setlocal
set "VENDIR=%~dp0..\.workbuddy\binaries\python\envs\default\Scripts"
if exist "%VENDIR%\pythonw.exe" (
    start "" "%VENDIR%\pythonw.exe" "%~dp0panel_qt.py"
    exit /b 0
)
if exist "%VENDIR%\python.exe" (
    "%VENDIR%\python.exe" "%~dp0panel_qt.py"
    if errorlevel 1 pause
    exit /b 0
)
python "%~dp0panel_qt.py"
if errorlevel 1 pause
