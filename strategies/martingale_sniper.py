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

def run_martingale_sniper(exchange, symbol='SOL/USDT:USDT', leverage=100, check_interval=60):
    add_log(f"🎲 [MARTINGALE SNIPER] Iniciado em {symbol}!")
    bot_state["is_running"] = True
    bot_state["status"] = f"🎲 Martingale ({leverage}x)"
    
    base_coin = symbol.split('/')[0]
    bot_state["coin_name"] = base_coin
    bot_state["coin_balance"] = 0.0 
    
    # Lógica de Meta (23%)
    initial_balance = get_unified_balance(exchange, 'USDT')
    bot_state["usdt_balance"] = initial_balance
    target_balance = initial_balance * 1.23
    
    add_log(f"Saldo Inicial: ${initial_balance:.2f} | META DO DIA: ${target_balance:.2f} (+23%)")
    
    set_margin_leverage(exchange, symbol, leverage)
    
    # Sistema Martingale
    base_trade_amount = 2.0  # Começa apostando 2 dólares de margem
    current_trade_amount = base_trade_amount
    in_position = False
    
    try:
        while bot_state["is_running"]:
            usdt_balance = get_unified_balance(exchange, 'USDT')
            bot_state["usdt_balance"] = usdt_balance
            
            # Checagem de Parada Automática (Auto-Shutdown)
            if usdt_balance >= target_balance:
                add_log(f"🏆 META BATIDA! Saldo atingiu ${usdt_balance:.2f}!")
                add_log("Desligando o robô para proteger seu lucro...")
                bot_state["is_running"] = False
                break
                
            # Verifica se foi liquidado ou perdeu e precisa dobrar
            if not in_position and usdt_balance < initial_balance - 0.5: 
                # Significa que perdeu a última operação. Dobrar a mão!
                current_trade_amount = base_trade_amount * 2
                add_log(f"⚠️ Prejuízo detectado. MARTINGALE ATIVADO! Próxima entrada será de ${current_trade_amount:.2f}")
            elif not in_position and usdt_balance >= initial_balance:
                # Recuperou ou lucrou. Volta pra mão base.
                current_trade_amount = base_trade_amount
                initial_balance = usdt_balance # Atualiza o patamar seguro
                
            # Trava de Segurança
            if current_trade_amount > usdt_balance:
                current_trade_amount = usdt_balance * 0.95 # All-in se não tiver saldo suficiente pra dobrar

            closes = fetch_historical_data(exchange, symbol, timeframe='1m', limit=50)
            if not closes or len(closes) < 15:
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
            if rsi >= 80: rsi_status = "SOBRECOMPRADO 🔴"
            elif rsi <= 20: rsi_status = "SOBREVENDIDO 🟢"
            bot_state["rsi_status"] = rsi_status
                
            add_log(f"Futuros: ${current_price:.4f} | RSI: {rsi:.1f} ({rsi_status})")
            
            # Gatilhos
            if not in_position and usdt_balance >= 2.0:
                if rsi <= 20: 
                    add_log(f"🎯 GATILHO MARTINGALE: Fundo! LONG de ${current_trade_amount:.2f}")
                    try:
                        amount_to_buy = (current_trade_amount * leverage) / current_price 
                        exchange.create_market_buy_order(symbol, amount_to_buy)
                        in_position = True
                        
                        tp_price = current_price * 1.01 
                        exchange.create_order(symbol, 'limit', 'sell', amount_to_buy, tp_price, params={'reduceOnly': True})
                        
                        sl_price = current_price * 0.99
                        exchange.create_order(symbol, 'stop', 'sell', amount_to_buy, sl_price, params={'reduceOnly': True, 'stopPrice': sl_price})
                        add_log(f"✅ Ordens de Proteção: TP ${tp_price:.4f} | SL ${sl_price:.4f}")
                    except Exception as e:
                        add_log(f"❌ Erro Martingale LONG: {e}")
                        
                elif rsi >= 80:
                    add_log(f"🎯 GATILHO MARTINGALE: Topo! SHORT de ${current_trade_amount:.2f}")
                    try:
                        amount_to_sell = (current_trade_amount * leverage) / current_price
                        exchange.create_market_sell_order(symbol, amount_to_sell)
                        in_position = True
                        
                        tp_price = current_price * 0.99 
                        exchange.create_order(symbol, 'limit', 'buy', amount_to_sell, tp_price, params={'reduceOnly': True})
                        
                        sl_price = current_price * 1.01
                        exchange.create_order(symbol, 'stop', 'buy', amount_to_sell, sl_price, params={'reduceOnly': True, 'stopPrice': sl_price})
                        add_log(f"✅ Ordens de Proteção: TP ${tp_price:.4f} | SL ${sl_price:.4f}")
                    except Exception as e:
                        add_log(f"❌ Erro Martingale SHORT: {e}")
            
            elif in_position:
                add_log("Aguardando operação fechar (Take Profit ou Stop Loss).")
                # Lógica simplificada de checagem para liberar in_position
                try:
                    positions = exchange.fetch_positions([symbol])
                    if not positions or float(positions[0].get('contracts', 0)) == 0:
                        in_position = False
                        add_log("Operação encerrada pelo mercado. Recalculando...")
                except:
                    pass
                
            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)
                
    except Exception as e:
        add_log(f"Erro Crítico Martingale: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("Bot Finalizado.")
