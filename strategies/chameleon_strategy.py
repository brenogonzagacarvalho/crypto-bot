"""
strategies/chameleon_strategy.py — 🦎 ESTRATÉGIA CAMALEÃO (Regime Adaptativo Multi-Skill)

Refatorada com `core/quant_skills.py`:
- Usa `MarketRegimeSkill` para classificar o mercado em `STRONG_UPTREND`, `STRONG_DOWNTREND`,
  `SQUEEZE_BREAKOUT`, `MEAN_REVERSION_RANGE` ou `HIGH_VOL_CHOP`.
- Adapta automaticamente a tática de entrada (Trend Following / Breakout vs. Mean Reversion VWAP/RSI).
- Usa `RiskOfficerSkill` para dimensionamento seguro (sem hardcode de $90 mínimo que bloqueava bancas menores),
  Breakeven em +1R, Trailing Stop Server-Side e fechamento de emergência se o regime reverter contra a posição.
"""

import time
import sys
import os
import csv
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
                symbol, regime, tipo, direcao, f'{preco:.4f}' if preco else '-',
                f'{rsi:.1f}' if rsi else '-',
                f'{ema200:.4f}' if ema200 else '-',
                f'{macd_hist:.4f}' if macd_hist else '-',
                f'{leverage}x' if leverage else '-',
                f'{quantidade:.6f}' if quantidade else '0',
                f'{saldo_usd:.2f}' if saldo_usd is not None else '-',
                status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso: Não foi possível gravar log CSV: {e}")


