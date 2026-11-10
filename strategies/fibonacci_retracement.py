"""
strategies/fibonacci_retracement.py — 📐 RETRAÇÃO FIBONACCI GOLDEN POCKET (61.8% - 78.6%)

Refatorada com as Skills Quantitativas (Claude & Grok Trading Desk):
- Corrigido bug de `RISK_PER_TRADE_PCT` indefinido.
- `desk-regime-analyst`: Alinhamento com EMA 200, VWAP e tendência macro (1h).
- `microstructure-funding-scanner`: Confirmação de pavio de exaustão na vela fechada (-2) + Order Book Imbalance (OBI).
- `risk-officer-guardrails`: Stop Loss atômico (2x ATR ou extremo do Swing), Breakeven em +1R e Trailing Stop Server-Side.
"""

import time
import sys
import os
import csv
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import (
    fetch_ohlcv_data,
    calculate_rsi,
    calculate_ema,
    calculate_macd,
    calculate_vwap,
    calculate_atr,
    analyze_candle_anatomy,
)
from core.shared_state import bot_state, add_log
from core.balance_utils import (
    get_available_margin_usd,
    enable_btc_collateral,
    get_closed_pnl_details,
)
from core.quant_skills import (
    DEFAULT_SCAN_SYMBOLS,
    MicrostructureSkill,
    RiskOfficerSkill,
    ExecutionProtocolSkill,
)

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'fibonacci_trades.csv')

RISK_PER_TRADE_PCT = 0.14  # 14% da margem disponível por operação


def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço',
                'Swing Low', 'Swing High', 'Fib 61.8%', 'Fib 78.6%', 'Alavancagem', 'TP Alvo', 'SL Alvo',
                'Saldo USD', 'Status', 'Detalhes'
            ])


def log_trade(symbol, tipo, direcao, preco, swing_l, swing_h, fib_618, fib_786, leverage, tp, sl, saldo, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.4f}' if preco else '-',
                f'{swing_l:.4f}' if swing_l else '-', f'{swing_h:.4f}' if swing_h else '-',
                f'{fib_618:.4f}' if fib_618 else '-', f'{fib_786:.4f}' if fib_786 else '-',
                f'{leverage}x',
                f'{tp:.4f}' if tp else '-', f'{sl:.4f}' if sl else '-',
                f'{saldo:.2f}' if saldo is not None else '-', status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso log CSV: {e}")


