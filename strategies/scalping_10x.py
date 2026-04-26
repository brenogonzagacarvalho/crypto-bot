import time
import sys
import os
import csv
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_historical_data, calculate_rsi
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance, get_available_margin_usd, enable_btc_collateral, place_maker_entry

# --- SISTEMA DE LOG EM CSV ---
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'scalping_10x_trades.csv')

def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço',
                'RSI', 'Valor ($)', 'Alavancagem', 'TP Alvo', 'SL Alvo',
                'Saldo USD', 'Status', 'Detalhes'
            ])

def log_trade(symbol, tipo, direcao, preco, rsi, valor, leverage, tp, sl, saldo, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.2f}',
                f'{rsi:.1f}' if rsi else '-', f'{valor:.2f}', f'{leverage}x',
                f'{tp:.2f}' if tp else '-', f'{sl:.2f}' if sl else '-',
                f'{saldo:.2f}', status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso: Não foi possível gravar log CSV: {e}")

# --- COLATERAL ---
def get_collateral_usd(exchange):
    """Usa a margem real disponível (totalAvailableBalance) da Bybit UTA."""
    available, total_equity = get_available_margin_usd(exchange)
    
    if available > 0.01:
        btc_bal = get_unified_balance(exchange, 'BTC')
        if btc_bal > 0.0:
            return available, 'BTC', btc_bal
        return available, 'USDT', available
    
    return 0.0, 'NONE', 0.0

def set_margin_leverage(exchange, symbol, leverage):
    try:
        exchange.set_leverage(leverage, symbol)
        return True
    except:
        return False

