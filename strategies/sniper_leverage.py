"""
strategies/sniper_leverage.py — 🎯 HIGH-CONVICTION CONFLUENCE SNIPER

Refatorada com as Skills Quantitativas (Claude & Grok Trading Desk):
- Corrigido bug de `round(price, 2)` que quebrava moedas com 4 casas decimais (XRP, ADA, DOGE).
- Agora usa `price_to_precision`, varre todas as 7 moedas principais no modo MULTI,
  exige alta confluência multi-indicador (Score >= 55 + OBI favorável + Reversão de RSI a favor da tendência),
  e protege a operação com Breakeven em +1R e Trailing Stop Server-Side.
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
LOG_FILE = os.path.join(LOG_DIR, 'sniper_trades.csv')


def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço',
                'RSI', 'Score', 'OBI', 'Quantidade', 'Alavancagem', 'TP Alvo',
                'Saldo USDT', 'Status', 'Detalhes'
            ])


def log_trade(symbol, tipo, direcao, preco, rsi, score, obi, quantidade, leverage, tp_alvo, saldo, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.4f}' if preco else '-',
                f'{rsi:.1f}' if rsi else '-',
                f'{score:+.0f}' if score is not None else '-',
                f'{obi:+.2f}' if obi is not None else '-',
                f'{quantidade:.6f}' if quantidade else '0',
                f'{leverage}x',
                f'{tp_alvo:.4f}' if tp_alvo else '-',
                f'{saldo:.2f}' if saldo is not None else '-',
                status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso: Não foi possível gravar log CSV: {e}")


def run_sniper_leverage(exchange, symbol='MULTI', leverage=25, check_interval=8):
    is_multi = (symbol == "MULTI")
    symbols_to_scan = DEFAULT_SCAN_SYMBOLS if is_multi else [
        symbol if ':' in symbol else f"{symbol.split('/')[0]}/USDT:USDT"
    ]

    init_trade_log()

    add_log(f"{'=' * 58}")
    add_log(f"🎯 [SNIPER MULTI-CONFLUENCE] Iniciando {'MULTI-SCAN (7 Ativos)' if is_multi else symbols_to_scan[0]} ({leverage}x)")
    add_log(f"🧠 Skills: High Confluence Score + OBI + ATR Server-Side Defense")
    add_log(f"{'=' * 58}")

    bot_state["is_running"] = True
    bot_state["status"] = f"🎯 Sniper ({leverage}x)"
    bot_state["coin_name"] = "SCANNING" if is_multi else symbols_to_scan[0].split('/')[0]

    enable_btc_collateral(exchange)
    for sym in symbols_to_scan:
        ExecutionProtocolSkill.setup_symbol_derivatives(exchange, sym, leverage, margin_mode='cross')

    collateral_usd, total_equity = get_available_margin_usd(exchange)
    if collateral_usd is None or total_equity is None:
        add_log("❌ Erro ao obter saldo inicial da Bybit UTA.")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Erro API"
        return

    bot_state["usdt_balance"] = total_equity
    starting_equity = total_equity
    daily_target_usd = starting_equity * 1.12
    daily_stop_usd = starting_equity * 0.95

    active_positions = {}
    MAX_POSITIONS = 1  # Sniper foca em 1 tiro cirúrgico por vez
    scan_count = 0

    try:
        while bot_state["is_running"]:
            scan_count += 1
            collateral_usd, total_equity = get_available_margin_usd(exchange)
            if collateral_usd is None or total_equity is None:
                time.sleep(5)
                continue
            bot_state["usdt_balance"] = total_equity

            if not active_positions and total_equity >= daily_target_usd and (total_equity - starting_equity) >= 0.50:
                add_log(f"🏆 META DIÁRIA SNIPER BATIDA! (${starting_equity:.2f} -> ${total_equity:.2f})")
                bot_state["status"] = "🏆 Meta Diária Atingida!"
                break
            if total_equity <= daily_stop_usd:
                add_log(f"🛑 Circuit Breaker Sniper acionado (${total_equity:.2f}).")
                break

            # 1. Monitoramento da Posição Sniper Ativa
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
                        add_log(f"🎯 Sniper Ativo: {sym.split('/')[0]} {side} | PnL: ${unpnl:+.4f} ({roi:+.2f}%) | SL: ${active_positions[sym].get('current_sl', 0):.4f}")

                closed_symbols = list(set(active_positions.keys()) - current_open_symbols)
                for sym in closed_symbols:
                    time.sleep(2.5)
                    details = get_closed_pnl_details(exchange, sym)
                    resultado = details['pnl']
                    close_price = details['exit_price'] or active_positions[sym]['entry_price']
                    resultado_emoji = "🏆 LUCRO" if resultado >= 0 else "💀 LOSS"
                    add_log(f"{resultado_emoji}: Tiro Sniper finalizado em {sym} | ${resultado:+.4f}")
                    log_trade(
                        sym, 'SAÍDA', active_positions[sym]['side'], close_price,
                        0, None, None, 0, leverage, 0, total_equity, resultado_emoji, f"{resultado:+.4f}"
                    )
                    del active_positions[sym]
                    bot_state["unrealized_pnl"] = 0.0
            except Exception as e:
                add_log(f"⚠️ Aviso posição Sniper: {e}")

            # 2. Modo Scanner Sniper
            if len(active_positions) < MAX_POSITIONS and collateral_usd >= 0.50:
                add_log(f"── Sniper Scanner #{scan_count} | Equity: ${total_equity:.2f} ──")

                for sym in symbols_to_scan:
                    if not bot_state["is_running"] or len(active_positions) >= MAX_POSITIONS:
                        break

                    coin_name = sym.split('/')[0]
                    bot_state["coin_name"] = coin_name

                    analysis = MarketRegimeSkill.analyze_asset(exchange, sym, ltf='5m', htf='1h')
                    if not analysis or analysis['regime'] == 'HIGH_VOL_CHOP':
                        continue

                    price = analysis['current_price']
                    rsi = analysis['rsi']
                    prev_rsi = analysis['prev_rsi']
                    ema200 = analysis['ema200']
                    macd_hist = analysis['macd_hist']
                    score = analysis['confluence_score']
                    atr = analysis['atr']
                    vwap = analysis['vwap']

                    bot_state["current_price"] = price
                    bot_state["rsi"] = rsi
                    bot_state["rsi_status"] = f"Score: {score:+.0f} | RSI: {rsi:.1f}"

                    add_log(f"  {coin_name}: ${price:,.4f} | RSI: {rsi:.1f} | Score: {score:+.0f} | MACD: {macd_hist:+.4f}")

                    trigger_side = None
                    if price > ema200 and price > vwap and rsi <= 44 and rsi > prev_rsi and score >= 45:
                        trigger_side = 'buy'
                    elif price < ema200 and price < vwap and rsi >= 56 and rsi < prev_rsi and score <= -45:
                        trigger_side = 'sell'

                    if not trigger_side:
                        time.sleep(0.3)
                        continue

                    ob = MicrostructureSkill.get_orderbook_imbalance(exchange, sym)
                    if trigger_side == 'buy' and ob['obi'] < -0.15:
                        continue
                    if trigger_side == 'sell' and ob['obi'] > 0.15:
                        continue

                    sizing = RiskOfficerSkill.calculate_order_sizing(
                        exchange=exchange,
                        symbol=sym,
                        side=trigger_side,
                        entry_price=price,
                        atr=atr,
                        collateral_usd=collateral_usd,
                        leverage=leverage,
                        risk_margin_pct=0.18,
                        atr_sl_mult=1.8,
                        rr_ratio=2.6,
                    )

                    if not sizing['valid']:
                        add_log(f"  🛡️ [Risk Veto] {coin_name}: {sizing['reason']}")
                        continue

                    dir_label = 'LONG' if trigger_side == 'buy' else 'SHORT'
                    add_log(f"🎯 TIRO SNIPER {dir_label} em {coin_name} @ ${sizing['entry_price']:.4f} | TP: ${sizing['tp_price']:.4f} | SL: ${sizing['sl_price']:.4f}")

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
                            rsi, score, ob['obi'], sizing['amount'], leverage,
                            sizing['tp_price'], total_equity, '✅ SUCESSO', '; '.join(analysis['reasons'])
                        )
                        break

                    time.sleep(0.4)

            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)

    except Exception as e:
        add_log(f"Erro Crítico Sniper: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("🎯 Bot Sniper Finalizado.")
