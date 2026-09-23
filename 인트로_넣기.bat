@echo off
rem Step 3 - insert an intro clip. Drag BOTH the zip and the intro mp4 together.
rem ASCII only, and no parentheses inside echo: cmd.exe breaks on both.
rem Do NOT call chcp here - in a .bat it swallows redirected stdin.
rem The python side sets the console code page itself.
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

if "%~1"=="" goto NOARGS
if "%~2"=="" goto ONEARG
goto FINDPY

:NOARGS
echo.
echo   Drag TWO files onto this .bat at the same time:
echo     - the project zip
echo     - the intro video, mp4
echo   Hold Ctrl, click both, then drag them together. Order does not matter.
echo.
pause
exit /b 1

:ONEARG
echo.
echo   Only one file was dropped. This step needs BOTH:
echo     - the project zip
echo     - the intro video, mp4
echo   Hold Ctrl, click both, then drag them together.
echo.
pause
exit /b 1

:FINDPY
rem Actually run each candidate: "where python" also finds the Microsoft Store
rem stub in WindowsApps, which only prints "Python was not found".
set "PY="
py --version >nul 2>nul
if not errorlevel 1 set "PY=py"
if defined PY goto RUN
python --version >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto RUN
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%~D\python.exe" set "PY="%%~D\python.exe""
if defined PY goto RUN
goto NOPY

:NOPY
echo.
echo   [ERROR] Python not found.
echo   Install it from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" during setup.
echo.
pause
exit /b 1

:RUN
%PY% "%~dp0tools\add_intro.py" %*
echo.
pause
