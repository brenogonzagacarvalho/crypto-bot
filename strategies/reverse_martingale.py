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
LOG_FILE = os.path.join(LOG_DIR, 'reverse_martingale_trades.csv')

def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço',
                'RSI', 'EMA200', 'MACD_Hist', 'Mão ($)', 'Alavancagem', 'TP Alvo', 'SL Alvo',
                'Saldo USD', 'Win Streak', 'Status', 'Detalhes'
            ])

def log_trade(symbol, tipo, direcao, preco, rsi, mao, leverage, tp, sl, saldo, wins, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.2f}',
                f'{rsi:.1f}' if rsi else '-', f'{detalhes.get("ema200", "-")}', f'{detalhes.get("macd", "-")}',
                f'{mao:.2f}', f'{leverage}x',
                f'{tp:.2f}' if tp else '-', f'{sl:.2f}' if sl else '-',
                f'{saldo:.2f}', wins, status, detalhes.get("msg", "")
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

def run_reverse_martingale(exchange, symbol='BTC/USDT:USDT', leverage=100, check_interval=30):
    is_multi = (symbol == "MULTI")
    symbols_to_scan = ["ETH/USDT:USDT", "BTC/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT"] if is_multi else [symbol]
    
    init_trade_log()
    
    add_log(f"🔥 [REVERSE MARTINGALE v2] {'MULTI-SCAN' if is_multi else symbol} com {leverage}x!")
    add_log(f"📋 Log: logs/reverse_martingale_trades.csv")
    bot_state["is_running"] = True
    bot_state["status"] = f"🔥 Rev. Martingale ({leverage}x)"
    
    bot_state["coin_name"] = "SCANNING" if is_multi else symbol.split('/')[0]
    bot_state["coin_balance"] = 0.0 
    
    # Habilita BTC como colateral
    if enable_btc_collateral(exchange):
        add_log("🔓 BTC habilitado como colateral!")
    
    # Detecta colateral
    collateral_usd, collateral_coin, collateral_raw = get_collateral_usd(exchange)
    bot_state["usdt_balance"] = collateral_usd
    
    if collateral_coin == 'BTC':
        add_log(f"💰 Colateral: {collateral_raw:.8f} BTC | Margem: ${collateral_usd:.2f} USD")
        bot_state["coin_balance"] = collateral_raw
    else:
        add_log(f"💰 Margem: ${collateral_usd:.2f} USDT")
    
    for sym in symbols_to_scan:
        set_margin_leverage(exchange, sym, leverage)
    
    # [MELHORIA #4] Mão ajustada ao saldo real (nunca mais que 80% da margem)
    base_trade_amount = min(1.0, collateral_usd * 0.80)
    current_trade_amount = base_trade_amount
    in_position = False
    active_symbol = None
    entry_price = 0.0
    entry_side = None
    
    wins_consecutivos = 0
    meta_wins = 6
    scan_count = 0
    
    # [MELHORIA #5] Histórico de RSI para confirmação de reversão
    rsi_history = {}  # {symbol: [rsi_anterior, rsi_atual]}
    
    # Meta diária: 23%
    starting_balance = collateral_usd
    daily_target_pct = 0.23
    daily_target_usd = starting_balance * (1 + daily_target_pct)
    add_log(f"🎯 Meta diária: ${daily_target_usd:.2f} (+{daily_target_pct*100:.0f}% sobre ${starting_balance:.2f})")
    add_log(f"🧠 Filtros Ativos: EMA 200 + MACD Confirmation | TF: 5m")
    add_log(f"🃏 Mão inicial: ${base_trade_amount:.2f} (80% da margem, máx $1.00)")
    
    try:
        while bot_state["is_running"]:
            scan_count += 1
            
            collateral_usd, collateral_coin, collateral_raw = get_collateral_usd(exchange)
            bot_state["usdt_balance"] = collateral_usd
            if collateral_coin == 'BTC':
                bot_state["coin_balance"] = collateral_raw
            
            # Meta diária (exige lucro mínimo de $0.50 para evitar falso positivo)
            if not in_position and collateral_usd >= daily_target_usd:
                lucro = collateral_usd - starting_balance
                if lucro >= 0.50:  # Ignora flutuações de centavos no colateral BTC
                    add_log(f"{'='*50}")
                    add_log(f"🏆🏆🏆 META DIÁRIA BATIDA! 🏆🏆🏆")
                    add_log(f"Início: ${starting_balance:.2f} → Final: ${collateral_usd:.2f}")
                    add_log(f"Lucro: +${lucro:.2f} (+{(lucro/starting_balance)*100:.1f}%)")
                    add_log(f"{'='*50}")
                    log_trade('-', 'META_DIARIA', '-', 0, 0, 0, leverage, 0, 0, collateral_usd, wins_consecutivos, '🏆 META BATIDA', f"Lucro: +${lucro:.2f}")
                    bot_state["status"] = "🏆 Meta Diária Atingida!"
                    bot_state["is_running"] = False
                    break
            
            # Meta de wins
            if not in_position and wins_consecutivos >= meta_wins:
                add_log(f"🏆 META DE WINS! ({wins_consecutivos} vitórias)")
                log_trade('-', 'META_WINS', '-', 0, 0, 0, leverage, 0, 0, collateral_usd, wins_consecutivos, '🏆 WINS')
                bot_state["is_running"] = False
                break
            
            # [MELHORIA #4] Ajusta mão ao saldo disponível
            if current_trade_amount > collateral_usd * 0.80:
                current_trade_amount = collateral_usd * 0.80
                
            if collateral_usd < 0.50:
                add_log(f"❌ Saldo insuficiente: ${collateral_usd:.2f}. Desligando...")
                bot_state["is_running"] = False
                break

            # [MELHORIA #3] Verifica margem ANTES de tentar operar
            if not in_position and current_trade_amount < 0.10:
                add_log(f"⚠️ Mão muito pequena (${current_trade_amount:.2f}). Margem insuficiente para operar.")
                for _ in range(check_interval):
                    if not bot_state["is_running"]: break
                    time.sleep(1)
                continue

            if not in_position:
                add_log(f"── Scanner #{scan_count} | ${collateral_usd:.2f} ({collateral_coin}) | Mão: ${current_trade_amount:.2f} | Wins: {wins_consecutivos}/{meta_wins} ──")
                
                found_entry = False
                for sym in symbols_to_scan:
                    if not bot_state["is_running"] or found_entry: break
                    
                    coin_name = sym.split('/')[0]
                    bot_state["coin_name"] = coin_name
                    
                    # Busca 210 velas de 5m para ter dados suficientes para EMA 200
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
                    bot_state["rsi_status"] = f"Rev.Mart W:{wins_consecutivos}"
                    
                    # Define a alavancagem máxima segura permitida pela Bybit para a moeda
                    coin_leverage = 50 if coin_name in ['BTC', 'ETH'] else 25
                    
                    trend = "ALTA 📈" if current_price > ema200 else "BAIXA 📉"
                    macd_status = "FORÇA ⚡" if abs(hist) > abs(hist*0.1) else "FRACO ☁️"
                    
                    add_log(f"  {coin_name}: ${current_price:,.2f} | RSI: {rsi:.1f} | Tendência: {trend} | MACD: {hist:.2f}")
                    
                    detalhes_scan = {"ema200": f"{ema200:.2f}", "macd": f"{hist:.4f}", "msg": f"Trend: {trend}"}
                    log_trade(sym, 'SCAN', '-', current_price, rsi, current_trade_amount, coin_leverage, 0, 0, collateral_usd, wins_consecutivos, trend, detalhes_scan)
                    
                    prev_rsi = rsi_history.get(sym, rsi)
                    rsi_history[sym] = rsi
                    
                    # GATILHO LONG: Preço > EMA200 (Tendência de Alta) + RSI Subindo + MACD Histograma Positivo
                    if current_price > ema200 and rsi <= 35 and rsi > prev_rsi and hist > 0:
                        add_log(f"🔥 SINAL LONG PROFISSIONAL em {coin_name}!")
                        amount_to_buy = (current_trade_amount * coin_leverage) / current_price
                        tp_price = round(current_price * 1.01, 2)
                        sl_price = round(current_price * 0.992, 2)
                        entry_limit_price = round(current_price, 2)
                        
                        try:
                            # Tenta ajustar a alavancagem logo antes de entrar para garantir
                            set_margin_leverage(exchange, sym, coin_leverage)
                            order, filled = place_maker_entry(exchange, sym, 'buy', amount_to_buy, entry_limit_price, tp_price, sl_price)
                            if filled:
                                in_position, active_symbol, entry_price, entry_side = True, sym, current_price, 'LONG'
                                found_entry = True
                                log_trade(sym, 'ENTRADA', 'LONG', current_price, rsi, current_trade_amount, coin_leverage, tp_price, sl_price, collateral_usd, wins_consecutivos, '✅ SUCESSO', detalhes_scan)
                        except Exception as e: add_log(f"❌ Erro: {e}")
                            
                    # GATILHO SHORT: Preço < EMA200 (Tendência de Baixa) + RSI Caindo + MACD Histograma Negativo
                    elif current_price < ema200 and rsi >= 65 and rsi < prev_rsi and hist < 0:
                        add_log(f"🔥 SINAL SHORT PROFISSIONAL em {coin_name}!")
                        amount_to_sell = (current_trade_amount * coin_leverage) / current_price
                        tp_price = round(current_price * 0.99, 2)
                        sl_price = round(current_price * 1.008, 2)
                        entry_limit_price = round(current_price, 2)
                        
                        try:
                            set_margin_leverage(exchange, sym, coin_leverage)
                            order, filled = place_maker_entry(exchange, sym, 'sell', amount_to_sell, entry_limit_price, tp_price, sl_price)
                            if filled:
                                in_position, active_symbol, entry_price, entry_side = True, sym, current_price, 'SHORT'
                                found_entry = True
                                log_trade(sym, 'ENTRADA', 'SHORT', current_price, rsi, current_trade_amount, coin_leverage, tp_price, sl_price, collateral_usd, wins_consecutivos, '✅ SUCESSO', detalhes_scan)
                        except Exception as e: add_log(f"❌ Erro: {e}")
                    
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
                        nivel_atual = min(wins_consecutivos, meta_wins) + 1
                        
                        add_log(f"📊 [RM Clássico Nível {nivel_atual}] {coin_name} {entry_side} ({leverage}x)")
                        add_log(f"  🎯 Preço: {entry_price:,.2f} → {current_price:,.2f} | P&L: {pnl_emoji} {pnl_pct:+.2f}%")
                        
                    positions = exchange.fetch_positions([active_symbol])
                    has_position = False
                    for pos in positions:
                        contracts = float(pos.get('contracts', 0))
                        if contracts > 0:
                            has_position = True
                            unrealized_pnl = float(pos.get('unrealizedPnl', 0))
                            add_log(f"  💰 Tamanho: {contracts} contratos | PnL Unrealized: ${unrealized_pnl:+.4f} USD")
                            break
                    
                    if not has_position:
                        new_collateral_usd, _, _ = get_collateral_usd(exchange)
                        resultado = get_closed_pnl(exchange, active_symbol, limit=1)
                        
                        if resultado > 0:
                            wins_consecutivos += 1
                            current_trade_amount *= 2
                            # [MELHORIA #4] Limita mão ao saldo real
                            current_trade_amount = min(current_trade_amount, new_collateral_usd * 0.80)
                            add_log(f"{'='*50}")
                            add_log(f"✅ WIN #{wins_consecutivos}! +${resultado:.4f} | Mão: ${current_trade_amount:.2f}")
                            add_log(f"{'='*50}")
                            log_trade('-', 'SAÍDA', entry_side or '-', current_price if closes else 0, 0, current_trade_amount, leverage, 0, 0, new_collateral_usd, wins_consecutivos, '✅ WIN', f"+${resultado:.4f}")
                        else:
                            wins_consecutivos = 0
                            base_trade_amount = min(1.0, new_collateral_usd * 0.80)
                            current_trade_amount = base_trade_amount
                            add_log(f"{'='*50}")
                            add_log(f"🔴 LOSS. ${resultado:.4f} | Reset mão: ${current_trade_amount:.2f}")
                            add_log(f"{'='*50}")
                            log_trade('-', 'SAÍDA', entry_side or '-', current_price if closes else 0, 0, current_trade_amount, leverage, 0, 0, new_collateral_usd, wins_consecutivos, '🔴 LOSS', f"${resultado:.4f}")
                        
                        in_position = False
                        active_symbol = None
                        entry_price = 0.0
                        entry_side = None
                        bot_state["usdt_balance"] = new_collateral_usd
                except Exception as e:
                    add_log(f"⚠️ Aviso posição: {e}")
                
            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)
                
    except Exception as e:
        add_log(f"Erro Crítico: {e}")
        log_trade('-', 'ERRO_CRITICO', '-', 0, 0, 0, leverage, 0, 0, 0, wins_consecutivos, '💥 CRASH', str(e))
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("Bot Finalizado.")
