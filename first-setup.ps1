# First Setup - AST Email Templates
$PROJECT_DIR = $PSScriptRoot

Write-Host "=========================================="
Write-Host "   First Setup - AST Email Templates"
Write-Host "=========================================="
Write-Host ""

# Step 1: Install backend dependencies
Write-Host "[1/3] Installing backend dependencies..."
Set-Location "$PROJECT_DIR\backend"
& py -3.12 -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install backend dependencies" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Step 2: Install frontend dependencies
Write-Host "[2/3] Installing frontend dependencies..."
Set-Location "$PROJECT_DIR\frontend"
& npm install
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install frontend dependencies" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Step 3: Install Electron dependencies
Write-Host "[3/3] Installing Electron dependencies..."
Set-Location "$PROJECT_DIR\electron"
& npm install
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install Electron dependencies" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "=========================================="
Write-Host "   Setup complete!"
Write-Host "=========================================="
Write-Host ""
Write-Host "Now run build-electron.ps1 to build the installer."
Write-Host ""
Read-Host "Press Enter to exit"
