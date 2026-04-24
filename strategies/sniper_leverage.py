import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_historical_data, calculate_rsi
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance

def set_margin_leverage(exchange, symbol, leverage):
    try:
        # Tenta setar a alavancagem
        exchange.set_leverage(leverage, symbol)
        add_log(f"Alavancagem setada para {leverage}x em {symbol}!")
        return True
    except Exception as e:
        # Se já estiver setado, a Bybit costuma retornar um erro que pode ser ignorado
        add_log(f"Aviso ao definir alavancagem: Pode já estar definida ou a API não tem permissão de Contratos.")
        return False

def run_sniper_leverage(exchange, symbol='BTC/USDT:USDT', leverage=100, check_interval=60):
    add_log(f"🎯 [SNIPER ALAVANCADO] Iniciando Mercado Futuro ({symbol}) com {leverage}x!")
    bot_state["is_running"] = True
    bot_state["status"] = f"🎯 Sniper Ativo ({leverage}x)"
    
    # Extrai a base coin
    base_coin = symbol.split('/')[0]
    bot_state["coin_name"] = base_coin
    
    # Atualiza saldo na tela inicial
    bot_state["coin_balance"] = 0.0 # Em futuros operamos apenas com saldo colateral de USDT
    usdt_balance = get_unified_balance(exchange, 'USDT')
    bot_state["usdt_balance"] = usdt_balance
    
    add_log(f"Saldo Detectado (Derivativos): ${usdt_balance:.2f} USDT")
    
    # Configura a alavancagem na Bybit
    set_margin_leverage(exchange, symbol, leverage)
    
    in_position = False
    
    try:
        while bot_state["is_running"]:
            closes = fetch_historical_data(exchange, symbol, timeframe='1m', limit=50)
            
            if not closes or len(closes) < 15:
                add_log("Aguardando dados da Bybit Futuros...")
                time.sleep(check_interval)
                continue
                
            current_price = closes[-1]
            rsi = calculate_rsi(closes, period=14)
            
            if rsi is None:
                time.sleep(check_interval)
                continue
                
            bot_state["current_price"] = current_price
            bot_state["rsi"] = rsi
            
            rsi_status = "Neutro"
            if rsi >= 80:
                rsi_status = "SOBRECOMPRADO EXTREMO 🔴"
            elif rsi <= 20:
                rsi_status = "SOBREVENDIDO EXTREMO 🟢"
            bot_state["rsi_status"] = rsi_status
                
            add_log(f"Futuros: ${current_price:.2f} | RSI: {rsi:.1f} ({rsi_status})")
            
            usdt_balance = get_unified_balance(exchange, 'USDT')
            bot_state["usdt_balance"] = usdt_balance
            
            if not in_position and usdt_balance >= 2.0: # Saldo mínimo seguro para tentar ordem alavancada
                # Regra Sniper Extrema
                if rsi <= 20: 
                    add_log("🎯 GATILHO SNIPER: Fundo extremo! LONG (Comprar) All-in 100x!")
                    try:
                        amount_to_buy = (usdt_balance * leverage * 0.95) / current_price 
                        order = exchange.create_market_buy_order(symbol, amount_to_buy)
                        add_log(f"✅ ORDEM LONG EXECUTADA!")
                        in_position = True
                        
                        # Take Profit para dobrar o capital
                        tp_price = current_price * 1.01 # 1% acima * 100x = 100% lucro
                        exchange.create_order(symbol, 'limit', 'sell', amount_to_buy, tp_price, params={'reduceOnly': True})
                        add_log(f"✅ Take Profit cravado em ${tp_price:.2f}")
                        
                    except Exception as e:
                        add_log(f"❌ Erro Sniper LONG: {e}")
                        
                elif rsi >= 80:
                    add_log("🎯 GATILHO SNIPER: Topo extremo! SHORT (Vender) All-in 100x!")
                    try:
                        amount_to_sell = (usdt_balance * leverage * 0.95) / current_price
                        order = exchange.create_market_sell_order(symbol, amount_to_sell)
                        add_log(f"✅ ORDEM SHORT EXECUTADA!")
                        in_position = True
                        
                        # Take Profit para dobrar o capital
                        tp_price = current_price * 0.99 # 1% abaixo * 100x = 100% lucro
                        exchange.create_order(symbol, 'limit', 'buy', amount_to_sell, tp_price, params={'reduceOnly': True})
                        add_log(f"✅ Take Profit cravado em ${tp_price:.2f}")
                        
                    except Exception as e:
                        add_log(f"❌ Erro Sniper SHORT: {e}")
            
            elif in_position:
                add_log("Aguardando Take Profit ou Liquidação (Operação Rolando).")
                
            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)
                
    except Exception as e:
        add_log(f"Erro Crítico Sniper: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("Bot Sniper Finalizado.")
