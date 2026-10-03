# Instala (o repara) Faceless Studio en UN SOLO SITIO y ordena las copias viejas.
#
# Uso (Windows + R, pegar y Enter):
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/nexolunch2026/automatizacion-yt/claude/hola-5p4ttp/scripts/instalar.ps1 | iex"
#
# Lo que hace (no borra nada):
#   1. Pone el programa en C:\Users\<tu>\FacelessStudio\programa, al lado de tus datos.
#   2. Si tus datos seguian dentro de una copia vieja, los copia a FacelessStudio\datos.
#   3. MUEVE las copias viejas del programa y los .zip descargados a
#      FacelessStudio\copias_viejas (no se borran: puedes recuperarlas).
#   4. Crea en el escritorio: "Faceless Studio", "JARVIS" y "Actualizar Faceless Studio".
#   5. Si JARVIS se encendia solo al prender el ordenador, lo apunta a la copia nueva.
#
# Todo el texto va sin tildes a proposito: la consola de Windows a veces las muestra mal.

$ErrorActionPreference = "Stop"

$FsRepo = "nexolunch2026/automatizacion-yt"
$FsBranch = "claude/hola-5p4ttp"
$FsZipUrl = "https://github.com/$FsRepo/archive/refs/heads/$FsBranch.zip"
# Lo que nunca se toca dentro de la carpeta del programa al copiar la version nueva.
$FsProtected = @(".venv", "datos", "copias_de_seguridad", "navegador_jarvis", ".git")

function Get-FsVersion([string]$Folder) {
    $config = Join-Path (Join-Path $Folder "app") "config.py"
    if (-not (Test-Path -LiteralPath $config)) { return $null }
    $match = Select-String -LiteralPath $config -Pattern 'VERSION = "([0-9.]+)"' | Select-Object -First 1
    if ($match) { return [version]$match.Matches[0].Groups[1].Value }
    return [version]"0.0"
}

