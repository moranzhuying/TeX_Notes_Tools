@echo off
rem Open the tools panel from source (development entry).
rem Prefers the packaged exe first, then the tool venv, then PATH python.
rem Layout: Tools\LaTeX-Toolbox.exe  +  Tools\src\ (scripts, this file).
rem NOTE: keep this file CRLF. cmd.exe mis-parses multi-line if-blocks in LF files.
setlocal
set "ROOT=%~dp0.."
if exist "%ROOT%\LaTeX-Toolbox.exe" goto exe
set "VENDIR=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts"
if exist "%VENDIR%\pythonw.exe" goto venv
set "VENDIR=%ROOT%\..\.workbuddy\binaries\python\envs\default\Scripts"
if exist "%VENDIR%\pythonw.exe" goto venv
goto plain
:exe
start "" "%ROOT%\LaTeX-Toolbox.exe"
exit /b 0
:venv
start "" "%VENDIR%\pythonw.exe" "%~dp0panel_qt.py"
exit /b 0
:plain
python "%~dp0panel_qt.py"
if errorlevel 1 pause
