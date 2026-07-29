import time
import sys
import os
import csv
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_ohlcv_data, calculate_rsi
from core.shared_state import bot_state, add_log
from core.balance_utils import get_available_margin_usd, enable_btc_collateral

# --- SISTEMA DE LOG EM CSV ---
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'candlestick_rsi_trades.csv')

def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço Executado',
                'Padrao_Candle', 'RSI', 'Alavancagem',
                'Take Profit', 'Stop Loss', 'Saldo USD', 'Status', 'Detalhes'
            ])

def log_trade(symbol, tipo, direcao, preco, padrao, rsi, leverage, tp, sl, saldo, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.4f}' if preco else '-',
                padrao if padrao else '-', f'{rsi:.1f}' if rsi else '-',
                f'{leverage}x',
                f'{tp:.4f}' if tp else '-', f'{sl:.4f}' if sl else '-',
                f'{saldo:.2f}', status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso log CSV: {e}")

def detect_candlestick_signals(data, rsi_value, rsi_oversold=33.0, rsi_overbought=68.0):
    """
    Identifica padrões de Candlestick e aplica o filtro de RSI:
    - Martelo (Hammer) / Engolfo de Alta -> Compra (se RSI < 33)
    - Estrela Cadente (Shooting Star) / Engolfo de Baixa -> Venda (se RSI > 68)
    """
    if not data or len(data['c']) < 2 or rsi_value is None:
        return None, None

    # Dados do candle atual (-1) e anterior (-2)
    o_curr, h_curr, l_curr, c_curr = data['o'][-1], data['h'][-1], data['l'][-1], data['c'][-1]
    o_prev, c_prev = data['o'][-2], data['c'][-2]

    body = abs(c_curr - o_curr)
    candle_range = h_curr - l_curr
    upper_shadow = h_curr - max(o_curr, c_curr)
    lower_shadow = min(o_curr, c_curr) - l_curr

    if candle_range == 0:
        return None, None

    # Padrões de Alta
    is_hammer = (lower_shadow >= 2.0 * body) and (upper_shadow <= 0.2 * candle_range) and (body > 0)
    is_bullish_engulfing = (c_prev < o_prev) and (c_curr > o_curr) and (c_curr >= o_prev) and (o_curr <= c_prev)

    # Padrões de Baixa
    is_shooting_star = (upper_shadow >= 2.0 * body) and (lower_shadow <= 0.2 * candle_range) and (body > 0)
    is_bearish_engulfing = (c_prev > o_prev) and (c_curr < o_curr) and (o_curr >= c_prev) and (c_curr <= o_prev)

    # Aplicação do Filtro de RSI (< 33 para Compra, > 68 para Venda)
    if (is_hammer or is_bullish_engulfing) and rsi_value < rsi_oversold:
        pattern_name = "Martelo" if is_hammer else "Engolfo de Alta"
        return "BUY", pattern_name

    if (is_shooting_star or is_bearish_engulfing) and rsi_value > rsi_overbought:
        pattern_name = "Estrela Cadente" if is_shooting_star else "Engolfo de Baixa"
        return "SELL", pattern_name

    return None, None

def run_candlestick_rsi_strategy(exchange, symbol='MULTI', leverage=10, check_interval=5):
    init_trade_log()

    is_multi = (symbol == "MULTI")
    symbols_to_scan = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "ADA/USDT:USDT", "DOGE/USDT:USDT"] if is_multi else [symbol]

    add_log(f"{'='*55}")
    add_log(f"🕯️ ESTRATÉGIA CANDLESTICK (Engolfo/Martelo/Estrela) + RSI FILTRO — {'MULTI-SCAN' if is_multi else symbol}")
    add_log(f"📊 Gráfico: 5m | Compra: RSI < 33 | Venda: RSI > 68 | Alavancagem: {leverage}x")
    add_log(f"{'='*55}")

    bot_state["is_running"] = True
    bot_state["status"]     = f"🕯️ CANDLE+RSI ({leverage}x)"
    bot_state["coin_name"]  = "SCANNING" if is_multi else symbol.split('/')[0]

    enable_btc_collateral(exchange)

    for sym in symbols_to_scan:
        try:
            exchange.set_margin_mode('isolated', sym)
        except Exception:
            pass
        try:
            exchange.set_leverage(leverage, sym)
        except Exception:
            pass

    active_positions = {}
    scan_count = 0

    while bot_state.get("is_running", False):
        scan_count += 1
        try:
            available_usd, total_equity = get_available_margin_usd(exchange)
            if available_usd is None:
                time.sleep(check_interval)
                continue

            bot_state["usdt_balance"] = total_equity

            for sym in symbols_to_scan:
                if not bot_state.get("is_running", False):
                    break

                ohlcv = fetch_ohlcv_data(exchange, sym, timeframe='5m', limit=50)
                if not ohlcv:
                    continue

                closes = ohlcv['c']
                rsi_val = calculate_rsi(closes, period=14)

                if rsi_val is None:
                    continue

                signal, pattern = detect_candlestick_signals(ohlcv, rsi_val, rsi_oversold=33.0, rsi_overbought=68.0)

                current_price = closes[-1]

                if signal and sym not in active_positions:
                    add_log(f"⚡ [SINAL {signal}] {sym} | Padrão: {pattern} | RSI: {rsi_val:.1f} | Preço: {current_price}")

                    # Definição de tamanho da ordem (2% do saldo por operação)
                    order_usdt = min(available_usd * 0.2, 50.0)
                    amount = (order_usdt * leverage) / current_price

                    side = 'buy' if signal == 'BUY' else 'sell'
                    tp_factor = 1.015 if signal == 'BUY' else 0.985
                    sl_factor = 0.990 if signal == 'BUY' else 1.010

                    tp_price = current_price * tp_factor
                    sl_price = current_price * sl_factor

                    try:
                        order = exchange.create_order(
                            symbol=sym,
                            type='market',
                            side=side,
                            amount=amount
                        )
                        add_log(f"✅ Ordem {signal} Executada em {sym}! Qtd: {amount:.4f} | Padrão: {pattern}")
                        active_positions[sym] = {
                            'side': signal,
                            'entry_price': current_price,
                            'amount': amount,
                            'pattern': pattern,
                            'tp': tp_price,
                            'sl': sl_price
                        }
                        log_trade(sym, 'ENTRY', signal, current_price, pattern, rsi_val, leverage, tp_price, sl_price, total_equity, 'EXECUTED')
                    except Exception as err:
                        add_log(f"❌ Erro ao enviar ordem para {sym}: {err}")

            time.sleep(check_interval)
        except Exception as e:
            add_log(f"⚠️ Erro no loop principal da estratégia: {e}")
            time.sleep(check_interval)

    add_log("🛑 Estratégia Candlestick + RSI finalizada.")
