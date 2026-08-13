# Build AST Email Templates (Desktop)
$PROJECT_DIR = $PSScriptRoot

Write-Host "=========================================="
Write-Host "   Build AST Email Templates (Desktop)"
Write-Host "=========================================="
Write-Host ""

# Step 0: Install frontend dependencies if needed
Write-Host "[0/4] Checking frontend dependencies..."
Set-Location "$PROJECT_DIR\frontend"
if (-not (Test-Path "node_modules")) {
    Write-Host "Installing frontend dependencies..."
    & npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to install frontend dependencies" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# Step 1: Build frontend
Write-Host "[1/4] Building frontend..."
Set-Location "$PROJECT_DIR\frontend"
& npm run build
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to build frontend" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Step 2: Install Electron dependencies
Write-Host "[2/4] Installing Electron dependencies..."
Set-Location "$PROJECT_DIR\electron"
if (-not (Test-Path "node_modules")) {
    & npm install
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install Electron dependencies" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Step 3: Build Electron app
Write-Host "[3/4] Building Electron app..."
& npm run build:win
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to build Electron app" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Step 4: Done
Write-Host "[4/4] Done!"
Write-Host ""
Write-Host "Installer location:"
Write-Host "  $PROJECT_DIR\dist-electron"
Write-Host ""
Read-Host "Press Enter to exit"
