"""
BOT AGRESSIVO PARA DOBRAR CAPITAL EM 7 DIAS (ALAVANCADO)
Arquivo: strategies/double_in_7_days.py
Par recomendado: SOL/USDT:USDT (lote mínimo baixo)
Alavancagem: 5x (ajustável)
ATENÇÃO: ALTA PROBABILIDADE DE PERDA TOTAL.
"""

import time, sys, os, csv, json
from datetime import datetime
from core.market_data import fetch_ohlcv_data, calculate_rsi, calculate_ema
from core.shared_state import bot_state, add_log
from core.balance_utils import (
    get_available_margin_usd,
    enable_btc_collateral,
    place_maker_entry
)

# ----------------- CONFIG -----------------
LEVERAGE = 5                     # alavancagem fixa
TP_PCT = 1.0                     # take profit 1%
SL_PCT = 0.5                     # stop loss 0.5%
TRAILING_ACTIVATION = 0.6        # ativa trailing após 0.6% de lucro
MAX_DAILY_LOSS = 0.20            # 20% de perda diária
INITIAL_RISK = 0.25              # 25% do capital na primeira aposta
MARTINGALE_FACTOR = 2            # dobra após vitória
SCAN_INTERVAL = 60               # segundos entre scans
# -------------------------------------------

LOG_FILE = 'logs/double7.csv'
os.makedirs('logs', exist_ok=True)

def init_log():
    with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['Data/Hora','Symbol','Tipo','Preço','RSI','Tamanho $','PnL $','Saldo $','Detalhes'])

