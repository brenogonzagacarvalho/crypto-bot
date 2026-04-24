import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_historical_data, calculate_rsi
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance

def set_margin_leverage(exchange, symbol, leverage):
    try:
        exchange.set_leverage(leverage, symbol)
        return True
    except:
        return False

def run_scalping_10x(exchange, symbol='BTC/USDT:USDT', leverage=10, check_interval=60):
    add_log(f"🛡️ [SCALPING 10x] Iniciado em {symbol}!")
    bot_state["is_running"] = True
    bot_state["status"] = f"🛡️ Scalping ({leverage}x)"
    
    base_coin = symbol.split('/')[0]
    bot_state["coin_name"] = base_coin
    
    set_margin_leverage(exchange, symbol, leverage)
    
    # Risco Máximo: 1 a 2 dólares (usaremos 1.5)
    trade_amount = 1.5 
    in_position = False
    
    try:
        while bot_state["is_running"]:
            usdt_balance = get_unified_balance(exchange, 'USDT')
            bot_state["usdt_balance"] = usdt_balance
            
            if usdt_balance >= 20.0:
                add_log(f"🏆 META SEMANAL BATIDA! Saldo de ${usdt_balance:.2f} alcançado.")
                bot_state["is_running"] = False
                break
                
            if usdt_balance < 1.0:
                add_log("❌ Saldo abaixo do mínimo de operação. Desligando...")
                bot_state["is_running"] = False
                break

            closes = fetch_historical_data(exchange, symbol, timeframe='1m', limit=50)
            if not closes or len(closes) < 15:
                time.sleep(check_interval)
                continue
                
            current_price = closes[-1]
            rsi = calculate_rsi(closes, period=14)
            
            if rsi is None: continue
            
            bot_state["current_price"] = current_price
            bot_state["rsi"] = rsi
            
            if not in_position:
                # Entradas com RSI um pouco mais seguro
                if rsi <= 25: 
                    add_log(f"🛡️ SINAL LONG! Entrando com ${trade_amount:.2f}")
                    try:
                        amount_to_buy = (trade_amount * leverage) / current_price 
                        exchange.create_market_buy_order(symbol, amount_to_buy)
                        in_position = True
                        
                        # Alvos: 2-3% ROE por operação (com 10x leverage = 0.2 a 0.3% no preço, usaremos 0.25%)
                        tp_price = current_price * 1.0025 
                        exchange.create_order(symbol, 'limit', 'sell', amount_to_buy, tp_price, params={'reduceOnly': True})
                        
                        # Stop loss rigoroso de 1% no preço = 10% ROE
                        sl_price = current_price * 0.99
                        exchange.create_order(symbol, 'stop', 'sell', amount_to_buy, sl_price, params={'reduceOnly': True, 'stopPrice': sl_price})
                    except Exception as e:
                        add_log(f"❌ Erro Scalper: {e}")
                        time.sleep(10)
                        
                elif rsi >= 75: 
                    add_log(f"🛡️ SINAL SHORT! Entrando com ${trade_amount:.2f}")
                    try:
                        amount_to_sell = (trade_amount * leverage) / current_price
                        exchange.create_market_sell_order(symbol, amount_to_sell)
                        in_position = True
                        
                        tp_price = current_price * 0.9975 
                        exchange.create_order(symbol, 'limit', 'buy', amount_to_sell, tp_price, params={'reduceOnly': True})
                        
                        sl_price = current_price * 1.01
                        exchange.create_order(symbol, 'stop', 'buy', amount_to_sell, sl_price, params={'reduceOnly': True, 'stopPrice': sl_price})
                    except Exception as e:
                        add_log(f"❌ Erro Scalper: {e}")
                        time.sleep(10)
            
            elif in_position:
                try:
                    positions = exchange.fetch_positions([symbol])
                    if not positions or float(positions[0].get('contracts', 0)) == 0:
                        in_position = False
                        add_log("Trade encerrado. Aguardando próxima oportunidade...")
                except:
                    pass
                
            for _ in range(check_interval):
                if not bot_state["is_running"]: break
                time.sleep(1)
                
    except Exception as e:
        add_log(f"Erro Crítico Scalper 10x: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
