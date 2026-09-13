@echo off
rem CapCut All-in-One launcher. The program lives in app\ - just run the exe there.
rem ASCII only: cmd.exe mangles multibyte characters inside batch files.
cd /d "%~dp0"

if not exist "%~dp0app\" goto NOAPP

for %%F in ("%~dp0app\*.exe") do (
    start "" "%%~F"
    exit /b 0
)

:NOAPP
echo [ERROR] app folder not found. Unzip the whole file first, then run this.
pause
exit /b 1
