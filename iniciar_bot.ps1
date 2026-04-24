# iniciar_bot.ps1 — Execute no terminal do VS Code (PowerShell)
$env:PYTHONUTF8 = "1"
Write-Host "Iniciando Bybit Trade Bot..." -ForegroundColor Cyan
& "C:\Users\Carvalho\AppData\Local\Programs\Python\Python311\python.exe" "$PSScriptRoot\desktop_app.py"
