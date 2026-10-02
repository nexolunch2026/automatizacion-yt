@echo off
chcp 65001 >nul
title Faceless Studio
cd /d "%~dp0"

echo.
echo   ==========================================
echo            FACELESS STUDIO
echo   ==========================================
echo.

rem La primera vez instala "uv", que descarga Python y todo lo necesario.
where uv >nul 2>nul
if errorlevel 1 (
    echo   Preparando el programa por primera vez.
    echo   Esto puede tardar unos minutos. No cierres esta ventana.
    echo.
    powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
)
set "PATH=%USERPROFILE%\.local\bin;%PATH%"

where uv >nul 2>nul
if errorlevel 1 (
    echo.
    echo   No se pudo preparar el programa. Revisa tu conexion a internet
    echo   y vuelve a hacer doble clic en Iniciar.
    pause
    exit /b 1
)

echo   Abriendo Faceless Studio en tu navegador...
uv run --no-dev python -m app

echo.
echo   Faceless Studio se ha cerrado.
pause
