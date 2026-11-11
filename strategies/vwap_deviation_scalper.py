"""
strategies/vwap_deviation_scalper.py — 🌊 VWAP DEVIATION SCALPER (±2 Sigma Z-Score Mean Reversion)

Refatorada com as Skills Quantitativas (Claude & Grok Trading Desk):
- Corrigida falha grave da versão anterior (que operava SEM Stop Loss e apenas LONG).
- Agora opera LONG (Z-Score <= -1.85 + RSI Sobrevendido + Rejeição) e SHORT (Z-Score >= +1.85 + RSI Sobrecomprado + Rejeição).
- Inclui Stop Loss dinâmico por ATR obrigatório, alvo na VWAP central (mínimo 2.0R),
  Breakeven automático em +1R e Trailing Stop Server-Side.
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
LOG_FILE = os.path.join(LOG_DIR, 'vwap_deviation_trades.csv')


def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço Executado',
                'VWAP', 'Z_Score', 'RSI', 'Alavancagem',
                'Take Profit', 'Stop Loss', 'Saldo USD', 'Status', 'Detalhes'
            ])


def log_trade(symbol, tipo, direcao, preco, vwap, z_score, rsi, leverage, tp, sl, saldo, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.4f}' if preco else '-',
                f'{vwap:.4f}' if vwap else '-', f'{z_score:+.2f}' if z_score is not None else '-',
                f'{rsi:.1f}' if rsi else '-',
                f'{leverage}x',
                f'{tp:.4f}' if tp else '-', f'{sl:.4f}' if sl else '-',
                f'{saldo:.2f}' if saldo is not None else '-', status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso log CSV: {e}")


def run_vwap_deviation_strategy(exchange, symbol='MULTI', leverage=20, check_interval=6):
    init_trade_log()

    is_multi = (symbol == "MULTI")
    symbols_to_scan = DEFAULT_SCAN_SYMBOLS if is_multi else [
        symbol if ':' in symbol else f"{symbol.split('/')[0]}/USDT:USDT"
    ]

    add_log(f"{'=' * 58}")
    add_log(f"🌊 ESTRATÉGIA VWAP ±2σ Z-SCORE — {'MULTI-SCAN' if is_multi else symbols_to_scan[0]}")
    add_log(f"📊 Skills: VWAP Sigma Bands + OBI + Mandatory ATR Stop ({leverage}x)")
    add_log(f"{'=' * 58}")

    bot_state["is_running"] = True
    bot_state["status"] = f"🌊 VWAP Dev ({leverage}x)"
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
                add_log(f"🏆 Meta diária atingida (+${delta:.2f})! Encerrando VWAP Scalper.")
                break
            if delta <= daily_loss_limit:
                add_log(f"🛑 Limite de perda diário atingido (-${abs(delta):.2f}).")
                break

            # 1. Monitoramento & Defesa Ativa de Posições
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
                        bot_state["status"] = f"🌊 {sym.split('/')[0]} {side} ({roi:+.2f}%)"

                closed_symbols = list(set(active_positions.keys()) - current_open_symbols)
                for sym in closed_symbols:
                    time.sleep(2.5)
                    details = get_closed_pnl_details(exchange, sym)
                    resultado = details['pnl']
                    exit_price = details['exit_price'] or active_positions[sym]['entry_price']
                    resultado_emoji = "🏆 LUCRO" if resultado > 0 else "💀 LOSS"
                    add_log(f"🚪 Posição VWAP fechada em {sym}! PnL: ${resultado:+.4f} {resultado_emoji}")
                    log_trade(
                        sym, 'SAÍDA', active_positions[sym]['side'], exit_price,
                        None, None, None, leverage, None, None, total_equity,
                        resultado_emoji, f"{resultado:+.4f}"
                    )
                    del active_positions[sym]
                    bot_state["unrealized_pnl"] = 0.0
            except Exception as e:
                add_log(f"⚠️ Erro ao monitorar posições: {e}")

            # 2. Scanner de Desvio Estatístico da VWAP (±2 SD)
            if len(active_positions) < MAX_POSITIONS:
                add_log(f"── VWAP Sigma Scanner #{scan_count} | Ativas: {len(active_positions)}/{MAX_POSITIONS} | Saldo: ${collateral_usd:.2f} ──")

                for sym in symbols_to_scan:
                    if not bot_state["is_running"] or len(active_positions) >= MAX_POSITIONS:
                        break
                    if sym in active_positions:
                        continue

                    coin_name = sym.split('/')[0]
                    bot_state["coin_name"] = coin_name

                    analysis = MarketRegimeSkill.analyze_asset(exchange, sym, ltf='5m', htf='1h')
                    if not analysis or not analysis['vwap_bands']:
                        continue

                    price = analysis['current_price']
                    rsi = analysis['rsi']
                    prev_rsi = analysis['prev_rsi']
                    vwap = analysis['vwap']
                    vb = analysis['vwap_bands']
                    z_score = vb['z_score']
                    atr = analysis['atr']
                    candle = analysis['candle']

                    bot_state["current_price"] = price
                    bot_state["rsi"] = rsi
                    bot_state["rsi_status"] = f"VWAP: ${vwap:.4f} | Z: {z_score:+.2f}σ"

                    add_log(f"  {coin_name}: ${price:,.4f} | VWAP: ${vwap:,.4f} | Z-Score: {z_score:+.2f}σ | RSI: {rsi:.1f}")

                    trigger_side = None
                    custom_tp = None

                    # Gatilho LONG: Preço abaixo de -1.85 Sigma da VWAP + RSI Sobrevendido virando para cima
                    if z_score <= -1.85 and rsi <= 36 and rsi >= prev_rsi - 0.5:
                        if candle and (candle['lower_wick_ratio'] >= 0.8 or candle['is_bullish']):
                            trigger_side = 'buy'
                            custom_tp = max(vwap, price + 2.0 * atr)

                    # Gatilho SHORT: Preço acima de +1.85 Sigma da VWAP + RSI Sobrecomprado virando para baixo
                    elif z_score >= 1.85 and rsi >= 64 and rsi <= prev_rsi + 0.5:
                        if candle and (candle['upper_wick_ratio'] >= 0.8 or candle['is_bearish']):
                            trigger_side = 'sell'
                            custom_tp = min(vwap, price - 2.0 * atr)

                    if not trigger_side:
                        time.sleep(0.3)
                        continue

                    ob = MicrostructureSkill.get_orderbook_imbalance(exchange, sym)
                    if trigger_side == 'buy' and ob['obi'] < -0.22:
                        continue
                    if trigger_side == 'sell' and ob['obi'] > 0.22:
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
                        atr_sl_mult=1.8,
                        rr_ratio=2.2,
                        custom_tp_price=custom_tp,
                    )

                    if not sizing['valid']:
                        add_log(f"  🛡️ [Risk Veto] {coin_name}: {sizing['reason']}")
                        continue

                    dir_label = 'LONG' if trigger_side == 'buy' else 'SHORT'
                    add_log(
                        f"🌊 SINAL VWAP {dir_label} ({z_score:+.2f}σ) em {coin_name}! "
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
                            vwap, z_score, rsi, leverage,
                            sizing['tp_price'], sizing['sl_price'], total_equity,
                            '✅ EXECUTADA', f'Z: {z_score:+.2f}σ | OBI: {ob["obi"]:+.2f}'
                        )

                    time.sleep(0.4)

            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)

    except Exception as e:
        add_log(f"⚠️ Erro crítico no loop da estratégia VWAP: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("🌊 Estratégia VWAP Deviation Finalizada.")