def run_chameleon_strategy(exchange, symbol='MULTI', leverage=20, check_interval=10):
    init_trade_log()

    is_multi = (symbol == "MULTI")
    symbols_to_scan = DEFAULT_SCAN_SYMBOLS if is_multi else [
        symbol if ':' in symbol else f"{symbol.split('/')[0]}/USDT:USDT"
    ]

    add_log(f"{'=' * 58}")
    add_log(f"🦎 ESTRATÉGIA CAMALEÃO — {'MULTI-SCAN' if is_multi else symbols_to_scan[0]}")
    add_log(f"📊 Skills: Regime Adaptativo (Trend + Squeeze + Range) | {leverage}x")
    add_log(f"{'=' * 58}")

    bot_state["is_running"] = True
    bot_state["status"] = f"🦎 Camaleão ({leverage}x)"
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
    daily_profit_target_usd = max(1.50, 0.18 * initial_equity_usd)
    daily_loss_limit_usd = min(-0.80, -0.10 * initial_equity_usd)

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

            delta = total_equity - initial_equity_usd
            if delta >= daily_profit_target_usd:
                add_log(f"🏆 Meta de lucro diário atingida (+${delta:.2f})! Desligando bot.")
                break
            if delta <= daily_loss_limit_usd:
                add_log(f"🛑 Limite de perda diário atingido (-${abs(delta):.2f})! Desligando bot.")
                break

            # --- MONITORAMENTO DE POSIÇÕES ABERTAS E DEFESA ATIVA ---
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
                                'sl_dist': entry_p * 0.006,
                                'current_sl': 0.0,
                                'breakeven_locked': False,
                            }

                        RiskOfficerSkill.manage_open_position(exchange, sym, pos, active_positions[sym])
                        bot_state["unrealized_pnl"] = unpnl
                        add_log(f"🦎 {sym.split('/')[0]} {side} | PnL: ${unpnl:+.4f} ({roi:+.2f}%) | SL: ${active_positions[sym].get('current_sl', 0):.4f}")

                closed_symbols = list(set(active_positions.keys()) - current_open_symbols)
                for sym in closed_symbols:
                    time.sleep(2.5)
                    details = get_closed_pnl_details(exchange, sym)
                    resultado = details['pnl']
                    close_price = details['exit_price'] or active_positions[sym]['entry_price']
                    resultado_emoji = "🏆 LUCRO" if resultado > 0 else "💀 LOSS"
                    add_log(f"{resultado_emoji}: Fechamento Camaleão em {sym} | ${resultado:+.4f}")
                    log_trade(
                        sym, 'OUT', 'SAÍDA', active_positions[sym]['side'],
                        close_price, 0, 0, 0, leverage, 0, total_equity, resultado_emoji, f"{resultado:+.4f}"
                    )
                    del active_positions[sym]
            except Exception as e:
                add_log(f"⚠️ Erro ao monitorar posições: {e}")

            # --- VERIFICAÇÃO DE INVERSÃO DE REGIME PARA POSIÇÕES ABERTAS ---
            for sym in list(active_positions.keys()):
                try:
                    analysis_pos = MarketRegimeSkill.analyze_asset(exchange, sym, ltf='5m', htf='1h')
                    if not analysis_pos:
                        continue
                    reg = analysis_pos['regime']
                    side_pos = active_positions[sym]['side']
                    score_pos = analysis_pos['confluence_score']

                    should_reverse_exit = (
                        (side_pos in ('LONG', 'BUY') and reg == 'STRONG_DOWNTREND' and score_pos <= -55)
                        or (side_pos in ('SHORT', 'SELL') and reg == 'STRONG_UPTREND' and score_pos >= 55)
                    )
                    if should_reverse_exit:
                        add_log(f"⚠️ Regime em {sym} inverteu fortemente para {reg} (Score {score_pos:+.0f})! Encerrando {side_pos}.")
                        positions = exchange.fetch_positions([sym])
                        for p in positions:
                            c_qty = float(p.get('contracts') or 0)
                            if p['symbol'] == sym and c_qty > 0:
                                close_side = 'sell' if side_pos in ('LONG', 'BUY') else 'buy'
                                exchange.create_order(sym, 'market', close_side, c_qty, params={'reduceOnly': True})
                                break
                except Exception:
                    pass

            # --- BUSCA POR NOVAS ENTRADAS ADAPTATIVAS ---
            if len(active_positions) < MAX_POSITIONS:
                add_log(f"── Camaleão Scanner #{scan_count} | Abertas {len(active_positions)}/{MAX_POSITIONS} | Saldo: ${collateral_usd:.2f} ──")

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

                    regime = analysis['regime']
                    price = analysis['current_price']
                    rsi = analysis['rsi']
                    prev_rsi = analysis['prev_rsi']
                    ema200 = analysis['ema200']
                    macd_hist = analysis['macd_hist']
                    vwap = analysis['vwap']
                    z_score = analysis['z_score']
                    atr = analysis['atr']
                    score = analysis['confluence_score']
                    candle = analysis['candle']

                    bot_state["current_price"] = price
                    bot_state["rsi"] = rsi
                    bot_state["status"] = f"🦎 {coin_name}: {regime}"
                    bot_state["rsi_status"] = f"Regime: {regime} | Score: {score:+.0f}"

                    add_log(f"  {coin_name}: ${price:,.4f} | Regime: {regime} | RSI: {rsi:.1f} | Z-VWAP: {z_score:+.2f} | Score: {score:+.0f}")

                    if regime == 'HIGH_VOL_CHOP':
                        continue

                    trigger_side = None
                    mode_label = None
                    rr_target = 2.6

                    # Modo 1: Tendência ou Squeeze Breakout
                    if regime in ('STRONG_UPTREND', 'SQUEEZE_BREAKOUT') and price > vwap and score >= 45 and 38 <= rsi <= 66:
                        trigger_side = 'buy'
                        mode_label = f"TREND_LONG ({regime})"
                        rr_target = 2.8
                    elif regime in ('STRONG_DOWNTREND', 'SQUEEZE_BREAKOUT') and price < vwap and score <= -45 and 34 <= rsi <= 62:
                        trigger_side = 'sell'
                        mode_label = f"TREND_SHORT ({regime})"
                        rr_target = 2.8

                    # Modo 2: Mean Reversion em Lateralização (Range)
                    elif regime == 'MEAN_REVERSION_RANGE':
                        if (rsi <= 33 or z_score <= -1.7) and rsi > prev_rsi and candle and (candle['lower_wick_ratio'] >= 1.1 or candle['is_bullish']):
                            trigger_side = 'buy'
                            mode_label = "RANGE_REVERSION_LONG"
                            rr_target = 2.2
                        elif (rsi >= 67 or z_score >= 1.7) and rsi < prev_rsi and candle and (candle['upper_wick_ratio'] >= 1.1 or candle['is_bearish']):
                            trigger_side = 'sell'
                            mode_label = "RANGE_REVERSION_SHORT"
                            rr_target = 2.2

                    if not trigger_side:
                        time.sleep(0.3)
                        continue

                    ob = MicrostructureSkill.get_orderbook_imbalance(exchange, sym)
                    if trigger_side == 'buy' and ob['obi'] < -0.20:
                        continue
                    if trigger_side == 'sell' and ob['obi'] > 0.20:
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
                        atr_sl_mult=2.0,
                        rr_ratio=rr_target,
                    )

                    if not sizing['valid']:
                        add_log(f"  🛡️ [Risk Veto] {coin_name}: {sizing['reason']}")
                        continue

                    dir_label = 'LONG' if trigger_side == 'buy' else 'SHORT'
                    add_log(f"🦎 [CAMALEÃO {mode_label}] {dir_label} em {coin_name} @ ${sizing['entry_price']:.4f}")

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
                            sym, regime, 'ENTRADA', dir_label, sizing['entry_price'],
                            rsi, ema200, macd_hist, leverage, sizing['amount'],
                            total_equity, '✅ EXECUTADA', mode_label
                        )

                    time.sleep(0.4)

            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)

    except Exception as e:
        add_log(f"💥 Erro Crítico na Estratégia Camaleão: {e}")
    finally:
        add_log(f"{'=' * 58}")
        add_log("Estratégia Camaleão Finalizada.")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
