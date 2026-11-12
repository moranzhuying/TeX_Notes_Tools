@echo off
rem 打开工具集图形面板（本地网页）。关掉本窗口即停止服务。
cd /d "%~dp0"
python panel_gui.py
if errorlevel 1 pause
