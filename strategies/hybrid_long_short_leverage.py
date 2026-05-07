"""
ESTRATÉGIA LONG/SHORT COM ALAVANCAGEM (FUTUROS PERPÉTUOS)
Arquivo: strategies/hybrid_long_short_leverage.py

Trabalha com USDT perpetual na Bybit (linear).
Mantém hedge inteligente entre posições long e short.
Alavancagem configurável (recomendado 2x–5x para segurança).
"""

import time
import sys
import os
import csv
from datetime import datetime
from enum import Enum
import pandas as pd
import numpy as np
import ccxt

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_historical_data, calculate_rsi
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance

# -------------------------------------------------------------------
# CONFIGURAÇÕES AJUSTÁVEIS PELO USUÁRIO
# -------------------------------------------------------------------
LEVERAGE = 3                 # Alavancagem alvo (1-10)
MAX_POSITION_PCT = 0.8       # % do capital total em margem (80%)
RISK_PER_TRADE_PCT = 0.02    # Risco de 2% do capital por operação
MIN_SCORE_TO_TRADE = 35      # Score mínimo do regime para agir
COOLDOWN_SCANS = 2           # Espera entre ajustes de posição
# -------------------------------------------------------------------

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'leveraged_long_short.csv')

class MarketRegime(Enum):
    STRONG_BULL = "STRONG_BULL"
    WEAK_BULL = "WEAK_BULL"
    RANGING = "RANGING"
    WEAK_BEAR = "WEAK_BEAR"
    STRONG_BEAR = "STRONG_BEAR"
    CHOPPY = "CHOPPY"

def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Timestamp', 'Symbol', 'Regime', 'Action',
                'Side', 'Size_USDT', 'Leverage', 'Entry_Price',
                'Exit_Price', 'PnL', 'Long_Exp', 'Short_Exp',
                'Equity', 'Reason'
            ])

def log_trade(symbol, regime, action, side, size_usdt, lev, entry, exit_p, pnl,
              long_exp, short_exp, equity, reason):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, regime, action, side,
                f'{size_usdt:.2f}', f'{lev}x',
                f'{entry:.2f}', f'{exit_p:.2f}', f'{pnl:.4f}',
                f'{long_exp:.2f}', f'{short_exp:.2f}',
                f'{equity:.2f}', reason
            ])
    except Exception as e:
        add_log(f"Log error: {e}")

# -------------------------------------------------------------------
# INDICADORES (mesma lógica do spot, mas com alguns ajustes)
# -------------------------------------------------------------------
def calculate_all_indicators(closes_5m, closes_15m, closes_1h, highs, lows, volumes):
    if len(closes_5m) < 50:
        return None

    current_price = closes_5m[-1]

    rsi_5m = calculate_rsi(closes_5m, 14)
    rsi_15m = calculate_rsi(closes_15m, 14) if len(closes_15m) >= 14 else rsi_5m
    rsi_1h = calculate_rsi(closes_1h, 14) if len(closes_1h) >= 14 else rsi_5m

    closes_series = pd.Series(closes_5m)
    ema_9 = closes_series.ewm(span=9, adjust=False).mean().iloc[-1]
    ema_21 = closes_series.ewm(span=21, adjust=False).mean().iloc[-1]
    ema_55 = closes_series.ewm(span=55, adjust=False).mean().iloc[-1]

    ema_12 = closes_series.ewm(span=12, adjust=False).mean()
    ema_26 = closes_series.ewm(span=26, adjust=False).mean()
    macd_line = ema_12 - ema_26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_histogram = macd_line.iloc[-1] - signal_line.iloc[-1]

    atr = calculate_atr(highs, lows, closes_5m, 14)
    volatility_pct = (atr / current_price * 100) if atr and current_price > 0 else 0
    bb_width = calculate_bb_width(closes_5m)
    vol_ratio = calculate_volume_ratio(volumes)
    adx = calculate_simple_adx(highs, lows, closes_5m, 14)

    return {
        'current_price': current_price,
        'rsi_5m': rsi_5m,
        'rsi_15m': rsi_15m,
        'rsi_1h': rsi_1h,
        'ema_9': ema_9,
        'ema_21': ema_21,
        'ema_55': ema_55,
        'macd_histogram': macd_histogram,
        'volatility_pct': volatility_pct,
        'bb_width': bb_width,
        'vol_ratio': vol_ratio,
        'adx': adx
    }

