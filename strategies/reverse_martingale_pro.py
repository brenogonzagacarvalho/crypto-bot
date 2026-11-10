"""
strategies/reverse_martingale_pro.py — 🔥 ANTI-MARTINGALE SOROS PRO (Paroli Profit Compounding)

Refatorada com as Skills Quantitativas (Claude & Grok Trading Desk):
- Corrigido o crash de `AttributeError: 'TrailingStopEngine' object has no attribute 'current_stop_price'`.
- Implementa o modelo institucional Paroli/Soros: arrisca mão base conservadora (10%) no Nível 1 e
  escala APENAS após vitórias confirmadas (até 4 níveis), reiniciando imediatamente para o Nível 1 após
  qualquer perda ou ao completar o ciclo de 4 vitórias seguidas.
- Integra `TrailingStopEngine` com sincronização Server-Side na Bybit V5.
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
from core.trailing_stop import TrailingStopEngine
from core.quant_skills import (
    DEFAULT_SCAN_SYMBOLS,
    MarketRegimeSkill,
    MicrostructureSkill,
    RiskOfficerSkill,
    ExecutionProtocolSkill,
)

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'rev_martingale_pro.csv')


def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço',
                'RSI', 'Valor', 'Alavancagem', 'Nível Win', 'TP', 'SL', 'Status', 'Detalhes'
            ])


def log_trade(symbol, tipo, direcao, preco, rsi, valor, leverage, wins, tp, sl, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.4f}' if preco else '-',
                f'{rsi:.1f}' if rsi else '-', f'{valor:.2f}' if valor else '0',
                f'{leverage}x', f'{wins}',
                f'{tp:.4f}' if tp else '-', f'{sl:.4f}' if sl else '-',
                status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso: Não foi possível gravar log CSV: {e}")


def run_reverse_martingale_pro(exchange, symbol='MULTI', leverage=25):
    init_trade_log()

    is_multi = (symbol == "MULTI")
    symbols_to_scan = DEFAULT_SCAN_SYMBOLS if is_multi else [
        symbol if ':' in symbol else f"{symbol.split('/')[0]}/USDT:USDT"
    ]

    add_log(f"{'=' * 58}")
    add_log(f"🔥 ANTI-MARTINGALE SOROS PRO — {'MULTI' if is_multi else symbols_to_scan[0]}")
    add_log(f"🛡️ Skills: 4-Level Paroli Compounding + Server-Side Stepped Trailing Stop")
    add_log(f"{'=' * 58}")

    bot_state["is_running"] = True
    bot_state["status"] = f"🔥 Soros Pro ({leverage}x)"

    enable_btc_collateral(exchange)
    for sym in symbols_to_scan:
        ExecutionProtocolSkill.setup_symbol_derivatives(exchange, sym, leverage, margin_mode='cross')

    # Sistema de 4 Níveis Soros (Risco Progressivo apenas com lucro acumulado)
    risco_niveis = {0: 0.10, 1: 0.16, 2: 0.24, 3: 0.32}
    wins_consecutivos = 0

    available_usd, total_equity = get_available_margin_usd(exchange)
    if available_usd is None or total_equity is None:
        add_log("❌ Falha ao ler saldo inicial na Bybit UTA.")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Erro API"
        return

    starting_balance = total_equity
    bot_state["usdt_balance"] = total_equity
    add_log(f"💰 Patrimônio Inicial: ${starting_balance:.2f} | Meta: +25% | Stop Diário: -8%")

    in_position = False
    active_symbol = None
    entry_price = 0.0
    entry_side = None
    scan_count = 0
    trailing_engine = None

    try:
        while bot_state["is_running"]:
            scan_count += 1
            available_usd, total_equity = get_available_margin_usd(exchange)
            if available_usd is None or total_equity is None:
                time.sleep(5)
                continue
            bot_state["usdt_balance"] = total_equity

            if total_equity <= starting_balance * 0.92:
                add_log(f"🛑 Circuit Breaker Diário: Patrimônio caiu 8% (${total_equity:.2f}). Protegendo banca.")
                break

            if not in_position and total_equity >= starting_balance * 1.25 and (total_equity - starting_balance) >= 0.50:
                add_log(f"🏆 META DO DIA ATINGIDA! Patrimônio cresceu +25% (${total_equity:.2f}).")
                break

            if not in_position:
                nivel_atual = min(wins_consecutivos, 3)
                risco_pct = risco_niveis[nivel_atual]
                trade_amount = max(1.0, available_usd * risco_pct)

                add_log(f"── Soros Nível {nivel_atual + 1}/4 | Risco: {risco_pct * 100:.0f}% (${trade_amount:.2f}) | Wins: {wins_consecutivos} ──")

                for sym in symbols_to_scan:
                    if not bot_state["is_running"]:
                        break

                    base_coin = sym.split('/')[0]
                    bot_state["coin_name"] = base_coin

                    analysis = MarketRegimeSkill.analyze_asset(exchange, sym, ltf='5m', htf='1h')
                    if not analysis or analysis['regime'] == 'HIGH_VOL_CHOP':
                        continue

                    price = analysis['current_price']
                    rsi = analysis['rsi']
                    prev_rsi = analysis['prev_rsi']
                    ema200 = analysis['ema200']
                    macd_hist = analysis['macd_hist']
                    atr = analysis['atr']
                    score = analysis['confluence_score']

                    bot_state["current_price"] = price
                    bot_state["rsi"] = rsi
                    bot_state["rsi_status"] = f"Soros Nv.{nivel_atual + 1} | Score: {score:+.0f}"

                    add_log(f"  {base_coin}: ${price:,.4f} | RSI: {rsi:.1f} | Score: {score:+.0f} | MACD: {macd_hist:+.4f}")

                    trigger_side = None
                    if price > ema200 and rsi <= 42 and rsi > prev_rsi and macd_hist >= 0 and score >= 35:
                        trigger_side = 'buy'
                    elif price < ema200 and rsi >= 58 and rsi < prev_rsi and macd_hist <= 0 and score <= -35:
                        trigger_side = 'sell'

                    if not trigger_side:
                        time.sleep(0.3)
                        continue

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
                        collateral_usd=available_usd,
                        leverage=leverage,
                        risk_margin_pct=risco_pct,
                        atr_sl_mult=1.8,
                        rr_ratio=2.8,
                    )

                    if not sizing['valid']:
                        continue

                    dir_label = 'LONG' if trigger_side == 'buy' else 'SHORT'
                    add_log(f"🔥 [SOROS NÍVEL {nivel_atual + 1}] {dir_label} em {base_coin} @ ${sizing['entry_price']:.4f}!")

                    _, filled = ExecutionProtocolSkill.execute_smart_order(
                        exchange, sym, trigger_side, sizing['amount'],
                        sizing['entry_price'], sizing['tp_price'], sizing['sl_price'],
                        allow_market_fallback=True
                    )
                    if filled:
                        in_position = True
                        active_symbol = sym
                        entry_price = sizing['entry_price']
                        entry_side = dir_label
                        trailing_engine = TrailingStopEngine(exchange, sym, initial_stop_pct=sizing['sl_dist_pct'], mode='stepped')
                        trailing_engine.activate(entry_price, dir_label, sizing['amount'], sizing['sl_price'])
                        log_trade(
                            sym, 'ENTRADA', dir_label, entry_price, rsi,
                            sizing['margin_usd'], leverage, wins_consecutivos,
                            sizing['tp_price'], sizing['sl_price'], '✅ SUCESSO', f'Nv.{nivel_atual + 1}'
                        )
                        break

                time.sleep(4)

            elif in_position and active_symbol:
                try:
                    coin_name = active_symbol.split('/')[0]
                    bot_state["coin_name"] = coin_name

                    positions = exchange.fetch_positions([active_symbol])
                    has_position = False
                    current_price = entry_price

                    for pos in positions:
                        contracts = float(pos.get('contracts') or 0)
                        if contracts > 0:
                            has_position = True
                            current_price = float(pos.get('markPrice') or entry_price)
                            unrealized_pnl = float(pos.get('unrealizedPnl') or 0)
                            roi = float(pos.get('percentage') or 0)
                            bot_state["current_price"] = current_price
                            bot_state["unrealized_pnl"] = unrealized_pnl

                            new_stop, adjusted = trailing_engine.update_price(current_price, sync_exchange=True)
                            if adjusted:
                                add_log(f"⚙️ [SOROS PRO] Trailing Stop Server-Side movido para ${new_stop:,.4f}!")

                            dist_stop = abs(current_price - trailing_engine.current_stop_price) / current_price * 100.0
                            add_log(
                                f"📊 [Soros Nv.{min(wins_consecutivos, 3) + 1}] {coin_name} {entry_side} | "
                                f"PnL: ${unrealized_pnl:+.4f} ({roi:+.2f}%) | Stop: ${trailing_engine.current_stop_price:,.4f} ({dist_stop:.2f}%)"
                            )
                            break

                    if not has_position:
                        time.sleep(2.5)
                        details = get_closed_pnl_details(exchange, active_symbol)
                        pnl = details['pnl']
                        exit_p = details['exit_price'] or current_price

                        if pnl > 0:
                            wins_consecutivos += 1
                            if wins_consecutivos >= 4:
                                add_log(f"🏆 CICLO SOROS 4/4 COMPLETO! Lucro da última mão: +${pnl:.4f}. Reiniciando ciclo para proteger lucro!")
                                wins_consecutivos = 0
                            else:
                                add_log(f"✅ WIN #{wins_consecutivos}! +${pnl:.4f} | Avançando para Nível {wins_consecutivos + 1}!")
                            log_trade(active_symbol, 'SAÍDA', entry_side, exit_p, 0, 0, leverage, wins_consecutivos, 0, 0, '🏆 WIN', f"{pnl:+.4f}")
                        else:
                            wins_consecutivos = 0
                            add_log(f"💀 LOSS (${pnl:+.4f}). Resetando Soros para Nível 1 (Mão Base).")
                            log_trade(active_symbol, 'SAÍDA', entry_side, exit_p, 0, 0, leverage, 0, 0, 0, '💀 LOSS', f"{pnl:+.4f}")

                        in_position = False
                        active_symbol = None
                        if trailing_engine:
                            trailing_engine.deactivate()
                        bot_state["unrealized_pnl"] = 0.0

                except Exception as e:
                    add_log(f"⚠️ Aviso monitoramento Soros Pro: {e}")

                time.sleep(4)

    except Exception as e:
        add_log(f"💥 Erro Crítico Soros Pro: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("🔥 Anti-Martingale Soros Pro Finalizado.")
