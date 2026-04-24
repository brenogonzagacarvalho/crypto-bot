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

def run_reverse_martingale(exchange, symbol='BTC/USDT:USDT', leverage=100, check_interval=60):
    add_log(f"🔥 [REVERSE MARTINGALE] Iniciado em {symbol} com {leverage}x!")
    bot_state["is_running"] = True
    bot_state["status"] = f"🔥 Rev. Martingale ({leverage}x)"
    
    base_coin = symbol.split('/')[0]
    bot_state["coin_name"] = base_coin
    bot_state["coin_balance"] = 0.0 
    
    set_margin_leverage(exchange, symbol, leverage)
    
    base_trade_amount = 1.0  # Mão base de $1
    current_trade_amount = base_trade_amount
    in_position = False
    
    wins_consecutivos = 0
    meta_wins = 6
    
    try:
        while bot_state["is_running"]:
            usdt_balance = get_unified_balance(exchange, 'USDT')
            bot_state["usdt_balance"] = usdt_balance
            
            # Gerenciamento Pós-Trade
            if not in_position:
                if wins_consecutivos >= meta_wins:
                    add_log(f"🏆 META DE 100 DÓLARES ATINGIDA! ({wins_consecutivos} vitórias consecutivas)")
                    bot_state["is_running"] = False
                    break
                    
            if current_trade_amount > usdt_balance:
                current_trade_amount = usdt_balance * 0.95 # All-in seguro se não tiver saldo total
                
            if usdt_balance < 1.0:
                add_log("❌ Saldo insuficiente para operar (< $1.00). Desligando...")
                bot_state["is_running"] = False
                break

            closes = fetch_historical_data(exchange, symbol, timeframe='1m', limit=50)
            if not closes or len(closes) < 15:
                time.sleep(check_interval)
                continue
                
            current_price = closes[-1]
            rsi = calculate_rsi(closes, period=14)
            
            if rsi is None:
                continue
                
            bot_state["current_price"] = current_price
            bot_state["rsi"] = rsi
            bot_state["rsi_status"] = f"Rev. Mart. Win:{wins_consecutivos}"
                
            # Gatilhos Agressivos (RSI 30/70 para não demorar muito a entrar)
            if not in_position:
                if rsi <= 30: # Gatilho de Long
                    add_log(f"🔥 SINAL LONG! Mão: ${current_trade_amount:.2f} | Win Streak: {wins_consecutivos}")
                    try:
                        amount_to_buy = (current_trade_amount * leverage) / current_price 
                        exchange.create_market_buy_order(symbol, amount_to_buy)
                        in_position = True
                        
                        # TP de 100% ROE para garantir dobra da mão
                        tp_price = current_price * 1.01 
                        exchange.create_order(symbol, 'limit', 'sell', amount_to_buy, tp_price, params={'reduceOnly': True})
                        
                        # SL rigido de 0.5% (Preço, = 50% de perda do capital aportado)
                        sl_price = current_price * 0.995
                        exchange.create_order(symbol, 'stop', 'sell', amount_to_buy, sl_price, params={'reduceOnly': True, 'stopPrice': sl_price})
                    except Exception as e:
                        add_log(f"❌ Erro na ordem: {e}")
                        time.sleep(10)
                        
                elif rsi >= 70: # Gatilho de Short
                    add_log(f"🔥 SINAL SHORT! Mão: ${current_trade_amount:.2f} | Win Streak: {wins_consecutivos}")
                    try:
                        amount_to_sell = (current_trade_amount * leverage) / current_price
                        exchange.create_market_sell_order(symbol, amount_to_sell)
                        in_position = True
                        
                        tp_price = current_price * 0.99 
                        exchange.create_order(symbol, 'limit', 'buy', amount_to_sell, tp_price, params={'reduceOnly': True})
                        
                        sl_price = current_price * 1.005
                        exchange.create_order(symbol, 'stop', 'buy', amount_to_sell, sl_price, params={'reduceOnly': True, 'stopPrice': sl_price})
                    except Exception as e:
                        add_log(f"❌ Erro na ordem: {e}")
                        time.sleep(10)
            
            elif in_position:
                try:
                    positions = exchange.fetch_positions([symbol])
                    if not positions or float(positions[0].get('contracts', 0)) == 0:
                        in_position = False
                        add_log("Trade encerrado. Avaliando resultado...")
                        
                        new_usdt_balance = get_unified_balance(exchange, 'USDT')
                        if new_usdt_balance > usdt_balance: # Ganhou
                            wins_consecutivos += 1
                            current_trade_amount *= 2 # Juros compostos / Reverse Martingale
                            add_log(f"✅ WIN! Lucro obtido. Dobrando a mão para ${current_trade_amount:.2f}")
                        else: # Perdeu
                            wins_consecutivos = 0
                            current_trade_amount = base_trade_amount
                            add_log(f"🔴 LOSS. Resetando a mão para ${base_trade_amount:.2f}")
                            
                        bot_state["usdt_balance"] = new_usdt_balance
                except:
                    pass
                
            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)
                
    except Exception as e:
        add_log(f"Erro Crítico Rev. Martingale: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("Bot Finalizado.")
