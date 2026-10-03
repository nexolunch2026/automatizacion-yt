# Busca las copias de Faceless Studio y tus datos en este ordenador, abre la buena y
# crea un acceso directo en el escritorio. No borra ni mueve nada.
# Uso (Windows + R, pegar y Enter):
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/nexolunch2026/automatizacion-yt/claude/hola-5p4ttp/scripts/buscar_datos.ps1 | iex"

$ErrorActionPreference = "SilentlyContinue"
$userHome = $env:USERPROFILE
Write-Host ""
Write-Host "  ============================================"
Write-Host "     BUSCANDO TUS DATOS DE FACELESS STUDIO"
Write-Host "  ============================================"
Write-Host "  Esto puede tardar 1 o 2 minutos. No cierres esta ventana."
Write-Host ""

# Se busca en tu carpeta de usuario (incluye Escritorio, Descargas y OneDrive), sin AppData.
$roots = Get-ChildItem -Path $userHome -Directory -Force | Where-Object { $_.Name -ne "AppData" }
$found = foreach ($root in $roots) {
    Get-ChildItem -Path $root.FullName -Recurse -Force -Include "Iniciar.bat", "faceless.db" -File
}

# Copias del programa: carpetas con Iniciar.bat y app\config.py
$programs = @()
foreach ($file in $found | Where-Object { $_.Name -eq "Iniciar.bat" }) {
    $config = Join-Path $file.DirectoryName "app\config.py"
    if (Test-Path $config) {
        $match = Select-String -Path $config -Pattern 'VERSION = "([0-9.]+)"'
        $text = if ($match) { $match.Matches[0].Groups[1].Value } else { "0.0" }
        $programs += [pscustomobject]@{ Folder = $file.DirectoryName; Version = [version]$text }
    }
}
$programs = $programs | Sort-Object Version -Descending

# Bases de datos (tus cuentas y proyectos)
$databases = $found | Where-Object { $_.Name -eq "faceless.db" } | Sort-Object LastWriteTime -Descending

Write-Host "  COPIAS DEL PROGRAMA ENCONTRADAS:"
if (-not $programs) { Write-Host "    (ninguna)" }
foreach ($p in $programs) { Write-Host ("    version {0,-8} -> {1}" -f $p.Version, $p.Folder) }
Write-Host ""
Write-Host "  TUS DATOS (archivo faceless.db):"
if (-not $databases) { Write-Host "    (ninguno)" }
foreach ($d in $databases) {
    Write-Host ("    {0,7} KB  {1}  -> {2}" -f [math]::Round($d.Length / 1KB), $d.LastWriteTime.ToString("dd/MM/yyyy HH:mm"), $d.DirectoryName)
}
Write-Host ""

$fixed = Join-Path $userHome "FacelessStudio\datos"
if (Test-Path (Join-Path $fixed "faceless.db")) {
    Write-Host "  OK: tus datos ya estan en su sitio fijo: $fixed"
} else {
    Write-Host "  Tus datos aun no estan en el sitio fijo ($fixed)."
    Write-Host "  Se copiaran solos la primera vez que abras la version 0.18 o mas nueva."
}
Write-Host ""

if (-not $programs) {
    Write-Host "  No encontre el programa. Descargalo de nuevo desde el enlace del README."
    Read-Host "  Pulsa Enter para cerrar"
    return
}

$best = $programs[0]
Write-Host "  EL PROGRAMA BUENO (el mas nuevo) ESTA EN:"
Write-Host "    $($best.Folder)"
Write-Host ""

# Acceso directo en el escritorio al programa bueno
$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path $desktop "Faceless Studio.lnk"))
$link.TargetPath = Join-Path $best.Folder "Iniciar.bat"
$link.WorkingDirectory = $best.Folder
$link.Save()
Write-Host "  Listo: hay un acceso directo 'Faceless Studio' en tu escritorio. Usa siempre ese."
if ($programs.Count -gt 1) {
    Write-Host "  Las otras copias del programa son viejas: cuando compruebes que todo esta bien,"
    Write-Host "  puedes borrarlas (tus datos no estan dentro de ellas desde la version 0.18)."
}
Write-Host ""

Start-Process explorer.exe $best.Folder
$answer = Read-Host "  Quieres ACTUALIZAR y abrir el programa bueno ahora? Escribe S y pulsa Enter"
if ($answer -match "^[sS]") {
    $update = Join-Path $best.Folder "Actualizar.bat"
    if (Test-Path $update) {
        Start-Process -FilePath $update -WorkingDirectory $best.Folder -Wait
    }
    Start-Process -FilePath (Join-Path $best.Folder "Iniciar.bat") -WorkingDirectory $best.Folder
}
