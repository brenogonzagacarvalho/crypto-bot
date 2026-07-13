import time
import sys
import os
import csv
from datetime import datetime
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_ohlcv_data, calculate_atr
from core.shared_state import bot_state, add_log
from core.balance_utils import get_available_margin_usd, enable_btc_collateral, get_closed_pnl

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
    symbols_to_scan = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "ADA/USDT:USDT", "DOGE/USDT:USDT"] if is_multi else [symbol]

    add_log(f"{'='*55}")
    add_log(f"📐 ESTRATÉGIA MÍNIMA/MÁXIMA DIÁRIA (YHL) — {'MULTI-SCAN' if is_multi else symbol}")
    add_log(f"📊 Compras limite na mínima do dia anterior | Alavancagem: {leverage}x")
    add_log(f"{'='*55}")

    bot_state["is_running"] = True
    bot_state["status"]     = f"📐 Mín/Máx Diária ({leverage}x)"
    bot_state["coin_name"]  = "SCANNING" if is_multi else symbol.split('/')[0]

    enable_btc_collateral(exchange)

    # Configura alavancagem para as moedas
    for sym in symbols_to_scan:
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
                            active_positions[sym] = {'side': side, 'entry_price': entry_p}
                            # Se havia uma ordem limite rastreada, remove do dicionário de ordens
                            if sym in active_limit_orders:
                                del active_limit_orders[sym]
                            
                            add_log(f"🔔 Ordem Limite preenchida em {sym}! Posição de {side} aberta.")
                            log_trade(sym, 'ENTRADA', side, entry_p, None, None, None, leverage, None, None, collateral_usd, '✅ Posição Aberta')

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
                    resultado = get_closed_pnl(exchange, sym, limit=1)
                    resultado_emoji = "🏆 LUCRO" if resultado > 0 else "💀 LOSS"
                    resultado_str = f"{'+$' if resultado >= 0 else '-$'}{abs(resultado):.4f}"
                    
                    add_log(f"🚪 Posição fechada em {sym}! PnL: {resultado_str} {resultado_emoji}")
                    log_trade(sym, 'SAÍDA', active_positions[sym]['side'], None, None, None, None, leverage, None, None, new_collateral_usd, resultado_emoji, f"Fechamento: {resultado_str}")
                    del active_positions[sym]
                    collateral_usd = new_collateral_usd

            except Exception as e:
                add_log(f"⚠️ Erro ao monitorar posições: {e}")

            # --- RASTREAMENTO E RENOVAÇÃO DE ORDENS LIMITE ---
            add_log(f"── Scanner #{scan_count} | Ativas: {len(active_positions)} | Ordens Livro: {len(active_limit_orders)} | Saldo: ${collateral_usd:.2f} ──")
            
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

                # Se temos ordem limite aberta
                if my_buys:
                    order_info = my_buys[0]
                    order_id = order_info['id']
                    
                    # Registra no cache local se não estiver
                    if sym not in active_limit_orders:
                        active_limit_orders[sym] = {
                            'order_id': order_id,
                            'date_placed': current_utc_day
                        }
                    
                    # Verifica se mudou o dia UTC para rolar a ordem
                    if active_limit_orders[sym]['date_placed'] != current_utc_day:
                        add_log(f"📆 Virada de dia UTC detectada para {sym}. Cancelando ordem antiga para atualizar níveis...")
                        try:
                            exchange.cancel_order(order_id, sym)
                            del active_limit_orders[sym]
                            add_log(f"✅ Ordem antiga {order_id} cancelada.")
                        except Exception as ce:
                            add_log(f"⚠️ Erro ao cancelar ordem antiga: {ce}")
                            del active_limit_orders[sym]
                    else:
                        # Ordem continua válida para o dia de hoje. Apenas exibe log informativo.
                        add_log(f"⏳ Ordem de compra limite ativa em {sym} no preço ${order_info['price']:.4f}")
                        continue

                # 2. Se NÃO temos ordem limite aberta para hoje, calcula níveis e envia uma
                if sym not in active_limit_orders:
                    # Busca candles 1D
                    ohlcv_1d = fetch_ohlcv_data(exchange, sym, timeframe='1d', limit=20)
                    if not ohlcv_1d:
                        add_log(f"⚠️ Não foi possível obter dados diários para {sym}.")
                        continue

                    # Index -2 é o dia de ontem completo
                    yesterday_high = ohlcv_1d['h'][-2]
                    yesterday_low = ohlcv_1d['l'][-2]
                    
                    atr_1d = calculate_atr(ohlcv_1d, period=14)
                    if atr_1d is None:
                        atr_1d = (yesterday_high - yesterday_low) * 0.5  # backup simples caso ATR falhe

                    # Preços calculados
                    entry_price = yesterday_low * 1.0005  # margem de 0.05% acima para garantir toque
                    tp_price = yesterday_high * 0.9995    # margem de 0.05% abaixo para garantir execução
                    
                    # Garante alvo de lucro mínimo de 10% ROI na margem (10% / alavancagem em % de preço)
                    min_tp_price = entry_price * (1 + 0.10 / leverage)
                    if tp_price < min_tp_price:
                        tp_price = min_tp_price

                    sl_price = entry_price - (1.5 * atr_1d)

                    # Formata precisões
                    try:
                        market = exchange.market(sym)
                        entry_price = float(exchange.price_to_precision(sym, entry_price))
                        tp_price = float(exchange.price_to_precision(sym, tp_price))
                        sl_price = float(exchange.price_to_precision(sym, sl_price))
                    except:
                        pass

                    add_log(f"📈 Níveis calculados para {sym}:")
                    add_log(f"   Mínima Ontem (Low): ${yesterday_low:.4f} | Máxima Ontem (High): ${yesterday_high:.4f}")
                    add_log(f"   🎯 COMPRA LIMITE: ${entry_price:.4f} | ALVO TP (Mín 10% ROI): ${tp_price:.4f} | STOP LOSS: DESATIVADO")

                    # Verifica ticker atual
                    try:
                        ticker = exchange.fetch_ticker(sym)
                        current_price = float(ticker['last'])
                    except:
                        current_price = entry_price

                    # Calcula quantidade da ordem (10% do saldo total da conta * alavancagem)
                    margin_allocated = collateral_usd * 0.10
                    # Proteção básica de saldo
                    if margin_allocated < 2.0:
                        margin_allocated = min(2.0, collateral_usd)
                        
                    trade_size_usd = margin_allocated * leverage
                    amount = trade_size_usd / entry_price

                    try:
                        min_amount = market['limits']['amount']['min']
                        if amount < min_amount:
                            amount = min_amount
                        amount = float(exchange.amount_to_precision(sym, amount))
                    except:
                        pass

                    # Verifica se o preço atual está acima ou próximo para posicionar a ordem limite
                    add_log(f"💵 Preço Atual {sym}: ${current_price:.4f} | Alocando Margem: ${margin_allocated:.2f} ({leverage}x)")
                    
                    try:
                        params = {
                            'takeProfit': f"{tp_price:.4f}".rstrip('0').rstrip('.'),
                            # 'stopLoss' removido conforme solicitado para evitar saídas em prejuízo (no-loss mode)
                        }
                        
                        # Garante que as quantidades mínimas sejam atendidas financeiramente
                        val_financeiro = amount * entry_price
                        required_margin = val_financeiro / leverage
                        
                        if required_margin > collateral_usd:
                            add_log(f"⚠️ Saldo insuficiente para margem exigida (${required_margin:.2f} > ${collateral_usd:.2f}). Ordem abortada.")
                            continue

                        print(f"Enviando ordem limite de COMPRA em {sym}: Preço ${entry_price:.4f} Qtd {amount}")
                        order = exchange.create_order(
                            symbol=sym,
                            type='limit',
                            side='buy',
                            amount=amount,
                            price=entry_price,
                            params=params
                        )
                        
                        order_id = order.get('id')
                        active_limit_orders[sym] = {
                            'order_id': order_id,
                            'date_placed': current_utc_day
                        }
                        
                        add_log(f"✅ Ordem limite de compra posicionada em {sym}! ID: {order_id}")
                        log_trade(sym, 'LIMITE_ENVIADA', 'LONG', entry_price, yesterday_high, yesterday_low, atr_1d, leverage, tp_price, sl_price, collateral_usd, '⏳ Pendente')
                        
                    except Exception as oe:
                        add_log(f"❌ Falha ao posicionar ordem limite em {sym}: {oe}")

            time.sleep(check_interval)

    except Exception as e:
        add_log(f"⚠️ Falha grave no loop da estratégia: {e}")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Erro Estratégia"
