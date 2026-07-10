import time
import sys
import os
import csv
from datetime import datetime
import pandas as pd
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_ohlcv_data, calculate_rsi, calculate_ema, calculate_macd
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance, get_available_margin_usd, enable_btc_collateral, place_maker_entry, get_closed_pnl

# --- SISTEMA DE LOG EM CSV ---
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'chameleon_trades.csv')

def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Regime', 'Tipo', 'Direção', 'Preço',
                'RSI', 'EMA200', 'MACD_Hist', 'Alavancagem', 'Quantidade',
                'Saldo USD', 'Status', 'Detalhes'
            ])

def log_trade(symbol, regime, tipo, direcao, preco, rsi, ema200, macd_hist, leverage, quantidade, saldo_usd, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, regime, tipo, direcao, f'{preco:.2f}',
                f'{rsi:.1f}' if rsi else '-',
                f'{ema200:.2f}' if ema200 else '-',
                f'{macd_hist:.4f}' if macd_hist else '-',
                f'{leverage}x' if leverage else '-',
                f'{quantidade:.8f}',
                f'{saldo_usd:.2f}', status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso: Não foi possível gravar log CSV: {e}")

# --- DETECÇÃO DE REGIME DE MERCADO ---
def detect_market_regime(ohlcv_5m, ohlcv_1h, ohlcv_15m):
    closes_5m = ohlcv_5m['c']
    current_price_5m = closes_5m[-1]
    ema20_5m  = calculate_ema(closes_5m, period=20)
    ema50_5m  = calculate_ema(closes_5m, period=50)
    ema200_5m = calculate_ema(closes_5m, period=200)
    rsi_5m    = calculate_rsi(closes_5m, period=14)
    _, _, hist_5m = calculate_macd(closes_5m)

    # Bandas de Bollinger para 5m
    df_5m = pd.DataFrame(ohlcv_5m)
    df_5m["MA20"]   = df_5m["c"].rolling(window=20).mean()
    df_5m["STDDEV"] = df_5m["c"].rolling(window=20).std()
    df_5m["UpperBB"] = df_5m["MA20"] + (df_5m["STDDEV"] * 2)
    df_5m["LowerBB"] = df_5m["MA20"] - (df_5m["STDDEV"] * 2)
    ma20_val = df_5m["MA20"].iloc[-1]
    bb_width_5m = (df_5m["UpperBB"].iloc[-1] - df_5m["LowerBB"].iloc[-1]) / ma20_val if ma20_val != 0 else 0

    # ATR para 15m (volatilidade)
    df_15m = pd.DataFrame(ohlcv_15m)
    df_15m["TR"] = np.maximum(
        df_15m["h"] - df_15m["l"],
        np.maximum(
            abs(df_15m["h"] - df_15m["c"].shift()),
            abs(df_15m["l"] - df_15m["c"].shift())
        )
    )
    atr_15m = df_15m["TR"].rolling(window=14).mean().iloc[-1] if not df_15m["TR"].empty else 0

    # EMA200 no 1h (tendência de longo prazo)
    closes_1h  = ohlcv_1h['c']
    ema200_1h  = calculate_ema(closes_1h, period=200)

    # Tendência de Alta Forte
    if (current_price_5m > ema20_5m and ema20_5m > ema50_5m and ema50_5m > ema200_5m
            and current_price_5m > ema200_1h and hist_5m > 0 and bb_width_5m < 0.04):
        return 'UPTREND'
    # Tendência de Baixa Forte
    elif (current_price_5m < ema20_5m and ema20_5m < ema50_5m and ema50_5m < ema200_5m
            and current_price_5m < ema200_1h and hist_5m < 0 and bb_width_5m < 0.04):
        return 'DOWNTREND'
    # Lateralização (Range)
    elif (abs(current_price_5m - ema200_5m) / ema200_5m < 0.008
            and 35 < rsi_5m < 65 and -0.001 < hist_5m < 0.001 and bb_width_5m > 0.01):
        return 'RANGE'
    # Alta Volatilidade / Indefinido
    elif atr_15m > (current_price_5m * 0.005):
        return 'VOLATILE'

    return 'NEUTRAL'

# --- ESTRATÉGIA DE TREND FOLLOWING ---
def execute_trend_following(exchange, symbol, current_price, regime, signals, usdt_balance, leverage):
    RISK_PER_TRADE_PCT = 0.01  # 1% do capital por trade

    if usdt_balance < 2.0:
        add_log(f"⚠️ Saldo USDT insuficiente para Trend Following ({usdt_balance:.2f} < 2.0).")
        return False

    trade_size_usd = max(2.0, usdt_balance * RISK_PER_TRADE_PCT * leverage)
    amount   = trade_size_usd / current_price
    tp_pct   = 0.015
    sl_pct   = 0.005

    if regime == 'UPTREND':
        tp_price = current_price * (1 + tp_pct)
        sl_price = current_price * (1 - sl_pct)
        add_log(f"📈 LONG em {symbol} (UPTREND) | Entrada: {current_price:.2f} TP: {tp_price:.2f} SL: {sl_price:.2f}")
        _, filled = place_maker_entry(exchange, symbol, 'buy', amount, current_price, tp_price, sl_price)
        return filled
    elif regime == 'DOWNTREND':
        tp_price = current_price * (1 - tp_pct)
        sl_price = current_price * (1 + sl_pct)
        add_log(f"📉 SHORT em {symbol} (DOWNTREND) | Entrada: {current_price:.2f} TP: {tp_price:.2f} SL: {sl_price:.2f}")
        _, filled = place_maker_entry(exchange, symbol, 'sell', amount, current_price, tp_price, sl_price)
        return filled
    return False

# --- ESTRATÉGIA DE MEAN REVERSION ---
def execute_mean_reversion(exchange, symbol, current_price, regime, signals, usdt_balance, leverage):
    RISK_PER_TRADE_PCT = 0.005  # 0.5% do capital por trade (mais conservador para range)

    if usdt_balance < 2.0:
        add_log(f"⚠️ Saldo USDT insuficiente para Mean Reversion ({usdt_balance:.2f} < 2.0).")
        return False

    trade_size_usd = max(2.0, usdt_balance * RISK_PER_TRADE_PCT * leverage)
    amount = trade_size_usd / current_price
    tp_pct = 0.0075
    sl_pct = 0.0025

    rsi = signals.get('rsi')
    if rsi is not None and rsi < 30:
        tp_price = current_price * (1 + tp_pct)
        sl_price = current_price * (1 - sl_pct)
        add_log(f"🔄 COMPRA em {symbol} (RANGE - RSI Sobrevendido {rsi:.1f}) | TP: {tp_price:.2f} SL: {sl_price:.2f}")
        _, filled = place_maker_entry(exchange, symbol, 'buy', amount, current_price, tp_price, sl_price)
        return filled
    elif rsi is not None and rsi > 70:
        tp_price = current_price * (1 - tp_pct)
        sl_price = current_price * (1 + sl_pct)
        add_log(f"🔄 VENDA em {symbol} (RANGE - RSI Sobrecomprado {rsi:.1f}) | TP: {tp_price:.2f} SL: {sl_price:.2f}")
        _, filled = place_maker_entry(exchange, symbol, 'sell', amount, current_price, tp_price, sl_price)
        return filled
    return False

# --- LOOP PRINCIPAL DA ESTRATÉGIA CAMALEÃO ---
def run_chameleon_strategy(exchange, symbol='BTC/USDT:USDT', leverage=10, check_interval=60):
    init_trade_log()

    is_multi = (symbol == "MULTI")
    symbols_to_scan = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "ADA/USDT:USDT", "DOGE/USDT:USDT"] if is_multi else [symbol]

    add_log(f"{'='*55}")
    add_log(f"🦎 ESTRATÉGIA CAMALEÃO — {'MULTI-SCAN' if is_multi else symbol}")
    add_log(f"📊 Adaptação Dinâmica ao Regime de Mercado | Alavancagem: {leverage}x")
    add_log(f"{'='*55}")

    bot_state["is_running"] = True
    bot_state["status"]     = f"🦎 Camaleão ({leverage}x)"
    bot_state["coin_name"]  = "SCANNING" if is_multi else symbol.split('/')[0]

    enable_btc_collateral(exchange)

    for sym in symbols_to_scan:
        try:
            exchange.set_leverage(leverage, sym)
            add_log(f"Alavancagem setada para {leverage}x em {sym}!")
        except Exception as e:
            pass

    # Lê saldo inicial
    collateral_usd, _ = get_available_margin_usd(exchange)
    if collateral_usd is None:
        add_log("❌ Falha ao ler saldo inicial. Encerrando.")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Erro API"
        return

    bot_state["usdt_balance"]       = collateral_usd
    initial_collateral_usd          = collateral_usd
    daily_profit_target_usd         = max(0.50, 0.05 * collateral_usd)   # meta +5% (mínimo $0.50)
    daily_loss_limit_usd            = min(-0.25, -0.02 * collateral_usd)  # limite -2% (mínimo -$0.25 para evitar desligamento precoce)

    active_positions = {}
    MAX_POSITIONS = 3
    scan_count   = 0

    try:
        while bot_state["is_running"]:
            scan_count += 1
            collateral_usd, _ = get_available_margin_usd(exchange)
            if collateral_usd is None:
                add_log("⚠️ Erro ao ler saldo. Aguardando...")
                time.sleep(10)
                continue
            bot_state["usdt_balance"] = collateral_usd

            # Verifica metas de lucro/perda diária
            delta = collateral_usd - initial_collateral_usd
            if delta >= daily_profit_target_usd:
                add_log(f"🏆 Meta de lucro diário atingida! Lucro: ${delta:.2f}. Desligando bot.")
                break
            if delta <= daily_loss_limit_usd:
                add_log(f"❌ Limite de perda diário atingido! Perda: ${abs(delta):.2f}. Desligando bot.")
                break

            # --- MONITORAMENTO DE POSIÇÕES ABERTAS ---
            try:
                all_positions = []
                for sym in symbols_to_scan:
                    try:
                        all_positions.extend(exchange.fetch_positions([sym]))
                    except:
                        pass
                current_open_symbols = set()

                for pos in all_positions:
                    contracts = float(pos.get('contracts') or 0)
                    if contracts > 0:
                        sym = pos['symbol']
                        current_open_symbols.add(sym)

                        entry_p = float(pos.get('entryPrice') or 0)
                        side = pos['side'].upper()
                        if sym not in active_positions:
                            active_positions[sym] = {'side': side, 'entry_price': entry_p}
                            log_trade(sym, 'DETECT', 'ENTRADA', side, entry_p, 0, 0, 0, leverage, contracts, collateral_usd, '✅ Posição Detectada')

                        unrealized_pnl = float(pos.get('unrealizedPnl') or 0)
                        liq_price = pos.get('liquidationPrice')
                        roi = pos.get('percentage')
                        margin = pos.get('initialMargin')

                        liq_str = f" | Liq: ${float(liq_price or 0):,.2f}" if liq_price else ""
                        roi_str = f" | ROI: {float(roi or 0):+.2f}%" if roi is not None else ""
                        marg_str = f" | Margem: ${float(margin or 0):.2f}" if margin else ""

                        add_log(f"📊 {sym} {side} Aberto:")
                        add_log(f"  💰 Qtd: {contracts}{marg_str}{liq_str}")
                        add_log(f"  💵 PnL: ${unrealized_pnl:+.4f}{roi_str}")
                
                # Checa fechamentos por TP/SL ou externo
                closed_symbols = list(set(active_positions.keys()) - current_open_symbols)
                for sym in closed_symbols:
                    new_collateral_usd, _ = get_available_margin_usd(exchange)
                    time.sleep(3) # Espera a Bybit registrar
                    resultado = get_closed_pnl(exchange, sym, limit=1)
                    resultado_emoji = "🏆 LUCRO" if resultado > 0 else "💀 LOSS"

                    add_log(f"{'='*50}")
                    add_log(f"{resultado_emoji}: Fechamento em {sym} | ${resultado:+.4f}")
                    add_log(f"{'='*50}")

                    try:
                        ticker = exchange.fetch_ticker(sym)
                        close_price = float(ticker['last'])
                    except:
                        close_price = active_positions[sym]['entry_price']

                    resultado_str = f"{'+$' if resultado >= 0 else '-$'}{abs(resultado):.4f}"
                    log_trade(sym, 'OUT', 'SAÍDA', active_positions[sym]['side'], close_price, 0, 0, 0, leverage, 0, new_collateral_usd, resultado_emoji, resultado_str)
                    del active_positions[sym]
                    collateral_usd = new_collateral_usd
            except Exception as e:
                add_log(f"⚠️ Erro ao monitorar posições: {e}")

            # --- MONITORAMENTO DE MUDANÇA DE REGIME PARA POSIÇÕES ABERTAS ---
            symbols_to_check = list(active_positions.keys())
            for sym in symbols_to_check:
                try:
                    ohlcv_5m  = fetch_ohlcv_data(exchange, sym, timeframe='5m',  limit=210)
                    ohlcv_15m = fetch_ohlcv_data(exchange, sym, timeframe='15m', limit=210)
                    ohlcv_1h  = fetch_ohlcv_data(exchange, sym, timeframe='1h',  limit=210)
                    if not ohlcv_5m or not ohlcv_15m or not ohlcv_1h: continue

                    regime_pos = detect_market_regime(ohlcv_5m, ohlcv_1h, ohlcv_15m)
                    side_pos = active_positions[sym]['side']

                    if ((regime_pos == 'DOWNTREND' and (side_pos == 'LONG' or side_pos == 'BUY')) or
                        (regime_pos == 'UPTREND' and (side_pos == 'SHORT' or side_pos == 'SELL')) or
                        regime_pos == 'VOLATILE'):
                        
                        add_log(f"⚠️ Regime em {sym} mudou para {regime_pos}! Fechando posição {side_pos} por segurança.")
                        
                        positions = exchange.fetch_positions([sym])
                        contracts = 0
                        for pos in positions:
                            if pos['symbol'] == sym:
                                contracts = float(pos.get('contracts') or 0)
                                break
                        
                        if contracts > 0:
                            side_to_close = 'sell' if side_pos in ['LONG', 'BUY'] else 'buy'
                            exchange.create_order(sym, 'market', side_to_close, contracts, params={'reduceOnly': True, 'category': 'linear'})
                            
                            new_collateral_usd, _ = get_available_margin_usd(exchange)
                            time.sleep(3)
                            resultado = get_closed_pnl(exchange, sym, limit=1)
                            resultado_emoji = "🏆 LUCRO" if resultado > 0 else "💀 LOSS"
                            resultado_str = f"{'+$' if resultado >= 0 else '-$'}{abs(resultado):.4f}"
                            
                            log_trade(sym, regime_pos, 'SAÍDA_REGIME', side_pos, ohlcv_5m['c'][-1], 0, 0, 0, leverage, contracts, new_collateral_usd, resultado_emoji, f"Fechamento por Regime: {resultado_str}")
                            
                            del active_positions[sym]
                            collateral_usd = new_collateral_usd
                except Exception as e:
                    add_log(f"⚠️ Erro ao verificar regime de saída para {sym}: {e}")

            # --- BUSCA POR NOVAS ENTRADAS ---
            if len(active_positions) < MAX_POSITIONS:
                add_log(f"── Scanner #{scan_count} | Abertas {len(active_positions)}/{MAX_POSITIONS} | Saldo: ${collateral_usd:.2f} ──")
                
                for sym in symbols_to_scan:
                    if not bot_state["is_running"] or len(active_positions) >= MAX_POSITIONS: break
                    if sym in active_positions: continue
                    
                    coin_name = sym.split('/')[0]
                    bot_state["coin_name"] = coin_name
                    
                    ohlcv_5m  = fetch_ohlcv_data(exchange, sym, timeframe='5m',  limit=210)
                    ohlcv_15m = fetch_ohlcv_data(exchange, sym, timeframe='15m', limit=210)
                    ohlcv_1h  = fetch_ohlcv_data(exchange, sym, timeframe='1h',  limit=210)
                    
                    if not ohlcv_5m or not ohlcv_15m or not ohlcv_1h:
                        continue
                    
                    regime_atual = detect_market_regime(ohlcv_5m, ohlcv_1h, ohlcv_15m)
                    bot_state["status"] = f"🦎 Analisando ({regime_atual})"
                    
                    closes_5m     = ohlcv_5m['c']
                    current_price = closes_5m[-1]
                    rsi           = calculate_rsi(closes_5m, period=14)
                    ema200        = calculate_ema(closes_5m, period=200)
                    _, _, hist    = calculate_macd(closes_5m)
                    
                    if rsi is None or ema200 is None or hist is None: continue
                    
                    bot_state["current_price"] = current_price
                    bot_state["rsi"]           = rsi
                    
                    signals = {'rsi': rsi, 'ema200': ema200, 'macd_hist': hist, 'current_price': current_price}
                    
                    log_trade(sym, regime_atual, 'SCAN', '-', current_price, rsi, ema200, hist, leverage, 0, collateral_usd, bot_state["status"], str(signals))
                    
                    if regime_atual in ['UPTREND', 'DOWNTREND']:
                        if execute_trend_following(exchange, sym, current_price, regime_atual, signals, collateral_usd, leverage):
                            entry_side = 'LONG' if regime_atual == 'UPTREND' else 'SHORT'
                            active_positions[sym] = {'side': entry_side, 'entry_price': current_price}
                            add_log(f"✅ Posição {entry_side} aberta em {sym} @ {current_price:.2f}")
                            
                    elif regime_atual == 'RANGE':
                        if execute_mean_reversion(exchange, sym, current_price, regime_atual, signals, collateral_usd, leverage):
                            entry_side = 'LONG' if (rsi < 30) else 'SHORT'
                            active_positions[sym] = {'side': entry_side, 'entry_price': current_price}
                            add_log(f"✅ Posição {entry_side} aberta em {sym} @ {current_price:.2f}")
                            
                    elif regime_atual == 'VOLATILE':
                        pass
                    
                    time.sleep(0.5)

            for _ in range(check_interval):
                if not bot_state["is_running"]: break
                time.sleep(1)
                
    except Exception as e:
        add_log(f"💥 Erro Crítico na Estratégia Camaleão: {e}")
    finally:
        add_log(f"{'='*55}")
        add_log("Estratégia Camaleão Finalizada.")
        bot_state["is_running"] = False
        bot_state["status"]     = "🔴 Desligado"
