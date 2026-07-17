import time
import sys
import os
import csv
import math
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_ohlcv_data, calculate_rsi, calculate_vwap
from core.shared_state import bot_state, add_log
from core.balance_utils import get_available_margin_usd, enable_btc_collateral, get_closed_pnl, get_closed_pnl_details

# --- SISTEMA DE LOG EM CSV ---
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'vwap_deviation_trades.csv')

def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço Executado',
                'VWAP', 'LowerBand', 'RSI', 'Alavancagem',
                'Take Profit', 'Stop Loss', 'Saldo USD', 'Status', 'Detalhes'
            ])

def log_trade(symbol, tipo, direcao, preco, vwap, lower_band, rsi, leverage, tp, sl, saldo, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.4f}' if preco else '-',
                f'{vwap:.4f}' if vwap else '-', f'{lower_band:.4f}' if lower_band else '-',
                f'{rsi:.1f}' if rsi else '-',
                f'{leverage}x',
                f'{tp:.4f}' if tp else '-', f'{sl:.4f}' if sl else '-',
                f'{saldo:.2f}', status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso log CSV: {e}")

def calculate_stddev(prices, vwap_val):
    if len(prices) < 2: return 0.0
    variance = sum((p - vwap_val) ** 2 for p in prices) / len(prices)
    return math.sqrt(variance)

