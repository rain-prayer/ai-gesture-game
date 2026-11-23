@echo off
rem Wrapper for scripts/publish.ps1
rem Usage: scripts\publish.bat -Remote gitee
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish.ps1" %*
pause
