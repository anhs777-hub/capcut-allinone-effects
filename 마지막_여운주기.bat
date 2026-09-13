@echo off
rem Step 4 - hold the last scene so the picture outlives the voice.
rem ASCII only, and no parentheses inside echo: cmd.exe breaks on both.
rem Do NOT call chcp here - in a .bat it swallows redirected stdin.
rem The python side sets the console code page itself.
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

if "%~1"=="" goto NOARGS
goto FINDPY

:NOARGS
echo.
echo   Drag a project zip onto this .bat file.
echo   Usually the file made in step 3, ending with _intro.
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
%PY% "%~dp0tools\hold_last.py" %*
echo.
pause
