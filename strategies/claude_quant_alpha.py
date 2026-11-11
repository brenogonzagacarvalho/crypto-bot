"""
strategies/claude_quant_alpha.py — 🤖 CLAUDE QUANT ALPHA (Squeeze Breakout & MTF Confluence)

Estratégia institucional baseada nas skills do Claude Trading Desk:
- `desk-regime-analyst`: Detecção de TTM Volatility Squeeze (Bollinger dentro de Keltner) +
  Alinhamento Multi-Timeframe (1h + 5m) + Score de Confluência Quantitativa (>= 60 pts).
- `microstructure-funding-scanner`: Filtro de Order Book Imbalance (OBI) e Volume Relativo (RVOL).
- `risk-officer-guardrails`: Stop Loss dinâmico por ATR (obrigatório), Take Profit 2.8R,
  Breakeven automático em +1R e Trailing Stop Server-Side na Bybit V5.
"""

import os
import sys
import csv
import time
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
LOG_FILE = os.path.join(LOG_DIR, 'claude_quant_alpha_trades.csv')


def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Regime', 'Tipo', 'Direção', 'Preço',
                'Score', 'ADX', 'RVOL', 'OBI', 'Alavancagem',
                'Take Profit', 'Stop Loss', 'Saldo USD', 'Status', 'Detalhes'
            ])


def log_trade(symbol, regime, tipo, direcao, preco, score, adx, rvol, obi, leverage, tp, sl, saldo, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol,
                regime,
                tipo,
                direcao,
                f'{preco:.4f}' if preco else '-',
                f'{score:+.0f}' if score is not None else '-',
                f'{adx:.1f}' if adx is not None else '-',
                f'{rvol:.2f}x' if rvol is not None else '-',
                f'{obi:+.2f}' if obi is not None else '-',
                f'{leverage}x',
                f'{tp:.4f}' if tp else '-',
                f'{sl:.4f}' if sl else '-',
                f'{saldo:.2f}' if saldo is not None else '-',
                status,
                detalhes,
            ])
    except Exception as e:
        add_log(f"Aviso log CSV: {e}")


