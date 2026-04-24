import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_historical_data, calculate_ema
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance

def set_margin_leverage(exchange, symbol, leverage):
    try:
        exchange.set_leverage(leverage, symbol)
        return True
    except:
        return False

def run_trend_scalper(exchange, symbol='SOL/USDT:USDT', leverage=100, check_interval=60):
    add_log(f"🌊 [TREND SCALPER] Iniciado em {symbol} com {leverage}x!")
    bot_state["is_running"] = True
    bot_state["status"] = f"🌊 Scalper EMA ({leverage}x)"
    
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
    base_trade_amount = 2.0
    current_trade_amount = base_trade_amount
    in_position = False
    
    # Guardar a EMA rápida anterior para verificar cruzamento exato
    previous_fast_ema = None
    previous_slow_ema = None
    
    try:
        while bot_state["is_running"]:
            usdt_balance = get_unified_balance(exchange, 'USDT')
            bot_state["usdt_balance"] = usdt_balance
            
            # Auto-Shutdown
            if usdt_balance >= target_balance:
                add_log(f"🏆 META BATIDA! Saldo atingiu ${usdt_balance:.2f}!")
                bot_state["is_running"] = False
                break
                
            # Martingale Logic
            if not in_position and usdt_balance < initial_balance - 0.5: 
                current_trade_amount = base_trade_amount * 2
                add_log(f"⚠️ Loss anterior. MARTINGALE! Próxima aposta: ${current_trade_amount:.2f}")
            elif not in_position and usdt_balance >= initial_balance:
                current_trade_amount = base_trade_amount
                initial_balance = usdt_balance
                
            if current_trade_amount > usdt_balance:
                current_trade_amount = usdt_balance * 0.95

            # Dados (precisamos de limites maiores para EMA 21)
            closes = fetch_historical_data(exchange, symbol, timeframe='1m', limit=60)
            if not closes or len(closes) < 30:
                time.sleep(check_interval)
                continue
                
            current_price = closes[-1]
            fast_ema = calculate_ema(closes, period=9)
            slow_ema = calculate_ema(closes, period=21)
            
            if fast_ema is None or slow_ema is None:
                time.sleep(check_interval)
                continue
                
            bot_state["current_price"] = current_price
            bot_state["rsi"] = fast_ema # Reutilizando campo do RSI para mostrar a EMA rápida na UI
            
            # Define o status da tendência
            trend_status = "Tendência de ALTA 📈" if fast_ema > slow_ema else "Tendência de QUEDA 📉"
            bot_state["rsi_status"] = trend_status
                
            add_log(f"Preço: ${current_price:.4f} | EMA9: {fast_ema:.4f} | EMA21: {slow_ema:.4f}")
            
            if not in_position and usdt_balance >= 2.0:
                # Se tínhamos as emas anteriores, podemos checar o cruzamento (Crossover)
                if previous_fast_ema is not None and previous_slow_ema is not None:
                    # Cruzou pra cima (Golden Cross de curtíssimo prazo)
                    if previous_fast_ema <= previous_slow_ema and fast_ema > slow_ema:
                        add_log(f"🌊 CRUZAMENTO DE ALTA! Entrando em LONG com ${current_trade_amount:.2f}")
                        try:
                            amount_to_buy = (current_trade_amount * leverage) / current_price 
                            exchange.create_market_buy_order(symbol, amount_to_buy)
                            in_position = True
                            
                            tp_price = current_price * 1.01 
                            exchange.create_order(symbol, 'limit', 'sell', amount_to_buy, tp_price, params={'reduceOnly': True})
                            
                            sl_price = current_price * 0.99
                            exchange.create_order(symbol, 'stop', 'sell', amount_to_buy, sl_price, params={'reduceOnly': True, 'stopPrice': sl_price})
                        except Exception as e:
                            add_log(f"❌ Erro Scalper LONG: {e}")
                            
                    # Cruzou pra baixo (Death Cross)
                    elif previous_fast_ema >= previous_slow_ema and fast_ema < slow_ema:
                        add_log(f"🌊 CRUZAMENTO DE QUEDA! Entrando em SHORT com ${current_trade_amount:.2f}")
                        try:
                            amount_to_sell = (current_trade_amount * leverage) / current_price
                            exchange.create_market_sell_order(symbol, amount_to_sell)
                            in_position = True
                            
                            tp_price = current_price * 0.99 
                            exchange.create_order(symbol, 'limit', 'buy', amount_to_sell, tp_price, params={'reduceOnly': True})
                            
                            sl_price = current_price * 1.01
                            exchange.create_order(symbol, 'stop', 'buy', amount_to_sell, sl_price, params={'reduceOnly': True, 'stopPrice': sl_price})
                        except Exception as e:
                            add_log(f"❌ Erro Scalper SHORT: {e}")
            
            elif in_position:
                add_log("Surfando a onda (Aguardando TP ou SL).")
                try:
                    positions = exchange.fetch_positions([symbol])
                    if not positions or float(positions[0].get('contracts', 0)) == 0:
                        in_position = False
                        add_log("Onda finalizada. Recalculando...")
                except:
                    pass
            
            # Atualiza histórico para o próximo ciclo
            previous_fast_ema = fast_ema
            previous_slow_ema = slow_ema
                
            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)
                
    except Exception as e:
        add_log(f"Erro Crítico Trend Scalper: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("Bot Finalizado.")
