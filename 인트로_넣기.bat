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
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py"
if not defined PY goto TRYPYTHON
goto RUN

:TRYPYTHON
where python >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY goto NOPY
goto RUN

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
