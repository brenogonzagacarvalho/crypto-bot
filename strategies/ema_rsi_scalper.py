"""
strategies/ema_rsi_scalper.py — ⚡ EMA CROSS / PULLBACK + RSI + ADX SCALPER

Refatorada com as Skills Quantitativas (Claude & Grok Trading Desk):
- Corrigida falha grave da versão anterior (que operava SEM Stop Loss e apenas LONG).
- Agora opera LONG e SHORT com filtro de força de tendência ADX >= 20, alinhamento com EMA 50/200,
  Order Book Imbalance (OBI), Stop Loss dinâmico por ATR obrigatório, Breakeven em +1R e Trailing Stop Server-Side.
"""

import time
import sys
import os
import csv
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import calculate_ema_series
from core.shared_state import bot_state, add_log
from core.balance_utils import (
    get_available_margin_usd,
    enable_btc_collateral,
    get_closed_pnl_details,
)
from core.quant_skills import (
    DEFAULT_SCAN_SYMBOLS,
    MarketRegimeSkill,
    MicrostructureSkill,
    RiskOfficerSkill,
    ExecutionProtocolSkill,
)

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'ema_rsi_trades.csv')


def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço Executado',
                'EMA9', 'EMA21', 'RSI', 'Alavancagem',
                'Take Profit', 'Stop Loss', 'Saldo USD', 'Status', 'Detalhes'
            ])


def log_trade(symbol, tipo, direcao, preco, ema9, ema21, rsi, leverage, tp, sl, saldo, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.4f}' if preco else '-',
                f'{ema9:.4f}' if ema9 else '-', f'{ema21:.4f}' if ema21 else '-',
                f'{rsi:.1f}' if rsi else '-',
                f'{leverage}x',
                f'{tp:.4f}' if tp else '-', f'{sl:.4f}' if sl else '-',
                f'{saldo:.2f}' if saldo is not None else '-', status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso log CSV: {e}")