def calculate_atr(highs, lows, closes, period=14):
    if len(closes) < period:
        return 0
    tr_list = []
    for i in range(1, min(len(highs), len(lows), len(closes))):
        h, l, c_prev = highs[i], lows[i], closes[i-1]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        tr_list.append(tr)
    return pd.Series(tr_list).rolling(period).mean().iloc[-1] if tr_list else 0

def calculate_bb_width(closes, period=20):
    if len(closes) < period:
        return 0
    s = pd.Series(closes)
    sma = s.rolling(period).mean()
    std = s.rolling(period).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    return ((upper - lower) / sma).iloc[-1] * 100

def calculate_volume_ratio(volumes, short_period=5, long_period=20):
    if len(volumes) < long_period:
        return 1.0
    vol_series = pd.Series(volumes)
    short_avg = vol_series.rolling(short_period).mean().iloc[-1]
    long_avg = vol_series.rolling(long_period).mean().iloc[-1]
    return short_avg / long_avg if long_avg > 0 else 1.0

def calculate_simple_adx(highs, lows, closes, period=14):
    if len(closes) < period * 2:
        return 25
    tr_list, plus_dm, minus_dm = [], [], []
    for i in range(1, len(closes)):
        h, l, c = highs[i], lows[i], closes[i]
        h_prev, l_prev, c_prev = highs[i-1], lows[i-1], closes[i-1]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        tr_list.append(tr)
        up_move = h - h_prev
        down_move = l_prev - l
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0)
    tr_smooth = pd.Series(tr_list).ewm(alpha=1/period, adjust=False).mean().iloc[-1]
    plus_dm_smooth = pd.Series(plus_dm).ewm(alpha=1/period, adjust=False).mean().iloc[-1]
    minus_dm_smooth = pd.Series(minus_dm).ewm(alpha=1/period, adjust=False).mean().iloc[-1]
    plus_di = (plus_dm_smooth / tr_smooth * 100) if tr_smooth > 0 else 0
    minus_di = (minus_dm_smooth / tr_smooth * 100) if tr_smooth > 0 else 0
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
    return dx

# -------------------------------------------------------------------
# DETECÇÃO DE REGIME (idêntica à versão spot)
# -------------------------------------------------------------------
def detect_market_regime(indicators):
    if not indicators:
        return MarketRegime.CHOPPY, {}

    rsi_5m = indicators['rsi_5m'] or 50
    rsi_1h = indicators['rsi_1h'] or 50
    ema_9 = indicators['ema_9']
    ema_21 = indicators['ema_21']
    ema_55 = indicators['ema_55']
    price = indicators['current_price']
    volatility = indicators['volatility_pct']
    adx = indicators['adx']
    macd_histogram = indicators['macd_histogram']

    reasons = []
    bull_score, bear_score = 0, 0

    if price > ema_9 > ema_21 > ema_55:
        bull_score += 30
        reasons.append("EMAs alinhadas alta")
    elif price < ema_9 < ema_21 < ema_55:
        bear_score += 30
        reasons.append("EMAs alinhadas baixa")
    elif price > ema_21:
        bull_score += 10
        reasons.append("Preço acima EMA21")
    else:
        bear_score += 10
        reasons.append("Preço abaixo EMA21")

    rsi_avg = (rsi_5m + rsi_1h) / 2
    if rsi_avg > 60:
        bull_score += 20
        reasons.append(f"RSI comprador ({rsi_avg:.0f})")
    elif rsi_avg < 40:
        bear_score += 20
        reasons.append(f"RSI vendedor ({rsi_avg:.0f})")

    if rsi_5m > 75:
        bear_score += 15
        reasons.append("RSI sobrecomprado (possível reversão)")
    elif rsi_5m < 25:
        bull_score += 15
        reasons.append("RSI sobrevendido (possível reversão)")

    if macd_histogram > 0:
        bull_score += 15
        reasons.append("MACD bullish")
    else:
        bear_score += 15
        reasons.append("MACD bearish")

    reasons.append(f"ADX: {adx:.0f}")
    reasons.append(f"Vol: {volatility:.1f}%")

    diff = bull_score - bear_score
    if volatility > 5 or adx < 10:
        regime = MarketRegime.CHOPPY
    elif diff > 40:
        regime = MarketRegime.STRONG_BULL
    elif diff > 15:
        regime = MarketRegime.WEAK_BULL
    elif diff > -15:
        regime = MarketRegime.RANGING
    elif diff > -40:
        regime = MarketRegime.WEAK_BEAR
    else:
        regime = MarketRegime.STRONG_BEAR

    return regime, {'bull_score': bull_score, 'bear_score': bear_score, 'reasons': reasons}

