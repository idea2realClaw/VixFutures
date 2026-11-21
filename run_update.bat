@echo off
setlocal
cd /d "%~dp0"

if not exist "D:\tmp" mkdir "D:\tmp"
set "LOG=D:\tmp\vixfutures_update.log"

echo [%date% %time%] START >> "%LOG%"

set "PY=C:\Users\zhuxi\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if exist "%PY%" goto RUN

where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  set "PY=py"
  goto RUN
)

where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  set "PY=python"
  goto RUN
)

echo [%date% %time%] NO_PYTHON_FOUND >> "%LOG%"
echo NO_PYTHON_FOUND
exit /b 1

:RUN
"%PY%" scripts\update_node.py >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo [%date% %time%] EXIT=%RC% >> "%LOG%"
echo VixFutures update finished, exit=%RC%. Log: %LOG%
exit /b %RC%
