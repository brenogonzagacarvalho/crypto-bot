from core.market_data import fetch_historical_data
import time
import sys
import os
import csv
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_ohlcv_data, calculate_rsi, calculate_ema, calculate_macd
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance, get_available_margin_usd, enable_btc_collateral, place_maker_entry, get_closed_pnl

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
                'RSI', 'EMA200', 'MACD', 'Valor ($)', 'Alavancagem', 'TP Alvo', 'SL Alvo',
                'Saldo USD', 'Status', 'Detalhes'
            ])

def log_trade(symbol, tipo, direcao, preco, rsi, valor, leverage, tp, sl, saldo, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.2f}',
                f'{rsi:.1f}' if rsi else '-', f'{detalhes.get("ema200", "-")}', f'{detalhes.get("macd", "-")}',
                f'{valor:.2f}', f'{leverage}x',
                f'{tp:.2f}' if tp else '-', f'{sl:.2f}' if sl else '-',
                f'{saldo:.2f}', status, detalhes.get("msg", "")
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
    trade_amount = min(1.5, collateral_usd * 0.40)
    active_positions = {}
    MAX_POSITIONS = 2
    check_interval = 5
    scan_count = 0
    rsi_history = {}
    
    # Meta diária: 23%
    starting_balance = collateral_usd
    daily_target_pct = 0.23
    daily_target_usd = starting_balance * (1 + daily_target_pct)
    add_log(f"🎯 Meta diária: ${daily_target_usd:.2f} (+{daily_target_pct*100:.0f}% sobre ${starting_balance:.2f})")
    add_log(f"🧠 Filtros: EMA 200 + MACD Confirmation | TF: 5m")
    add_log(f"🃏 Mão: ${trade_amount:.2f}")
    
    try:
        while bot_state["is_running"]:
            scan_count += 1
            
            try:
                collateral_usd, collateral_coin, _ = get_collateral_usd(exchange)
                bot_state["usdt_balance"] = collateral_usd
            except Exception as e:
                add_log(f"⚠️ Erro ao ler banca: {e}")
                time.sleep(2)
                continue
                
            trade_amount = min(1.5, collateral_usd * 0.40)
            
            if len(active_positions) < MAX_POSITIONS and trade_amount < 0.10:
                add_log(f"⚠️ Mão muito pequena (${trade_amount:.2f}). Aguardando...")
                for _ in range(check_interval):
                    if not bot_state["is_running"]: break
                    time.sleep(1)
                continue

            # --- MONITORAMENTO DE POSIÇÕES ABERTAS ---
            try:
                all_positions = []
                for sym in symbols_to_scan:
                    try:
                        all_positions.extend(exchange.fetch_positions([sym]))
                    except: pass
                current_open_symbols = set()
                
                for pos in all_positions:
                    contracts = float(pos.get('contracts', 0))
                    if contracts > 0:
                        sym = pos['symbol']
                        current_open_symbols.add(sym)
                        
                        if sym not in active_positions:
                            active_positions[sym] = {'side': pos['side'].upper(), 'entry_price': float(pos['entryPrice'])}
                            log_trade(sym, 'ENTRADA', pos['side'].upper(), float(pos['entryPrice']), 0, trade_amount, leverage, 0, 0, collateral_usd, '✅ Detectada')
                            
                        unrealized_pnl = float(pos.get('unrealizedPnl', 0))
                        liq_price = pos.get('liquidationPrice')
                        roi = pos.get('percentage')
                        margin = pos.get('initialMargin')
                        
                        liq_str = f" | Liq: ${float(liq_price):,.2f}" if liq_price else ""
                        roi_str = f" | ROI: {float(roi):+.2f}%" if roi is not None else ""
                        marg_str = f" | Margem: ${float(margin):.2f}" if margin else ""
                        
                        add_log(f"📊 {sym} {pos['side'].upper()} Aberto:")
                        add_log(f"  💰 Qtd: {contracts}{marg_str}{liq_str}")
                        add_log(f"  💵 PnL: ${unrealized_pnl:+.4f}{roi_str}")
                
                # Checa fechamentos
                closed_symbols = list(set(active_positions.keys()) - current_open_symbols)
                for sym in closed_symbols:
                    new_collateral_usd, _, _ = get_collateral_usd(exchange)
                    resultado = get_closed_pnl(exchange, sym, limit=1)
                    resultado_emoji = "🏆 LUCRO" if resultado > 0 else "💀 LOSS"
                    
                    add_log(f"{'='*50}")
                    add_log(f"{resultado_emoji}: Fechamento em {sym} | ${resultado:+.4f}")
                    add_log(f"{'='*50}")
                    
                    log_trade(sym, 'SAÍDA', active_positions[sym]['side'], 0, 0, trade_amount, leverage, 0, 0, new_collateral_usd, resultado_emoji, f"${resultado:+.4f}")
                    del active_positions[sym]
                    collateral_usd = new_collateral_usd
            except Exception as e:
                add_log(f"⚠️ Erro ao monitorar posições: {e}")

            # --- BUSCA POR NOVAS ENTRADAS ---
            if len(active_positions) < MAX_POSITIONS:
                add_log(f"── Scanner #{scan_count} | Abertas {len(active_positions)}/{MAX_POSITIONS} | Mão: ${trade_amount:.2f} ──")
                
                for sym in symbols_to_scan:
                    if not bot_state["is_running"] or len(active_positions) >= MAX_POSITIONS: break
                    if sym in active_positions: continue
                    
                    coin_name = sym.split('/')[0]
                    bot_state["coin_name"] = coin_name
                    
                    ohlcv = fetch_ohlcv_data(exchange, sym, timeframe='5m', limit=210)
                    if not ohlcv: continue
                    
                    closes = ohlcv['c']
                    current_price = closes[-1]
                    rsi = calculate_rsi(closes, period=14)
                    ema200 = calculate_ema(closes, period=200)
                    macd, signal, hist = calculate_macd(closes)
                    
                    if rsi is None or ema200 is None or hist is None: continue
                    
                    bot_state["current_price"] = current_price
                    bot_state["rsi"] = rsi
                    trend = "ALTA 📈" if current_price > ema200 else "BAIXA 📉"
                    
                    detalhes_scan = {"ema200": f"{ema200:.2f}", "macd": f"{hist:.4f}", "msg": f"Trend: {trend}"}
                    
                    prev_rsi = rsi_history.get(sym, rsi)
                    rsi_history[sym] = rsi
                    
                    # GATILHO LONG: Acima da EMA 200 + RSI Subindo + MACD Positivo
                    if current_price > ema200 and rsi <= 45 and rsi > prev_rsi: 
                        add_log(f"🛡️ SCALP LONG em {coin_name}!")
                        amount_to_buy = (trade_amount * leverage) / current_price
                        tp_price = float(exchange.price_to_precision(sym, current_price * 1.0025))
                        sl_price = float(exchange.price_to_precision(sym, current_price * 0.995))
                        
                        try:
                            order, filled = place_maker_entry(exchange, sym, 'buy', amount_to_buy, current_price, tp_price, sl_price)
                            if filled:
                                active_positions[sym] = {'side': 'LONG', 'entry_price': current_price}
                                log_trade(sym, 'ENTRADA', 'LONG', current_price, rsi, trade_amount, leverage, tp_price, sl_price, collateral_usd, '✅ SUCESSO', detalhes_scan)
                        except Exception as e: add_log(f"❌ Erro: {e}")
                            
                    # GATILHO SHORT: Abaixo da EMA 200 + RSI Caindo + MACD Negativo
                    elif current_price < ema200 and rsi >= 55 and rsi < prev_rsi: 
                        add_log(f"🛡️ SCALP SHORT em {coin_name}!")
                        amount_to_sell = (trade_amount * leverage) / current_price
                        tp_price = float(exchange.price_to_precision(sym, current_price * 0.9975))
                        sl_price = float(exchange.price_to_precision(sym, current_price * 1.005))
                        
                        try:
                            order, filled = place_maker_entry(exchange, sym, 'sell', amount_to_sell, current_price, tp_price, sl_price)
                            if filled:
                                active_positions[sym] = {'side': 'SHORT', 'entry_price': current_price}
                                log_trade(sym, 'ENTRADA', 'SHORT', current_price, rsi, trade_amount, leverage, tp_price, sl_price, collateral_usd, '✅ SUCESSO', detalhes_scan)
                        except Exception as e: add_log(f"❌ Erro: {e}")
                        
                    time.sleep(0.5)
            
            for _ in range(check_interval):
                if not bot_state["is_running"]: break
                time.sleep(1)
    except Exception as e:
        add_log(f"⚠️ Erro crítico no loop principal: {e}")
        time.sleep(5)