def run_double_7(exchange, symbol='SOL/USDT:USDT'):
    init_log()
    add_log("🚀 BOT AGRESSIVO INICIADO — meta: dobrar em 7 dias")
    bot_state["is_running"] = True
    bot_state["status"] = "🔥 Agressivo 5x"

    enable_btc_collateral(exchange)
    try: exchange.set_leverage(LEVERAGE, symbol)
    except: pass

    starting, _ = get_available_margin_usd(exchange)
    target = starting * 2.0
    daily_stop = starting * (1 - MAX_DAILY_LOSS)
    add_log(f"💰 Início: ${starting:.2f} | Meta final: ${target:.2f} | Stop diário: -{MAX_DAILY_LOSS*100:.0f}%")

    current_bet = starting * INITIAL_RISK
    win_streak = 0
    in_position = False
    entry_price = 0.0
    entry_side = None
    trailing_stop_price = 0.0

    while bot_state["is_running"]:
        # atualiza saldo
        equity, _ = get_available_margin_usd(exchange)
        bot_state["usdt_balance"] = equity

        # verifica meta ou stop diário
        if equity >= target:
            add_log(f"🏆 META ATINGIDA! ${equity:.2f}")
            bot_state["is_running"] = False
            break
        if equity <= daily_stop:
            add_log(f"🛑 STOP DIÁRIO: ${equity:.2f} (limite {daily_stop:.2f})")
            bot_state["is_running"] = False
            break

        # ajusta aposta ao capital disponível
        current_bet = min(current_bet, equity * 0.8)

        # modo scanner
        if not in_position:
            ohlcv = fetch_ohlcv_data(exchange, symbol, '1m', limit=100)
            if not ohlcv:
                time.sleep(SCAN_INTERVAL)
                continue
            closes = ohlcv['c']
            price = closes[-1]
            rsi = calculate_rsi(closes, 14)
            if rsi is None:
                time.sleep(SCAN_INTERVAL)
                continue

            # Sinal de entrada simples: RSI < 30 (sobrevendido) para LONG, RSI > 70 (sobrecomprado) para SHORT
            if rsi < 30:
                side = 'buy'
                add_log(f"🎯 Sinal LONG | RSI={rsi:.1f}")
            elif rsi > 70:
                side = 'sell'
                add_log(f"🎯 Sinal SHORT | RSI={rsi:.1f}")
            else:
                add_log(f"⏳ RSI neutro ({rsi:.1f}), aguardando...")
                time.sleep(SCAN_INTERVAL)
                continue

            qty = (current_bet * LEVERAGE) / price
            
            # Ajusta qty para o lote mínimo da exchange, se necessário
            try:
                market = exchange.market(symbol)
                min_qty = market['limits']['amount']['min']
                if qty < min_qty:
                    cost = (min_qty * price) / LEVERAGE
                    if cost > equity * 0.95:  # margem de segurança
                        add_log(f"⚠️ Saldo insuficiente para lote mínimo de {min_qty} {symbol}.")
                        time.sleep(SCAN_INTERVAL)
                        continue
                    qty = min_qty
            except Exception as e:
                pass

            tp = price * (1 + TP_PCT/100) if side == 'buy' else price * (1 - TP_PCT/100)
            sl = price * (1 - SL_PCT/100) if side == 'buy' else price * (1 + SL_PCT/100)

            res = place_maker_entry(exchange, symbol, side, qty, price, tp, sl)
            if res and res[1]:  # filled
                in_position = True
                entry_side = side
                entry_price = price
                trailing_stop_price = sl
                add_log(f"✅ Entrou {side.upper()} a ${price:.2f} | TP:{tp:.2f} SL:{sl:.2f} | Aposta ${current_bet:.2f}")
                with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
                    csv.writer(f).writerow([datetime.now(), symbol, 'ENTRY', price, rsi, current_bet, 0, equity, ''])
            else:
                add_log("❌ Falha na entrada, aguardando...")
                time.sleep(SCAN_INTERVAL)

        # modo posição aberta
        else:
            ohlcv = fetch_ohlcv_data(exchange, symbol, '1m', limit=5)
            if ohlcv:
                price = ohlcv['c'][-1]
                # trailing stop
                if entry_side == 'buy':
                    profit_pct = (price - entry_price) / entry_price * 100
                    if profit_pct >= TRAILING_ACTIVATION:
                        new_sl = price * (1 - SL_PCT/100)
                        if new_sl > trailing_stop_price:
                            trailing_stop_price = new_sl
                            add_log(f"🔄 Trailing SL ajustado para ${trailing_stop_price:.2f}")
                    if price <= trailing_stop_price:
                        # fecha posição
                        try:
                            formatted_qty = float(exchange.amount_to_precision(symbol, qty))
                            exchange.create_market_sell_order(symbol, formatted_qty, {'reduceOnly': True})
                        except: pass
                        pnl = (price - entry_price) * (current_bet * LEVERAGE) / entry_price
                        in_position = False
                        add_log(f"🛑 Trailing Stop atingido | PnL: ${pnl:+.2f}")
                        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
                            csv.writer(f).writerow([datetime.now(), symbol, 'CLOSE', price, 0, 0, pnl, equity+pnl, 'TRAILING'])
                        if pnl > 0:
                            win_streak += 1
                            current_bet = starting * INITIAL_RISK * (MARTINGALE_FACTOR ** win_streak)
                            add_log(f"📈 Win streak: {win_streak} | Próxima aposta: ${current_bet:.2f}")
                        else:
                            win_streak = 0
                            current_bet = starting * INITIAL_RISK
                            add_log(f"📉 Loss. Reiniciando aposta para ${current_bet:.2f}")

                else:  # short
                    profit_pct = (entry_price - price) / entry_price * 100
                    if profit_pct >= TRAILING_ACTIVATION:
                        new_sl = price * (1 + SL_PCT/100)
                        if new_sl < trailing_stop_price:
                            trailing_stop_price = new_sl
                    if price >= trailing_stop_price:
                        try:
                            formatted_qty = float(exchange.amount_to_precision(symbol, qty))
                            exchange.create_market_buy_order(symbol, formatted_qty, {'reduceOnly': True})
                        except: pass
                        pnl = (entry_price - price) * (current_bet * LEVERAGE) / entry_price
                        in_position = False
                        # ... (same logging and martingale logic as above)

            time.sleep(SCAN_INTERVAL)

    bot_state["is_running"] = False
    bot_state["status"] = "🔴 Desligado"
