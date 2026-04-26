"""
PREDITOR AVANÇADO - MÚLTIPLOS INDICADORES + GESTÃO DE RISCO
RSI + MACD + EMA + Bollinger + ATR + Volume
"""

import time
import sys
import os
import csv
from datetime import datetime
import pandas as pd
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_historical_data, calculate_rsi
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance

# --- SISTEMA DE LOG EM CSV ---
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'spot_trades.csv')

def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço',
                'RSI', 'MACD_Signal', 'Score', 'Quantidade',
                'Saldo Moeda', 'Saldo USD', 'Status', 'Detalhes'
            ])

def log_trade(symbol, tipo, direcao, preco, rsi, macd_signal, score,
              quantidade, saldo_moeda, saldo_usd, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.2f}',
                f'{rsi:.1f}' if rsi else '-',
                f'{macd_signal}' if macd_signal else '-',
                f'{score:.0f}' if score else '-',
                f'{quantidade:.8f}',
                f'{saldo_moeda:.8f}', f'{saldo_usd:.2f}',
                status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso: Não foi possível gravar log CSV: {e}")


# === INDICADORES TÉCNICOS ===

def calculate_macd(closes, fast=12, slow=26, signal=9):
    """MACD: tendência + momentum"""
    if len(closes) < slow + signal:
        return None, None, None
    s = pd.Series(closes)
    ema_fast = s.ewm(span=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line.iloc[-1], signal_line.iloc[-1], histogram.iloc[-1]

def calculate_ema(closes, period=20):
    """EMA para tendência"""
    if len(closes) < period:
        return None
    return pd.Series(closes).ewm(span=period, adjust=False).mean().iloc[-1]

def calculate_atr(highs, lows, closes, period=14):
    """ATR: volatilidade"""
    if len(closes) < period + 1:
        return None
    tr_list = []
    for i in range(1, len(closes)):
        high = highs[i] if i < len(highs) else closes[i]
        low = lows[i] if i < len(lows) else closes[i]
        tr = max(high - low, abs(high - closes[i-1]), abs(low - closes[i-1]))
        tr_list.append(tr)
    return pd.Series(tr_list).rolling(window=period).mean().iloc[-1]

def calculate_bollinger_bands(closes, period=20, std_dev=2):
    """Bandas de Bollinger"""
    if len(closes) < period:
        return None, None, None
    s = pd.Series(closes)
    sma = s.rolling(window=period).mean()
    std = s.rolling(window=period).std()
    return sma.iloc[-1] + std.iloc[-1] * std_dev, sma.iloc[-1], sma.iloc[-1] - std.iloc[-1] * std_dev

def calculate_volume_trend(volumes, period=10):
    """Ratio de volume vs média"""
    if len(volumes) < period:
        return None
    avg = pd.Series(volumes).rolling(window=period).mean().iloc[-1]
    return volumes[-1] / avg if avg > 0 else 1.0


# === BALANÇO ===

def get_free_balance(exchange, coin):
    """Busca saldo na conta UTA da Bybit."""
    try:
        resp = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
        coins = resp.get('result', {}).get('list', [{}])[0].get('coin', [])
        for c in coins:
            if c.get('coin') == coin:
                return float(c.get('availableToWithdraw') or c.get('walletBalance') or 0)
    except:
        pass
    try:
        balance = exchange.fetch_balance({'type': 'unified'})
        return float(balance.get('free', {}).get(coin, 0) or 0)
    except:
        return 0.0


# === SCORE MULTI-INDICADOR ===

def calculate_trade_score(exchange, symbol):
    """
    Score de -100 a +100:
    > 0 = tendência de COMPRA
    < 0 = tendência de VENDA
    """
    try:
        closes_1m = fetch_historical_data(exchange, symbol, timeframe='1m', limit=100)
        closes_5m = fetch_historical_data(exchange, symbol, timeframe='5m', limit=100)

        ohlcv_1m = exchange.fetch_ohlcv(symbol, timeframe='1m', limit=100)
        highs = [c[2] for c in ohlcv_1m]
        lows = [c[3] for c in ohlcv_1m]
        volumes = [c[5] for c in ohlcv_1m]

        if not closes_1m or len(closes_1m) < 30:
            return 0, {}

        current_price = closes_1m[-1]
        score = 0
        signals = {}

        # 1. RSI 1m
        rsi_1m = calculate_rsi(closes_1m, period=14)
        rsi_5m = calculate_rsi(closes_5m, period=14) if closes_5m and len(closes_5m) >= 14 else None

        if rsi_1m:
            if rsi_1m < 25:
                score += 25; signals['rsi_1m'] = 'STRONG_BUY'
            elif rsi_1m < 35:
                score += 15; signals['rsi_1m'] = 'BUY'
            elif rsi_1m > 75:
                score -= 25; signals['rsi_1m'] = 'STRONG_SELL'
            elif rsi_1m > 65:
                score -= 15; signals['rsi_1m'] = 'SELL'
            else:
                signals['rsi_1m'] = 'NEUTRAL'

        # 2. RSI 5m confirmação
        if rsi_5m and rsi_1m:
            if rsi_1m < 35 and rsi_5m < 40:
                score += 10; signals['rsi_5m'] = 'CONFIRMA_BUY'
            elif rsi_1m > 65 and rsi_5m > 60:
                score -= 10; signals['rsi_5m'] = 'CONFIRMA_SELL'

        # 3. MACD
        macd_line, signal_line, histogram = calculate_macd(closes_1m)
        if macd_line is not None and signal_line is not None:
            if macd_line > signal_line and histogram > 0:
                score += 15; signals['macd'] = 'BULLISH'
            elif macd_line < signal_line and histogram < 0:
                score -= 15; signals['macd'] = 'BEARISH'
            else:
                signals['macd'] = 'NEUTRAL'

            if histogram and histogram > 0 and macd_line and abs(macd_line) > 0:
                if histogram > abs(macd_line) * 0.1:
                    score += 5; signals['macd_str'] = 'STRONG'

        # 4. EMA trend
        ema_20 = calculate_ema(closes_1m, 20)
        ema_50 = calculate_ema(closes_1m, 50)
        if ema_20 and ema_50:
            if current_price > ema_20 > ema_50:
                score += 15; signals['trend'] = 'UPTREND'
            elif current_price < ema_20 < ema_50:
                score -= 15; signals['trend'] = 'DOWNTREND'
            else:
                signals['trend'] = 'SIDEWAYS'

        # 5. Bollinger Bands
        bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(closes_1m)
        if bb_lower and bb_upper:
            if current_price <= bb_lower:
                score += 10; signals['bb'] = 'LOWER_BAND'
            elif current_price >= bb_upper:
                score -= 10; signals['bb'] = 'UPPER_BAND'
            else:
                signals['bb'] = 'MIDDLE'

        # 6. Volume confirmation
        volume_ratio = calculate_volume_trend(volumes)
        if volume_ratio and volume_ratio > 1.5:
            if score > 0:
                score += 10; signals['vol'] = f'HIGH_BUY({volume_ratio:.1f}x)'
            elif score < 0:
                score -= 10; signals['vol'] = f'HIGH_SELL({volume_ratio:.1f}x)'
        elif volume_ratio:
            signals['vol'] = f'{volume_ratio:.1f}x'

        # 7. ATR volatility filter
        atr = calculate_atr(highs, lows, closes_1m, period=14)
        if atr and current_price > 0:
            vol_pct = (atr / current_price) * 100
            if vol_pct > 2:
                score = int(score * 0.5)  # Penaliza alta volatilidade
                signals['atr'] = f'HIGH_RISK({vol_pct:.1f}%)'
            else:
                signals['atr'] = f'OK({vol_pct:.1f}%)'

        signals['score'] = score
        signals['rsi'] = rsi_1m
        signals['current_price'] = current_price

        return score, signals

    except Exception as e:
        add_log(f"Erro no score: {e}")
        return 0, {}


# === EXECUÇÃO ===

def execute_spot_order(exchange, symbol, side, amount):
    """Executa ordem Spot na Bybit UTA."""
    add_log(f"📤 {side.upper()} {amount:.8f} {symbol}...")
    try:
        params = {'isLeverage': 0}
        if side == 'sell':
            order = exchange.create_market_sell_order(symbol, amount, params=params)
        else:
            order = exchange.create_market_buy_order(symbol, amount, params=params)
        add_log(f"✅ Ordem executada! ID: {order.get('id', 'N/A')}")
        return True
    except Exception as e:
        add_log(f"❌ Falha: {e}")
        return False


# === LOOP PRINCIPAL ===

def run_live_predictor(exchange, symbol='BTC/USDT', check_interval=60):
    """Preditor Spot Avançado — RSI + MACD + EMA + Bollinger + ATR + Volume"""
    init_trade_log()

    add_log(f"{'='*55}")
    add_log(f"🤖 PREDITOR AVANÇADO — {symbol}")
    add_log(f"📊 RSI · MACD · EMA · Bollinger · ATR · Volume")
    add_log(f"{'='*55}")

    bot_state["is_running"] = True
    bot_state["status"] = "🟢 Analisando"

    base_coin = symbol.split('/')[0]
    bot_state["coin_name"] = base_coin

    # Parâmetros de risco
    RISK_PER_TRADE = 0.80   # 80% do saldo por trade (conta pequena)
    MIN_SCORE = 50           # Só opera com score >= 50
    COOLDOWN = 2             # Scans entre trades

    add_log(f"⚙️ Risco: {RISK_PER_TRADE*100:.0f}% | Score mín: {MIN_SCORE} | Cooldown: {COOLDOWN}")

    # Saldos iniciais
    coin_balance = get_free_balance(exchange, base_coin)
    usdt_balance = get_free_balance(exchange, 'USDT')

    if usdt_balance < 0.01 and coin_balance > 0:
        try:
            ticker = exchange.fetch_ticker(symbol)
            usdt_balance = coin_balance * ticker['last']
            add_log(f"💰 {coin_balance:.8f} {base_coin} (≈ ${usdt_balance:.2f})")
        except:
            add_log(f"💰 {coin_balance:.8f} {base_coin}")
    else:
        add_log(f"💰 ${usdt_balance:.2f} USDT | {coin_balance:.8f} {base_coin}")

    bot_state["coin_balance"] = coin_balance
    bot_state["usdt_balance"] = usdt_balance

    # Meta diária 23%
    starting_usd = usdt_balance if usdt_balance > 0.01 else (coin_balance * 77000)  # estimativa
    daily_target = starting_usd * 1.23
    add_log(f"🎯 Meta: ${daily_target:.2f} (+23% sobre ${starting_usd:.2f})")

    in_position = coin_balance > 0.00001
    scan_count = 0
    trades_today = 0
    last_trade_scan = 0

    try:
        while bot_state["is_running"]:
            scan_count += 1

            # Atualiza saldos
            coin_balance = get_free_balance(exchange, base_coin)
            usdt_balance = get_free_balance(exchange, 'USDT')

            if usdt_balance < 0.01 and coin_balance > 0:
                try:
                    ticker = exchange.fetch_ticker(symbol)
                    usdt_balance = coin_balance * ticker['last']
                except:
                    pass

            bot_state["coin_balance"] = coin_balance
            bot_state["usdt_balance"] = usdt_balance

            # Meta diária (lucro mínimo $0.50)
            current_total = usdt_balance + (coin_balance * bot_state.get("current_price", 0))
            if current_total >= daily_target and (current_total - starting_usd) >= 0.50:
                lucro = current_total - starting_usd
                add_log(f"{'='*50}")
                add_log(f"🏆🏆🏆 META DIÁRIA BATIDA! 🏆🏆🏆")
                add_log(f"${starting_usd:.2f} → ${current_total:.2f} (+${lucro:.2f})")
                add_log(f"{'='*50}")
                bot_state["status"] = "🏆 Meta Atingida!"
                bot_state["is_running"] = False
                break

            # Score multi-indicador
            score, signals = calculate_trade_score(exchange, symbol)
            current_price = signals.get('current_price', 0)
            rsi = signals.get('rsi', None)

            bot_state["current_price"] = current_price
            bot_state["rsi"] = rsi if rsi else 0

            # Status visual
            if score >= MIN_SCORE:
                bot_state["rsi_status"] = f"COMPRA 🟢 ({score}pts)"
            elif score <= -MIN_SCORE:
                bot_state["rsi_status"] = f"VENDA 🔴 ({score}pts)"
            elif abs(score) > 20:
                bot_state["rsi_status"] = f"Leve {'↑' if score > 0 else '↓'} ({score}pts)"
            else:
                bot_state["rsi_status"] = f"Neutro ⚪ ({score}pts)"

            # Log compacto
            score_bar = "▲" * min(abs(int(score/5)), 20) if score > 0 else "▼" * min(abs(int(score/5)), 20)
            trend = signals.get('trend', '-')
            macd = signals.get('macd', '-')
            atr = signals.get('atr', '-')

            add_log(f"#{scan_count} [{score_bar}] {score:+.0f}pts | RSI:{rsi:.0f} MACD:{macd} Trend:{trend} ATR:{atr}")

            log_trade(symbol, 'SCAN', '-', current_price, rsi,
                     signals.get('macd', ''), score,
                     0, coin_balance, usdt_balance,
                     bot_state["rsi_status"], str(signals))

            # --- DECISÃO DE TRADE ---
            cooldown_active = (scan_count - last_trade_scan) < COOLDOWN

            # VENDA: Score negativo forte + tem moeda
            if score <= -MIN_SCORE and in_position and not cooldown_active:
                if signals.get('macd') == 'BEARISH' or signals.get('trend') == 'DOWNTREND':
                    coin_to_sell = get_free_balance(exchange, base_coin)
                    sell_pct = min(abs(score) / 100, 0.80)
                    amount_to_sell = coin_to_sell * sell_pct

                    if amount_to_sell > 0:
                        add_log(f"🔴 VENDA {sell_pct*100:.0f}%! Score: {score} | {amount_to_sell:.8f} {base_coin}")

                        if execute_spot_order(exchange, symbol, 'sell', amount_to_sell):
                            trades_today += 1
                            last_trade_scan = scan_count
                            new_coin = get_free_balance(exchange, base_coin)
                            new_usdt = get_free_balance(exchange, 'USDT')
                            bot_state["coin_balance"] = new_coin
                            bot_state["usdt_balance"] = new_usdt
                            in_position = new_coin > 0.00001

                            log_trade(symbol, 'VENDA', 'SELL', current_price, rsi,
                                     macd, score, amount_to_sell, new_coin, new_usdt, '✅ SUCESSO')

            # COMPRA: Score positivo forte + tem USDT
            elif score >= MIN_SCORE and not in_position and not cooldown_active:
                if signals.get('trend') == 'UPTREND' or signals.get('macd') == 'BULLISH':
                    usdt_available = get_free_balance(exchange, 'USDT')
                    usdt_to_spend = usdt_available * RISK_PER_TRADE
                    score_mult = min(abs(score) / 100, 1.0)
                    usdt_to_spend = usdt_to_spend * score_mult
                    amount_to_buy = usdt_to_spend / current_price if current_price > 0 else 0

                    if amount_to_buy > 0 and usdt_to_spend >= 1:
                        add_log(f"🟢 COMPRA ${usdt_to_spend:.2f}! Score: {score} | {amount_to_buy:.8f} {base_coin}")

                        if execute_spot_order(exchange, symbol, 'buy', amount_to_buy):
                            trades_today += 1
                            last_trade_scan = scan_count
                            new_coin = get_free_balance(exchange, base_coin)
                            new_usdt = get_free_balance(exchange, 'USDT')
                            bot_state["coin_balance"] = new_coin
                            bot_state["usdt_balance"] = new_usdt
                            in_position = True

                            log_trade(symbol, 'COMPRA', 'BUY', current_price, rsi,
                                     macd, score, amount_to_buy, new_coin, new_usdt, '✅ SUCESSO')
                    else:
                        add_log(f"⚠️ USDT insuficiente (${usdt_to_spend:.2f})")
            else:
                if cooldown_active:
                    wait = COOLDOWN - (scan_count - last_trade_scan)
                    add_log(f"⏳ Cooldown: {wait} scans")

            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)

    except Exception as e:
        add_log(f"💥 Erro Crítico: {e}")
        log_trade(symbol, 'ERRO_CRITICO', '-', 0, 0, '', 0, 0, 0, 0, '💥 CRASH', str(e))
    finally:
        add_log(f"{'='*55}")
        add_log(f"📊 SESSÃO: {trades_today} trades | ${usdt_balance:.2f} USDT | {coin_balance:.8f} {base_coin}")
        add_log(f"{'='*55}")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("Bot Finalizado.")
