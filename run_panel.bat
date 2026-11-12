@echo off
rem Open the tools panel (Qt desktop window) without leaving a console behind.
rem Finds a Python that can import PySide6: tool venv first, then PATH python.
rem NOTE: keep this file CRLF. cmd.exe mis-parses multi-line if-blocks in LF files.
setlocal
set "VENDIR=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts"
if exist "%VENDIR%\pythonw.exe" goto run
set "VENDIR=%~dp0..\.workbuddy\binaries\python\envs\default\Scripts"
if exist "%VENDIR%\pythonw.exe" goto run
goto plain
:run
start "" "%VENDIR%\pythonw.exe" "%~dp0panel_qt.py"
exit /b 0
:plain
python "%~dp0panel_qt.py"
if errorlevel 1 pause