def run_claude_quant_alpha(exchange, symbol='MULTI', leverage=20, check_interval=8):
    init_trade_log()

    is_multi = (symbol == 'MULTI')
    symbols_to_scan = DEFAULT_SCAN_SYMBOLS if is_multi else [
        symbol if ':' in symbol else f"{symbol.split('/')[0]}/USDT:USDT"
    ]

    add_log(f"{'=' * 60}")
    add_log(f"🤖 CLAUDE QUANT ALPHA — {'MULTI-ASSET SCANNER' if is_multi else symbols_to_scan[0]}")
    add_log(f"📐 Skills: TTM Squeeze + MTF Confluence (>=60) + OBI + ATR Defense ({leverage}x)")
    add_log(f"{'=' * 60}")

    bot_state["is_running"] = True
    bot_state["status"] = f"🤖 Claude Alpha ({leverage}x)"
    bot_state["coin_name"] = "SCANNING" if is_multi else symbols_to_scan[0].split('/')[0]

    enable_btc_collateral(exchange)
    for sym in symbols_to_scan:
        ExecutionProtocolSkill.setup_symbol_derivatives(exchange, sym, leverage, margin_mode='cross')

    available_usd, total_equity = get_available_margin_usd(exchange)
    if available_usd is None or total_equity is None:
        add_log("❌ Falha ao ler saldo inicial na Bybit UTA. Encerrando.")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Erro API"
        return

    bot_state["usdt_balance"] = total_equity
    initial_equity = total_equity
    daily_profit_target = max(0.60, initial_equity * 0.08)   # +8% meta diária
    daily_loss_limit = min(-0.35, -initial_equity * 0.04)    # -4% circuit breaker diário

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

            # 1. Circuit Breakers do Risk Officer
            delta_equity = total_equity - initial_equity
            if delta_equity >= daily_profit_target:
                add_log(f"🏆 [CLAUDE ALPHA] Meta diária atingida (+${delta_equity:.2f})! Protegendo capital.")
                break
            if delta_equity <= daily_loss_limit:
                add_log(f"🛑 [RISK OFFICER] Circuit Breaker diário acionado (-${abs(delta_equity):.2f}).")
                break

            # 2. Monitoramento e Defesa Ativa (Breakeven +1R e Trailing Stop Server-Side)
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
                        add_log(f"📊 {sym.split('/')[0]} {side} | PnL: ${unpnl:+.4f} ({roi:+.2f}%) | SL: ${active_positions[sym].get('current_sl', 0):.4f}")

                # Reconciliação de posições encerradas
                closed_symbols = list(set(active_positions.keys()) - current_open_symbols)
                for sym in closed_symbols:
                    time.sleep(2.5)
                    details = get_closed_pnl_details(exchange, sym)
                    pnl = details['pnl']
                    exit_p = details['exit_price'] or active_positions[sym]['entry_price']
                    emoji = "🏆 LUCRO" if pnl > 0 else "💀 LOSS"
                    add_log(f"{emoji} [CLAUDE ALPHA] {sym} fechada | PnL Líquido: ${pnl:+.4f}")
                    log_trade(
                        sym, 'CLOSED', 'SAÍDA', active_positions[sym]['side'],
                        exit_p, None, None, None, None, leverage, None, None,
                        total_equity, emoji, f"{pnl:+.4f}"
                    )
                    del active_positions[sym]
            except Exception as e:
                add_log(f"⚠️ Aviso no monitoramento de posições: {e}")

            # 3. Scanner Multi-Factor (Regime + Squeeze + Microestrutura)
            if len(active_positions) < MAX_POSITIONS:
                add_log(f"── Claude Alpha Scan #{scan_count} | Ativas: {len(active_positions)}/{MAX_POSITIONS} | Equity: ${total_equity:.2f} ──")

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
                    score = analysis['confluence_score']
                    price = analysis['current_price']
                    rsi = analysis['rsi']
                    adx = analysis['adx']
                    rvol = analysis['rvol']
                    atr = analysis['atr']
                    vwap = analysis['vwap']

                    bot_state["current_price"] = price
                    bot_state["rsi"] = rsi
                    bot_state["rsi_status"] = f"{regime} | Score: {score:+.0f} | ADX: {adx:.0f}"

                    if regime == 'HIGH_VOL_CHOP':
                        continue

                    # Microestrutura (Order Book Imbalance & Funding Rate)
                    ob_info = MicrostructureSkill.get_orderbook_imbalance(exchange, sym, limit=20)
                    obi = ob_info['obi']

                    add_log(
                        f"  {coin_name}: ${price:,.4f} | Regime: {regime} | Score: {score:+.0f} | "
                        f"ADX: {adx:.1f} | RVOL: {rvol:.2f}x | OBI: {obi:+.2f}"
                    )

                    # Critérios de Entrada LONG (Confluência Alta ou Squeeze Breakout Bullish)
                    is_long_signal = (
                        (score >= 60.0 and regime in ('STRONG_UPTREND', 'SQUEEZE_BREAKOUT') and price > vwap and obi >= -0.08)
                        or (regime == 'SQUEEZE_BREAKOUT' and score >= 45.0 and rvol >= 1.35 and obi >= 0.08 and price > analysis['ema21'])
                    )

                    # Critérios de Entrada SHORT (Confluência Baixa ou Squeeze Breakout Bearish)
                    is_short_signal = (
                        (score <= -60.0 and regime in ('STRONG_DOWNTREND', 'SQUEEZE_BREAKOUT') and price < vwap and obi <= 0.08)
                        or (regime == 'SQUEEZE_BREAKOUT' and score <= -45.0 and rvol >= 1.35 and obi <= -0.08 and price < analysis['ema21'])
                    )

                    if not is_long_signal and not is_short_signal:
                        time.sleep(0.3)
                        continue

                    side = 'buy' if is_long_signal else 'sell'
                    dir_label = 'LONG' if is_long_signal else 'SHORT'

                    sizing = RiskOfficerSkill.calculate_order_sizing(
                        exchange=exchange,
                        symbol=sym,
                        side=side,
                        entry_price=price,
                        atr=atr,
                        collateral_usd=collateral_usd,
                        leverage=leverage,
                        risk_margin_pct=0.15,
                        atr_sl_mult=2.0,
                        rr_ratio=1.75,
                    )

                    if not sizing['valid']:
                        add_log(f"  🛡️ [Risk Veto] {coin_name}: {sizing['reason']}")
                        continue

                    add_log(
                        f"🤖 [CLAUDE ALPHA {dir_label}] {coin_name} @ ${sizing['entry_price']:.4f} | "
                        f"Score: {score:+.0f} | TP: ${sizing['tp_price']:.4f} | SL: ${sizing['sl_price']:.4f}"
                    )

                    _, filled = ExecutionProtocolSkill.execute_smart_order(
                        exchange=exchange,
                        symbol=sym,
                        side=side,
                        amount=sizing['amount'],
                        entry_price=sizing['entry_price'],
                        tp_price=sizing['tp_price'],
                        sl_price=sizing['sl_price'],
                        allow_market_fallback=True,
                        max_wait=10,
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
                            score, adx, rvol, obi, leverage,
                            sizing['tp_price'], sizing['sl_price'], total_equity,
                            '✅ EXECUTADA', '; '.join(analysis['reasons'])
                        )

                    time.sleep(0.4)

            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)

    except Exception as e:
        add_log(f"💥 Erro Crítico no Claude Quant Alpha: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("🤖 Claude Quant Alpha Finalizado.")

