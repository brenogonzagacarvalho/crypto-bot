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
from core.balance_utils import get_unified_balance, get_available_margin_usd, enable_btc_collateral, place_maker_entry

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

    if usdt_balance < 10:
        add_log(f"⚠️ Saldo USDT insuficiente para Trend Following ({usdt_balance:.2f} < 10).")
        return False

    trade_size_usd = usdt_balance * RISK_PER_TRADE_PCT * leverage
    if trade_size_usd < 1:
        add_log(f"⚠️ Tamanho de trade muito pequeno ({trade_size_usd:.2f} USD).")
        return False

    amount   = trade_size_usd / current_price
    tp_pct   = 0.01
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

    if usdt_balance < 10:
        add_log(f"⚠️ Saldo USDT insuficiente para Mean Reversion ({usdt_balance:.2f} < 10).")
        return False

    trade_size_usd = usdt_balance * RISK_PER_TRADE_PCT * leverage
    if trade_size_usd < 1:
        add_log(f"⚠️ Tamanho de trade muito pequeno ({trade_size_usd:.2f} USD).")
        return False

    amount = trade_size_usd / current_price
    tp_pct = 0.005
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

    add_log(f"{'='*55}")
    add_log(f"🦎 ESTRATÉGIA CAMALEÃO — {symbol}")
    add_log(f"📊 Adaptação Dinâmica ao Regime de Mercado")
    add_log(f"{'='*55}")

    bot_state["is_running"] = True
    bot_state["status"]     = "🟢 Analisando Regimes"
    bot_state["coin_name"]  = symbol.split('/')[0]

    enable_btc_collateral(exchange)

    try:
        exchange.set_leverage(leverage, symbol)
        add_log(f"Alavancagem setada para {leverage}x em {symbol}!")
    except Exception as e:
        add_log(f"Aviso: Não foi possível setar alavancagem para {leverage}x: {e}")

    # Lê saldo inicial ANTES de usar collateral_usd
    collateral_usd, _ = get_available_margin_usd(exchange)
    if collateral_usd is None:
        add_log("❌ Falha ao ler saldo inicial. Encerrando.")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Erro API"
        return

    bot_state["usdt_balance"]       = collateral_usd
    initial_collateral_usd          = collateral_usd
    daily_profit_target_usd         = 0.05 * collateral_usd   # meta +5%
    daily_loss_limit_usd            = -0.02 * collateral_usd  # limite -2%

    in_position  = False
    active_symbol = None
    entry_price  = 0.0
    entry_side   = None
    regime_atual = 'NEUTRAL'
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

            add_log(f"── Scan #{scan_count} | ${collateral_usd:.2f} USD ──")

            # Coleta de dados para detecção de regime
            ohlcv_5m  = fetch_ohlcv_data(exchange, symbol, timeframe='5m',  limit=210)
            ohlcv_15m = fetch_ohlcv_data(exchange, symbol, timeframe='15m', limit=210)
            ohlcv_1h  = fetch_ohlcv_data(exchange, symbol, timeframe='1h',  limit=210)

            if not ohlcv_5m or not ohlcv_15m or not ohlcv_1h:
                add_log("Erro ao buscar dados OHLCV. Pulando scan.")
                time.sleep(check_interval)
                continue

            # Verifica metas de lucro/perda diária
            delta = collateral_usd - initial_collateral_usd
            if delta >= daily_profit_target_usd:
                add_log(f"🏆 Meta de lucro diário atingida! Lucro: ${delta:.2f}. Desligando bot.")
                break
            if delta <= daily_loss_limit_usd:
                add_log(f"❌ Limite de perda diário atingido! Perda: ${abs(delta):.2f}. Desligando bot.")
                break

            regime_atual = detect_market_regime(ohlcv_5m, ohlcv_1h, ohlcv_15m)
            add_log(f"Regime de Mercado Detectado: {regime_atual}")
            bot_state["status"] = f"🟢 Analisando ({regime_atual})"

            closes_5m     = ohlcv_5m['c']
            current_price = closes_5m[-1]
            rsi           = calculate_rsi(closes_5m, period=14)
            ema200        = calculate_ema(closes_5m, period=200)
            _, _, hist    = calculate_macd(closes_5m)

            bot_state["current_price"] = current_price
            bot_state["rsi"]           = rsi

            signals = {'rsi': rsi, 'ema200': ema200, 'macd_hist': hist, 'current_price': current_price}

            log_trade(symbol, regime_atual, 'SCAN', '-', current_price, rsi, ema200, hist, leverage, 0, collateral_usd, bot_state["status"], str(signals))

            if not in_position:
                if regime_atual in ['UPTREND', 'DOWNTREND']:
                    if execute_trend_following(exchange, symbol, current_price, regime_atual, signals, collateral_usd, leverage):
                        in_position   = True
                        active_symbol = symbol
                        entry_price   = current_price
                        entry_side    = 'LONG' if regime_atual == 'UPTREND' else 'SHORT'
                        add_log(f"✅ Posição {entry_side} aberta em {active_symbol} @ {entry_price:.2f}")
                elif regime_atual == 'RANGE':
                    if execute_mean_reversion(exchange, symbol, current_price, regime_atual, signals, collateral_usd, leverage):
                        in_position   = True
                        active_symbol = symbol
                        entry_price   = current_price
                        rsi_val       = signals.get('rsi')
                        entry_side    = 'LONG' if (rsi_val is not None and rsi_val < 30) else 'SHORT'
                        add_log(f"✅ Posição {entry_side} aberta em {active_symbol} @ {entry_price:.2f}")
                elif regime_atual == 'VOLATILE':
                    add_log("⚠️ Mercado Volátil. Não operando neste regime.")
            else:
                # Monitora posição existente
                try:
                    positions    = exchange.fetch_positions([active_symbol])
                    has_position = False
                    for pos in positions:
                        if float(pos.get('contracts', 0)) != 0:
                            has_position = True
                            pnl_pct = float(pos.get('percentage', 0))
                            add_log(f"Monitorando {active_symbol} ({entry_side}) @ {entry_price:.2f} | PnL: {pnl_pct:.2f}%")
                            break
                    if not has_position:
                        add_log(f"✅ Posição em {active_symbol} fechada (TP/SL ou manual).")
                        in_position   = False
                        active_symbol = None
                        entry_price   = 0.0
                        entry_side    = None
                except Exception as e:
                    add_log(f"Erro ao verificar posições: {e}")
                    in_position   = False
                    active_symbol = None
                    entry_price   = 0.0
                    entry_side    = None

                # Sai se o regime inverter contra a posição
                if ((regime_atual == 'DOWNTREND' and entry_side == 'LONG') or
                        (regime_atual == 'UPTREND' and entry_side == 'SHORT') or
                        regime_atual == 'VOLATILE'):
                    add_log(f"⚠️ Regime mudou para {regime_atual}! Resetando estado da posição {entry_side}.")
                    in_position   = False
                    active_symbol = None
                    entry_price   = 0.0
                    entry_side    = None

            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)

    except Exception as e:
        add_log(f"💥 Erro Crítico na Estratégia Camaleão: {e}")
        log_trade(symbol, regime_atual, 'ERRO_CRITICO', '-', 0, 0, 0, 0, leverage, 0, collateral_usd, '💥 CRASH', str(e))
    finally:
        add_log(f"{'='*55}")
        add_log("Estratégia Camaleão Finalizada.")
        bot_state["is_running"] = False
        bot_state["status"]     = "🔴 Desligado"
