from core.market_data import fetch_historical_data
import time
import sys
import os
import csv
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_ohlcv_data, calculate_rsi, calculate_ema, calculate_macd
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance, get_available_margin_usd, enable_btc_collateral, place_maker_entry

# --- SISTEMA DE LOG EM CSV ---
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'sniper_trades.csv')

def init_trade_log():
    """Cria o diretório e o arquivo CSV de log se não existirem."""
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço',
                'RSI', 'EMA200', 'MACD', 'Quantidade', 'Alavancagem', 'TP Alvo',
                'Saldo USDT', 'Status', 'Detalhes'
            ])

def log_trade(symbol, tipo, direcao, preco, rsi, quantidade, leverage, tp_alvo, saldo, status, detalhes=''):
    """Grava uma linha no CSV de log de trades."""
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.2f}',
                f'{rsi:.1f}', f'{detalhes.get("ema200", "-")}', f'{detalhes.get("macd", "-")}',
                f'{quantidade:.8f}', f'{leverage}x',
                f'{tp_alvo:.2f}' if tp_alvo else '-',
                f'{saldo:.2f}', status, detalhes.get("msg", "")
            ])
    except Exception as e:
        add_log(f"Aviso: Não foi possível gravar log CSV: {e}")

# --- FUNÇÕES PRINCIPAIS ---

def set_margin_leverage(exchange, symbol, leverage):
    try:
        exchange.set_leverage(leverage, symbol)
        add_log(f"Alavancagem setada para {leverage}x em {symbol}!")
        return True
    except Exception as e:
        return False

def get_collateral_usd(exchange):
    """Usa a margem real disponível (totalAvailableBalance) da Bybit UTA."""
    available, total_equity = get_available_margin_usd(exchange)
    
    if available > 0.01:
        # Detecta qual moeda é o colateral principal
        btc_bal = get_unified_balance(exchange, 'BTC')
        if btc_bal > 0.0:
            return available, 'BTC', btc_bal
        return available, 'USDT', available
    
    return 0.0, 'NONE', 0.0

