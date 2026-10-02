@echo off
rem Todo va entre parentesis: Windows lee el bloque entero antes de ejecutarlo,
rem asi que este archivo se puede sobrescribir durante la actualizacion.
(
    chcp 65001 >nul
    title Faceless Studio - Actualizar
    cd /d "%~dp0"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    where uv >nul 2>nul || (
        echo.
        echo   Primero abre el programa una vez con Iniciar.
        echo.
        pause
        exit /b 1
    )
    uv run --no-dev python -m app.updater
    pause
    exit /b
)