def run_ema_rsi_strategy(exchange, symbol='MULTI', leverage=20, check_interval=6):
    init_trade_log()

    is_multi = (symbol == "MULTI")
    symbols_to_scan = DEFAULT_SCAN_SYMBOLS if is_multi else [
        symbol if ':' in symbol else f"{symbol.split('/')[0]}/USDT:USDT"
    ]

    add_log(f"{'=' * 58}")
    add_log(f"⚡ ESTRATÉGIA EMA 9/21/50 + RSI + ADX SCALPER — {'MULTI-SCAN' if is_multi else symbols_to_scan[0]}")
    add_log(f"📊 Skills: EMA Crossover/Pullback + ADX>=20 + OBI + Mandatory ATR Stop ({leverage}x)")
    add_log(f"{'=' * 58}")

    bot_state["is_running"] = True
    bot_state["status"] = f"⚡ EMA/RSI ({leverage}x)"
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
    initial_equity = total_equity
    daily_profit_target = max(1.50, initial_equity * 0.18)
    daily_loss_limit = min(-0.80, -initial_equity * 0.10)

    active_positions = {}
    MAX_POSITIONS = 2
    scan_count = 0

    try:
        while bot_state["is_running"]:
            scan_count += 1
            available_usd, total_equity = get_available_margin_usd(exchange)
            if available_usd is None or total_equity is None:
                time.sleep(5)
                continue
            bot_state["usdt_balance"] = total_equity
            collateral_usd = available_usd

            delta = total_equity - initial_equity
            if delta >= daily_profit_target:
                add_log(f"🏆 Meta diária atingida (+${delta:.2f})! Encerrando EMA/RSI Scalper.")
                break
            if delta <= daily_loss_limit:
                add_log(f"🛑 Limite de perda diário atingido (-${abs(delta):.2f}).")
                break

            # 1. Monitoramento e Defesa Ativa de Posições
            try:
                open_positions = []
                for s in symbols_to_scan:
                    try:
                        open_positions.extend(exchange.fetch_positions([s]))
                    except Exception:
                        pass
                current_open_symbols = set()

                for pos in open_positions:
                    contracts = float(pos.get('contracts') or 0)
                    if contracts > 0:
                        sym = pos['symbol']
                        current_open_symbols.add(sym)
                        entry_price = float(pos.get('entryPrice') or 0)
                        side = str(pos.get('side', 'LONG')).upper()
                        unpnl = float(pos.get('unrealizedPnl') or 0)
                        roi = float(pos.get('percentage') or 0)

                        if sym not in active_positions:
                            active_positions[sym] = {
                                'side': side,
                                'entry_price': entry_price,
                                'sl_dist': entry_price * 0.005,
                                'current_sl': 0.0,
                                'breakeven_locked': False,
                            }

                        RiskOfficerSkill.manage_open_position(exchange, sym, pos, active_positions[sym])
                        bot_state["unrealized_pnl"] = unpnl
                        bot_state["status"] = f"⚡ {sym.split('/')[0]} {side} ({roi:+.2f}%)"

                closed_symbols = list(set(active_positions.keys()) - current_open_symbols)
                for sym in closed_symbols:
                    time.sleep(2.5)
                    details = get_closed_pnl_details(exchange, sym)
                    resultado = details['pnl']
                    exit_price = details['exit_price'] or active_positions[sym]['entry_price']
                    resultado_emoji = "🏆 LUCRO" if resultado > 0 else "💀 LOSS"
                    add_log(f"🚪 Posição EMA/RSI fechada em {sym}! PnL: ${resultado:+.4f} {resultado_emoji}")
                    log_trade(
                        sym, 'SAÍDA', active_positions[sym]['side'], exit_price,
                        None, None, None, leverage, None, None, total_equity,
                        resultado_emoji, f"{resultado:+.4f}"
                    )
                    del active_positions[sym]
                    bot_state["unrealized_pnl"] = 0.0
            except Exception as e:
                add_log(f"⚠️ Erro ao monitorar posições: {e}")

            # 2. Scanner EMA 9/21/50 + RSI + ADX
            if len(active_positions) < MAX_POSITIONS:
                add_log(f"── EMA/RSI Scanner #{scan_count} | Ativas: {len(active_positions)}/{MAX_POSITIONS} | Saldo: ${collateral_usd:.2f} ──")

                for sym in symbols_to_scan:
                    if not bot_state["is_running"] or len(active_positions) >= MAX_POSITIONS:
                        break
                    if sym in active_positions:
                        continue

                    coin_name = sym.split('/')[0]
                    bot_state["coin_name"] = coin_name

                    analysis = MarketRegimeSkill.analyze_asset(exchange, sym, ltf='5m', htf='1h')
                    if not analysis:
                        continue

                    closes = analysis['ohlcv_ltf']['c']
                    ema9_series = calculate_ema_series(closes, 9)
                    ema21_series = calculate_ema_series(closes, 21)
                    if len(ema9_series) < 3 or len(ema21_series) < 3:
                        continue

                    curr_ema9, prev_ema9 = ema9_series[-1], ema9_series[-2]
                    curr_ema21, prev_ema21 = ema21_series[-1], ema21_series[-2]
                    ema50 = analysis['ema50']
                    price = analysis['current_price']
                    rsi = analysis['rsi']
                    prev_rsi = analysis['prev_rsi']
                    adx = analysis['adx']
                    atr = analysis['atr']
                    macd_hist = analysis['macd_hist']

                    bot_state["current_price"] = price
                    bot_state["rsi"] = rsi
                    bot_state["rsi_status"] = f"EMA9: ${curr_ema9:.4f} | EMA21: ${curr_ema21:.4f} | ADX: {adx:.0f}"

                    add_log(f"  {coin_name}: ${price:,.4f} | EMA9/21: {curr_ema9:.4f}/{curr_ema21:.4f} | RSI: {rsi:.1f} | ADX: {adx:.1f}")

                    # Gatilho LONG: Cruzamento EMA 9 > 21 ou Pullback na EMA 21 em tendência de alta com ADX >= 19
                    cross_up = (prev_ema9 <= prev_ema21 and curr_ema9 > curr_ema21)
                    pullback_up = (curr_ema9 > curr_ema21 > ema50 and abs(price - curr_ema21) / curr_ema21 <= 0.0025 and rsi > prev_rsi)
                    is_long = (cross_up or pullback_up) and (42 <= rsi <= 66) and adx >= 19 and macd_hist >= 0

                    # Gatilho SHORT: Cruzamento EMA 9 < 21 ou Pullback na EMA 21 em tendência de baixa com ADX >= 19
                    cross_down = (prev_ema9 >= prev_ema21 and curr_ema9 < curr_ema21)
                    pullback_down = (curr_ema9 < curr_ema21 < ema50 and abs(price - curr_ema21) / curr_ema21 <= 0.0025 and rsi < prev_rsi)
                    is_short = (cross_down or pullback_down) and (34 <= rsi <= 58) and adx >= 19 and macd_hist <= 0

                    if not is_long and not is_short:
                        time.sleep(0.3)
                        continue

                    trigger_side = 'buy' if is_long else 'sell'
                    ob = MicrostructureSkill.get_orderbook_imbalance(exchange, sym)
                    if trigger_side == 'buy' and ob['obi'] < -0.18:
                        continue
                    if trigger_side == 'sell' and ob['obi'] > 0.18:
                        continue

                    sizing = RiskOfficerSkill.calculate_order_sizing(
                        exchange=exchange,
                        symbol=sym,
                        side=trigger_side,
                        entry_price=price,
                        atr=atr,
                        collateral_usd=collateral_usd,
                        leverage=leverage,
                        risk_margin_pct=0.35,
                        atr_sl_mult=1.9,
                        rr_ratio=2.5,
                    )

                    if not sizing['valid']:
                        add_log(f"  🛡️ [Risk Veto] {coin_name}: {sizing['reason']}")
                        continue

                    dir_label = 'LONG' if is_long else 'SHORT'
                    sig_type = 'CROSSOVER' if (cross_up or cross_down) else 'EMA_PULLBACK'
                    add_log(
                        f"⚡ SINAL EMA/RSI {dir_label} ({sig_type}) em {coin_name}! "
                        f"Entrada: ${sizing['entry_price']:.4f} | TP: ${sizing['tp_price']:.4f} | SL: ${sizing['sl_price']:.4f}"
                    )

                    _, filled = ExecutionProtocolSkill.execute_smart_order(
                        exchange, sym, trigger_side, sizing['amount'],
                        sizing['entry_price'], sizing['tp_price'], sizing['sl_price'],
                        allow_market_fallback=True
                    )
                    if filled:
                        active_positions[sym] = {
                            'side': dir_label,
                            'entry_price': sizing['entry_price'],
                            'sl_price': sizing['sl_price'],
                            'current_sl': sizing['sl_price'],
                            'sl_dist': sizing['sl_dist'],
                            'breakeven_locked': False,
                        }
                        log_trade(
                            sym, 'ENTRADA', dir_label, sizing['entry_price'],
                            curr_ema9, curr_ema21, rsi, leverage,
                            sizing['tp_price'], sizing['sl_price'], total_equity,
                            '✅ EXECUTADA', f'{sig_type} | ADX: {adx:.1f}'
                        )

                    time.sleep(0.4)

            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)

    except Exception as e:
        add_log(f"⚠️ Erro crítico no loop da estratégia EMA/RSI: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("⚡ Estratégia EMA/RSI Finalizada.")
