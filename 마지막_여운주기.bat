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
%PY% "%~dp0tools\hold_last.py" %*
echo.
pause
