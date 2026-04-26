import os
import threading
from flask import Flask, render_template, jsonify, request
from core.connection import get_exchange, check_connection
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance
from strategies.live_predictor import run_live_predictor
from strategies.sniper_leverage import run_sniper_leverage
from strategies.martingale_sniper import run_martingale_sniper
from strategies.trend_scalper import run_trend_scalper
from strategies.reverse_martingale import run_reverse_martingale
from strategies.reverse_martingale_pro import run_reverse_martingale_pro
from strategies.scalping_10x import run_scalping_10x
from strategies.survival_scalper import run_survival_scalper
import time

app = Flask(__name__)

# Instância global da exchange
exchange = None

def init_exchange():
    """Inicializa a exchange e lê o saldo inicial."""
    global exchange
    exchange = get_exchange()
    if check_connection(exchange):
        # Lê o saldo real logo que o servidor inicia
        try:
            # Usa V5 direto para pegar todos os saldos da UTA
            resp = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
            coins = resp.get('result', {}).get('list', [{}])[0].get('coin', [])
            for c in coins:
                if c.get('coin') == 'USDT':
                    bot_state["usdt_balance"] = float(c.get('walletBalance') or 0)
                if c.get('coin') == 'BTC':
                    bot_state["coin_balance"] = float(c.get('walletBalance') or 0)
                    bot_state["coin_name"] = "BTC"
            print(f"[OK] Saldo carregado: BTC={bot_state['coin_balance']:.8f} | USDT={bot_state['usdt_balance']:.4f}")
        except Exception as e:
            print(f"[AVISO] Não foi possível carregar saldo inicial: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def status():
    return jsonify(bot_state)

@app.route('/api/balance')
def refresh_balance():
    """Rota para ler o saldo atual da Bybit a qualquer momento."""
    global exchange
    if not exchange:
        exchange = get_exchange()
    try:
        resp = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
        coins = resp.get('result', {}).get('list', [{}])[0].get('coin', [])
        result = {}
        for c in coins:
            if float(c.get('walletBalance') or 0) > 0:
                result[c['coin']] = float(c.get('walletBalance') or 0)
                # Atualiza o shared_state também
                if c['coin'] == 'USDT':
                    bot_state["usdt_balance"] = result[c['coin']]
                if c['coin'] == 'BTC':
                    bot_state["coin_balance"] = result[c['coin']]
                    bot_state["coin_name"] = "BTC"
        return jsonify({"balances": result, "status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/positions')
def get_positions():
    """Busca todas as posições abertas na Bybit."""
    global exchange
    if not exchange:
        exchange = get_exchange()
    try:
        # Busca posições linear (USDT Perpetuals)
        positions = exchange.fetch_positions(params={'category': 'linear', 'settleCoin': 'USDT'})
        open_positions = []
        for p in positions:
            if float(p.get('contracts', 0) or 0) > 0:
                open_positions.append({
                    "symbol": p['symbol'],
                    "side": p['side'],
                    "contracts": p['contracts'],
                    "entryPrice": p['entryPrice'],
                    "unrealizedPnl": p['unrealizedPnl'],
                    "leverage": p['leverage']
                })
        return jsonify({"positions": open_positions, "status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/close_all', methods=['POST'])
def close_all():
    """Fecha todas as posições abertas imediatamente."""
    global exchange
    if not exchange:
        exchange = get_exchange()
    try:
        positions = exchange.fetch_positions(params={'category': 'linear', 'settleCoin': 'USDT'})
        closed = 0
        for p in positions:
            contracts = float(p.get('contracts', 0) or 0)
            if contracts > 0:
                close_side = 'sell' if p['side'].lower() == 'long' else 'buy'
                exchange.create_order(
                    symbol=p['symbol'],
                    type='market',
                    side=close_side,
                    amount=contracts,
                    params={'reduceOnly': True}
                )
                add_log(f"MANUAL: Posição {p['symbol']} fechada via Dashboard.")
                closed += 1
        return jsonify({"message": f"{closed} posições fechadas com sucesso.", "status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/start', methods=['POST'])
def start_bot():
    global exchange
    
    if bot_state["is_running"]:
        return jsonify({"message": "Bot já está rodando!"}), 400
        
    if not exchange:
        exchange = get_exchange()
        if not check_connection(exchange):
            add_log("Falha ao conectar na Bybit. Verifique as credenciais.")
            return jsonify({"message": "Erro de conexão"}), 500
            
    bot_state["logs"] = [] # Limpa logs antigos
    
    data = request.get_json() or {}
    strategy = data.get('strategy', 'spot')
    symbol = data.get('symbol', 'BTC/USDT:USDT')
    
    estrategias_multi = ['survival', 'reverse_martingale', 'scalping_10x', 'sniper']
    if symbol == 'MULTI' and strategy not in estrategias_multi:
        add_log(f"⚠️ A estratégia '{strategy}' não suporta MULTI. Usando BTC por padrão.")
        symbol = 'BTC/USDT:USDT'
    
    if strategy == 'sniper':
        add_log(f"Comando de INICIAR SNIPER recebido para {symbol}...")
        thread = threading.Thread(target=run_sniper_leverage, args=(exchange, symbol))
    elif strategy == 'martingale':
        add_log(f"Comando de INICIAR MARTINGALE recebido para {symbol}...")
        thread = threading.Thread(target=run_martingale_sniper, args=(exchange, symbol))
    elif strategy == 'trend':
        add_log(f"Comando de INICIAR TREND SCALPER recebido para {symbol}...")
        thread = threading.Thread(target=run_trend_scalper, args=(exchange, symbol))
    elif strategy == 'reverse_martingale':
        add_log(f"Comando de INICIAR REVERSE MARTINGALE PRO recebido para {symbol}...")
        thread = threading.Thread(target=run_reverse_martingale_pro, args=(exchange, symbol))
    elif strategy == 'scalping_10x':
        add_log(f"Comando de INICIAR SCALPING 10X recebido para {symbol}...")
        thread = threading.Thread(target=run_scalping_10x, args=(exchange, symbol))
    elif strategy == 'survival':
        add_log(f"Comando de INICIAR SURVIVAL SCALPER recebido para {symbol}...")
        thread = threading.Thread(target=run_survival_scalper, args=(exchange, symbol))
    else:
        add_log(f"Comando de INICIAR SPOT recebido para {symbol}...")
        thread = threading.Thread(target=run_live_predictor, args=(exchange, symbol))
        
    thread.daemon = True
    thread.start()
    
    return jsonify({"message": "Bot iniciado com sucesso"})

@app.route('/api/stop', methods=['POST'])
def stop_bot():
    if not bot_state["is_running"]:
        return jsonify({"message": "Bot já está parado."}), 400
        
    add_log("Comando de PARAR recebido. Aguardando ciclo terminar...")
    bot_state["is_running"] = False
    
    return jsonify({"message": "Bot está sendo desligado..."})

if __name__ == '__main__':
    print("Iniciando Servidor Web do Bot...")
    print("Conectando na Bybit e carregando saldo...")
    init_exchange()
    print("Acesse http://127.0.0.1:5000 no seu navegador!")
    app.run(host='127.0.0.1', port=5000, debug=False)
