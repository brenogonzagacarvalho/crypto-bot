# iniciar_bot.ps1 — Execute no terminal do VS Code (PowerShell)
$env:PYTHONUTF8 = "1"
Write-Host "Iniciando Bybit Quant Trade Bot..." -ForegroundColor Cyan
python "$PSScriptRoot\desktop_app.py"