function Find-FsCopies([string]$UserHome, [string]$Skip) {
    # Carpetas con Iniciar.bat y app\config.py dentro de tu usuario, sin AppData ni $Skip.
    $copies = @()
    $roots = Get-ChildItem -LiteralPath $UserHome -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne "AppData" -and $_.FullName -ne $Skip }
    foreach ($root in $roots) {
        $found = Get-ChildItem -LiteralPath $root.FullName -Recurse -Depth 6 -Force -File `
            -Filter "Iniciar.bat" -ErrorAction SilentlyContinue
        foreach ($file in $found) {
            $folder = $file.DirectoryName
            $inside = ($folder + [IO.Path]::DirectorySeparatorChar).StartsWith(
                $Skip + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
            if ($Skip -and $inside) { continue }
            $version = Get-FsVersion $folder
            if ($version) {
                $copies += [pscustomobject]@{ Folder = $folder; Version = $version }
            }
        }
    }
    return @($copies | Sort-Object Version -Descending)
}

function Find-FsZips([string]$UserHome) {
    $downloads = Join-Path $UserHome "Downloads"
    if (-not (Test-Path -LiteralPath $downloads)) { return @() }
    return @(Get-ChildItem -LiteralPath $downloads -File -Filter "automatizacion-yt*.zip" -ErrorAction SilentlyContinue)
}

function Import-FsLegacyData($Copies, [string]$DataDir) {
    # Si aun no hay datos en el sitio fijo, copia los mas recientes de una copia vieja.
    # Devuelve la carpeta de la que se copiaron, o $null.
    if (Test-Path -LiteralPath (Join-Path $DataDir "faceless.db")) { return $null }
    $best = $null
    foreach ($copy in $Copies) {
        $db = Join-Path (Join-Path $copy.Folder "datos") "faceless.db"
        if (Test-Path -LiteralPath $db) {
            $when = (Get-Item -LiteralPath $db).LastWriteTime
            if (-not $best -or $when -gt $best.When) {
                $best = [pscustomobject]@{ Folder = (Join-Path $copy.Folder "datos"); When = $when }
            }
        }
    }
    if (-not $best) { return $null }
    New-Item -ItemType Directory -Force -Path (Split-Path $DataDir -Parent) | Out-Null
    Copy-Item -LiteralPath $best.Folder -Destination $DataDir -Recurse -Force
    return $best.Folder
}

function Find-FsNewerData($Copies, [string]$DataDir) {
    # Copias viejas con una base de datos MAS NUEVA que la del sitio fijo (para avisar).
    $fixed = Join-Path $DataDir "faceless.db"
    if (-not (Test-Path -LiteralPath $fixed)) { return @() }
    $limit = (Get-Item -LiteralPath $fixed).LastWriteTime
    return @($Copies | Where-Object {
        $db = Join-Path (Join-Path $_.Folder "datos") "faceless.db"
        (Test-Path -LiteralPath $db) -and (Get-Item -LiteralPath $db).LastWriteTime -gt $limit
    })
}

function Move-FsToOld($Items, [string]$OldDir) {
    # Mueve carpetas o archivos a $OldDir sin pisar nada. Devuelve los que no se pudieron mover.
    $failed = @()
    New-Item -ItemType Directory -Force -Path $OldDir | Out-Null
    foreach ($path in $Items) {
        $name = Split-Path $path -Leaf
        $dest = Join-Path $OldDir $name
        $n = 2
        while (Test-Path -LiteralPath $dest) { $dest = Join-Path $OldDir "$name ($n)"; $n++ }
        try {
            Move-Item -LiteralPath $path -Destination $dest -ErrorAction Stop
        } catch {
            $failed += $path
        }
    }
    return $failed
}

function Sync-FsFolder([string]$Source, [string]$Target) {
    # Copia la version nueva encima de la instalada, sin tocar .venv ni datos.
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    $robocopy = Get-Command robocopy -ErrorAction SilentlyContinue
    if ($robocopy) {
        $robocopyArgs = @($Source, $Target, "/MIR", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/XD") + $FsProtected
        & robocopy @robocopyArgs | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "No se pudo copiar el programa (robocopy $LASTEXITCODE)." }
        $global:LASTEXITCODE = 0
    } else {
        Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $Target -Recurse -Force
        }
    }
}

function Install-FsProgram([string]$ZipSource, [string]$Target) {
    # $ZipSource: la direccion del .zip en GitHub o la ruta de un .zip ya descargado.
    $temp = Join-Path ([IO.Path]::GetTempPath()) ("faceless-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $temp | Out-Null
    try {
        $zip = Join-Path $temp "programa.zip"
        if (Test-Path -LiteralPath $ZipSource) {
            Copy-Item -LiteralPath $ZipSource -Destination $zip
        } else {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $ZipSource -OutFile $zip -UseBasicParsing
        }
        Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $temp "x") -Force
        $root = Get-ChildItem -LiteralPath (Join-Path $temp "x") -Recurse -Filter "Iniciar.bat" -File |
            Select-Object -First 1
        if (-not $root) { throw "El archivo descargado no contiene el programa." }
        Sync-FsFolder $root.DirectoryName $Target
    } finally {
        Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
    return Get-FsVersion $Target
}

function Repair-FsStartup([string]$StartupDir, [string]$ProgramDir) {
    # "JARVIS al encender" guarda la ruta de la carpeta: si existe, la apunta a la nueva.
    $file = Join-Path $StartupDir "JARVIS Faceless Studio.bat"
    if (-not (Test-Path -LiteralPath $file)) { return $false }
    $jarvis = Join-Path $ProgramDir "JARVIS.bat"
    Set-Content -LiteralPath $file -Encoding ASCII -Value @("@echo off", "start `"`" /min `"$jarvis`"")
    return $true
}

function New-FsShortcuts([string]$Desktop, [string]$ProgramDir) {
    $shell = New-Object -ComObject WScript.Shell
    $links = @(
        @("Faceless Studio", "Iniciar.bat"),
        @("JARVIS", "JARVIS.bat"),
        @("Actualizar Faceless Studio", "Actualizar.bat")
    )
    foreach ($item in $links) {
        $link = $shell.CreateShortcut((Join-Path $Desktop ($item[0] + ".lnk")))
        $link.TargetPath = Join-Path $ProgramDir $item[1]
        $link.WorkingDirectory = $ProgramDir
        $link.Save()
    }
}

