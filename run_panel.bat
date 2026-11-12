@echo off
rem Open the tools panel.
rem Prefers the packaged exe (no Python needed), then the tool venv, then PATH python.
rem NOTE: keep this file CRLF. cmd.exe mis-parses multi-line if-blocks in LF files.
setlocal
if exist "%~dp0LaTeX-Toolbox.exe" goto exe
set "VENDIR=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts"
if exist "%VENDIR%\pythonw.exe" goto venv
set "VENDIR=%~dp0..\.workbuddy\binaries\python\envs\default\Scripts"
if exist "%VENDIR%\pythonw.exe" goto venv
goto plain
:exe
start "" "%~dp0LaTeX-Toolbox.exe"
exit /b 0
:venv
start "" "%VENDIR%\pythonw.exe" "%~dp0panel_qt.py"
exit /b 0
:plain
python "%~dp0panel_qt.py"
if errorlevel 1 pause
