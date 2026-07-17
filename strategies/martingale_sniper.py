import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_ohlcv_data, calculate_rsi, calculate_ema, calculate_atr
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance, get_available_margin_usd

def set_margin_leverage(exchange, symbol, leverage):
    try:
        exchange.set_leverage(leverage, symbol)
        return True
    except:
        return False

def run_martingale_sniper(exchange, symbol='SOL/USDT:USDT', leverage=20, check_interval=10):
    add_log(f"🎲 [MARTINGALE SNIPER] Iniciado em {symbol}!")
    bot_state["is_running"] = True
    bot_state["status"] = f"🎲 Martingale ({leverage}x)"
    
    base_coin = symbol.split('/')[0]
    bot_state["coin_name"] = base_coin
    bot_state["coin_balance"] = 0.0 
    
    # Busca margem unificada inicial
    initial_balance = get_unified_balance(exchange, 'USDT')
    bot_state["usdt_balance"] = initial_balance
    target_balance = initial_balance * 1.23 # Meta de 23%
    
    add_log(f"Saldo Inicial: ${initial_balance:.2f} | META DO DIA: ${target_balance:.2f} (+23%)")
    
    set_margin_leverage(exchange, symbol, leverage)
    
    # Sistema Martingale
    # Margem mínima de entrada ajustada para $1.00 para evitar poeira de saldos e proteger contas pequenas
    base_trade_amount = max(1.0, initial_balance * 0.10)  
    current_trade_amount = base_trade_amount
    in_position = False
    scan_count = 0
    
    try:
        while bot_state["is_running"]:
            scan_count += 1
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
                add_log(f"⚠️ Prejuízo detectado. MARTINGALE ATIVADO! Próxima entrada será de ${current_trade_amount:.2f} de margem.")
            elif not in_position and usdt_balance >= initial_balance:
                # Recuperou ou lucrou. Volta pra mão base.
                current_trade_amount = base_trade_amount
                initial_balance = usdt_balance # Atualiza o patamar seguro
                
            # Trava de Segurança
            if current_trade_amount > usdt_balance:
                current_trade_amount = max(1.0, usdt_balance * 0.95) # All-in seguro
 
            if not in_position:
                # 1. Busca dados gráficos de 1m para entrada
                ohlcv = fetch_ohlcv_data(exchange, symbol, timeframe='1m', limit=100)
                if not ohlcv:
                    time.sleep(5)
                    continue
                    
                closes = ohlcv['c']
                current_price = closes[-1]
                rsi = calculate_rsi(closes, period=14)
                atr = calculate_atr(ohlcv, period=14)
                
                if rsi is None or atr is None:
                    time.sleep(5)
                    continue
                    
                bot_state["current_price"] = current_price
                bot_state["rsi"] = rsi
                
                # 2. Filtro de Macro-Tendência HTF (1 Hora EMA 50)
                htf_trend = "NEUTRAL"
                try:
                    ohlcv_1h = fetch_ohlcv_data(exchange, symbol, timeframe='1h', limit=100)
                    if ohlcv_1h:
                        closes_1h = ohlcv_1h['c']
                        ema50_1h = calculate_ema(closes_1h, period=50)
                        if ema50_1h is not None:
                            htf_trend = "UPTREND" if current_price > ema50_1h else "DOWNTREND"
                except:
                    pass

                # 3. Filtro de Risco e Lote Mínimo
                try:
                    market = exchange.market(symbol)
                    min_amount = market['limits']['amount']['min']
                    min_val_usd = min_amount * current_price
                    target_val_usd = current_trade_amount * leverage
                    
                    if min_val_usd > target_val_usd * 1.3:
                        if scan_count % 10 == 1:
                            add_log(f"⚠️ Martingale: {base_coin} ignorada: lote mínimo (${min_val_usd:.2f}) excede risco (${target_val_usd:.2f}).")
                        time.sleep(10)
                        continue
                except:
                    pass

                # Prepara o status do RSI
                rsi_status = "Neutro"
                if rsi >= 80: rsi_status = "SOBRECOMPRADO 🔴"
                elif rsi <= 20: rsi_status = "SOBREVENDIDO 🟢"
                bot_state["rsi_status"] = rsi_status
                    
                add_log(f"Futuros 1m: ${current_price:.4f} | RSI: {rsi:.1f} ({rsi_status}) | HTF: {htf_trend}")
                
                # Stop Loss dinâmico por ATR (min 0.5%, max 1.5% do preço de entrada)
                dist = 2 * atr
                dist = max(current_price * 0.005, min(current_price * 0.015, dist))

                # GATILHOS
                trigger_buy = False
                trigger_sell = False
                signal_type = "TENDÊNCIA"

                # Gatilho Long: RSI <= 20
                if rsi <= 20:
                    # Permite se estiver em UPTREND ou se for sobrevenda extrema (RSI <= 12)
                    if htf_trend == "UPTREND":
                        trigger_buy = True
                        signal_type = "TENDÊNCIA"
                    elif rsi <= 12:
                        trigger_buy = True
                        signal_type = "REVERSÃO EXTREMA"

                # Gatilho Short: RSI >= 80
                elif rsi >= 80:
                    # Permite se estiver em DOWNTREND ou se for sobrecompra extrema (RSI >= 88)
                    if htf_trend == "DOWNTREND":
                        trigger_sell = True
                        signal_type = "TENDÊNCIA"
                    elif rsi >= 88:
                        trigger_sell = True
                        signal_type = "REVERSÃO EXTREMA"

                # Executa as Ordens com TP/SL embutidos de forma atômica
                if trigger_buy and usdt_balance >= 1.0:
                    add_log(f"🎯 GATILHO MARTINGALE LONG ({signal_type}): RSI {rsi:.1f} | Mão: ${current_trade_amount:.2f}")
                    try:
                        amount_to_buy = (current_trade_amount * leverage) / current_price 
                        
                        try:
                            amount_to_buy = float(exchange.amount_to_precision(symbol, amount_to_buy))
                        except: pass

                        sl_price = current_price - dist
                        tp_price = current_price + 3 * dist # Proporção 3:1
                        tp_price_prec = float(exchange.price_to_precision(symbol, tp_price))
                        sl_price_prec = float(exchange.price_to_precision(symbol, sl_price))

                        params = {
                            'takeProfit': str(tp_price_prec),
                            'stopLoss': str(sl_price_prec)
                        }

                        exchange.create_order(symbol, 'market', 'buy', amount_to_buy, params=params)
                        in_position = True
                        add_log(f"✅ Executada! Ordens anexadas: TP ${tp_price_prec:.4f} | SL ${sl_price_prec:.4f}")
                    except Exception as e:
                        add_log(f"❌ Erro Martingale LONG: {e}")
                        
                elif trigger_sell and usdt_balance >= 1.0:
                    add_log(f"🎯 GATILHO MARTINGALE SHORT ({signal_type}): RSI {rsi:.1f} | Mão: ${current_trade_amount:.2f}")
                    try:
                        amount_to_sell = (current_trade_amount * leverage) / current_price
                        
                        try:
                            amount_to_sell = float(exchange.amount_to_precision(symbol, amount_to_sell))
                        except: pass

                        sl_price = current_price + dist
                        tp_price = current_price - 3 * dist # Proporção 3:1
                        tp_price_prec = float(exchange.price_to_precision(symbol, tp_price))
                        sl_price_prec = float(exchange.price_to_precision(symbol, sl_price))

                        params = {
                            'takeProfit': str(tp_price_prec),
                            'stopLoss': str(sl_price_prec)
                        }

                        exchange.create_order(symbol, 'market', 'sell', amount_to_sell, params=params)
                        in_position = True
                        add_log(f"✅ Executada! Ordens anexadas: TP ${tp_price_prec:.4f} | SL ${sl_price_prec:.4f}")
                    except Exception as e:
                        add_log(f"❌ Erro Martingale SHORT: {e}")
            
            else:
                # Monitora a posição aberta
                try:
                    positions = exchange.fetch_positions([symbol])
                    if not positions or float(positions[0].get('contracts', 0)) == 0:
                        in_position = False
                        add_log("🚪 Operação encerrada pelo mercado (TP ou SL atingido). Recalculando...")
                except Exception as pe:
                    pass
                time.sleep(2)
                
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