function Invoke-FsInstall {
    $userHome = $env:USERPROFILE
    $base = Join-Path $userHome "FacelessStudio"
    $programDir = Join-Path $base "programa"
    $dataDir = Join-Path $base "datos"
    $oldDir = Join-Path $base "copias_viejas"

    Write-Host ""
    Write-Host "  ================================================"
    Write-Host "     FACELESS STUDIO: INSTALAR Y ORDENAR CARPETAS"
    Write-Host "  ================================================"
    Write-Host ""
    Write-Host "  IMPORTANTE: cierra antes la ventana negra de Faceless Studio si esta abierta."
    Write-Host "  Buscando copias del programa (1 o 2 minutos)..."
    Write-Host ""

    $copies = Find-FsCopies $userHome $base
    $zips = Find-FsZips $userHome
    if ($copies) {
        Write-Host "  Copias del programa encontradas:"
        foreach ($c in $copies) { Write-Host ("    version {0,-8} {1}" -f $c.Version, $c.Folder) }
    } else {
        Write-Host "  No hay copias viejas del programa."
    }
    if ($zips) { Write-Host ("  Archivos .zip descargados: {0}" -f $zips.Count) }
    Write-Host ""
    Write-Host "  Voy a:"
    Write-Host "    1. Poner la version mas nueva en: $programDir"
    Write-Host "    2. Dejar tus datos en:            $dataDir"
    if ($copies -or $zips) {
        Write-Host "    3. MOVER (no borrar) las copias viejas y los .zip a: $oldDir"
    }
    Write-Host "    4. Crear en el escritorio: Faceless Studio, JARVIS y Actualizar Faceless Studio"
    Write-Host ""
    $answer = Read-Host "  Escribe S y pulsa Enter para empezar (cualquier otra cosa cancela)"
    if ($answer -notmatch "^[sS]") { Write-Host "  Cancelado. No se ha tocado nada."; return }

    $from = Import-FsLegacyData $copies $dataDir
    if ($from) { Write-Host "  Tus datos se copiaron desde: $from" }
    if (Test-Path -LiteralPath (Join-Path $dataDir "faceless.db")) {
        Write-Host "  OK: tus datos estan en $dataDir"
    }
    foreach ($c in (Find-FsNewerData $copies $dataDir)) {
        Write-Host "  OJO: $($c.Folder) tiene datos mas nuevos que los del sitio fijo."
        Write-Host "       No se pierden: la copia se guarda entera en copias_viejas. Avisa a Claude."
    }

    Write-Host "  Descargando la version mas nueva..."
    $version = Install-FsProgram $FsZipUrl $programDir
    Write-Host "  OK: version $version instalada en $programDir"

    $items = @($copies | ForEach-Object { $_.Folder }) + @($zips | ForEach-Object { $_.FullName })
    if ($items) {
        $failed = Move-FsToOld $items $oldDir
        Write-Host ("  OK: {0} copias viejas guardadas en {1}" -f ($items.Count - $failed.Count), $oldDir)
        foreach ($f in $failed) {
            Write-Host "  No pude mover (quiza esta abierta o en OneDrive): $f"
        }
    }

    New-FsShortcuts ([Environment]::GetFolderPath("Desktop")) $programDir
    Write-Host "  OK: accesos directos creados en el escritorio. Usa SIEMPRE esos."
    $startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
    if (Repair-FsStartup $startup $programDir) {
        Write-Host "  OK: JARVIS se seguira encendiendo solo al prender el ordenador."
    }

    Write-Host ""
    Write-Host "  LISTO. Abro Faceless Studio (la primera vez tarda unos minutos)."
    Start-Process -FilePath (Join-Path $programDir "Iniciar.bat") -WorkingDirectory $programDir
    Read-Host "  Pulsa Enter para cerrar esta ventana"
}

if (-not $env:FACELESS_INSTALL_TEST) { Invoke-FsInstall }