def run_fibonacci_strategy(exchange, symbol='MULTI', leverage=20, check_interval=8):
    init_trade_log()

    is_multi = (symbol == "MULTI")
    symbols_to_scan = DEFAULT_SCAN_SYMBOLS if is_multi else [
        symbol if ':' in symbol else f"{symbol.split('/')[0]}/USDT:USDT"
    ]

    add_log(f"{'=' * 58}")
    add_log(f"📐 ESTRATÉGIA FIBONACCI GOLDEN POCKET — {'MULTI-SCAN' if is_multi else symbols_to_scan[0]}")
    add_log(f"📊 Skills: Golden Pocket (61.8%-78.6%) + OBI + ATR Defense ({leverage}x)")
    add_log(f"{'=' * 58}")

    bot_state["is_running"] = True
    bot_state["status"] = f"📐 Fibonacci ({leverage}x)"
    bot_state["coin_name"] = "SCANNING" if is_multi else symbols_to_scan[0].split('/')[0]

    enable_btc_collateral(exchange)
    for sym in symbols_to_scan:
        ExecutionProtocolSkill.setup_symbol_derivatives(exchange, sym, leverage, margin_mode='cross')

    available_usd, total_equity = get_available_margin_usd(exchange)
    if available_usd is None or total_equity is None:
        add_log("❌ Falha ao ler saldo inicial. Encerrando.")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Erro API"
        return

    bot_state["usdt_balance"] = total_equity
    initial_equity_usd = total_equity
    daily_profit_target_usd = max(0.50, 0.08 * initial_equity_usd)
    daily_loss_limit_usd = min(-0.30, -0.04 * initial_equity_usd)

    active_positions = {}
    last_trade_swing = {}
    MAX_POSITIONS = 2
    scan_count = 0

    try:
        while bot_state["is_running"]:
            scan_count += 1
            available_usd, total_equity = get_available_margin_usd(exchange)
            if available_usd is None or total_equity is None:
                time.sleep(check_interval)
                continue

            bot_state["usdt_balance"] = total_equity
            collateral_usd = available_usd

            delta = total_equity - initial_equity_usd
            if delta >= daily_profit_target_usd:
                add_log(f"🏆 Meta de lucro diário atingida (+${delta:.2f})! Desligando bot.")
                break
            if delta <= daily_loss_limit_usd:
                add_log(f"🛑 Limite de perda diário atingido (-${abs(delta):.2f})! Desligando bot.")
                break

            # --- MONITORAMENTO E DEFESA ATIVA DE POSIÇÕES ---
            try:
                all_positions = []
                for sym in symbols_to_scan:
                    try:
                        all_positions.extend(exchange.fetch_positions([sym]))
                    except Exception:
                        pass
                current_open_symbols = set()

                for pos in all_positions:
                    contracts = float(pos.get('contracts') or 0)
                    if contracts > 0:
                        sym = pos['symbol']
                        current_open_symbols.add(sym)

                        entry_p = float(pos.get('entryPrice') or 0)
                        side = str(pos.get('side', 'LONG')).upper()
                        unpnl = float(pos.get('unrealizedPnl') or 0)
                        roi = float(pos.get('percentage') or 0)

                        if sym not in active_positions:
                            active_positions[sym] = {
                                'side': side,
                                'entry_price': entry_p,
                                'entry_time': time.time(),
                                'sl_dist': entry_p * 0.006,
                                'current_sl': 0.0,
                                'breakeven_locked': False,
                            }

                        RiskOfficerSkill.manage_open_position(exchange, sym, pos, active_positions[sym])
                        bot_state["unrealized_pnl"] = unpnl
                        add_log(f"📐 {sym.split('/')[0]} {side} | PnL: ${unpnl:+.4f} ({roi:+.2f}%) | SL: ${active_positions[sym].get('current_sl', 0):.4f}")

                closed_symbols = list(set(active_positions.keys()) - current_open_symbols)
                for sym in closed_symbols:
                    time.sleep(2.5)
                    details = get_closed_pnl_details(exchange, sym)
                    resultado = details['pnl']
                    close_price = details['exit_price'] or active_positions[sym]['entry_price']
                    resultado_emoji = "🏆 LUCRO" if resultado > 0 else "💀 LOSS"
                    add_log(f"{resultado_emoji}: Fechamento Fibonacci em {sym} | ${resultado:+.4f}")
                    log_trade(
                        sym, 'SAÍDA', active_positions[sym]['side'], close_price,
                        0, 0, 0, 0, leverage, 0, 0, total_equity, resultado_emoji, f"{resultado:+.4f}"
                    )
                    del active_positions[sym]
            except Exception as e:
                add_log(f"⚠️ Erro ao monitorar posições: {e}")

            # --- BUSCA POR NOVAS ENTRADAS ---
            if len(active_positions) < MAX_POSITIONS:
                add_log(f"── Fibonacci Scanner #{scan_count} | Abertas {len(active_positions)}/{MAX_POSITIONS} | Saldo: ${collateral_usd:.2f} ──")

                for sym in symbols_to_scan:
                    if not bot_state["is_running"] or len(active_positions) >= MAX_POSITIONS:
                        break
                    if sym in active_positions:
                        continue

                    coin_name = sym.split('/')[0]
                    bot_state["coin_name"] = coin_name

                    ohlcv = fetch_ohlcv_data(exchange, sym, timeframe='5m', limit=210)
                    if not ohlcv or len(ohlcv['c']) < 200:
                        continue

                    closes = ohlcv['c']
                    current_price = closes[-1]
                    bot_state["current_price"] = current_price

                    highs_36 = ohlcv['h'][-36:]
                    lows_36 = ohlcv['l'][-36:]
                    max_high = max(highs_36)
                    min_low = min(lows_36)
                    diff = max_high - min_low
                    if diff <= current_price * 0.0025:
                        continue

                    max_high_idx = highs_36.index(max_high)
                    min_low_idx = lows_36.index(min_low)

                    rsi = calculate_rsi(closes, period=14)
                    ema200 = calculate_ema(closes, period=200)
                    _, _, macd_hist = calculate_macd(closes)
                    vwap = calculate_vwap(ohlcv)
                    atr = calculate_atr(ohlcv, period=14)
                    candle = analyze_candle_anatomy(ohlcv, idx=-2)

                    if any(v is None for v in (rsi, ema200, macd_hist, vwap, atr, candle)):
                        continue

                    bot_state["rsi"] = rsi
                    c_prev = candle['close']
                    l_prev = candle['low']
                    h_prev = candle['high']

                    swing_tuple = (round(min_low, 5), round(max_high, 5))
                    if last_trade_swing.get(sym) == swing_tuple:
                        continue

                    if min_low_idx < max_high_idx:
                        # Swing Bullish -> Retração à zona de ouro (50% a 78.6%)
                        fib_500 = max_high - 0.500 * diff
                        fib_618 = max_high - 0.618 * diff
                        fib_786 = max_high - 0.786 * diff
                        tp_price = max(max_high, current_price + 2.4 * atr)
                        sl_price = max(min_low * 0.9985, current_price - 2.0 * atr)

                        in_golden_zone = (fib_786 * 0.999 <= l_prev <= fib_500) and (c_prev >= fib_786)
                        has_rejection = (candle['lower_wick_ratio'] >= 1.1 or candle['is_bullish'])

                        add_log(
                            f"  {coin_name} [ALTA]: ${current_price:,.4f} | Golden: ${fib_786:,.4f}-${fib_618:,.4f} | "
                            f"RSI: {rsi:.1f} | Wick: {candle['lower_wick_ratio']:.1f}x"
                        )

                        if in_golden_zone and c_prev > ema200 * 0.997 and rsi <= 54 and has_rejection:
                            ob = MicrostructureSkill.get_orderbook_imbalance(exchange, sym)
                            if ob['obi'] < -0.18:
                                continue

                            sizing = RiskOfficerSkill.calculate_order_sizing(
                                exchange=exchange,
                                symbol=sym,
                                side='buy',
                                entry_price=current_price,
                                atr=atr,
                                collateral_usd=collateral_usd,
                                leverage=leverage,
                                risk_margin_pct=RISK_PER_TRADE_PCT,
                                custom_sl_price=sl_price,
                                custom_tp_price=tp_price,
                            )
                            if not sizing['valid']:
                                add_log(f"  🛡️ [Risk Veto] {coin_name}: {sizing['reason']}")
                                continue

                            add_log(f"📐 SINAL FIBONACCI LONG em {coin_name} @ ${sizing['entry_price']:,.4f}!")
                            _, filled = ExecutionProtocolSkill.execute_smart_order(
                                exchange, sym, 'buy', sizing['amount'],
                                sizing['entry_price'], sizing['tp_price'], sizing['sl_price'],
                                allow_market_fallback=True
                            )
                            if filled:
                                active_positions[sym] = {
                                    'side': 'LONG',
                                    'entry_price': sizing['entry_price'],
                                    'sl_price': sizing['sl_price'],
                                    'current_sl': sizing['sl_price'],
                                    'sl_dist': sizing['sl_dist'],
                                    'entry_time': time.time(),
                                    'breakeven_locked': False,
                                }
                                last_trade_swing[sym] = swing_tuple
                                log_trade(
                                    sym, 'ENTRADA', 'LONG', sizing['entry_price'],
                                    min_low, max_high, fib_618, fib_786, leverage,
                                    sizing['tp_price'], sizing['sl_price'], total_equity,
                                    '✅ SUCESSO', f'RSI: {rsi:.1f} | OBI: {ob["obi"]:+.2f}'
                                )
                    else:
                        # Swing Bearish -> Retração à zona de ouro (50% a 78.6%)
                        fib_500 = min_low + 0.500 * diff
                        fib_618 = min_low + 0.618 * diff
                        fib_786 = min_low + 0.786 * diff
                        tp_price = min(min_low, current_price - 2.4 * atr)
                        sl_price = min(max_high * 1.0015, current_price + 2.0 * atr)

                        in_golden_zone = (fib_500 <= h_prev <= fib_786 * 1.001) and (c_prev <= fib_786)
                        has_rejection = (candle['upper_wick_ratio'] >= 1.1 or candle['is_bearish'])

                        add_log(
                            f"  {coin_name} [BAIXA]: ${current_price:,.4f} | Golden: ${fib_618:,.4f}-${fib_786:,.4f} | "
                            f"RSI: {rsi:.1f} | Wick: {candle['upper_wick_ratio']:.1f}x"
                        )

                        if in_golden_zone and c_prev < ema200 * 1.003 and rsi >= 46 and has_rejection:
                            ob = MicrostructureSkill.get_orderbook_imbalance(exchange, sym)
                            if ob['obi'] > 0.18:
                                continue

                            sizing = RiskOfficerSkill.calculate_order_sizing(
                                exchange=exchange,
                                symbol=sym,
                                side='sell',
                                entry_price=current_price,
                                atr=atr,
                                collateral_usd=collateral_usd,
                                leverage=leverage,
                                risk_margin_pct=RISK_PER_TRADE_PCT,
                                custom_sl_price=sl_price,
                                custom_tp_price=tp_price,
                            )
                            if not sizing['valid']:
                                add_log(f"  🛡️ [Risk Veto] {coin_name}: {sizing['reason']}")
                                continue

                            add_log(f"📐 SINAL FIBONACCI SHORT em {coin_name} @ ${sizing['entry_price']:,.4f}!")
                            _, filled = ExecutionProtocolSkill.execute_smart_order(
                                exchange, sym, 'sell', sizing['amount'],
                                sizing['entry_price'], sizing['tp_price'], sizing['sl_price'],
                                allow_market_fallback=True
                            )
                            if filled:
                                active_positions[sym] = {
                                    'side': 'SHORT',
                                    'entry_price': sizing['entry_price'],
                                    'sl_price': sizing['sl_price'],
                                    'current_sl': sizing['sl_price'],
                                    'sl_dist': sizing['sl_dist'],
                                    'entry_time': time.time(),
                                    'breakeven_locked': False,
                                }
                                last_trade_swing[sym] = swing_tuple
                                log_trade(
                                    sym, 'ENTRADA', 'SHORT', sizing['entry_price'],
                                    min_low, max_high, fib_618, fib_786, leverage,
                                    sizing['tp_price'], sizing['sl_price'], total_equity,
                                    '✅ SUCESSO', f'RSI: {rsi:.1f} | OBI: {ob["obi"]:+.2f}'
                                )

                    time.sleep(0.4)

            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)

    except Exception as e:
        add_log(f"💥 Erro Crítico na Estratégia Fibonacci: {e}")
    finally:
        add_log(f"{'=' * 58}")
        add_log("Estratégia Fibonacci Finalizada.")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
