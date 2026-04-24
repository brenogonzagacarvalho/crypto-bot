import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_historical_data, calculate_rsi
from core.shared_state import bot_state, add_log

def get_free_balance(exchange, coin):
    """Busca saldo na conta Unified Trading Account (UTA) da Bybit."""
    # Tenta a API V5 direta (mais confiável para UTA)
    try:
        resp = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
        coins = resp.get('result', {}).get('list', [{}])[0].get('coin', [])
        for c in coins:
            if c.get('coin') == coin:
                val = float(c.get('availableToWithdraw') or c.get('walletBalance') or 0)
                return val
    except:
        pass
    
    # Fallback padrão do ccxt
    try:
        balance = exchange.fetch_balance({'type': 'unified'})
        return float(balance.get('free', {}).get(coin, 0) or 0)
    except:
        pass
    return 0.0

def execute_market_order(exchange, symbol, side, amount):
    """Executa ordem de mercado com suporte a Bybit Unified Trading Account."""
    add_log(f"[ORDEM REAL] Enviando {side.upper()} para {amount:.8f} {symbol}...")
    try:
        # Parâmetro obrigatório para Bybit UTA no modo Spot
        uta_params = {'category': 'spot'}
        
        if side.lower() == 'sell':
            order = exchange.create_market_sell_order(symbol, amount, params=uta_params)
        elif side.lower() == 'buy':
            order = exchange.create_market_buy_order(symbol, amount, params=uta_params)
        else:
            return False
            
        add_log(f"ORDEM EXECUTADA! ID: {order.get('id', 'N/A')}")
        return True
    except Exception as e:
        add_log(f"FALHA NA ORDEM: {e}")
        return False

def run_live_predictor(exchange, symbol='BTC/USDT', check_interval=60):
    add_log(f"Iniciando Bot LIVE para {symbol}")
    bot_state["is_running"] = True
    bot_state["status"] = "🟢 Em Execução (Analisando RSI)"
    
    # Extrai o nome da moeda base (ex: 'BTC' de 'BTC/USDT')
    base_coin = symbol.split('/')[0]
    bot_state["coin_name"] = base_coin
    
    # Atualiza saldo na tela inicial
    bot_state["coin_balance"] = get_free_balance(exchange, base_coin)
    bot_state["usdt_balance"] = get_free_balance(exchange, 'USDT')
    
    in_position = bot_state["coin_balance"] > 0.00001
    add_log(f"Estado: {'COM MOEDA (Vai vender na Alta)' if in_position else 'SEM MOEDA (Vai comprar na Baixa)'}")
        
    try:
        while bot_state["is_running"]:
            closes = fetch_historical_data(exchange, symbol, timeframe='1m', limit=50)
            
            if not closes or len(closes) < 15:
                add_log("Aguardando mais dados do mercado...")
                time.sleep(check_interval)
                continue
                
            current_price = closes[-1]
            rsi = calculate_rsi(closes, period=14)
            
            if rsi is None:
                time.sleep(check_interval)
                continue
                
            # Atualiza o Frontend
            bot_state["current_price"] = current_price
            bot_state["rsi"] = rsi
            
            rsi_status = "Neutro"
            if rsi >= 70:
                rsi_status = "SOBRECOMPRADO 🔴"
            elif rsi <= 30:
                rsi_status = "SOBREVENDIDO 🟢"
            bot_state["rsi_status"] = rsi_status
                
            add_log(f"Preço: ${current_price:.2f} | RSI: {rsi:.1f} ({rsi_status})")
            
            # LÓGICA DE VENDA
            if rsi >= 70 and in_position:
                add_log(">>> PREVISÃO: Mercado pode cair! Vendendo tudo...")
                coin_to_sell = get_free_balance(exchange, base_coin)
                if coin_to_sell > 0:
                    if execute_market_order(exchange, symbol, 'sell', coin_to_sell):
                        in_position = False
                        bot_state["coin_balance"] = get_free_balance(exchange, base_coin)
                        bot_state["usdt_balance"] = get_free_balance(exchange, 'USDT')
                        
            # LÓGICA DE COMPRA
            elif rsi <= 30 and not in_position:
                add_log(">>> PREVISÃO: Fundo detectado! Comprando moeda...")
                usdt_to_spend = get_free_balance(exchange, 'USDT')
                safe_usdt = usdt_to_spend * 0.99 
                amount_coin_to_buy = safe_usdt / current_price
                
                if amount_coin_to_buy > 0:
                    if execute_market_order(exchange, symbol, 'buy', amount_coin_to_buy):
                        in_position = True
                        bot_state["coin_balance"] = get_free_balance(exchange, base_coin)
                        bot_state["usdt_balance"] = get_free_balance(exchange, 'USDT')
                        
            # Sleep com check iterativo para conseguir parar mais rápido pelo botão do dashboard
            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)
                
    except Exception as e:
        add_log(f"Erro Crítico: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("Bot Finalizado.")
