# Source Montage — serve the MCP server on a FREE public https URL (Cloudflare quick tunnel).
# Usage:  powershell -ExecutionPolicy Bypass -File serve-public.ps1
# The public MCP endpoint becomes  https://<name>.trycloudflare.com/mcp
Set-Location $PSScriptRoot
$port = 19790

$py = "backend\.venv-build\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "D:\SourceMind\Sourcebase\backend\.venv\Scripts\python.exe" }
if (-not (Test-Path $py)) { $py = "python" }

Write-Host "Starting Source Montage backend on http://127.0.0.1:$port ..." -ForegroundColor Cyan
Start-Process -FilePath $py -ArgumentList "-m","uvicorn","server:app","--app-dir","backend","--host","127.0.0.1","--port","$port" `
  -WindowStyle Hidden
Start-Sleep -Seconds 4

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
  Write-Host "cloudflared not found. Install:  winget install Cloudflare.cloudflared" -ForegroundColor Yellow
  Write-Host "Backend still running locally — MCP at http://127.0.0.1:$port/mcp" -ForegroundColor Yellow
  exit 1
}
Write-Host "Opening a free public tunnel — your MCP URL is the printed https line + /mcp :" -ForegroundColor Green
cloudflared tunnel --url "http://127.0.0.1:$port"
