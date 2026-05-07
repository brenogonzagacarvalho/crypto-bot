import time
import sys
import os
import csv
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_ohlcv_data, calculate_rsi, calculate_ema, calculate_macd
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance, get_available_margin_usd, enable_btc_collateral, place_maker_entry

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'survival_trades.csv')
MARKET_LOG_FILE = os.path.join(LOG_DIR, 'survival_market_data.csv')
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'risk_params.json')

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f).get('survival_scalper', {})
    except Exception as e:
        add_log(f"Aviso: Não foi possível carregar config: {e}. Usando defaults.")
        return {
            "max_leverage": 20, "risk_per_trade": 0.20, "max_daily_loss_pct": 0.30,
            "min_balance": 3.0, "take_profit_pct": 1.5, "stop_loss_pct": 0.8,
            "cooldown_seconds": 30, "min_winrate_to_continue": 40
        }

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

def init_market_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(MARKET_LOG_FILE):
        with open(MARKET_LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Data/Hora', 'Moeda', 'Preço', 'RSI', 'EMA200', 'MACD', 'Tendência'])

def log_trade(symbol, tipo, direcao, preco, rsi, valor, leverage, tp, sl, saldo, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.2f}',
                f'{rsi:.1f}' if rsi else '-', f'{detalhes.get("ema200", "-")}' if isinstance(detalhes, dict) else '-', 
                f'{detalhes.get("macd", "-")}' if isinstance(detalhes, dict) else '-',
                f'{valor:.2f}', f'{leverage}x',
                f'{tp:.2f}' if tp else '-', f'{sl:.2f}' if sl else '-',
                f'{saldo:.2f}', status, detalhes.get("msg", "") if isinstance(detalhes, dict) else detalhes
            ])
    except Exception as e:
        add_log(f"Aviso log CSV: {e}")

def log_market_data(symbol, price, rsi, ema200, macd, trend):
    try:
        with open(MARKET_LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, f'{price:.6f}', f'{rsi:.2f}', f'{ema200:.6f}', f'{macd:.6f}', trend
            ])
    except Exception:
        pass

def get_collateral_usd(exchange):
    available, _ = get_available_margin_usd(exchange)
    if available is None:
        return None, 'ERROR', None
        
    if available > 0.01:
        btc_bal = get_unified_balance(exchange, 'BTC')
        if btc_bal > 0.0: return available, 'BTC', btc_bal
        return available, 'USDT', available
    return 0.0, 'NONE', 0.0

def run_survival_scalper(exchange, symbol='MULTI'):
    is_multi = (symbol == "MULTI")
    # Expansão para 7 moedas principais
    symbols_to_scan = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "ADA/USDT:USDT", "DOGE/USDT:USDT", "BNB/USDT:USDT"] if is_multi else [symbol]
    
    init_trade_log()
    init_market_log()
    
    config = load_config()
    leverage = config['max_leverage']
    
    add_log(f"🛡️ [SURVIVAL SCALPER] Iniciado em {'MULTI' if is_multi else symbol} com {leverage}x")
    bot_state["is_running"] = True
    bot_state["status"] = f"🛡️ Survival ({leverage}x)"
    
    enable_btc_collateral(exchange)
    
    collateral_usd, collateral_coin, _ = get_collateral_usd(exchange)
    
    if collateral_usd is None:
        add_log("❌ Falha crítica ao ler o saldo inicial. Verifique sua chave de API (restrição de IP).")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Erro API"
        return
        
    bot_state["usdt_balance"] = collateral_usd
    starting_balance = collateral_usd
    
    # Validação de banca mínima
    if collateral_usd < config['min_balance']:
        add_log(f"❌ BANCA INSUFICIENTE! Mínimo ${config['min_balance']:.2f}, Atual: ${collateral_usd:.2f}")
        bot_state["is_running"] = False
        return

    add_log(f"💰 Margem Inicial: ${collateral_usd:.2f} ({collateral_coin})")
    
    for sym in symbols_to_scan:
        try: exchange.set_leverage(leverage, sym)
        except: pass

    active_positions = {}
    MAX_POSITIONS = 2
    scan_count = 0
    rsi_history = {}
    last_trade_time = 0
    
    daily_loss_limit = starting_balance * (1 - config['max_daily_loss_pct'])
    
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
                positions = exchange.fetch_positions(symbols_to_scan)
                current_open_symbols = set()
                
                for pos in positions:
                    contracts = float(pos.get('contracts', 0))
                    if contracts > 0:
                        sym = pos['symbol']
                        current_open_symbols.add(sym)
                        
                        if sym not in active_positions:
                            active_positions[sym] = {'side': pos['side'].upper(), 'entry_price': float(pos['entryPrice'])}
                            
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
                    resultado = new_collateral_usd - collateral_usd
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
                    
                    prev_rsi = rsi_history.get(sym, rsi)
                    rsi_history[sym] = rsi
                    
                    # GATILHO LONG: Tendência + Sobrevenda + Reversão
                    if rsi <= 45 and rsi > prev_rsi: 
                        add_log(f"🛡️ SINAL LONG DE SOBREVIVÊNCIA em {coin_name}!")
                        amount_to_buy = (trade_amount * leverage) / current_price
                        tp_price = round(current_price * (1 + (config['take_profit_pct']/100)), 2)
                        sl_price = round(current_price * (1 - (config['stop_loss_pct']/100)), 2)
                        
                        try:
                            order, filled = place_maker_entry(exchange, sym, 'buy', amount_to_buy, current_price, tp_price, sl_price)
                            if filled:
                                active_positions[sym] = {'side': 'LONG', 'entry_price': current_price}
                                log_trade(sym, 'ENTRADA', 'LONG', current_price, rsi, trade_amount, leverage, tp_price, sl_price, collateral_usd, '✅ SUCESSO')
                        except Exception as e: add_log(f"❌ Erro: {e}")
                            
                    # GATILHO SHORT: Tendência Baixa + Sobrecompra + Reversão
                    elif rsi >= 55 and rsi < prev_rsi: 
                        add_log(f"🛡️ SINAL SHORT DE SOBREVIVÊNCIA em {coin_name}!")
                        amount_to_sell = (trade_amount * leverage) / current_price
                        tp_price = round(current_price * (1 - (config['take_profit_pct']/100)), 2)
                        sl_price = round(current_price * (1 + (config['stop_loss_pct']/100)), 2)
                        
                        try:
                            order, filled = place_maker_entry(exchange, sym, 'sell', amount_to_sell, current_price, tp_price, sl_price)
                            if filled:
                                active_positions[sym] = {'side': 'SHORT', 'entry_price': current_price}
                                log_trade(sym, 'ENTRADA', 'SHORT', current_price, rsi, trade_amount, leverage, tp_price, sl_price, collateral_usd, '✅ SUCESSO')
                        except Exception as e: add_log(f"❌ Erro: {e}")
                        
                    time.sleep(0.5)
            
            for _ in range(check_interval):
                if not bot_state["is_running"]: break
                time.sleep(1)
