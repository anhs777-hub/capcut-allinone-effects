@echo off
rem Build CapCut All-in-One. ASCII only: cmd.exe mangles multibyte in .bat files.
cd /d "%~dp0"

py -3.13 build.py
if errorlevel 1 goto FALLBACK
goto END

:FALLBACK
echo [WARN] Python 3.13 not found via the py launcher, trying default python...
python build.py

:END
pause
