@echo off
cd /d "%~dp0active"
"%~dp0python.exe" -m interface.wms_launcher --diagnostico
echo.
pause