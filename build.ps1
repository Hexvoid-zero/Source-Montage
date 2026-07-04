# Build Source Montage into a standalone Windows app (native pywebview window).
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1
Set-Location $PSScriptRoot

Write-Host "1/2  Preparing Python build env..."
if (-not (Test-Path .venv-build)) { python -m venv .venv-build }
.\.venv-build\Scripts\python.exe -m pip install -q -r backend\requirements.txt pyinstaller

Write-Host "2/2  Packaging exe (onedir = fast startup)..."
Remove-Item -Recurse -Force build, dist, SourceMontage.spec -ErrorAction SilentlyContinue
.\.venv-build\Scripts\python.exe -m PyInstaller --noconfirm --onedir --windowed --optimize 2 --name SourceMontage `
  --exclude-module tkinter --exclude-module _tkinter `
  --add-data "static;static" --collect-submodules uvicorn `
  --collect-all webview --collect-all clr_loader --collect-all pythonnet --hidden-import clr `
  --hidden-import server `
  --paths backend backend\launcher.py

Write-Host "Done -> dist\SourceMontage\SourceMontage.exe"
