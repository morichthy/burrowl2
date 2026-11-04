@echo off
rem burrowl launcher: uses the bundled standalone Python, independent of the system environment.
setlocal
set "BURROWL_LAUNCHER=%~f0"
set "BURROWL_HOME=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
"%~dp0python\python.exe" -m burrowl.interfaces.cli %*
exit /b %ERRORLEVEL%
