@echo off
chcp 65001 >nul
rem Hace que JARVIS se encienda solo cada vez que prendes el ordenador.
set "DEST=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\JARVIS Faceless Studio.bat"
(
  echo @echo off
  echo start "" /min "%~dp0JARVIS.bat"
) > "%DEST%"
echo.
echo   Listo. JARVIS se encendera solo cuando prendas el ordenador.
echo   Para quitarlo, borra el archivo:
echo   %DEST%
echo.
pause
