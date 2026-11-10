"""
strategies/candlestick_rsi_scalper.py — 🕯️ PRICE ACTION (Pinbar/Engulfing) + RSI + OBI SCALPER

Refatorada com as Skills Quantitativas (Claude & Grok Trading Desk):
- Corrigido bug crítico onde TP e SL eram calculados mas NÃO enviados na ordem, e posições abertas nunca eram monitoradas.
- Agora avalia a vela fechada (`idx=-2`) via `analyze_candle_anatomy` (Martelo, Estrela Cadente, Engolfo de Alta/Baixa),
  filtra por RSI + Bandas de Bollinger / VWAP + Order Book Imbalance (OBI),
  e executa com TP/SL atômicos + Breakeven em +1R e Trailing Stop Server-Side.
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
                f'{saldo:.2f}' if saldo is not None else '-', status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso log CSV: {e}")


def run_candlestick_rsi_strategy(exchange, symbol='MULTI', leverage=15, check_interval=6):
    init_trade_log()

    is_multi = (symbol == "MULTI")
    symbols_to_scan = DEFAULT_SCAN_SYMBOLS if is_multi else [
        symbol if ':' in symbol else f"{symbol.split('/')[0]}/USDT:USDT"
    ]

    add_log(f"{'=' * 58}")
    add_log(f"🕯️ ESTRATÉGIA CANDLESTICK PRICE ACTION + RSI — {'MULTI-SCAN' if is_multi else symbols_to_scan[0]}")
    add_log(f"📊 Skills: Closed-Candle Pinbar/Engulfing + RSI + OBI + ATR Stop ({leverage}x)")
    add_log(f"{'=' * 58}")

    bot_state["is_running"] = True
    bot_state["status"] = f"🕯️ Candle+RSI ({leverage}x)"
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
    daily_profit_target = max(0.50, initial_equity * 0.08)
    daily_loss_limit = min(-0.30, -initial_equity * 0.04)

    active_positions = {}
    MAX_POSITIONS = 2
    scan_count = 0

    try:
        while bot_state.get("is_running", False):
            scan_count += 1
            available_usd, total_equity = get_available_margin_usd(exchange)
            if available_usd is None or total_equity is None:
                time.sleep(check_interval)
                continue

            bot_state["usdt_balance"] = total_equity
            collateral_usd = available_usd

            delta = total_equity - initial_equity
            if delta >= daily_profit_target:
                add_log(f"🏆 Meta diária atingida (+${delta:.2f})! Encerrando Candlestick+RSI.")
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
                        add_log(f"🕯️ {sym.split('/')[0]} {side} | PnL: ${unpnl:+.4f} ({roi:+.2f}%) | SL: ${active_positions[sym].get('current_sl', 0):.4f}")

                closed_symbols = list(set(active_positions.keys()) - current_open_symbols)
                for sym in closed_symbols:
                    time.sleep(2.5)
                    details = get_closed_pnl_details(exchange, sym)
                    pnl = details['pnl']
                    exit_p = details['exit_price'] or active_positions[sym]['entry_price']
                    emoji = "🏆 LUCRO" if pnl > 0 else "💀 LOSS"
                    add_log(f"{emoji} [CANDLE+RSI] {sym} encerrada | PnL: ${pnl:+.4f}")
                    log_trade(
                        sym, 'SAÍDA', active_positions[sym]['side'], exit_p,
                        active_positions[sym].get('pattern', '-'), None, leverage,
                        None, None, total_equity, emoji, f"{pnl:+.4f}"
                    )
                    del active_positions[sym]
            except Exception as e:
                add_log(f"⚠️ Erro ao monitorar posições: {e}")

            # 2. Scanner de Padrões de Candlestick na Vela Fechada (-2) + RSI
            if len(active_positions) < MAX_POSITIONS:
                add_log(f"── Candlestick Scanner #{scan_count} | Ativas: {len(active_positions)}/{MAX_POSITIONS} | Saldo: ${collateral_usd:.2f} ──")

                for sym in symbols_to_scan:
                    if not bot_state.get("is_running", False) or len(active_positions) >= MAX_POSITIONS:
                        break
                    if sym in active_positions:
                        continue

                    coin_name = sym.split('/')[0]
                    bot_state["coin_name"] = coin_name

                    analysis = MarketRegimeSkill.analyze_asset(exchange, sym, ltf='5m', htf='1h')
                    if not analysis or not analysis['candle']:
                        continue

                    price = analysis['current_price']
                    rsi = analysis['rsi']
                    atr = analysis['atr']
                    rvol = analysis['rvol']
                    candle = analysis['candle']
                    pattern_name = candle['pattern_name']
                    pattern_bias = candle['pattern_bias']

                    bot_state["current_price"] = price
                    bot_state["rsi"] = rsi
                    bot_state["rsi_status"] = f"RSI: {rsi:.1f} | Padrão: {pattern_name or 'Nenhum'}"

                    add_log(f"  {coin_name}: ${price:,.4f} | RSI: {rsi:.1f} | Padrão: {pattern_name or '-'} | RVOL: {rvol:.2f}x")

                    trigger_side = None
                    if pattern_bias == 'BULLISH' and (rsi <= 42 or (analysis['htf_trend'] == 'UPTREND' and rsi <= 52)):
                        trigger_side = 'buy'
                    elif pattern_bias == 'BEARISH' and (rsi >= 58 or (analysis['htf_trend'] == 'DOWNTREND' and rsi >= 48)):
                        trigger_side = 'sell'

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
                        risk_margin_pct=0.14,
                        atr_sl_mult=1.9,
                        rr_ratio=2.4,
                    )

                    if not sizing['valid']:
                        add_log(f"  🛡️ [Risk Veto] {coin_name}: {sizing['reason']}")
                        continue

                    dir_label = 'LONG' if trigger_side == 'buy' else 'SHORT'
                    add_log(
                        f"🕯️ [SINAL {dir_label}] {coin_name} | Padrão: {pattern_name} | RSI: {rsi:.1f} | "
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
                            'pattern': pattern_name,
                            'breakeven_locked': False,
                        }
                        log_trade(
                            sym, 'ENTRADA', dir_label, sizing['entry_price'],
                            pattern_name, rsi, leverage,
                            sizing['tp_price'], sizing['sl_price'], total_equity,
                            '✅ EXECUTADA', f'RVOL: {rvol:.2f}x | OBI: {ob["obi"]:+.2f}'
                        )

                    time.sleep(0.4)

            for _ in range(check_interval):
                if not bot_state.get("is_running", False):
                    break
                time.sleep(1)

    except Exception as e:
        add_log(f"⚠️ Erro no loop principal da estratégia Candlestick+RSI: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("🛑 Estratégia Candlestick + RSI finalizada.")
