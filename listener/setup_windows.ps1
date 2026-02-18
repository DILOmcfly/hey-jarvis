# Hey Jarvis V2 — Windows Setup Script
# Run this ONCE to set up the listener on Windows

Write-Host "=== Hey Jarvis V2 Setup ===" -ForegroundColor Cyan

# Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "ERROR: Python not found. Install Python 3.12+ from python.org" -ForegroundColor Red
    exit 1
}
Write-Host "Python: $($python.Source)"

# Create venv
if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv venv
}

# Activate and install
Write-Host "Installing dependencies..."
& venv\Scripts\pip.exe install --upgrade pip
& venv\Scripts\pip.exe install -r requirements.txt

# Create audio output directory
$audioDir = "$env:USERPROFILE\oye-ikigai-audio"
if (-not (Test-Path $audioDir)) {
    New-Item -ItemType Directory -Path $audioDir | Out-Null
    Write-Host "Created audio directory: $audioDir"
}

# Create logs directory
if (-not (Test-Path "logs")) {
    New-Item -ItemType Directory -Path "logs" | Out-Null
}

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Green
Write-Host "To start manually: .\start_jarvis.bat"
Write-Host "To auto-start: Copy start_silent.vbs to Windows Startup folder"
Write-Host "Startup folder: shell:startup"
