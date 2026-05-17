# MeshCompute Bot Builder (Windows)
# Ausfuehren mit: powershell -ExecutionPolicy Bypass -File setup_bot_windows.ps1

$ErrorActionPreference = "Stop"

function Write-Green($msg)  { Write-Host $msg -ForegroundColor Green }
function Write-Red($msg)    { Write-Host $msg -ForegroundColor Red }
function Write-Yellow($msg) { Write-Host $msg -ForegroundColor Yellow }

Write-Green "MeshCompute Bot Builder (Windows)"

# Python pruefen
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Red "Fehler: Python wurde nicht gefunden. Bitte installiere Python 3 von https://python.org"
    exit 1
}

# Server-URL einlesen
$SERVER_URL = Read-Host "Server-URL (z.B. wss://mein-server.de:443/ws)"
if ([string]::IsNullOrWhiteSpace($SERVER_URL)) {
    Write-Red "Fehler: Server-URL darf nicht leer sein."
    exit 1
}

# Registration Token einlesen
$REG_TOKEN = Read-Host "Registration Token"
if ([string]::IsNullOrWhiteSpace($REG_TOKEN)) {
    Write-Red "Fehler: Registration Token darf nicht leer sein."
    exit 1
}

# Plattformwahl
Write-Host ""
Write-Host "Waehle die Zielplattform:"
Write-Host "  windows - Windows EXE"
Write-Host "  linux   - Nicht moeglich unter Windows (benutze setup_bot_linux.sh)"
Write-Host "  apk     - Nicht moeglich unter Windows"
Write-Host ""
$PLATFORM = Read-Host "Plattform (windows)"

if ($PLATFORM -ne "windows") {
    Write-Red "Nur 'windows' wird unter Windows unterstuetzt."
    exit 1
}

# Pfade bestimmen
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$REPO_DIR   = Split-Path -Parent $SCRIPT_DIR
$CLIENT_FILE = Join-Path $REPO_DIR "client\main.py"

# Repository ggf. klonen
if (-not (Test-Path $CLIENT_FILE)) {
    Write-Yellow "Repository nicht gefunden, klone einmalig..."
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Red "Fehler: git wurde nicht gefunden. Bitte installiere Git von https://git-scm.com"
        exit 1
    }
    git clone https://github.com/Kiwilus/meshcompute.git $REPO_DIR
    if ($LASTEXITCODE -ne 0) {
        Write-Red "Fehler: Klonen fehlgeschlagen."
        exit 1
    }
}

Set-Location $REPO_DIR

# Abhaengigkeiten installieren
Write-Host "Installiere Abhaengigkeiten..."
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Red "Fehler: pip install fehlgeschlagen."
    exit 1
}

# Build-Verzeichnis vorbereiten
$BUILD_DIR = Join-Path $env:USERPROFILE "meshcompute-build"
if (Test-Path $BUILD_DIR) {
    Remove-Item -Recurse -Force $BUILD_DIR
}
New-Item -ItemType Directory -Path $BUILD_DIR | Out-Null

Copy-Item $CLIENT_FILE (Join-Path $BUILD_DIR "main.py")

# build_config.py erzeugen
$configContent = @"
SERVER_URL = "$SERVER_URL"
REGISTRATION_TOKEN = "$REG_TOKEN"
"@
Set-Content -Path (Join-Path $BUILD_DIR "build_config.py") -Value $configContent -Encoding UTF8

Set-Location $BUILD_DIR

# PyInstaller pruefen/installieren
$pyiCheck = python -c "import PyInstaller" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Yellow "PyInstaller nicht gefunden, installiere..."
    python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        Write-Red "Fehler: PyInstaller-Installation fehlgeschlagen."
        exit 1
    }
}

# Windows EXE bauen
Write-Green "Baue Windows EXE..."
python -m PyInstaller --onefile --name "meshbot" `
    --add-data "build_config.py;." main.py

if ($LASTEXITCODE -ne 0) {
    Write-Red "Fehler: PyInstaller-Build fehlgeschlagen."
    exit 1
}

$EXE_PATH = Join-Path $BUILD_DIR "dist\meshbot.exe"
if (Test-Path $EXE_PATH) {
    Write-Green "Windows EXE erfolgreich erstellt: $EXE_PATH"
} else {
    Write-Red "Fehler: EXE-Datei wurde nicht gefunden."
    exit 1
}