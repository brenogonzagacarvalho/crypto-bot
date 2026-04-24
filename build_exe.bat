@echo off
echo ============================================
echo   Bybit Trade Bot — Gerando .exe standalone
echo ============================================
echo.

:: Limpa builds anteriores
if exist "dist\BybitBot" rmdir /s /q "dist\BybitBot"
if exist "build"         rmdir /s /q "build"

:: Gera o executável
pyinstaller ^
  --name "BybitBot" ^
  --icon "icon.ico" ^
  --windowed ^
  --onedir ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --add-data "core;core" ^
  --add-data "strategies;strategies" ^
  --add-data ".env;." ^
  --add-data "icon.ico;." ^
  --hidden-import "engineio.async_drivers.threading" ^
  --hidden-import "ccxt" ^
  --hidden-import "flask" ^
  --hidden-import "webview" ^
  desktop_app.py

echo.
if exist "dist\BybitBot\BybitBot.exe" (
    echo [OK] Build concluido! Executavel em: dist\BybitBot\BybitBot.exe
) else (
    echo [ERRO] Build falhou. Verifique os erros acima.
)
echo.
pause