# -------------------------------------------------------------------
# GESTÃO DE POSIÇÕES COM ALAVANCAGEM
# -------------------------------------------------------------------
def calculate_futures_position_sizes(regime, total_equity, current_price, leverage):
    """Retorna (long_size_usdt, short_size_usdt, long_contracts, short_contracts)."""
    alloc = {
        MarketRegime.STRONG_BULL: (0.50, 0.20),
        MarketRegime.WEAK_BULL:   (0.35, 0.25),
        MarketRegime.RANGING:     (0.30, 0.30),
        MarketRegime.WEAK_BEAR:   (0.25, 0.35),
        MarketRegime.STRONG_BEAR: (0.20, 0.50),
        MarketRegime.CHOPPY:      (0.10, 0.10),
    }
    long_alloc, short_alloc = alloc.get(regime, (0.10, 0.10))
    # A alavancagem reduz o capital necessário para abrir a posição.
    # Ex.: para ter exposição de $100 com 5x, precisa de $20 de margem.
    long_notional = total_equity * long_alloc
    short_notional = total_equity * short_alloc

    # Número de contratos (USDT perpetual usa contratos lineares de 1 USD)
    long_contracts = long_notional / current_price
    short_contracts = short_notional / current_price

    return long_notional, short_notional, long_contracts, short_contracts

def set_leverage(exchange, symbol, leverage):
    """Ajusta alavancagem para o par e define modo cross para usar multi-colateral no UTA."""
    try:
        if not getattr(exchange, 'markets', None):
            exchange.load_markets()
        market = exchange.market(symbol)
        
        # Primeiro garantir que está em marginMode cross
        try:
            exchange.set_margin_mode('cross', symbol)
        except Exception as e:
            if "not modified" not in str(e).lower() and "110026" not in str(e):
                add_log(f"Aviso margin mode: {e}")
                
        # Depois setar a alavancagem
        exchange.set_leverage(leverage, symbol)
        add_log(f"Alavancagem definida: {leverage}x CROSS para {symbol}")
        return True
    except Exception as e:
        if "leverage not modified" in str(e).lower() or "110043" in str(e):
            add_log(f"Alavancagem já está configurada em {leverage}x CROSS para {symbol}")
            return True
        add_log(f"Erro ao definir alavancagem: {e}")
        return False

def get_positions(exchange, symbol):
    """Retorna dicionário com posições atuais (long e short)."""
    try:
        positions = exchange.fetch_positions([symbol])
        long_pos = next((p for p in positions if p['side'] == 'long'), None)
        short_pos = next((p for p in positions if p['side'] == 'short'), None)
        return long_pos, short_pos
    except Exception as e:
        add_log(f"Erro ao buscar posições: {e}")
        return None, None