def run_scalping_10x(exchange, symbol='BTC/USDT:USDT', leverage=10, check_interval=60):
    is_multi = (symbol == "MULTI")
    symbols_to_scan = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"] if is_multi else [symbol]
    
    init_trade_log()
    
    add_log(f"🛡️ [SCALPING 10x] Iniciado em {'MULTI-SCAN (BTC, ETH, SOL)' if is_multi else symbol}!")
    add_log(f"📋 Log de trades: logs/scalping_10x_trades.csv")
    bot_state["is_running"] = True
    bot_state["status"] = f"🛡️ Scalping ({leverage}x)"
    
    bot_state["coin_name"] = "SCANNING" if is_multi else symbol.split('/')[0]
    bot_state["coin_balance"] = 0.0
    
    # Habilita BTC como colateral para Derivativos (resolve erro 110007)
    if enable_btc_collateral(exchange):
        add_log("🔓 BTC habilitado como colateral para Futuros!")
    
    # Detecta colateral (margem real disponível)
    collateral_usd, collateral_coin, collateral_raw = get_collateral_usd(exchange)
    bot_state["usdt_balance"] = collateral_usd
    
    if collateral_coin == 'BTC':
        add_log(f"💰 Colateral: {collateral_raw:.8f} BTC | Margem disponível: ${collateral_usd:.2f} USD")
        bot_state["coin_balance"] = collateral_raw
    else:
        add_log(f"💰 Margem disponível: ${collateral_usd:.2f} USDT")
    
    for sym in symbols_to_scan:
        set_margin_leverage(exchange, sym, leverage)
    
    # Mão ajustada ao saldo (máximo $1.50, nunca mais que 80% da margem)
    trade_amount = min(1.5, collateral_usd * 0.80)
    in_position = False
    active_symbol = None
    entry_price = 0.0
    entry_side = None
    scan_count = 0
    rsi_history = {}
    
    # Meta diária: 23%
    starting_balance = collateral_usd
    daily_target_pct = 0.23
    daily_target_usd = starting_balance * (1 + daily_target_pct)
    add_log(f"🎯 Meta diária: ${daily_target_usd:.2f} (+{daily_target_pct*100:.0f}% sobre ${starting_balance:.2f})")
    add_log(f"🃏 Mão: ${trade_amount:.2f}")
    
    try:
        while bot_state["is_running"]:
            scan_count += 1
            
            collateral_usd, collateral_coin, collateral_raw = get_collateral_usd(exchange)
            bot_state["usdt_balance"] = collateral_usd
            if collateral_coin == 'BTC':
                bot_state["coin_balance"] = collateral_raw
            
            # Meta diária (exige lucro mínimo de $0.50)
            if not in_position and collateral_usd >= daily_target_usd:
                lucro = collateral_usd - starting_balance
                if lucro >= 0.50:
                    add_log(f"{'='*50}")
                    add_log(f"🏆🏆🏆 META DIÁRIA BATIDA! 🏆🏆🏆")
                    add_log(f"Início: ${starting_balance:.2f} → Final: ${collateral_usd:.2f}")
                    add_log(f"Lucro: +${lucro:.2f} (+{(lucro/starting_balance)*100:.1f}%)")
                    add_log(f"{'='*50}")
                    log_trade('-', 'META_DIARIA', '-', 0, 0, 0, leverage, 0, 0, collateral_usd, '🏆 META BATIDA', f"Lucro: +${lucro:.2f}")
                    bot_state["status"] = "🏆 Meta Diária Atingida!"
                    bot_state["is_running"] = False
                    break
                
            if collateral_usd < 0.50:
                add_log(f"❌ Saldo insuficiente: ${collateral_usd:.2f}. Desligando...")
                bot_state["is_running"] = False
                break

            # Ajusta mão ao saldo
            trade_amount = min(1.5, collateral_usd * 0.80)
            
            if not in_position and trade_amount < 0.10:
                add_log(f"⚠️ Mão muito pequena (${trade_amount:.2f}). Aguardando...")
                for _ in range(check_interval):
                    if not bot_state["is_running"]: break
                    time.sleep(1)
                continue

            if not in_position:
                add_log(f"── Scanner #{scan_count} | ${collateral_usd:.2f} ({collateral_coin}) | Mão: ${trade_amount:.2f} ──")
                
                found_entry = False
                for sym in symbols_to_scan:
                    if not bot_state["is_running"] or found_entry: break
                    
                    coin_name = sym.split('/')[0]
                    bot_state["coin_name"] = coin_name
                    closes = fetch_historical_data(exchange, sym, timeframe='1m', limit=50)
                    if not closes or len(closes) < 15:
                        continue
                        
                    current_price = closes[-1]
                    rsi = calculate_rsi(closes, period=14)
                    if rsi is None: continue
                    
                    bot_state["current_price"] = current_price
                    bot_state["rsi"] = rsi
                    
                    rsi_bar = "█" * int(rsi / 5) + "░" * (20 - int(rsi / 5))
                    rsi_status = "Neutro"
                    if rsi >= 75: rsi_status = "SOBRECOMPRADO 🔴"
                    elif rsi <= 25: rsi_status = "SOBREVENDIDO 🟢"
                    bot_state["rsi_status"] = rsi_status
                    
                    add_log(f"  {coin_name}: ${current_price:,.2f} | RSI [{rsi_bar}] {rsi:.1f} {rsi_status}")
                    log_trade(sym, 'SCAN', '-', current_price, rsi, trade_amount, leverage, 0, 0, collateral_usd, rsi_status)
                    
                    # Filtro de confirmação RSI
                    prev_rsi = rsi_history.get(sym, rsi)
                    rsi_history[sym] = rsi
                    
                    # Gatilho LONG (RSI <= 25 E subindo)
                    if rsi <= 25 and rsi > prev_rsi: 
                        add_log(f"🛡️ SCALP LONG CONFIRMADO em {coin_name}! RSI: {prev_rsi:.1f}→{rsi:.1f}")
                        amount_to_buy = (trade_amount * leverage) / current_price
                        tp_price = round(current_price * 1.0025, 2)
                        sl_price = round(current_price * 0.99, 2)
                        entry_limit_price = round(current_price, 2)
                        
                        try:
                            add_log(f"📤 Limit PostOnly BUY @ ${entry_limit_price:,.2f} (maker 0.02%)...")
                            order, filled = place_maker_entry(
                                exchange, sym, 'buy', amount_to_buy,
                                entry_limit_price, tp_price, sl_price, max_wait=15
                            )
                            if filled:
                                in_position = True
                                active_symbol = sym
                                entry_price = current_price
                                entry_side = 'LONG'
                                found_entry = True
                                add_log(f"✅ LONG (maker)! TP: ${tp_price:,.2f} | SL: ${sl_price:,.2f}")
                                log_trade(sym, 'ENTRADA', 'LONG', current_price, rsi, trade_amount, leverage, tp_price, sl_price, collateral_usd, '✅ SUCESSO (maker)', f"OrderID: {order.get('id', 'N/A')}")
                            else:
                                add_log(f"⏳ Não preenchida em 15s. Cancelada.")
                        except Exception as e:
                            add_log(f"❌ Erro ({coin_name}): {e}")
                            add_log(f"⏸️ Pausando {check_interval}s...")
                            break
                            
                    elif rsi >= 75 and rsi < prev_rsi: 
                        add_log(f"🛡️ SCALP SHORT CONFIRMADO em {coin_name}! RSI: {prev_rsi:.1f}→{rsi:.1f}")
                        amount_to_sell = (trade_amount * leverage) / current_price
                        tp_price = round(current_price * 0.9975, 2)
                        sl_price = round(current_price * 1.01, 2)
                        entry_limit_price = round(current_price, 2)
                        
                        try:
                            add_log(f"📤 Limit PostOnly SELL @ ${entry_limit_price:,.2f} (maker 0.02%)...")
                            order, filled = place_maker_entry(
                                exchange, sym, 'sell', amount_to_sell,
                                entry_limit_price, tp_price, sl_price, max_wait=15
                            )
                            if filled:
                                in_position = True
                                active_symbol = sym
                                entry_price = current_price
                                entry_side = 'SHORT'
                                found_entry = True
                                add_log(f"✅ SHORT (maker)! TP: ${tp_price:,.2f} | SL: ${sl_price:,.2f}")
                                log_trade(sym, 'ENTRADA', 'SHORT', current_price, rsi, trade_amount, leverage, tp_price, sl_price, collateral_usd, '✅ SUCESSO (maker)', f"OrderID: {order.get('id', 'N/A')}")
                            else:
                                add_log(f"⏳ Não preenchida em 15s. Cancelada.")
                        except Exception as e:
                            add_log(f"❌ Erro ({coin_name}): {e}")
                            add_log(f"⏸️ Pausando {check_interval}s...")
                            break
                    
                    elif rsi <= 25:
                        add_log(f"  ⏳ {coin_name}: RSI caindo ({prev_rsi:.1f}→{rsi:.1f}), aguardando reversão...")
                    elif rsi >= 75:
                        add_log(f"  ⏳ {coin_name}: RSI subindo ({prev_rsi:.1f}→{rsi:.1f}), aguardando reversão...")
                    
                    time.sleep(0.5)
            
            elif in_position and active_symbol:
                try:
                    coin_name = active_symbol.split('/')[0]
                    bot_state["coin_name"] = coin_name
                    closes = fetch_historical_data(exchange, active_symbol, timeframe='1m', limit=15)
                    
                    if closes:
                        current_price = closes[-1]
                        bot_state["current_price"] = current_price
                        
                        if entry_side == 'LONG':
                            pnl_pct = ((current_price - entry_price) / entry_price) * 100 * leverage
                        else:
                            pnl_pct = ((entry_price - current_price) / entry_price) * 100 * leverage
                        
                        pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
                        add_log(f"📊 {coin_name} {entry_side} | ${entry_price:,.2f} → ${current_price:,.2f} | P&L: {pnl_emoji} {pnl_pct:+.1f}%")
                    
                    positions = exchange.fetch_positions([active_symbol])
                    has_position = False
                    for pos in positions:
                        contracts = float(pos.get('contracts', 0))
                        if contracts > 0:
                            has_position = True
                            unrealized_pnl = float(pos.get('unrealizedPnl', 0))
                            add_log(f"  💰 Contratos: {contracts} | PnL: ${unrealized_pnl:.4f}")
                            break
                    
                    if not has_position:
                        new_collateral_usd, _, _ = get_collateral_usd(exchange)
                        resultado = new_collateral_usd - collateral_usd
                        resultado_emoji = "🏆 LUCRO" if resultado >= 0 else "💀 LOSS"
                        
                        add_log(f"{'='*50}")
                        add_log(f"{resultado_emoji}: {entry_side} em {coin_name} | ${resultado:+.4f}")
                        add_log(f"{'='*50}")
                        
                        log_trade(active_symbol, 'SAÍDA', entry_side, current_price if closes else 0, 0, trade_amount, leverage, 0, 0, new_collateral_usd, resultado_emoji, f"${resultado:+.4f}")
                        
                        in_position = False
                        active_symbol = None
                        entry_price = 0.0
                        entry_side = None
                        add_log("🔄 Voltando ao Scanner...")
                except Exception as e:
                    add_log(f"⚠️ Aviso posição: {e}")
                
            for _ in range(check_interval):
                if not bot_state["is_running"]: break
                time.sleep(1)
                
    except Exception as e:
        add_log(f"Erro Crítico Scalper 10x: {e}")
        log_trade('-', 'ERRO_CRITICO', '-', 0, 0, 0, leverage, 0, 0, 0, '💥 CRASH', str(e))
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"

