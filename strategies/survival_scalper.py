"""
strategies/survival_scalper.py — ⚔️ SURVIVAL SCALPER PRO (Micro-Account Compounder)

Refatorada com as Skills Quantitativas (Claude & Grok Trading Desk):
- Otimizada para bancas pequenas ($3 a $100) com filtro inteligente de lote mínimo (`RiskOfficerSkill`).
- Combina sinais de Tendência (HTF + VWAP + EMA200) e Contra-Tendência Extrema (RSI + Pavio de Rejeição + OBI).
- Defesa ativa agressiva: ativa Breakeven rápido em +1R e Trailing Stop Server-Side para proteger cada centavo.
"""

import time
import sys
import os
import csv
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.shared_state import bot_state, add_log
from core.balance_utils import (
    get_unified_balance,
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
LOG_FILE = os.path.join(LOG_DIR, 'survival_trades.csv')
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'risk_params.json')


def load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f).get('survival_scalper', {})
    except Exception:
        return {
            "max_leverage": 20,
            "risk_per_trade": 0.18,
            "max_daily_loss_pct": 0.15,
            "min_balance": 2.0,
        }


def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço',
                'RSI', 'EMA200', 'MACD', 'Valor ($)', 'Alavancagem', 'TP Alvo', 'SL Alvo',
                'Saldo USD', 'Status', 'Detalhes'
            ])


def log_trade(symbol, tipo, direcao, preco, rsi, valor, leverage, tp, sl, saldo, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.4f}' if preco else '-',
                f'{rsi:.1f}' if rsi else '-', '-', '-',
                f'{valor:.2f}' if valor else '0', f'{leverage}x',
                f'{tp:.4f}' if tp else '-', f'{sl:.4f}' if sl else '-',
                f'{saldo:.2f}' if saldo is not None else '-', status, str(detalhes)
            ])
    except Exception as e:
        add_log(f"Aviso log CSV: {e}")