def close_position(exchange, symbol, side, amount=None):
    """Fecha posição (usa reduce_only)."""
    try:
        if side == 'long':
            exchange.create_market_sell_order(symbol, amount, {'reduceOnly': True})
        else:
            exchange.create_market_buy_order(symbol, amount, {'reduceOnly': True})
        add_log(f"Posição {side} fechada (qtd: {amount})")
        return True
    except Exception as e:
        add_log(f"Erro ao fechar {side}: {e}")
        return False

def adjust_futures_positions(exchange, symbol, current_price,
                             target_long_notional, target_short_notional,
                             current_long_notional, current_short_notional,
                             long_qty, short_qty, total_equity):
    """Ajusta posições long/short para os targets, respeitando a alavancagem."""
    min_trade = max(0.5, total_equity * 0.01)
    
    if not getattr(exchange, 'markets', None) or symbol not in exchange.markets:
        exchange.load_markets()
    
    market = exchange.market(symbol)
    
    # Ajusta Long
    diff_long = target_long_notional - current_long_notional
    if abs(diff_long) > min_trade:
        if diff_long > 0:
            # Comprar mais contratos long
            buy_qty = diff_long / current_price
            try:
                final_qty = float(exchange.amount_to_precision(symbol, buy_qty))
            except Exception:
                final_qty = 0.0
            
            if final_qty > 0:
                add_log(f"Aumentando LONG em ${diff_long:.2f} ({final_qty} contratos)")
                try:
                    exchange.create_market_buy_order(symbol, final_qty)
                except Exception as e:
                    add_log(f"Erro compra long: {e}")
            else:
                add_log(f"Tamanho LONG ({buy_qty:.4f}) menor que a precisão mínima do par. Ignorando aumento.")
        else:
            # Reduzir long
            sell_qty = min(abs(diff_long) / current_price, long_qty * 0.99)
            try:
                final_qty = float(exchange.amount_to_precision(symbol, sell_qty))
            except Exception:
                final_qty = 0.0
            
            if final_qty > 0:
                add_log(f"Reduzindo LONG em ${abs(diff_long):.2f} ({final_qty} contratos)")
                close_position(exchange, symbol, 'long', final_qty)

    # Ajusta Short
    diff_short = target_short_notional - current_short_notional
    if abs(diff_short) > min_trade:
        if diff_short > 0:
            # Aumentar short (vender)
            sell_qty = diff_short / current_price
            try:
                final_qty = float(exchange.amount_to_precision(symbol, sell_qty))
            except Exception:
                final_qty = 0.0
            
            if final_qty > 0:
                add_log(f"Aumentando SHORT em ${diff_short:.2f} ({final_qty} contratos)")
                try:
                    exchange.create_market_sell_order(symbol, final_qty)
                except Exception as e:
                    add_log(f"Erro venda short: {e}")
            else:
                add_log(f"Tamanho SHORT ({sell_qty:.4f}) menor que a precisão mínima do par. Ignorando aumento.")
        else:
            # Reduzir short (comprar)
            buy_qty = min(abs(diff_short) / current_price, short_qty * 0.99)
            try:
                final_qty = float(exchange.amount_to_precision(symbol, buy_qty))
            except Exception:
                final_qty = 0.0
            
            if final_qty > 0:
                add_log(f"Reduzindo SHORT em ${abs(diff_short):.2f} ({final_qty} contratos)")
                close_position(exchange, symbol, 'short', final_qty)

