"""
strategies/grok_whale_flow.py — 🧠 GROK WHALE FLOW (Order Book Imbalance, Funding Squeeze & Liquidity Sweeps)

Estratégia inspirada nos desks HyperGrok & PumpGrok:
- `microstructure-funding-scanner`: Lê desequilíbrios reais do Livro de Ofertas L2 (OBI),
  taxas de financiamento extremas (Funding Rate Short/Long Squeeze), picos de volume institucional (RVOL)
  e varreduras de liquidez (Stop-Hunts / Turtle Soup).
- `risk-officer-guardrails`: Stop Loss dinâmico por ATR (obrigatório), Take Profit 2.6R,
  Breakeven em +1R e Trailing Stop Server-Side na Bybit V5.
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
LOG_FILE = os.path.join(LOG_DIR, 'grok_whale_flow_trades.csv')


def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Gatilho', 'Tipo', 'Direção', 'Preço',
                'OBI', 'Funding%', 'RVOL', 'RSI', 'Alavancagem',
                'Take Profit', 'Stop Loss', 'Saldo USD', 'Status', 'Detalhes'
            ])


def log_trade(symbol, gatilho, tipo, direcao, preco, obi, funding, rvol, rsi, leverage, tp, sl, saldo, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol,
                gatilho,
                tipo,
                direcao,
                f'{preco:.4f}' if preco else '-',
                f'{obi:+.2f}' if obi is not None else '-',
                f'{funding:+.4f}%' if funding is not None else '-',
                f'{rvol:.2f}x' if rvol is not None else '-',
                f'{rsi:.1f}' if rsi is not None else '-',
                f'{leverage}x',
                f'{tp:.4f}' if tp else '-',
                f'{sl:.4f}' if sl else '-',
                f'{saldo:.2f}' if saldo is not None else '-',
                status,
                detalhes,
            ])
    except Exception as e:
        add_log(f"Aviso log CSV: {e}")


def run_grok_whale_flow(exchange, symbol='MULTI', leverage=25, check_interval=6):
    init_trade_log()

    is_multi = (symbol == 'MULTI')
    symbols_to_scan = DEFAULT_SCAN_SYMBOLS if is_multi else [
        symbol if ':' in symbol else f"{symbol.split('/')[0]}/USDT:USDT"
    ]

    add_log(f"{'=' * 60}")
    add_log(f"🧠 GROK WHALE FLOW & SQUEEZE — {'MULTI-SCAN' if is_multi else symbols_to_scan[0]}")
    add_log(f"🐋 Skills: Order Book Imbalance + Funding Squeeze + Liquidity Sweep ({leverage}x)")
    add_log(f"{'=' * 60}")

    bot_state["is_running"] = True
    bot_state["status"] = f"🧠 Grok Flow ({leverage}x)"
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
    daily_profit_target = max(1.50, initial_equity * 0.18)   # +18% meta diária
    daily_loss_limit = min(-0.80, -initial_equity * 0.10)    # -10% circuit breaker diário

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

            # 1. Circuit Breakers Diários
            delta = total_equity - initial_equity
            if delta >= daily_profit_target:
                add_log(f"🏆 [GROK FLOW] Meta diária batida (+${delta:.2f})! Encerrando.")
                break
            if delta <= daily_loss_limit:
                add_log(f"🛑 [RISK OFFICER] Limite de perda diário atingido (-${abs(delta):.2f}).")
                break

            # 2. Monitoramento & Defesa Ativa de Posições
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
                        add_log(f"🐋 {sym.split('/')[0]} {side} | PnL: ${unpnl:+.4f} ({roi:+.2f}%) | SL: ${active_positions[sym].get('current_sl', 0):.4f}")

                closed_symbols = list(set(active_positions.keys()) - current_open_symbols)
                for sym in closed_symbols:
                    time.sleep(2.5)
                    details = get_closed_pnl_details(exchange, sym)
                    pnl = details['pnl']
                    exit_p = details['exit_price'] or active_positions[sym]['entry_price']
                    emoji = "🏆 LUCRO" if pnl > 0 else "💀 LOSS"
                    add_log(f"{emoji} [GROK FLOW] {sym} encerrada | PnL: ${pnl:+.4f}")
                    log_trade(
                        sym, 'CLOSE', 'SAÍDA', active_positions[sym]['side'],
                        exit_p, None, None, None, None, leverage, None, None,
                        total_equity, emoji, f"{pnl:+.4f}"
                    )
                    del active_positions[sym]
            except Exception as e:
                add_log(f"⚠️ Aviso ao monitorar posições: {e}")

            # 3. Scanner de Microestrutura (Order Book + Funding + Sweeps)
            if len(active_positions) < MAX_POSITIONS:
                add_log(f"── Grok Whale Scanner #{scan_count} | Ativas: {len(active_positions)}/{MAX_POSITIONS} | Equity: ${total_equity:.2f} ──")

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

                    price = analysis['current_price']
                    rsi = analysis['rsi']
                    rvol = analysis['rvol']
                    atr = analysis['atr']
                    vwap = analysis['vwap']
                    ohlcv = analysis['ohlcv_ltf']

                    ob = MicrostructureSkill.get_orderbook_imbalance(exchange, sym, limit=20)
                    fr = MicrostructureSkill.get_funding_rate(exchange, sym)
                    sweep = MicrostructureSkill.detect_liquidity_sweep(ohlcv, lookback=24)

                    obi = ob['obi']
                    spread_pct = ob['spread_pct']
                    funding_pct = fr['funding_rate_pct']
                    sweep_type = sweep['sweep_type']

                    bot_state["current_price"] = price
                    bot_state["rsi"] = rsi
                    bot_state["rsi_status"] = f"OBI: {obi:+.2f} | Fund: {funding_pct:+.3f}% | RVOL: {rvol:.1f}x"

                    if spread_pct > 0.08:
                        continue

                    add_log(
                        f"  {coin_name}: ${price:,.4f} | OBI: {obi:+.2f} | Fund: {funding_pct:+.4f}% | "
                        f"RVOL: {rvol:.2f}x | Sweep: {sweep_type or '-'}"
                    )

                    trigger_side = None
                    trigger_name = None

                    # Setup 1: Liquidity Sweep (Stop-Hunt) + Absorção no Order Book
                    if sweep_type == 'BULLISH_SWEEP' and obi >= 0.08 and rsi <= 55:
                        trigger_side = 'buy'
                        trigger_name = 'BULL_LIQUIDITY_SWEEP'
                    elif sweep_type == 'BEARISH_SWEEP' and obi <= -0.08 and rsi >= 45:
                        trigger_side = 'sell'
                        trigger_name = 'BEAR_LIQUIDITY_SWEEP'

                    # Setup 2: Funding Rate Squeeze + Volume Institucional
                    elif fr['squeeze_bias'] == 'SHORT_SQUEEZE_BULLISH' and price > vwap and obi >= 0.14 and rvol >= 1.25:
                        trigger_side = 'buy'
                        trigger_name = 'SHORT_SQUEEZE_FLOW'
                    elif fr['squeeze_bias'] == 'LONG_FLUSH_BEARISH' and price < vwap and obi <= -0.14 and rvol >= 1.25:
                        trigger_side = 'sell'
                        trigger_name = 'LONG_FLUSH_FLOW'

                    # Setup 3: Whale Wall Order Book Imbalance + Fluxo de Volume
                    elif obi >= 0.22 and rvol >= 1.35 and price > analysis['ema21'] and analysis['macd_hist'] > 0 and rsi < 68:
                        trigger_side = 'buy'
                        trigger_name = 'WHALE_BID_WALL'
                    elif obi <= -0.22 and rvol >= 1.35 and price < analysis['ema21'] and analysis['macd_hist'] < 0 and rsi > 32:
                        trigger_side = 'sell'
                        trigger_name = 'WHALE_ASK_WALL'

                    if not trigger_side:
                        time.sleep(0.3)
                        continue

                    dir_label = 'LONG' if trigger_side == 'buy' else 'SHORT'
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
                        rr_ratio=2.6,
                    )

                    if not sizing['valid']:
                        add_log(f"  🛡️ [Risk Veto] {coin_name}: {sizing['reason']}")
                        continue

                    add_log(
                        f"🧠 [GROK {trigger_name} {dir_label}] {coin_name} @ ${sizing['entry_price']:.4f} | "
                        f"OBI: {obi:+.2f} | TP: ${sizing['tp_price']:.4f} | SL: ${sizing['sl_price']:.4f}"
                    )

                    _, filled = ExecutionProtocolSkill.execute_smart_order(
                        exchange=exchange,
                        symbol=sym,
                        side=trigger_side,
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
                            sym, trigger_name, 'ENTRADA', dir_label, sizing['entry_price'],
                            obi, funding_pct, rvol, rsi, leverage,
                            sizing['tp_price'], sizing['sl_price'], total_equity,
                            '✅ EXECUTADA', f"Trigger: {trigger_name}"
                        )

                    time.sleep(0.4)

            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)

    except Exception as e:
        add_log(f"💥 Erro Crítico no Grok Whale Flow: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("🧠 Grok Whale Flow Finalizado.")