def run_survival_scalper(exchange, symbol='MULTI'):
    is_multi = (symbol == "MULTI")
    # Ordena pares de lote mínimo baixo primeiro para maximizar compatibilidade com bancas pequenas
    low_lot_priority = [
        "XRP/USDT:USDT",
        "DOGE/USDT:USDT",
        "ADA/USDT:USDT",
        "SOL/USDT:USDT",
        "ETH/USDT:USDT",
        "BNB/USDT:USDT",
        "BTC/USDT:USDT",
    ]
    symbols_to_scan = low_lot_priority if is_multi else [
        symbol if ':' in symbol else f"{symbol.split('/')[0]}/USDT:USDT"
    ]

    init_trade_log()
    config = load_config()
    leverage = int(config.get('max_leverage', 20))
    risk_pct = float(config.get('risk_per_trade', 0.38))
    min_balance = float(config.get('min_balance', 2.0))

    add_log(f"{'=' * 58}")
    add_log(f"⚔️ [SURVIVAL SCALPER PRO] Iniciado em {'MULTI' if is_multi else symbols_to_scan[0]} ({leverage}x)")
    add_log(f"🛡️ Skills: Smart Min-Lot Filter + MTF Confluence + Breakeven +1R")
    add_log(f"{'=' * 58}")

    bot_state["is_running"] = True
    bot_state["status"] = f"⚔️ Survival ({leverage}x)"

    enable_btc_collateral(exchange)
    for sym in symbols_to_scan:
        ExecutionProtocolSkill.setup_symbol_derivatives(exchange, sym, leverage, margin_mode='cross')

    collateral_usd, total_equity = get_available_margin_usd(exchange)
    if collateral_usd is None or total_equity is None:
        add_log("❌ Falha crítica ao ler o saldo inicial na Bybit UTA.")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Erro API"
        return

    bot_state["usdt_balance"] = total_equity
    starting_equity = total_equity

    if total_equity < min_balance:
        add_log(f"❌ BANCA INSUFICIENTE! Mínimo ${min_balance:.2f}, Atual: ${total_equity:.2f}")
        bot_state["is_running"] = False
        return

    active_positions = {}
    MAX_POSITIONS = 2
    check_interval = 6
    scan_count = 0
    max_loss_pct = min(0.15, float(config.get('max_daily_loss_pct', 0.15)))

    try:
        while bot_state["is_running"]:
            scan_count += 1
            collateral_usd, total_equity = get_available_margin_usd(exchange)
            if collateral_usd is None or total_equity is None:
                time.sleep(5)
                continue
            bot_state["usdt_balance"] = total_equity

            if total_equity <= starting_equity * (1.0 - max_loss_pct):
                add_log(f"🛑 [RISK OFFICER] Stop Diário de Sobrevivência atingido (${total_equity:.2f}).")
                break

            # 1. Monitoramento e Defesa Ativa de Posições
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
                                'sl_dist': entry_p * 0.005,
                                'current_sl': 0.0,
                                'breakeven_locked': False,
                            }

                        RiskOfficerSkill.manage_open_position(exchange, sym, pos, active_positions[sym])
                        bot_state["unrealized_pnl"] = unpnl
                        add_log(f"⚔️ {sym.split('/')[0]} {side} | PnL: ${unpnl:+.4f} ({roi:+.2f}%) | SL: ${active_positions[sym].get('current_sl', 0):.4f}")

                closed_symbols = list(set(active_positions.keys()) - current_open_symbols)
                for sym in closed_symbols:
                    time.sleep(2.5)
                    details = get_closed_pnl_details(exchange, sym)
                    resultado = details['pnl']
                    close_price = details['exit_price'] or active_positions[sym]['entry_price']
                    resultado_emoji = "🏆 LUCRO" if resultado > 0 else "💀 LOSS"
                    add_log(f"{resultado_emoji}: Fechamento Survival em {sym} | ${resultado:+.4f}")
                    log_trade(
                        sym, 'SAÍDA', active_positions[sym]['side'], close_price,
                        0, 0, leverage, 0, 0, total_equity, resultado_emoji, f"{resultado:+.4f}"
                    )
                    del active_positions[sym]
            except Exception as e:
                add_log(f"⚠️ Erro ao monitorar posições: {e}")

            # 2. Scanner Survival Pro
            if len(active_positions) < MAX_POSITIONS:
                add_log(f"── Survival Scanner #{scan_count} | Abertas {len(active_positions)}/{MAX_POSITIONS} | Margem: ${collateral_usd:.2f} ──")

                for sym in symbols_to_scan:
                    if not bot_state["is_running"] or len(active_positions) >= MAX_POSITIONS:
                        break
                    if sym in active_positions:
                        continue

                    coin_name = sym.split('/')[0]
                    bot_state["coin_name"] = coin_name

                    analysis = MarketRegimeSkill.analyze_asset(exchange, sym, ltf='5m', htf='1h')
                    if not analysis or analysis['regime'] == 'HIGH_VOL_CHOP':
                        continue

                    price = analysis['current_price']
                    rsi = analysis['rsi']
                    prev_rsi = analysis['prev_rsi']
                    ema200 = analysis['ema200']
                    vwap = analysis['vwap']
                    atr = analysis['atr']
                    htf_trend = analysis['htf_trend']
                    candle = analysis['candle']

                    bot_state["current_price"] = price
                    bot_state["rsi"] = rsi
                    bot_state["rsi_status"] = f"HTF: {htf_trend} | RSI: {rsi:.1f}"

                    add_log(f"  {coin_name}: ${price:,.4f} | RSI: {rsi:.1f} (Ant: {prev_rsi:.1f}) | HTF: {htf_trend}")

                    trigger_side = None
                    signal_type = None

                    # Gatilho LONG: Exaustão de Sobrevenda ou Pullback na Tendência de Alta
                    if rsi <= 28 and rsi > prev_rsi and candle and candle['lower_wick_ratio'] >= 1.0:
                        trigger_side = 'buy'
                        signal_type = 'REVERSÃO_EXTREMA'
                    elif 35 <= rsi <= 46 and rsi > prev_rsi and htf_trend == 'UPTREND' and price > ema200 and price > vwap:
                        trigger_side = 'buy'
                        signal_type = 'TENDÊNCIA_HTF'

                    # Gatilho SHORT: Exaustão de Sobrecompra ou Pullback na Tendência de Baixa
                    elif rsi >= 72 and rsi < prev_rsi and candle and candle['upper_wick_ratio'] >= 1.0:
                        trigger_side = 'sell'
                        signal_type = 'REVERSÃO_EXTREMA'
                    elif 54 <= rsi <= 65 and rsi < prev_rsi and htf_trend == 'DOWNTREND' and price < ema200 and price < vwap:
                        trigger_side = 'sell'
                        signal_type = 'TENDÊNCIA_HTF'

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
                        risk_margin_pct=risk_pct,
                        atr_sl_mult=1.9,
                        rr_ratio=2.6,
                    )

                    if not sizing['valid']:
                        continue

                    dir_label = 'LONG' if trigger_side == 'buy' else 'SHORT'
                    add_log(f"⚔️ SINAL SURVIVAL {dir_label} ({signal_type}) em {coin_name} @ ${sizing['entry_price']:.4f}!")

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
                            rsi, sizing['margin_usd'], leverage,
                            sizing['tp_price'], sizing['sl_price'], total_equity,
                            f'✅ EXECUTADA ({signal_type})', f'OBI: {ob["obi"]:+.2f}'
                        )

                    time.sleep(0.4)

            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)

    except Exception as e:
        add_log(f"⚠️ Erro crítico no Survival Scalper: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("⚔️ Survival Scalper Finalizado.")