# -------------------------------------------------------------------
# LOOP PRINCIPAL
# -------------------------------------------------------------------
def run_leveraged_long_short(exchange, symbol='BTC/USDT:USDT', leverage=None):
    """
    Estratégia Long/Short com alavancagem em futuros perpétuos.
    symbol ex: 'BTC/USDT:USDT' (linear perpetual)
    """
    if leverage is None:
        leverage = LEVERAGE
    init_trade_log()

    add_log("="*70)
    add_log(f"🚀 LONG/SHORT ALAVANCADO ({leverage}x) INICIADO")
    add_log(f"   Par: {symbol} | Risco: {RISK_PER_TRADE_PCT*100}% por trade")
    add_log("="*70)

    # Configura alavancagem
    if not set_leverage(exchange, symbol, leverage):
        add_log("Não foi possível definir alavancagem. Abortando.")
        return

    bot_state["is_running"] = True
    bot_state["status"] = f"🟢 Long/Short {leverage}x"

    base_coin = symbol.split('/')[0]
    bot_state["coin_name"] = base_coin

    # Estado
    last_regime = None
    regime_stable_count = 0
    trades_this_regime = 0
    last_adjustment_scan = 0
    scan_count = 0

    # Para cálculo de equity e metas diárias
    usdt_balance = get_unified_balance(exchange, 'USDT')
    initial_equity = usdt_balance if usdt_balance > 0 else 1.0
    current_equity = usdt_balance
    
    add_log(f"💰 Equity Inicial: ${initial_equity:.2f} | Meta +20%: ${initial_equity*1.2:.2f} | Stop -20%: ${initial_equity*0.8:.2f}")

    try:
        while bot_state["is_running"]:
            scan_count += 1
            
            # Filtro de Liquidez (00h às 06h UTC)
            utc_hour = datetime.utcnow().hour
            if 0 <= utc_hour < 6:
                bot_state["status"] = "⏳ Pausado (Baixa Liquidez UTC)"
                add_log(f"[{datetime.utcnow().strftime('%H:%M')} UTC] Horário de baixa liquidez. Bot pausado.")
                time.sleep(60)
                continue
            else:
                bot_state["status"] = f"🟢 Long/Short {leverage}x"

            # Atualiza saldo USDT (equity)
            try:
                usdt_balance = get_unified_balance(exchange, 'USDT')
            except:
                pass

            # Obtém dados OHLCV
            ohlcv_5m = exchange.fetch_ohlcv(symbol, '5m', limit=100)
            ohlcv_15m = exchange.fetch_ohlcv(symbol, '15m', limit=100)
            ohlcv_1h = exchange.fetch_ohlcv(symbol, '1h', limit=100)

            closes_5m = [c[4] for c in ohlcv_5m]
            closes_15m = [c[4] for c in ohlcv_15m]
            closes_1h = [c[4] for c in ohlcv_1h]
            highs = [c[2] for c in ohlcv_5m]
            lows = [c[3] for c in ohlcv_5m]
            volumes = [c[5] for c in ohlcv_5m]

            indicators = calculate_all_indicators(closes_5m, closes_15m, closes_1h,
                                                  highs, lows, volumes)
            if not indicators:
                time.sleep(30)
                continue

            current_price = indicators['current_price']
            regime, regime_info = detect_market_regime(indicators)

            # Estabilidade do regime
            if regime == last_regime:
                regime_stable_count += 1
            else:
                regime_stable_count = 1
                trades_this_regime = 0
                add_log(f"🔄 Regime alterado: {last_regime} → {regime}")
                last_regime = regime

            # Posições atuais
            long_pos, short_pos = get_positions(exchange, symbol)
            
            # Verifica Stop Fixo por PnL (-10% da posição)
            panic_close = False
            for pos in [long_pos, short_pos]:
                if pos and pos['contracts'] > 0:
                    # 'percentage' no ccxt costuma ser o PnL% ROE (ex: -10 para -10%)
                    roe = pos.get('percentage', 0)
                    if roe is None: # Tenta estimar se percentage não existir
                        unrealized = pos.get('unrealizedPnl', 0)
                        margin = pos.get('initialMargin', 0)
                        if margin and margin > 0:
                            roe = (unrealized / margin) * 100
                        else:
                            roe = 0
                            
                    if roe <= -10.0:
                        add_log(f"🚨 PANIC STOP! Posição {pos['side']} atingiu {roe:.2f}% de ROE.")
                        panic_close = True
            
            if panic_close:
                add_log("Fechando TODAS as posições e desligando o bot por segurança.")
                if long_pos and long_pos['contracts'] > 0:
                    close_position(exchange, symbol, 'long', long_pos['contracts'])
                if short_pos and short_pos['contracts'] > 0:
                    close_position(exchange, symbol, 'short', short_pos['contracts'])
                bot_state["is_running"] = False
                continue

            long_contracts = long_pos['contracts'] if long_pos else 0
            short_contracts = short_pos['contracts'] if short_pos else 0
            long_notional = long_contracts * current_price
            short_notional = short_contracts * current_price
            # Equity = USDT livre + PnL não realizado (aproximado)
            total_equity = usdt_balance
            
            # Verifica Metas Diárias
            if total_equity >= initial_equity * 1.20:
                add_log(f"🏆 META DIÁRIA ATINGIDA! Equity cresceu 20% (${total_equity:.2f}). Encerrando operações.")
                bot_state["is_running"] = False
                continue
            if total_equity <= initial_equity * 0.80:
                add_log(f"🛑 STOP DIÁRIO ATINGIDO! Equity caiu 20% (${total_equity:.2f}). Encerrando operações para proteger capital.")
                bot_state["is_running"] = False
                continue

            bot_state["current_price"] = current_price
            bot_state["usdt_balance"] = total_equity
            bot_state["market_regime"] = regime.value
            bot_state["rsi"] = indicators['rsi_5m'] or 50
            bot_state["rsi_status"] = f"{regime.value} | L:{long_notional:.1f} S:{short_notional:.1f}"

            # Log
            add_log(f"#{scan_count} {regime.value} | Preço: {current_price:.2f} | "
                   f"Long: ${long_notional:.2f} | Short: ${short_notional:.2f} | "
                   f"Equity: ${total_equity:.2f} | ADX: {indicators['adx']:.0f}")

            # Cálculo dos targets
            target_long, target_short, target_long_qty, target_short_qty = calculate_futures_position_sizes(
                regime, total_equity, current_price, leverage
            )

            # Verifica se precisa ajustar (após cooldown)
            can_adjust = (scan_count - last_adjustment_scan) >= COOLDOWN_SCANS
            if can_adjust:
                min_trade_value = max(0.5, total_equity * 0.02)
                need_adjust = (abs(target_long - long_notional) > min_trade_value or
                               abs(target_short - short_notional) > min_trade_value)
                if need_adjust and trades_this_regime < 5:
                    add_log(f"⚡ Ajustando posições para {regime.value}")
                    adjust_futures_positions(
                        exchange, symbol, current_price,
                        target_long, target_short,
                        long_notional, short_notional,
                        long_contracts, short_contracts, total_equity
                    )
                    trades_this_regime += 1
                    last_adjustment_scan = scan_count

                    # Log trade
                    log_trade(symbol, regime.value, 'REBALANCE', 'BOTH',
                              (target_long+target_short), leverage,
                              current_price, 0, 0,
                              target_long, target_short, total_equity,
                              '; '.join(regime_info['reasons']))

            # Sleep com interrupção estendido para 60s
            for _ in range(60):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)

    except KeyboardInterrupt:
        add_log("Interrompido pelo usuário.")
    except ccxt.RateLimitExceeded as e:
        add_log("Rate limit excedido, aguardando 60s...")
        time.sleep(60)
    except Exception as e:
        add_log(f"💥 ERRO: {e}")
        if "Too many visits" in str(e) or "10006" in str(e):
            add_log("Excesso de visitas API (HTTP 10006). Pausando 60s...")
            time.sleep(60)
    finally:
        # Fecha todas as posições ao desligar? (opcional)
        add_log("Encerrando bot... posições mantidas (gerencie manualmente).")
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("Bot Long/Short Alavancado Finalizado.")

# Para teste standalone
if __name__ == "__main__":
    from core.connection import get_exchange
    exchange = get_exchange()
    run_leveraged_long_short(exchange, 'BTC/USDT:USDT')
