import time
import sys
import os
import csv
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_ohlcv_data, calculate_rsi, calculate_ema, calculate_macd
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance, get_available_margin_usd, enable_btc_collateral, place_maker_entry
from core.trailing_stop import TrailingStopEngine

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'rev_martingale_pro.csv')

def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Data/Hora', 'Moeda', 'Tipo', 'Direção', 'Preço',
                'RSI', 'Valor', 'Alavancagem', 'Nível Win', 'TP', 'SL', 'Status', 'Detalhes'
            ])

def log_trade(symbol, tipo, direcao, preco, rsi, valor, leverage, wins, tp, sl, status, detalhes=''):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, tipo, direcao, f'{preco:.4f}',
                f'{rsi:.1f}', f'{valor:.2f}', f'{leverage}x', f'{wins}',
                f'{tp:.4f}', f'{sl:.4f}', status, detalhes
            ])
    except Exception as e:
        add_log(f"Aviso: Não foi possível gravar log CSV: {e}")

def run_reverse_martingale_pro(exchange, symbol='BTC/USDT:USDT'):
    init_trade_log()
    
    is_multi = (symbol == "MULTI")
    symbols_to_scan = ["ETH/USDT:USDT", "BTC/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT"] if is_multi else [symbol]
    
    if not is_multi:
        base_coin = symbol.split('/')[0]
        symbol = f"{base_coin}/USDT:USDT"
        symbols_to_scan = [symbol]
    
    add_log(f"{'='*50}")
    add_log(f"🔥 REVERSE MARTINGALE PRO INICIADO — {'MULTI' if is_multi else symbol}")
    add_log(f"🛡️ Com Trailing Stop & Filtros Institucionais")
    add_log(f"{'='*50}")

    bot_state["is_running"] = True
    bot_state["status"] = "🔥 Analisando (PRO)"

    # Configuração da estratégia
    for sym in symbols_to_scan:
        bc = sym.split('/')[0]
        leverage = 25 if bc == 'BTC' else 30
        try: exchange.set_leverage(leverage, sym)
        except: pass
    
    # Sistema de 5 Níveis (Risco Progressivo)
    risco_niveis = { 0: 0.10, 1: 0.15, 2: 0.25, 3: 0.35, 4: 0.50 }
    wins_consecutivos = 0
    
    enable_btc_collateral(exchange)
    
    available_usd, _ = get_available_margin_usd(exchange)
    starting_balance = available_usd
    add_log(f"💰 Saldo Inicial: ${available_usd:.2f} | Meta: +50%")

    in_position = False
    active_symbol = None
    entry_price = 0.0
    entry_side = None
    scan_count = 0
    rsi_history = {}
    last_trade_time = 0
    
    # Engine do Trailing Stop
    trailing_engine = None

    try:
        while bot_state["is_running"]:
            scan_count += 1
            available_usd, _ = get_available_margin_usd(exchange)
            bot_state["usdt_balance"] = available_usd
            
            # Trava de Segurança Diária
            if available_usd < starting_balance * 0.70:
                add_log(f"🛑 TRAVA DE SEGURANÇA: Saldo caiu 30%. Bot parado para proteção.")
                bot_state["is_running"] = False
                break
                
            # Meta Atingida
            if available_usd >= starting_balance * 1.50:
                add_log(f"🏆 META DO DIA ATINGIDA! Saldo cresceu 50% (${available_usd:.2f}). Descanse e volte amanhã.")
                bot_state["is_running"] = False
                break

            if not in_position:
                time_since_trade = time.time() - last_trade_time
                if time_since_trade < 60:
                    time.sleep(5)
                    continue

                nivel_atual = min(wins_consecutivos, 4)
                risco_pct = risco_niveis[nivel_atual]
                trade_amount = available_usd * risco_pct
                
                if scan_count % 10 == 0:
                    add_log(f"── Nível {nivel_atual+1} | Risco: {risco_pct*100}% (${trade_amount:.2f}) | Wins Seguidos: {wins_consecutivos} ──")

                found_entry = False
                for sym in symbols_to_scan:
                    if not bot_state["is_running"] or found_entry: break
                    
                    base_coin = sym.split('/')[0]
                    current_leverage = 25 if base_coin == 'BTC' else 30
                    
                    ohlcv = fetch_ohlcv_data(exchange, sym, timeframe='1m', limit=210)
                    if not ohlcv: continue
                        
                    closes = ohlcv['c']
                    current_price = closes[-1]
                    rsi = calculate_rsi(closes, period=14)
                    ema200 = calculate_ema(closes, period=200)
                    macd, signal, hist = calculate_macd(closes)
                    
                    if rsi is None or ema200 is None or hist is None: continue
                        
                    bot_state["current_price"] = current_price
                    bot_state["rsi"] = rsi
                    bot_state["coin_name"] = base_coin
                    
                    prev_rsi = rsi_history.get(sym, rsi)
                    rsi_history[sym] = rsi
                    
                    # LOG DO SCANNER (Monitor de Saídas)
                    trend = "ALTA 📈" if current_price > ema200 else "BAIXA 📉"
                    macd_status = "FORÇA ⚡" if abs(hist) > abs(hist*0.1) else "FRACO ☁️"
                    add_log(f"  {base_coin}: ${current_price:,.2f} | RSI: {rsi:.1f} | Tendência: {trend} | MACD: {hist:.2f}")
                    
                    # Logando o scan no CSV para visualização posterior no Histórico (opcional)
                    detalhes_scan = {"ema200": f"{ema200:.2f}", "macd": f"{hist:.4f}", "msg": f"Trend: {trend}"}
                    log_trade(sym, 'SCAN', '-', current_price, rsi, trade_amount, current_leverage, wins_consecutivos, 0, 0, trend, detalhes_scan.get("msg", ""))
                    
                    # GATILHO LONG PRO
                    if current_price > ema200 and rsi <= 30 and rsi > prev_rsi and hist > 0:
                        add_log(f"🔥 SINAL LONG PRO em {base_coin}!")
                        amount_to_buy = (trade_amount * current_leverage) / current_price
                        sl_price = current_price * 0.99
                        
                        order, filled = place_maker_entry(exchange, sym, 'buy', amount_to_buy, current_price, None, sl_price)
                        if filled:
                            in_position, active_symbol, entry_price, entry_side = True, sym, current_price, 'LONG'
                            found_entry = True
                            trailing_engine = TrailingStopEngine(exchange, sym, initial_stop_pct=1.0, mode='stepped')
                            trailing_engine.activate(entry_price, 'LONG', amount_to_buy, sl_price)
                            log_trade(sym, 'ENTRADA', 'LONG', current_price, rsi, trade_amount, current_leverage, wins_consecutivos, 0, sl_price, '✅ SUCESSO')
                            
                    # GATILHO SHORT PRO
                    elif current_price < ema200 and rsi >= 70 and rsi < prev_rsi and hist < 0:
                        add_log(f"🔥 SINAL SHORT PRO em {base_coin}!")
                        amount_to_sell = (trade_amount * current_leverage) / current_price
                        sl_price = current_price * 1.01
                        
                        order, filled = place_maker_entry(exchange, sym, 'sell', amount_to_sell, current_price, None, sl_price)
                        if filled:
                            in_position, active_symbol, entry_price, entry_side = True, sym, current_price, 'SHORT'
                            found_entry = True
                            trailing_engine = TrailingStopEngine(exchange, sym, initial_stop_pct=1.0, mode='stepped')
                            trailing_engine.activate(entry_price, 'SHORT', amount_to_sell, sl_price)
                            log_trade(sym, 'ENTRADA', 'SHORT', current_price, rsi, trade_amount, current_leverage, wins_consecutivos, 0, sl_price, '✅ SUCESSO')
                
                time.sleep(1)
                
            elif in_position and active_symbol:
                try:
                    coin_name = active_symbol.split('/')[0]
                    bot_state["coin_name"] = coin_name
                    closes = fetch_ohlcv_data(exchange, active_symbol, timeframe='1m', limit=10)
                    if closes and closes['c']:
                        current_price = closes['c'][-1]
                        bot_state["current_price"] = current_price
                        
                        # Calculando PnL
                        active_leverage = 25 if active_symbol.startswith('BTC') else 30
                        if entry_side == 'LONG':
                            pnl_pct = ((current_price - entry_price) / entry_price) * 100 * active_leverage
                            distancia_stop = ((current_price - trailing_engine.current_stop_price) / current_price) * 100
                        else:
                            pnl_pct = ((entry_price - current_price) / entry_price) * 100 * active_leverage
                            distancia_stop = ((trailing_engine.current_stop_price - current_price) / current_price) * 100
                        
                        pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
                        nivel_atual = min(wins_consecutivos, 4) + 1
                        
                        add_log(f"📊 [RM PRO Nível {nivel_atual}] {coin_name} {entry_side} ({active_leverage}x)")
                        add_log(f"  🎯 Preço: {entry_price:,.2f} → {current_price:,.2f} | P&L: {pnl_emoji} {pnl_pct:+.2f}%")
                        add_log(f"  🛡️ Trailing Stop: ${trailing_engine.current_stop_price:,.4f} (Distância: {distancia_stop:.2f}%)")
                        
                        # Buscar informações da posição (PnL em USD e Tamanho)
                        positions = exchange.fetch_positions([active_symbol])
                        for pos in positions:
                            contracts = float(pos.get('contracts', 0))
                            if contracts > 0:
                                unrealized_pnl = float(pos.get('unrealizedPnl', 0))
                                add_log(f"  💰 Tamanho: {contracts} contratos | PnL Unrealized: ${unrealized_pnl:+.4f} USD")
                                break
                        
                        # Atualiza o Trailing Stop localmente
                        new_stop, adjusted = trailing_engine.update_price(current_price)
                        if adjusted:
                            add_log(f"  ⚙️ Trailing Stop movido para ${new_stop:,.4f} acompanhando preço!")
                        
                        # Verifica Stop Loss
                        if trailing_engine.should_execute_stop(current_price):
                            add_log(f"🛑 Trailing Stop Acionado em ${current_price:.4f}! Fechando ordem...")
                            # Executa fechamento a mercado via API
                            side_to_close = 'sell' if entry_side == 'LONG' else 'buy'
                            try:
                                exchange.create_order(active_symbol, 'market', side_to_close, trailing_engine.position_size, params={'reduceOnly': True, 'category': 'linear'})
                            except Exception as e:
                                add_log(f"Erro ao fechar posição: {e}")
                                
                            # Verifica lucro/prejuízo
                            active_leverage = 25 if active_symbol.startswith('BTC') else 30
                            pnl_pct = ((current_price - entry_price)/entry_price)*100 if entry_side == 'LONG' else ((entry_price - current_price)/entry_price)*100
                            pnl_pct *= active_leverage
                            
                            if pnl_pct > 0:
                                add_log(f"✅ WIN! Trailing stop garantiu lucro de {pnl_pct:.2f}%")
                                wins_consecutivos += 1
                            else:
                                add_log(f"❌ LOSS! Stop loss limitou a perda em {pnl_pct:.2f}%")
                                wins_consecutivos = 0 # Reset Pro
                                
                            in_position = False
                            active_symbol = None
                            trailing_engine.deactivate()
                            last_trade_time = time.time()
                            
                    # Verifica se posição sumiu (Take Profit atingido na Exchange)
                    positions = exchange.fetch_positions([active_symbol]) if active_symbol else []
                    has_position = False
                    for pos in positions:
                        if float(pos.get('contracts', 0)) > 0:
                            has_position = True
                            break
                            
                    if not has_position and in_position:
                        add_log(f"🏆 Posição fechada na exchange! WIN computado.")
                        wins_consecutivos += 1
                        in_position = False
                        active_symbol = None
                        trailing_engine.deactivate()
                        last_trade_time = time.time()
                        
                except Exception as e:
                    pass
                    
            for _ in range(2):
                if not bot_state["is_running"]: break
                time.sleep(1)

    except Exception as e:
        add_log(f"💥 Erro Crítico RevMart PRO: {e}")
    finally:
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
