import time
import sys
import os
import csv
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_ohlcv_data, calculate_rsi, calculate_ema, calculate_macd
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance, get_available_margin_usd, enable_btc_collateral, place_maker_entry, get_closed_pnl

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'fibonacci_trades.csv')

def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço',
                'Swing Low', 'Swing High', 'Fib 61.8%', 'Fib 78.6%', 'Alavancagem', 'TP Alvo', 'SL Alvo',
                'Saldo USD', 'Status', 'Detalhes'
            ])

def log_trade(symbol, tipo, direcao, preco, swing_l, swing_h, fib_618, fib_786, leverage, tp, sl, saldo, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.4f}',
                f'{swing_l:.4f}' if swing_l else '-', f'{swing_h:.4f}' if swing_h else '-',
                f'{fib_618:.4f}' if fib_618 else '-', f'{fib_786:.4f}' if fib_786 else '-',
                f'{leverage}x',
                f'{tp:.4f}' if tp else '-', f'{sl:.4f}' if sl else '-',
                f'{saldo:.2f}', status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso log CSV: {e}")

def run_fibonacci_strategy(exchange, symbol='MULTI', leverage=25, check_interval=10):
    init_trade_log()

    is_multi = (symbol == "MULTI")
    symbols_to_scan = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "ADA/USDT:USDT", "DOGE/USDT:USDT"] if is_multi else [symbol]

    add_log(f"{'='*55}")
    add_log(f"📐 ESTRATÉGIA RETRAÇÃO FIBONACCI 61.8% — {'MULTI-SCAN' if is_multi else symbol}")
    add_log(f"📊 Swings no 5m e Entrada no Toque do 1m | Alavancagem: {leverage}x")
    add_log(f"{'='*55}")

    bot_state["is_running"] = True
    bot_state["status"]     = f"📐 Fibonacci ({leverage}x)"
    bot_state["coin_name"]  = "SCANNING" if is_multi else symbol.split('/')[0]

    enable_btc_collateral(exchange)

    for sym in symbols_to_scan:
        try:
            exchange.set_leverage(leverage, sym)
            add_log(f"Alavancagem setada para {leverage}x em {sym}!")
        except Exception as e:
            pass

    # Saldo Inicial
    available_usd, total_equity = get_available_margin_usd(exchange)
    if available_usd is None or total_equity is None:
        add_log("❌ Falha ao ler saldo inicial. Encerrando.")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Erro API"
        return

    bot_state["usdt_balance"]       = total_equity  # Mostra patrimônio total
    initial_equity_usd              = total_equity
    daily_profit_target_usd         = max(0.50, 0.05 * initial_equity_usd)   # meta +5% (mínimo $0.50)
    daily_loss_limit_usd            = min(-0.25, -0.02 * initial_equity_usd)  # limite -2% (mínimo -$0.25 para evitar desligamento precoce)

    active_positions = {}
    last_trade_swing = {}  # {sym: (min_low, max_high)} para evitar re-entradas no mesmo swing
    MAX_POSITIONS = 3
    scan_count = 0

    try:
        while bot_state["is_running"]:
            scan_count += 1
            available_usd, total_equity = get_available_margin_usd(exchange)
            if available_usd is None or total_equity is None:
                add_log("⚠️ Erro ao ler saldo. Aguardando...")
                time.sleep( check_interval )
                continue
            bot_state["usdt_balance"] = total_equity
            collateral_usd = available_usd

            # Metas diárias baseadas no Patrimônio Total (impede ruídos por margem bloqueada)
            delta = total_equity - initial_equity_usd
            if delta >= daily_profit_target_usd:
                add_log(f"🏆 Meta de lucro diário atingida! Lucro: ${delta:.2f}. Desligando bot.")
                break
            if delta <= daily_loss_limit_usd:
                add_log(f"❌ Limite de perda diário atingido! Perda: ${abs(delta):.2f}. Desligando bot.")
                break

            # --- MONITORAMENTO DE POSIÇÕES ABERTAS ---
            try:
                all_positions = []
                for sym in symbols_to_scan:
                    try:
                        all_positions.extend(exchange.fetch_positions([sym]))
                    except:
                        pass
                current_open_symbols = set()

                for pos in all_positions:
                    contracts = float(pos.get('contracts') or 0)
                    if contracts > 0:
                        sym = pos['symbol']
                        current_open_symbols.add(sym)

                        entry_p = float(pos.get('entryPrice') or 0)
                        side = pos['side'].upper()
                        if sym not in active_positions:
                            active_positions[sym] = {'side': side, 'entry_price': entry_p}
                            log_trade(sym, 'DETECT', 'ENTRADA', side, entry_p, 0, 0, 0, 0, leverage, 0, 0, collateral_usd, '✅ Posição Detectada')

                        unrealized_pnl = float(pos.get('unrealizedPnl') or 0)
                        liq_price = pos.get('liquidationPrice')
                        roi = pos.get('percentage')
                        margin = pos.get('initialMargin')

                        liq_str = f" | Liq: ${float(liq_price or 0):,.2f}" if liq_price else ""
                        roi_str = f" | ROI: {float(roi or 0):+.2f}%" if roi is not None else ""
                        marg_str = f" | Margem: ${float(margin or 0):.2f}" if margin else ""

                        add_log(f"📊 {sym} {side} Aberto:")
                        add_log(f"  💰 Qtd: {contracts}{marg_str}{liq_str}")
                        add_log(f"  💵 PnL: ${unrealized_pnl:+.4f}{roi_str}")

                # Checa fechamentos
                closed_symbols = list(set(active_positions.keys()) - current_open_symbols)
                for sym in closed_symbols:
                    new_collateral_usd, _ = get_available_margin_usd(exchange)
                    time.sleep(3)
                    resultado = get_closed_pnl(exchange, sym, limit=1)
                    resultado_emoji = "🏆 LUCRO" if resultado > 0 else "💀 LOSS"

                    add_log(f"{'='*50}")
                    add_log(f"{resultado_emoji}: Fechamento em {sym} | ${resultado:+.4f}")
                    add_log(f"{'='*50}")

                    try:
                        ticker = exchange.fetch_ticker(sym)
                        close_price = float(ticker['last'])
                    except:
                        close_price = active_positions[sym]['entry_price']

                    resultado_str = f"{'+$' if resultado >= 0 else '-$'}{abs(resultado):.4f}"
                    log_trade(sym, 'OUT', active_positions[sym]['side'], close_price, 0, 0, 0, 0, leverage, 0, 0, new_collateral_usd, resultado_emoji, resultado_str)
                    del active_positions[sym]
                    collateral_usd = new_collateral_usd
            except Exception as e:
                add_log(f"⚠️ Erro ao monitorar posições: {e}")

            # --- BUSCA POR NOVAS ENTRADAS (VELAS 5m SWING E 1m TOQUE) ---
            if len(active_positions) < MAX_POSITIONS:
                add_log(f"── Scanner #{scan_count} | Abertas {len(active_positions)}/{MAX_POSITIONS} | Saldo: ${collateral_usd:.2f} ──")

                for sym in symbols_to_scan:
                    if not bot_state["is_running"] or len(active_positions) >= MAX_POSITIONS: break
                    if sym in active_positions: continue

                    coin_name = sym.split('/')[0]
                    bot_state["coin_name"] = coin_name

                    # 1. Obter dados de 1m (limit=210 para podermos calcular EMA 200)
                    ohlcv_1m = fetch_ohlcv_data(exchange, sym, timeframe='1m', limit=210)
                    if not ohlcv_1m or len(ohlcv_1m['c']) < 200: continue
                    current_price = ohlcv_1m['c'][-1]
                    bot_state["current_price"] = current_price

                    # 2. Calcular Swings baseados nas últimas 30 velas de 1m
                    highs_30 = ohlcv_1m['h'][-30:]
                    lows_30 = ohlcv_1m['l'][-30:]
                    closes_1m = ohlcv_1m['c']

                    max_high = max(highs_30)
                    min_low = min(lows_30)
                    diff = max_high - min_low

                    if diff <= 0: continue

                    max_high_idx = highs_30.index(max_high)
                    min_low_idx = lows_30.index(min_low)

                    # 3. Calcular Indicadores Técnicos de Confirmação no gráfico de 1m
                    rsi_1m = calculate_rsi(closes_1m, period=14)
                    ema200 = calculate_ema(closes_1m, period=200)
                    macd_line, signal_line, macd_hist = calculate_macd(closes_1m)

                    if rsi_1m is None or ema200 is None or macd_hist is None: continue

                    # Identifica tipo de Swing e níveis Fib baseado na cronologia
                    if min_low_idx < max_high_idx:
                        # Swing Bullish (Uptrend) -> Procuramos LONG na retração
                        trend = "ALTA 📈"
                        fib_618 = min_low + 0.618 * diff
                        tp_price = max_high
                        sl_price = min_low # Fundo do Swing para segurança

                        # Trava de Stop Loss percentual máxima (1.5%)
                        max_sl_dist = current_price * 0.015
                        if (current_price - sl_price) > max_sl_dist:
                            sl_price = current_price - max_sl_dist

                        # Evita re-entrar no mesmo swing
                        swing_tuple = (min_low, max_high)
                        if last_trade_swing.get(sym) == swing_tuple:
                            continue

                        # Loga status dos indicadores no scanner
                        add_log(f"  {coin_name}: Preço: ${current_price:,.4f} | Fib 61.8%: ${fib_618:,.4f} | Sl (Fundo): ${sl_price:,.4f} | RSI: {rsi_1m:.1f} | EMA200: {ema200:.2f}")

                        # Gatilhos + Indicadores
                        # 1. Preço entre Fib 61.8% e o Fundo do Swing (min_low)
                        # 2. Preço acima da EMA 200 (Tendência de Alta)
                        # 3. RSI em zona de recuo (<= 50)
                        # 4. Histograma do MACD indicando que a queda desacelerou
                        if (sl_price < current_price <= fib_618 and 
                            current_price > ema200 and 
                            rsi_1m <= 50 and 
                            macd_hist > -0.05 * current_price):
                            
                            add_log(f"📐 SINAL FIBONACCI LONG CONFIRMADO em {coin_name}! Entrada em {current_price:,.4f}")
                            RISK_PER_TRADE_PCT = 0.01
                            trade_size_usd = max(2.0, collateral_usd * RISK_PER_TRADE_PCT * leverage)
                            amount = trade_size_usd / current_price
                            
                            tp_price_prec = float(exchange.price_to_precision(sym, tp_price))
                            sl_price_prec = float(exchange.price_to_precision(sym, sl_price))

                            try:
                                _, filled = place_maker_entry(exchange, sym, 'buy', amount, current_price, tp_price_prec, sl_price_prec)
                                if filled:
                                    active_positions[sym] = {'side': 'LONG', 'entry_price': current_price}
                                    last_trade_swing[sym] = swing_tuple
                                    log_trade(sym, 'ENTRADA', 'LONG', current_price, min_low, max_high, fib_618, sl_price, leverage, tp_price_prec, sl_price_prec, collateral_usd, '✅ SUCESSO', f'RSI: {rsi_1m:.1f}')
                            except Exception as e:
                                add_log(f"❌ Erro de Entrada LONG: {e}")

                    else:
                        # Swing Bearish (Downtrend) -> Procuramos SHORT na retração
                        trend = "BAIXA 📉"
                        fib_618 = max_high - 0.618 * diff
                        tp_price = min_low
                        sl_price = max_high # Topo do Swing para segurança

                        # Trava de Stop Loss percentual máxima (1.5%)
                        max_sl_dist = current_price * 0.015
                        if (sl_price - current_price) > max_sl_dist:
                            sl_price = current_price + max_sl_dist

                        swing_tuple = (min_low, max_high)
                        if last_trade_swing.get(sym) == swing_tuple:
                            continue

                        # Loga status dos indicadores no scanner
                        add_log(f"  {coin_name}: Preço: ${current_price:,.4f} | Fib 61.8%: ${fib_618:,.4f} | Sl (Topo): ${sl_price:,.4f} | RSI: {rsi_1m:.1f} | EMA200: {ema200:.2f}")

                        # Gatilhos + Indicadores
                        # 1. Preço entre Fib 61.8% e o Topo do Swing (max_high)
                        # 2. Preço abaixo da EMA 200 (Tendência de Baixa)
                        # 3. RSI em zona de recuo (>= 50)
                        # 4. Histograma do MACD indicando que a alta desacelerou
                        if (fib_618 <= current_price < sl_price and 
                            current_price < ema200 and 
                            rsi_1m >= 50 and 
                            macd_hist < 0.05 * current_price):
                            
                            add_log(f"📐 SINAL FIBONACCI SHORT CONFIRMADO em {coin_name}! Entrada em {current_price:,.4f}")
                            RISK_PER_TRADE_PCT = 0.01
                            trade_size_usd = max(2.0, collateral_usd * RISK_PER_TRADE_PCT * leverage)
                            amount = trade_size_usd / current_price
                            
                            tp_price_prec = float(exchange.price_to_precision(sym, tp_price))
                            sl_price_prec = float(exchange.price_to_precision(sym, sl_price))

                            try:
                                _, filled = place_maker_entry(exchange, sym, 'sell', amount, current_price, tp_price_prec, sl_price_prec)
                                if filled:
                                    active_positions[sym] = {'side': 'SHORT', 'entry_price': current_price}
                                    last_trade_swing[sym] = swing_tuple
                                    log_trade(sym, 'ENTRADA', 'SHORT', current_price, min_low, max_high, fib_618, sl_price, leverage, tp_price_prec, sl_price_prec, collateral_usd, '✅ SUCESSO', f'RSI: {rsi_5m:.1f}')
                            except Exception as e:
                                add_log(f"❌ Erro de Entrada SHORT: {e}")

                    time.sleep(0.5)

            for _ in range(check_interval):
                if not bot_state["is_running"]: break
                time.sleep(1)

    except Exception as e:
        add_log(f"💥 Erro Crítico na Estratégia Fibonacci: {e}")
    finally:
        add_log(f"{'='*55}")
        add_log("Estratégia Fibonacci Finalizada.")
        bot_state["is_running"] = False
        bot_state["status"]     = "🔴 Desligado"