def run_sniper_leverage(exchange, symbol='BTC/USDT:USDT', leverage=100, check_interval=60):
    is_multi = (symbol == "MULTI")
    symbols_to_scan = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"] if is_multi else [symbol]
    
    # Inicializa o log CSV
    init_trade_log()
    
    add_log(f"🎯 [SNIPER ALAVANCADO] Iniciando {'MULTI-SCAN (BTC, ETH, SOL)' if is_multi else symbol} com {leverage}x!")
    add_log(f"📋 Log de trades será gravado em: logs/sniper_trades.csv")
    bot_state["is_running"] = True
    bot_state["status"] = f"🎯 Sniper Ativo ({leverage}x)"
    
    bot_state["coin_name"] = "SCANNING" if is_multi else symbol.split('/')[0]
    bot_state["coin_balance"] = 0.0

    # Habilita BTC como colateral para Derivativos (resolve erro 110007)
    if enable_btc_collateral(exchange):
        add_log("🔓 BTC habilitado como colateral para Futuros!")
    
    # Detecta colateral: BTC ou USDT (agora usando margem REAL disponível)
    collateral_usd, collateral_coin, collateral_raw = get_collateral_usd(exchange)
    bot_state["usdt_balance"] = collateral_usd
    
    if collateral_coin == 'BTC':
        add_log(f"💰 Colateral: {collateral_raw:.8f} BTC | Margem disponível: ${collateral_usd:.2f} USD")
        bot_state["coin_balance"] = collateral_raw
    else:
        add_log(f"💰 Margem disponível: ${collateral_usd:.2f} USDT")
    
    for sym in symbols_to_scan:
        set_margin_leverage(exchange, sym, leverage)
        
    in_position = False
    active_symbol = None
    entry_price = 0.0
    entry_side = None
    scan_count = 0
    
    # Filtro de confirmação RSI
    rsi_history = {}
    
    # Meta diária: 23%
    starting_balance = collateral_usd
    daily_target_pct = 0.23
    daily_target_usd = starting_balance * (1 + daily_target_pct)
    add_log(f"🎯 Meta diária: ${daily_target_usd:.2f} (+{daily_target_pct*100:.0f}% sobre ${starting_balance:.2f})")
    add_log(f"🧠 Filtros: EMA 200 + MACD Confirmation | TF: 5m")
    
    try:
        while bot_state["is_running"]:
            scan_count += 1
            
            # Atualiza colateral (BTC ou USDT)
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
                    log_trade('-', 'META_DIARIA', '-', 0, 0, 0, leverage, 0, collateral_usd, '🏆 META BATIDA', f"Lucro: +${lucro:.2f}")
                    bot_state["status"] = "🏆 Meta Diária Atingida!"
                    bot_state["is_running"] = False
                    break
            
            # ============================================================
            # MODO SCANNER: Procurando oportunidade em todas as moedas
            # ============================================================
            if not in_position and collateral_usd >= 0.50:
                add_log(f"── Scanner #{scan_count} | ${collateral_usd:.2f} ({collateral_coin}) ──")
                
                found_entry = False
                for sym in symbols_to_scan:
                    if not bot_state["is_running"] or found_entry: break
                    
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
                    add_log(f"  {coin_name}: ${current_price:,.2f} | RSI: {rsi:.1f} | Tendência: {trend} | MACD: {hist:.2f}")
                    
                    detalhes_scan = {"ema200": f"{ema200:.2f}", "macd": f"{hist:.4f}", "msg": f"Trend: {trend}"}
                    log_trade(sym, 'SCAN', '-', current_price, rsi, 0, leverage, 0, collateral_usd, trend, detalhes_scan)
                    
                    prev_rsi = rsi_history.get(sym, rsi)
                    rsi_history[sym] = rsi
                        
                    # GATILHO LONG: Acima da EMA 200 + RSI Subindo + MACD Positivo
                    if current_price > ema200 and rsi <= 45 and rsi > prev_rsi: 
                        add_log(f"🎯 SNIPER LONG PROFISSIONAL em {coin_name}!")
                        trade_size = collateral_usd * 0.95
                        amount_to_buy = (trade_size * leverage) / current_price
                        tp_price = round(current_price * 1.01, 2)
                        sl_price = round(current_price * 0.995, 2)
                        entry_limit_price = round(current_price, 2)
                        
                        try:
                            order, filled = place_maker_entry(exchange, sym, 'buy', amount_to_buy, entry_limit_price, tp_price, sl_price)
                            if filled:
                                in_position, active_symbol, entry_price, entry_side = True, sym, current_price, 'LONG'
                                found_entry = True
                                log_trade(sym, 'ENTRADA', 'LONG', current_price, rsi, amount_to_buy, leverage, tp_price, collateral_usd, '✅ SUCESSO', detalhes_scan)
                        except Exception as e: add_log(f"❌ Erro: {e}")
                            
                    # GATILHO SHORT: Abaixo da EMA 200 + RSI Caindo + MACD Negativo
                    elif current_price < ema200 and rsi >= 55 and rsi < prev_rsi:
                        add_log(f"🎯 SNIPER SHORT PROFISSIONAL em {coin_name}!")
                        trade_size = collateral_usd * 0.95
                        amount_to_sell = (trade_size * leverage) / current_price
                        tp_price = round(current_price * 0.99, 2)
                        sl_price = round(current_price * 1.005, 2)
                        entry_limit_price = round(current_price, 2)
                        
                        try:
                            order, filled = place_maker_entry(exchange, sym, 'sell', amount_to_sell, entry_limit_price, tp_price, sl_price)
                            if filled:
                                in_position, active_symbol, entry_price, entry_side = True, sym, current_price, 'SHORT'
                                found_entry = True
                                log_trade(sym, 'ENTRADA', 'SHORT', current_price, rsi, amount_to_sell, leverage, tp_price, collateral_usd, '✅ SUCESSO', detalhes_scan)
                        except Exception as e: add_log(f"❌ Erro: {e}")
                    elif rsi <= 45:
                        add_log(f"  ⏳ {coin_name}: RSI caindo ({prev_rsi:.1f}→{rsi:.1f}), aguardando reversão...")
                    elif rsi >= 55:
                        add_log(f"  ⏳ {coin_name}: RSI subindo ({prev_rsi:.1f}→{rsi:.1f}), aguardando reversão...")
                    
                    time.sleep(0.5)
                    
            # ============================================================
            # MODO POSIÇÃO ABERTA: Monitorando trade ativo
            # ============================================================
            elif in_position and active_symbol:
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
                
                try:
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
                        add_log(f"${collateral_usd:.2f} → ${new_collateral_usd:.2f}")
                        add_log(f"{'='*50}")
                        
                        log_trade(active_symbol, 'SAÍDA', entry_side, current_price if closes else 0, 0, 0, leverage, 0, new_collateral_usd, resultado_emoji, f"${resultado:+.4f}")
                        
                        in_position = False
                        active_symbol = None
                        entry_price = 0.0
                        entry_side = None
                        add_log("🔄 Voltando ao Scanner...")
                        
                except Exception as e:
                    add_log(f"⚠️ Aviso posição: {e}")
                
            elif not in_position and collateral_usd < 0.50:
                add_log(f"⚠️ Saldo insuficiente: ${collateral_usd:.2f}")
                
            for _ in range(check_interval):
                if not bot_state["is_running"]: break
                time.sleep(1)
                
    except Exception as e:
        add_log(f"Erro Crítico Sniper: {e}")
        log_trade('-', 'ERRO_CRITICO', '-', 0, 0, 0, leverage, 0, 0, '💥 CRASH', str(e))
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("Bot Sniper Finalizado.")

