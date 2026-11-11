"""
strategies/daily_range_scalper.py — 📐 YHL LIQUIDITY SWEEP (Mínima/Máxima Diária & Stop-Hunt)

Refatorada com as Skills Quantitativas (Claude & Grok Trading Desk):
- Substitui as ordens limite cegas SEM Stop Loss da versão antiga por uma estratégia institucional
  ICT/SMC de Liquidity Sweep (Turtle Soup) e Rejeição nas Mínimas/Máximas Diárias (YHL) e Range de 24h.
- Opera LONG (varredura/defesa da Mínima Diária) e SHORT (varredura/rejeição da Máxima Diária)
  com Stop Loss dinâmico por ATR obrigatório, Breakeven em +1R e Trailing Stop Server-Side.
"""

import time
import sys
import os
import csv
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_ohlcv_data, calculate_atr, calculate_ema
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
LOG_FILE = os.path.join(LOG_DIR, 'daily_range_trades.csv')


def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço Executado',
                'Máxima Ref', 'Mínima Ref', 'ATR', 'Alavancagem',
                'Take Profit', 'Stop Loss', 'Saldo USD', 'Status', 'Detalhes'
            ])


def log_trade(symbol, tipo, direcao, preco, swing_h, swing_l, atr_val, leverage, tp, sl, saldo, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.4f}' if preco else '-',
                f'{swing_h:.4f}' if swing_h else '-', f'{swing_l:.4f}' if swing_l else '-',
                f'{atr_val:.4f}' if atr_val else '-',
                f'{leverage}x',
                f'{tp:.4f}' if tp else '-', f'{sl:.4f}' if sl else '-',
                f'{saldo:.2f}' if saldo is not None else '-', status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso log CSV: {e}")