# --- LOOP PRINCIPAL DA ESTRATÉGIA ---
def run_vwap_deviation_strategy(exchange, symbol='MULTI', leverage=30, check_interval=5):
    init_trade_log()

    is_multi = (symbol == "MULTI")
    symbols_to_scan = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "ADA/USDT:USDT", "DOGE/USDT:USDT", "BNB/USDT:USDT"] if is_multi else [symbol]

    add_log(f"{'='*55}")
    add_log(f"🌊 ESTRATÉGIA VWAP DEVIATION SCALPER — {'MULTI-SCAN' if is_multi else symbol}")
    add_log(f"📊 Gráfico: 1m | Desvios da VWAP & Reversão à Média | Alavancagem: {leverage}x")
    add_log(f"{'='*55}")

    bot_state["is_running"] = True
    bot_state["status"]     = f"🌊 VWAP Dev ({leverage}x)"
    bot_state["coin_name"]  = "SCANNING" if is_multi else symbol.split('/')[0]

    enable_btc_collateral(exchange)

    # Configura alavancagem e margem isolada para as moedas
    for sym in symbols_to_scan:
        try:
            exchange.set_margin_mode('isolated', sym)
            add_log(f"Margem configurada para ISOLADA em {sym}!")
        except Exception as e:
            pass
        try:
            exchange.set_leverage(leverage, sym)
            add_log(f"Alavancagem setada para {leverage}x em {sym}!")
        except Exception as e:
            pass

    # Lê saldo inicial
    available_usd, total_equity = get_available_margin_usd(exchange)
    if available_usd is None or total_equity is None:
        add_log("❌ Falha ao ler saldo inicial. Encerrando.")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Erro API"
        return

    active_positions = {}
    active_limit_orders = {}
    scan_count = 0

    # Sincroniza posições existentes
    try:
        open_positions = []
        for s in symbols_to_scan:
            try:
                open_positions.extend(exchange.fetch_positions([s]))
            except:
                pass
        for pos in open_positions:
            contracts = float(pos.get('contracts') or 0)
            if contracts > 0:
                sym = pos['symbol']
                active_positions[sym] = {
                    'side': pos['side'].upper(),
                    'entry_price': float(pos.get('entryPrice') or 0),
                    'contracts': contracts
                }
                add_log(f"Sincronizado: Posição de {pos['side'].upper()} ativa em {sym}.")
    except Exception as e:
        add_log(f"Aviso ao sincronizar posições iniciais: {e}")

    try:
        while bot_state["is_running"]:
            scan_count += 1
            
            try:
                collateral_usd, total_equity = get_available_margin_usd(exchange)
                if collateral_usd is None:
                    add_log("⚠️ Erro ao atualizar saldo. Aguardando...")
                    time.sleep(5)
                    continue
                bot_state["usdt_balance"] = collateral_usd
            except Exception as e:
                add_log(f"⚠️ Erro ao atualizar saldo: {e}")
                time.sleep(2)
                continue

            # 1. MONITORAMENTO DAS POSIÇÕES ABERTAS
            try:
                open_positions = []
                for s in symbols_to_scan:
                    try:
                        open_positions.extend(exchange.fetch_positions([s]))
                    except:
                        pass
                current_open_symbols = set()
                
                for pos in open_positions:
                    contracts = float(pos.get('contracts') or 0)
                    if contracts > 0:
                        sym = pos['symbol']
                        current_open_symbols.add(sym)
                        
                        entry_price = float(pos.get('entryPrice') or 0)
                        unpnl = float(pos.get('unrealizedPnl') or 0)
                        roi = float(pos.get('percentage') or 0)
                        
                        if sym not in active_positions:
                            active_positions[sym] = {
                                'side': pos['side'].upper(),
                                'entry_price': entry_price,
                                'contracts': contracts
                            }
                            log_trade(sym, 'ENTRADA', pos['side'].upper(), entry_price, None, None, None, leverage, None, None, collateral_usd, '✅ Detectada')
                        
                        bot_state["unrealized_pnl"] = unpnl
                        bot_state["current_price"] = float(pos.get('markPrice') or entry_price)
                        bot_state["status"] = f"📊 {sym.split('/')[0]} {pos['side'].upper()} (+{roi:.2f}% ROI)"
                
                closed_symbols = list(set(active_positions.keys()) - current_open_symbols)
                for sym in closed_symbols:
                    new_collateral_usd, _ = get_available_margin_usd(exchange)
                    time.sleep(3)
                    details = get_closed_pnl_details(exchange, sym)
                    resultado = details['pnl']
                    exit_price = details['exit_price']
                    
                    resultado_emoji = "🏆 LUCRO" if resultado > 0 else "💀 LOSS"
                    resultado_str = f"{'+$' if resultado >= 0 else '-$'}{abs(resultado):.4f}"
                    
                    add_log(f"🚪 Posição fechada em {sym}! PnL: {resultado_str} {resultado_emoji} | Preço de Saída: ${exit_price:.4f}")
                    log_trade(sym, 'SAÍDA', active_positions[sym]['side'], exit_price, None, None, None, leverage, None, None, new_collateral_usd, resultado_emoji, f"Fechamento: {resultado_str}")
                    del active_positions[sym]
                    collateral_usd = new_collateral_usd
                    bot_state["unrealized_pnl"] = 0.0

            except Exception as e:
                add_log(f"⚠️ Erro ao monitorar posições: {e}")

            # --- LIMITE DE 1 MÃO ATIVA ---
            add_log(f"── Scanner #{scan_count} | Ativas: {len(active_positions)} | Saldo: ${collateral_usd:.2f} ──")
            
            if len(active_positions) >= 1:
                for s in symbols_to_scan:
                    if s not in active_positions and s in active_limit_orders:
                        try:
                            order_id = active_limit_orders[s]['order_id']
                            exchange.cancel_order(order_id, s)
                            add_log(f"🧹 Mantendo apenas 1 mão ativa: Cancelada ordem pendente em {s}.")
                        except:
                            pass
                        del active_limit_orders[s]
                time.sleep(check_interval)
                continue

            # Busca por novas entradas de reversão à média da VWAP
            for sym in symbols_to_scan:
                if not bot_state["is_running"]: break
                if sym in active_positions: continue
                
                coin_name = sym.split('/')[0]
                bot_state["coin_name"] = coin_name
                bot_state["status"] = f"🌊 Analisando {coin_name}"

                ohlcv_1m = fetch_ohlcv_data(exchange, sym, timeframe='1m', limit=50)
                if not ohlcv_1m:
                    continue

                closes = ohlcv_1m['c']
                highs = ohlcv_1m['h']
                lows = ohlcv_1m['l']
                current_price = closes[-1]
                
                rsi = calculate_rsi(closes, period=14)
                vwap = calculate_vwap(ohlcv_1m)
                
                if rsi is None or vwap is None:
                    continue

                # Calcula typical prices para desvio padrão
                typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
                stddev = calculate_stddev(typical_prices, vwap)
                
                # Banda de desvio inferior (2 Desvios Padrões da VWAP)
                lower_band = vwap - (stddev * 2.0)

                bot_state["current_price"] = current_price
                bot_state["rsi"] = rsi
                bot_state["rsi_status"] = f"VWAP: ${vwap:.4f} | Banda Inf: ${lower_band:.4f}"

                # GATILHO COMPRA LONG:
                # 1. Preço atual está abaixo da banda inferior da VWAP (Preço < VWAP - 2 * SD)
                # 2. RSI (14) está abaixo de 30 (sobrevenda extrema)
                is_deviated_down = (current_price < lower_band)
                is_rsi_oversold = (rsi <= 30)

                if is_deviated_down and is_rsi_oversold:
                    add_log(f"🌊 SINAL DE REVERSÃO (VWAP DEVIATION) detectado em {coin_name}!")
                    add_log(f"   RSI: {rsi:.1f} (Sobrevenda) | Preço (${current_price:.4f}) abaixo da Banda (${lower_band:.4f})")

                    entry_price = current_price
                    # Alvo de TP na VWAP, com garantia de no mínimo 10% ROI
                    min_tp_price = entry_price * (1 + 0.10 / leverage)
                    tp_price = max(vwap, min_tp_price)

                    try:
                        market = exchange.market(sym)
                        entry_price = float(exchange.price_to_precision(sym, entry_price))
                        tp_price = float(exchange.price_to_precision(sym, tp_price))
                    except:
                        pass

                    add_log(f"   🎯 COMPRA LIMITE: ${entry_price:.4f} | ALVO TP (Retorno VWAP): ${tp_price:.4f} | STOP LOSS: DESATIVADO")

                    # Margem alocada por operação: 10% do saldo total (Juros Compostos)
                    margin_allocated = collateral_usd * 0.10
                    if margin_allocated < 1.0:
                        margin_allocated = min(1.0, collateral_usd)

                    trade_size_usd = margin_allocated * leverage
                    amount = trade_size_usd / entry_price

                    try:
                        min_amount = market['limits']['amount']['min']
                        if amount < min_amount:
                            amount = min_amount
                        amount = float(exchange.amount_to_precision(sym, amount))
                    except:
                        pass

                    val_financeiro = amount * entry_price
                    required_margin = val_financeiro / leverage
                    if required_margin > collateral_usd:
                        add_log(f"⚠️ Saldo insuficiente para margem exigida (${required_margin:.2f} > ${collateral_usd:.2f}). Ordem abortada.")
                        continue

                    try:
                        params = {
                            'takeProfit': f"{tp_price:.4f}".rstrip('0').rstrip('.'),
                        }
                        print(f"Enviando ordem limite de COMPRA em {sym}: Preço ${entry_price:.4f} Qtd {amount}")
                        order = exchange.create_order(
                            symbol=sym,
                            type='limit',
                            side='buy',
                            amount=amount,
                            price=entry_price,
                            params=params
                        )
                        order_id = order.get('id')
                        active_limit_orders[sym] = {
                            'order_id': order_id,
                            'date_placed': datetime.now().strftime('%Y-%m-%d')
                        }
                        add_log(f"✅ Ordem limite posicionada em {sym}! ID: {order_id}")
                        log_trade(sym, 'ENTRADA', 'LONG', entry_price, vwap, lower_band, rsi, leverage, tp_price, None, collateral_usd, '✅ POSICIONADA')
                        
                        break
                    except Exception as e:
                        add_log(f"❌ Erro ao enviar ordem em {sym}: {e}")

                time.sleep(0.5)

            for _ in range(check_interval):
                if not bot_state["is_running"]: break
                time.sleep(1)

    except Exception as e:
        add_log(f"⚠️ Erro crítico no loop da estratégia: {e}")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Erro Loop"
