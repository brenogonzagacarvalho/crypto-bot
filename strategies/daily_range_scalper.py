import time
import sys
import os
import csv
from datetime import datetime
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_ohlcv_data, calculate_atr, calculate_ema
from core.shared_state import bot_state, add_log
from core.balance_utils import get_available_margin_usd, enable_btc_collateral, get_closed_pnl, get_closed_pnl_details

# --- SISTEMA DE LOG EM CSV ---
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'daily_range_trades.csv')

def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço Executado',
                'Máxima Ontem', 'Mínima Ontem', 'ATR 1D', 'Alavancagem',
                'Take Profit', 'Stop Loss', 'Saldo USD', 'Status', 'Detalhes'
            ])

def log_trade(symbol, tipo, direcao, preco, swing_h, swing_l, atr_1d, leverage, tp, sl, saldo, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.4f}' if preco else '-',
                f'{swing_h:.4f}' if swing_h else '-', f'{swing_l:.4f}' if swing_l else '-',
                f'{atr_1d:.4f}' if atr_1d else '-',
                f'{leverage}x',
                f'{tp:.4f}' if tp else '-', f'{sl:.4f}' if sl else '-',
                f'{saldo:.2f}', status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso log CSV: {e}")

# --- LOOP PRINCIPAL DA ESTRATÉGIA ---
def run_daily_range_strategy(exchange, symbol='MULTI', leverage=20, check_interval=60):
    init_trade_log()

    is_multi = (symbol == "MULTI")
    symbols_to_scan = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "ADA/USDT:USDT", "DOGE/USDT:USDT", "BNB/USDT:USDT"] if is_multi else [symbol]

    add_log(f"{'='*55}")
    add_log(f"📐 ESTRATÉGIA MÍNIMA/MÁXIMA DIÁRIA (YHL) — {'MULTI-SCAN' if is_multi else symbol}")
    add_log(f"📊 Compras limite na mínima do dia anterior | Alavancagem: {leverage}x")
    add_log(f"{'='*55}")

    bot_state["is_running"] = True
    bot_state["status"]     = f"📐 Mín/Máx Diária ({leverage}x)"
    bot_state["coin_name"]  = "SCANNING" if is_multi else symbol.split('/')[0]

    enable_btc_collateral(exchange)

    # Configura alavancagem e margem isolada para as moedas
    for sym in symbols_to_scan:
        try:
            exchange.set_margin_mode('isolated', sym)
            add_log(f"Margem configurada para ISOLADA em {sym}!")
        except Exception as e:
            pass
        try:
            exchange.set_leverage(leverage, sym)
            add_log(f"Alavancagem setada para {leverage}x em {sym}!")
        except Exception as e:
            pass

    # Lê saldo inicial
    available_usd, total_equity = get_available_margin_usd(exchange)
    if available_usd is None or total_equity is None:
        add_log("❌ Falha ao ler saldo inicial. Encerrando.")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Erro API"
        return

    bot_state["usdt_balance"] = total_equity
    initial_equity_usd = total_equity
    daily_profit_target_usd = max(0.50, 0.05 * initial_equity_usd)   # meta +5%
    daily_loss_limit_usd = min(-0.25, -0.02 * initial_equity_usd)  # limite -2%

    active_positions = {}
    active_limit_orders = {}  # {sym: {'order_id': id, 'date_placed': 'YYYY-MM-DD'}}
    scan_count = 0

    try:
        while bot_state["is_running"]:
            scan_count += 1
            available_usd, total_equity = get_available_margin_usd(exchange)
            if available_usd is None or total_equity is None:
                add_log("⚠️ Erro ao ler saldo. Aguardando...")
                time.sleep(10)
                continue
            bot_state["usdt_balance"] = total_equity
            collateral_usd = available_usd

            # Verifica meta diária
            delta = total_equity - initial_equity_usd
            if delta >= daily_profit_target_usd:
                add_log(f"🏆 Meta de lucro diário atingida! Lucro: ${delta:.2f}. Desligando bot.")
                break
            if delta <= daily_loss_limit_usd:
                add_log(f"❌ Limite de perda diário atingido! Perda: ${abs(delta):.2f}. Desligando bot.")
                break

            current_utc_day = datetime.utcnow().strftime('%Y-%m-%d')

            # --- MONITORAMENTO DE POSIÇÕES E FECHAMENTOS ---
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
                        
                        # Se acabou de preencher a ordem
                        if sym not in active_positions:
                            active_positions[sym] = {
                                'side': side,
                                'entry_price': entry_p,
                                'contracts': contracts
                            }
                            # Se havia uma ordem limite rastreada, remove do dicionário de ordens
                            if sym in active_limit_orders:
                                del active_limit_orders[sym]
                            
                            add_log(f"🔔 Ordem Limite preenchida em {sym}! Posição de {side} aberta.")
                            log_trade(sym, 'ENTRADA', side, entry_p, None, None, None, leverage, None, None, collateral_usd, '✅ Posição Aberta')
                        elif contracts > active_positions[sym].get('contracts', 0):
                            # Significa que a ordem de preço médio (Order 2) foi preenchida!
                            new_tp_price = entry_p * (1 + 0.10 / leverage)
                            try:
                                market = exchange.market(sym)
                                bybit_symbol = market['id'] if market else sym.replace('/', '').split(':')[0]
                                exchange.privatePostV5PositionSetTpSl({
                                    'category': 'linear',
                                    'symbol': bybit_symbol,
                                    'takeProfit': f"{new_tp_price:.4f}".rstrip('0').rstrip('.'),
                                    'positionIdx': 0
                                })
                                add_log(f"🔄 Preço Médio acionado em {sym}! Preço de entrada recalculado para ${entry_p:.4f}. TP ajustado para ${new_tp_price:.4f}")
                            except Exception as e:
                                add_log(f"⚠️ Erro ao atualizar TP pós Preço Médio em {sym}: {e}")
                            
                            active_positions[sym]['contracts'] = contracts
                            active_positions[sym]['entry_price'] = entry_p

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

                # Monitora posições fechadas
                closed_symbols = list(set(active_positions.keys()) - current_open_symbols)
                for sym in closed_symbols:
                    new_collateral_usd, _ = get_available_margin_usd(exchange)
                    time.sleep(3) # tempo para Bybit registrar o fechamento
                    details = get_closed_pnl_details(exchange, sym)
                    resultado = details['pnl']
                    exit_price = details['exit_price']
                    
                    resultado_emoji = "🏆 LUCRO" if resultado > 0 else "💀 LOSS"
                    resultado_str = f"{'+$' if resultado >= 0 else '-$'}{abs(resultado):.4f}"
                    
                    add_log(f"🚪 Posição fechada em {sym}! PnL: {resultado_str} {resultado_emoji} | Preço de Saída: ${exit_price:.4f}")
                    log_trade(sym, 'SAÍDA', active_positions[sym]['side'], exit_price, None, None, None, leverage, None, None, new_collateral_usd, resultado_emoji, f"Fechamento: {resultado_str}")
                    
                    # Cancela qualquer outra ordem de compra pendente para esse ativo (ex: se Order 2 não chegou a fillar)
                    try:
                        open_orders = exchange.fetch_open_orders(sym)
                        for o in open_orders:
                            if o['side'] == 'buy':
                                exchange.cancel_order(o['id'], sym)
                                add_log(f"🧹 Posição encerrada em {sym}. Cancelando ordem de preço médio pendente.")
                    except:
                        pass
                        
                    del active_positions[sym]
                    collateral_usd = new_collateral_usd

            except Exception as e:
                add_log(f"⚠️ Erro ao monitorar posições: {e}")

            # --- RASTREAMENTO E RENOVAÇÃO DE ORDENS LIMITE ---
            add_log(f"── Scanner #{scan_count} | Ativas: {len(active_positions)} | Ordens Livro: {len(active_limit_orders)} | Saldo: ${collateral_usd:.2f} ──")
            
            # Limita a apenas 1 operação ativa por vez (apenas uma mão ativa)
            for sym in symbols_to_scan:
                if not bot_state["is_running"]: break
                if sym in active_positions: continue
                
                coin_name = sym.split('/')[0]
                bot_state["coin_name"] = coin_name
                bot_state["status"] = f"📐 Analisando {coin_name}"

                # 1. Verifica se há ordem aberta no livro da Bybit
                try:
                    open_orders = exchange.fetch_open_orders(sym)
                    my_buys = [o for o in open_orders if o['side'] == 'buy' and o['type'] == 'limit']
                except Exception as e:
                    add_log(f"⚠️ Erro ao buscar ordens abertas em {sym}: {e}")
                    continue

                # Se temos ordens limites abertas
                if my_buys:
                    # Se mudou o dia UTC, cancela todas para atualizar níveis
                    date_placed = active_limit_orders.get(sym, {}).get('date_placed', current_utc_day)
                    if date_placed != current_utc_day:
                        add_log(f"📆 Virada de dia UTC detectada para {sym}. Cancelando ordens antigas...")
                        for o in my_buys:
                            try:
                                exchange.cancel_order(o['id'], sym)
                            except:
                                pass
                        if sym in active_limit_orders:
                            del active_limit_orders[sym]
                        add_log(f"✅ Ordens antigas canceladas para {sym}.")
                    else:
                        add_log(f"⏳ {len(my_buys)} ordem(ns) de compra limite ativa(s) em {sym}.")
                        continue

                # 2. Se NÃO temos ordem limite ativa para hoje, calcula níveis e envia duas (Preço Médio)
                if sym not in active_limit_orders:
                    # Busca candles 1D
                    ohlcv_1d = fetch_ohlcv_data(exchange, sym, timeframe='1d', limit=20)
                    if not ohlcv_1d:
                        add_log(f"⚠️ Não foi possível obter dados diários para {sym}.")
                        continue

                    # Index -2 é o dia de ontem completo
                    yesterday_high = ohlcv_1d['h'][-2]
                    yesterday_low = ohlcv_1d['l'][-2]
                    yesterday_close = ohlcv_1d['c'][-2]
                    
                    # Filtro de Trend Diária (EMA 50)
                    ema50_1d = calculate_ema(ohlcv_1d['c'], period=50)
                    if ema50_1d is not None and yesterday_close < ema50_1d:
                        add_log(f"⚠️ {sym} em tendência diária de baixa. Pulando por segurança.")
                        continue
                    
                    atr_1d = calculate_atr(ohlcv_1d, period=14)
                    if atr_1d is None:
                        atr_1d = (yesterday_high - yesterday_low) * 0.5

                    # Níveis calculados
                    # Entrada 1: Mínima de ontem
                    entry_price_1 = yesterday_low * 1.0005
                    # Entrada 2: Preço Médio (1.2% abaixo da mínima de ontem)
                    entry_price_2 = yesterday_low * 0.9880
                    
                    # TPs correspondentes (10% ROI)
                    tp_price_1 = entry_price_1 * (1 + 0.10 / leverage)
                    tp_price_2 = entry_price_2 * (1 + 0.10 / leverage)

                    try:
                        market = exchange.market(sym)
                        entry_price_1 = float(exchange.price_to_precision(sym, entry_price_1))
                        entry_price_2 = float(exchange.price_to_precision(sym, entry_price_2))
                        tp_price_1 = float(exchange.price_to_precision(sym, tp_price_1))
                        tp_price_2 = float(exchange.price_to_precision(sym, tp_price_2))
                    except:
                        pass

                    add_log(f"📈 Níveis calculados para {sym}:")
                    add_log(f"   Mínima Ontem: ${yesterday_low:.4f} | Entrada 1: ${entry_price_1:.4f} | Entrada 2 (Média): ${entry_price_2:.4f}")
                    add_log(f"   🎯 ALVO TP 1: ${tp_price_1:.4f} | ALVO TP 2: ${tp_price_2:.4f} | STOP LOSS: DESATIVADO")

                    try:
                        ticker = exchange.fetch_ticker(sym)
                        current_price = float(ticker['last'])
                    except:
                        current_price = entry_price_1

                    # Margem alocada por ordem: 10% do saldo total
                    margin_allocated = collateral_usd * 0.10
                    if margin_allocated < 1.0:
                        margin_allocated = min(1.0, collateral_usd)
                        
                    trade_size_usd = margin_allocated * leverage
                    amount_1 = trade_size_usd / entry_price_1
                    amount_2 = trade_size_usd / entry_price_2

                    try:
                        min_amount = market['limits']['amount']['min']
                        if amount_1 < min_amount: amount_1 = min_amount
                        if amount_2 < min_amount: amount_2 = min_amount
                        amount_1 = float(exchange.amount_to_precision(sym, amount_1))
                        amount_2 = float(exchange.amount_to_precision(sym, amount_2))
                    except:
                        pass

                    add_log(f"💵 Preço Atual {sym}: ${current_price:.4f} | Margem Alocada: ${margin_allocated:.2f} ({leverage}x)")
                    
                    try:
                        # 1. Envia Ordem Principal
                        params_1 = {'takeProfit': f"{tp_price_1:.4f}".rstrip('0').rstrip('.')}
                        order_1 = exchange.create_order(
                            symbol=sym, type='limit', side='buy',
                            amount=amount_1, price=entry_price_1, params=params_1
                        )
                        order_id_1 = order_1.get('id')
                        add_log(f"✅ Ordem 1 (Principal) enviada para {sym}: Preço ${entry_price_1:.4f} Qtd {amount_1}")
                        
                        # 2. Envia Ordem de Preço Médio (se houver saldo suficiente)
                        order_id_2 = None
                        required_both_margin = (amount_1 * entry_price_1 + amount_2 * entry_price_2) / leverage
                        if required_both_margin <= collateral_usd:
                            params_2 = {'takeProfit': f"{tp_price_2:.4f}".rstrip('0').rstrip('.')}
                            order_2 = exchange.create_order(
                                symbol=sym, type='limit', side='buy',
                                amount=amount_2, price=entry_price_2, params=params_2
                            )
                            order_id_2 = order_2.get('id')
                            add_log(f"✅ Ordem 2 (Preço Médio) enviada para {sym}: Preço ${entry_price_2:.4f} Qtd {amount_2}")
                        else:
                            add_log(f"⚠️ Saldo restringe colocar a Ordem 2 de preço médio em {sym}.")

                        active_limit_orders[sym] = {
                            'order_id_1': order_id_1,
                            'order_id_2': order_id_2,
                            'date_placed': current_utc_day
                        }
                        
                        log_trade(sym, 'LIMITE_ENVIADA', 'LONG', entry_price_1, yesterday_high, yesterday_low, atr_1d, leverage, tp_price_1, None, collateral_usd, '⏳ Pendente')
                        
                    except Exception as oe:
                        add_log(f"❌ Falha ao posicionar ordens limite em {sym}: {oe}")

            time.sleep(check_interval)

    except Exception as e:
        add_log(f"⚠️ Falha grave no loop da estratégia: {e}")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Erro Estratégia"
