"""
desktop_app.py — Ponto de entrada do Bybit Trade Bot como App Desktop
Usa pywebview para abrir uma janela nativa do Windows com a interface Flask.
Execute: python desktop_app.py
"""

import sys
import io
import os

# ─── Força UTF-8 globalmente (evita crash com emojis no Windows) ─────────────
os.environ.setdefault('PYTHONUTF8', '1')
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import threading
import time
import os
import socket
import webview

# ─── Resolve caminhos quando empacotado com PyInstaller ───────────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
    os.chdir(BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Configura o Flask (importa APÓS ajustar o diretório) ────────────────────
from web_app import app, init_exchange

HOST = '127.0.0.1'
PORT = 5000
URL  = f'http://{HOST}:{PORT}'


def wait_for_server(host: str, port: int, timeout: float = 15.0) -> bool:
    """Aguarda o servidor Flask estar aceitando conexões."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def start_flask():
    """Inicia o servidor Flask em thread daemon."""
    print("[Flask] Inicializando exchange...")
    init_exchange()
    print(f"[Flask] Servidor rodando em {URL}")
    # use_reloader=False é obrigatório em threads
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


def main():
    # 1. Inicia Flask em background
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # 2. Aguarda o servidor ficar pronto
    print("[App] Aguardando servidor Flask...")
    if not wait_for_server(HOST, PORT):
        print("[ERRO] Servidor Flask não respondeu a tempo. Verifique as dependências.")
        sys.exit(1)

    # 3. Determina caminho do ícone
    icon_path = os.path.join(BASE_DIR, 'icon.ico')
    if not os.path.exists(icon_path):
        icon_path = None

    # 4. Cria a janela desktop
    print("[App] Abrindo janela desktop...")
    window = webview.create_window(
        title        = 'Bybit Trade Bot',
        url          = URL,
        width        = 1200,
        height       = 800,
        min_size     = (900, 650),
        resizable    = True,
        text_select  = False,
        background_color = '#0d1117',
    )

    # Inicia o loop do pywebview (bloqueante — encerra ao fechar a janela)
    webview.start(
        icon=icon_path,
        # debug=True,   # Descomente para abrir DevTools na janela
    )

    print("[App] Janela fechada. Encerrando...")


if __name__ == '__main__':
    main()
