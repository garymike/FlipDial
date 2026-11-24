@echo off
rem Double-click to update FlipDial.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" %*
if errorlevel 1 pause