def run_daily_range_strategy(exchange, symbol='MULTI', leverage=20, check_interval=10):
    init_trade_log()

    is_multi = (symbol == "MULTI")
    symbols_to_scan = DEFAULT_SCAN_SYMBOLS if is_multi else [
        symbol if ':' in symbol else f"{symbol.split('/')[0]}/USDT:USDT"
    ]

    add_log(f"{'=' * 58}")
    add_log(f"📐 ESTRATÉGIA YHL LIQUIDITY SWEEP (Mín/Máx Diária) — {'MULTI-SCAN' if is_multi else symbols_to_scan[0]}")
    add_log(f"📊 Skills: ICT Stop-Hunt Sweep + OBI + Mandatory ATR Stop ({leverage}x)")
    add_log(f"{'=' * 58}")

    bot_state["is_running"] = True
    bot_state["status"] = f"📐 Mín/Máx Diária ({leverage}x)"
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
                time.sleep(8)
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

            # --- MONITORAMENTO DE POSIÇÕES E DEFESA ATIVA ---
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
                        add_log(f"📐 {sym.split('/')[0]} {side} | PnL: ${unpnl:+.4f} ({roi:+.2f}%) | SL: ${active_positions[sym].get('current_sl', 0):.4f}")

                closed_symbols = list(set(active_positions.keys()) - current_open_symbols)
                for sym in closed_symbols:
                    time.sleep(2.5)
                    details = get_closed_pnl_details(exchange, sym)
                    resultado = details['pnl']
                    exit_price = details['exit_price'] or active_positions[sym]['entry_price']
                    resultado_emoji = "🏆 LUCRO" if resultado > 0 else "💀 LOSS"
                    add_log(f"🚪 Posição YHL fechada em {sym}! PnL: ${resultado:+.4f} {resultado_emoji}")
                    log_trade(
                        sym, 'SAÍDA', active_positions[sym]['side'], exit_price,
                        None, None, None, leverage, None, None, total_equity,
                        resultado_emoji, f"{resultado:+.4f}"
                    )
                    del active_positions[sym]
            except Exception as e:
                add_log(f"⚠️ Erro ao monitorar posições: {e}")

            # --- SCANNER DE MÍNIMA/MÁXIMA DIÁRIA & LIQUIDITY SWEEPS ---
            if len(active_positions) < MAX_POSITIONS:
                add_log(f"── YHL Sweep Scanner #{scan_count} | Ativas: {len(active_positions)}/{MAX_POSITIONS} | Saldo: ${collateral_usd:.2f} ──")

                for sym in symbols_to_scan:
                    if not bot_state["is_running"] or len(active_positions) >= MAX_POSITIONS:
                        break
                    if sym in active_positions:
                        continue

                    coin_name = sym.split('/')[0]
                    bot_state["coin_name"] = coin_name

                    ohlcv_1d = fetch_ohlcv_data(exchange, sym, timeframe='1d', limit=15)
                    analysis = MarketRegimeSkill.analyze_asset(exchange, sym, ltf='15m', htf='1h')
                    if not ohlcv_1d or len(ohlcv_1d['c']) < 3 or not analysis:
                        continue

                    yesterday_high = ohlcv_1d['h'][-2]
                    yesterday_low = ohlcv_1d['l'][-2]
                    price = analysis['current_price']
                    rsi = analysis['rsi']
                    atr = analysis['atr']
                    candle = analysis['candle']
                    sweep_24h = MicrostructureSkill.detect_liquidity_sweep(analysis['ohlcv_ltf'], lookback=32)

                    bot_state["current_price"] = price
                    bot_state["rsi"] = rsi
                    bot_state["rsi_status"] = f"YL: ${yesterday_low:.4f} | YH: ${yesterday_high:.4f}"

                    dist_to_yl_pct = abs(price - yesterday_low) / yesterday_low * 100.0 if yesterday_low > 0 else 99.0
                    dist_to_yh_pct = abs(price - yesterday_high) / yesterday_high * 100.0 if yesterday_high > 0 else 99.0

                    add_log(
                        f"  {coin_name}: ${price:,.4f} | Y.Low: ${yesterday_low:,.4f} ({dist_to_yl_pct:.2f}%) | "
                        f"Y.High: ${yesterday_high:,.4f} ({dist_to_yh_pct:.2f}%) | Sweep: {sweep_24h['sweep_type'] or '-'}"
                    )

                    trigger_side = None
                    setup_reason = None

                    # 1. Bullish YHL Sweep / Reteste da Mínima de Ontem ou Range 24h
                    if (dist_to_yl_pct <= 0.45 and price >= yesterday_low * 0.997 and rsi <= 46 and candle and (candle['is_bullish'] or candle['lower_wick_ratio'] >= 1.1)):
                        trigger_side = 'buy'
                        setup_reason = 'YESTERDAY_LOW_DEFENSE'
                    elif sweep_24h['sweep_type'] == 'BULLISH_SWEEP' and rsi <= 48:
                        trigger_side = 'buy'
                        setup_reason = '24H_LOW_LIQUIDITY_SWEEP'

                    # 2. Bearish YHL Sweep / Rejeição da Máxima de Ontem ou Range 24h
                    elif (dist_to_yh_pct <= 0.45 and price <= yesterday_high * 1.003 and rsi >= 54 and candle and (candle['is_bearish'] or candle['upper_wick_ratio'] >= 1.1)):
                        trigger_side = 'sell'
                        setup_reason = 'YESTERDAY_HIGH_REJECTION'
                    elif sweep_24h['sweep_type'] == 'BEARISH_SWEEP' and rsi >= 52:
                        trigger_side = 'sell'
                        setup_reason = '24H_HIGH_LIQUIDITY_SWEEP'

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
                        rr_ratio=2.6,
                    )

                    if not sizing['valid']:
                        add_log(f"  🛡️ [Risk Veto] {coin_name}: {sizing['reason']}")
                        continue

                    dir_label = 'LONG' if trigger_side == 'buy' else 'SHORT'
                    add_log(
                        f"📐 [YHL {setup_reason}] {dir_label} em {coin_name} @ ${sizing['entry_price']:.4f} | "
                        f"TP: ${sizing['tp_price']:.4f} | SL: ${sizing['sl_price']:.4f}"
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
                            yesterday_high, yesterday_low, atr, leverage,
                            sizing['tp_price'], sizing['sl_price'], total_equity,
                            '✅ EXECUTADA', setup_reason
                        )

                    time.sleep(0.4)

            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)

    except Exception as e:
        add_log(f"⚠️ Falha grave no loop da estratégia YHL: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("📐 Estratégia YHL Mínima/Máxima Diária Finalizada.")
