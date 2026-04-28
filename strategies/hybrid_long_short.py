"""
ESTRATÉGIA LONG/SHORT HÍBRIDA COM HEDGE
Arquivo: strategies/hybrid_long_short.py

Sistema que alterna entre:
1. MODO TREND: Segue tendência principal (Long em alta, Short em queda)
2. MODO RANGE: Opera os dois lados em mercado lateral
3. HEDGE PROTETOR: Sempre mantém posição contrária mínima
"""

import time
import sys
import os
import csv
from datetime import datetime
from enum import Enum
import pandas as pd
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_historical_data, calculate_rsi
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance

# --- CONFIGURAÇÕES DE LOG ---
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'long_short_trades.csv')

class MarketRegime(Enum):
    STRONG_BULL = "STRONG_BULL"      # Long apenas
    WEAK_BULL = "WEAK_BULL"          # Long 70% / Short 30%
    RANGING = "RANGING"              # Long 50% / Short 50%
    WEAK_BEAR = "WEAK_BEAR"          # Short 70% / Long 30%
    STRONG_BEAR = "STRONG_BEAR"      # Short apenas
    CHOPPY = "CHOPPY"                # Sem trades (alta volatilidade)

class PositionType(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    HEDGE = "HEDGE"

def init_trade_log():
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Timestamp', 'Symbol', 'Regime', 'Action', 'Side',
                'Entry_Price', 'Exit_Price', 'Size', 'PnL_USDT',
                'Long_Exposure%', 'Short_Exposure%', 'Total_Exposure%',
                'Balance_USDT', 'RSI', 'Volatility', 'Reason'
            ])

def log_trade(symbol, regime, action, side, entry, exit_price, 
              size, pnl, long_exp, short_exp, total_exp, balance, 
              rsi, volatility, reason):
    try:
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol, regime, action, side,
                f'{entry:.2f}', f'{exit_price:.2f}', f'{size:.8f}',
                f'{pnl:.4f}', f'{long_exp:.1f}', f'{short_exp:.1f}',
                f'{total_exp:.1f}', f'{balance:.2f}',
                f'{rsi:.1f}' if rsi else '-', 
                f'{volatility:.2f}' if volatility else '-',
                reason
            ])
    except Exception as e:
        add_log(f"Log error: {e}")

# --- INDICADORES AVANÇADOS ---

def calculate_all_indicators(closes_5m, closes_15m, closes_1h, highs, lows, volumes):
    """Calcula TODOS indicadores necessários para regime detection"""
    if len(closes_5m) < 50:
        return None
    
    current_price = closes_5m[-1]
    
    # RSI em múltiplos timeframes
    rsi_5m = calculate_rsi(closes_5m, 14)
    rsi_15m = calculate_rsi(closes_15m, 14) if len(closes_15m) >= 14 else rsi_5m
    rsi_1h = calculate_rsi(closes_1h, 14) if len(closes_1h) >= 14 else rsi_5m
    
    # EMAs para tendência
    closes_series = pd.Series(closes_5m)
    ema_9 = closes_series.ewm(span=9, adjust=False).mean().iloc[-1]
    ema_21 = closes_series.ewm(span=21, adjust=False).mean().iloc[-1]
    ema_55 = closes_series.ewm(span=55, adjust=False).mean().iloc[-1]
    
    # MACD
    ema_12 = closes_series.ewm(span=12, adjust=False).mean()
    ema_26 = closes_series.ewm(span=26, adjust=False).mean()
    macd_line = ema_12 - ema_26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_current = macd_line.iloc[-1]
    signal_current = signal_line.iloc[-1]
    macd_histogram = macd_current - signal_current
    
    # ATR para volatilidade
    atr = calculate_atr(highs, lows, closes_5m, 14)
    volatility_pct = (atr / current_price * 100) if atr and current_price > 0 else 0
    
    # Bollinger Bands width (indica squeeze/expansão)
    bb_width = calculate_bb_width(closes_5m)
    
    # Volume trend
    vol_ratio = calculate_volume_ratio(volumes)
    
    # ADX caseiro (simplificado)
    adx = calculate_simple_adx(highs, lows, closes_5m, 14)
    
    return {
        'current_price': current_price,
        'rsi_5m': rsi_5m,
        'rsi_15m': rsi_15m,
        'rsi_1h': rsi_1h,
        'ema_9': ema_9,
        'ema_21': ema_21,
        'ema_55': ema_55,
        'macd_line': macd_current,
        'macd_signal': signal_current,
        'macd_histogram': macd_histogram,
        'volatility_pct': volatility_pct,
        'bb_width': bb_width,
        'vol_ratio': vol_ratio,
        'adx': adx
    }

def calculate_atr(highs, lows, closes, period=14):
    """Average True Range"""
    if len(closes) < period:
        return 0
    
    tr_list = []
    for i in range(1, min(len(highs), len(lows), len(closes))):
        h, l, c_prev = highs[i], lows[i], closes[i-1]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        tr_list.append(tr)
    
    return pd.Series(tr_list).rolling(period).mean().iloc[-1] if tr_list else 0

def calculate_bb_width(closes, period=20):
    """Bollinger Band Width"""
    if len(closes) < period:
        return 0
    
    s = pd.Series(closes)
    sma = s.rolling(period).mean()
    std = s.rolling(period).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    
    return ((upper - lower) / sma).iloc[-1] * 100

def calculate_volume_ratio(volumes, short_period=5, long_period=20):
    """Volume ratio curto/longo prazo"""
    if len(volumes) < long_period:
        return 1.0
    
    vol_series = pd.Series(volumes)
    short_avg = vol_series.rolling(short_period).mean().iloc[-1]
    long_avg = vol_series.rolling(long_period).mean().iloc[-1]
    
    return short_avg / long_avg if long_avg > 0 else 1.0

def calculate_simple_adx(highs, lows, closes, period=14):
    """ADX simplificado"""
    if len(closes) < period * 2:
        return 25  # Neutro
    
    # True Range
    tr_list = []
    plus_dm = []
    minus_dm = []
    
    for i in range(1, len(closes)):
        h, l, c = highs[i], lows[i], closes[i]
        h_prev, l_prev, c_prev = highs[i-1], lows[i-1], closes[i-1]
        
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        tr_list.append(tr)
        
        up_move = h - h_prev
        down_move = l_prev - l
        
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0)
    
    # Suavização
    tr_smooth = pd.Series(tr_list).ewm(alpha=1/period, adjust=False).mean().iloc[-1]
    plus_dm_smooth = pd.Series(plus_dm).ewm(alpha=1/period, adjust=False).mean().iloc[-1]
    minus_dm_smooth = pd.Series(minus_dm).ewm(alpha=1/period, adjust=False).mean().iloc[-1]
    
    plus_di = (plus_dm_smooth / tr_smooth * 100) if tr_smooth > 0 else 0
    minus_di = (minus_dm_smooth / tr_smooth * 100) if tr_smooth > 0 else 0
    
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
    
    return dx

# --- DETECTOR DE REGIME DE MERCADO ---

def detect_market_regime(indicators):
    """
    Detecta o regime atual do mercado
    Usa lógica fuzzy para transições suaves
    """
    if not indicators:
        return MarketRegime.CHOPPY, {}
    
    # Extrai indicadores
    rsi_5m = indicators['rsi_5m'] or 50
    rsi_1h = indicators['rsi_1h'] or 50
    ema_9 = indicators['ema_9']
    ema_21 = indicators['ema_21']
    ema_55 = indicators['ema_55']
    price = indicators['current_price']
    volatility = indicators['volatility_pct']
    adx = indicators['adx']
    macd_histogram = indicators['macd_histogram']
    bb_width = indicators['bb_width']
    
    reasons = []
    bull_score = 0
    bear_score = 0
    
    # 1. Estrutura de EMAs (alinhamneto)
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
    
    # 2. RSI multi-timeframe
    rsi_avg = (rsi_5m + rsi_1h) / 2
    if rsi_avg > 60:
        bull_score += 20
        reasons.append(f"RSI comprador ({rsi_avg:.0f})")
    elif rsi_avg < 40:
        bear_score += 20
        reasons.append(f"RSI vendedor ({rsi_avg:.0f})")
    
    # RSI extremo pode indicar reversão
    if rsi_5m > 75:
        bear_score += 15  # Sobcomprado pode cair
        reasons.append("RSI sobrecomprado (reversão)")
    elif rsi_5m < 25:
        bull_score += 15  # Sobrevendido pode subir
        reasons.append("RSI sobrevendido (reversão)")
    
    # 3. MACD
    if macd_histogram > 0:
        bull_score += 15
        reasons.append("MACD bullish")
    else:
        bear_score += 15
        reasons.append("MACD bearish")
    
    # 4. ADX (força da tendência)
    if adx > 40:
        reasons.append(f"Tendência FORTE (ADX:{adx:.0f})")
    elif adx > 25:
        reasons.append(f"Tendência MODERADA (ADX:{adx:.0f})")
    else:
        reasons.append(f"Sem tendência (ADX:{adx:.0f})")
    
    # 5. Volatilidade
    if volatility > 3:
        reasons.append(f"ALTA volatilidade: {volatility:.1f}%")
    elif volatility < 0.5:
        reasons.append(f"BAIXA volatilidade: {volatility:.1f}%")
    
    # 6. Bollinger Band Width (contração/expansão)
    if bb_width < 2:
        reasons.append("BB Squeeze (breakout iminente)")
    
    # Determina regime
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
    
    info = {
        'bull_score': bull_score,
        'bear_score': bear_score,
        'reasons': reasons,
        'adx': adx,
        'volatility': volatility
    }
    
    return regime, info

# --- GESTÃO DE POSIÇÕES LONG/SHORT ---

def calculate_position_sizes(regime, total_balance, current_price):
    """
    Calcula tamanhos das posições Long e Short baseado no regime
    Retorna: (long_size%, short_size%, long_usdt, short_usdt)
    """
    base_capital = total_balance * 0.95  # Reserva 5% para fees
    
    # Distribuição por regime
    allocations = {
        MarketRegime.STRONG_BULL:   (0.80, 0.10),  # 80% Long, 10% Short (hedge)
        MarketRegime.WEAK_BULL:     (0.50, 0.15),  # 50% Long, 15% Short
        MarketRegime.RANGING:       (0.30, 0.30),  # 30% Long, 30% Short
        MarketRegime.WEAK_BEAR:     (0.15, 0.50),  # 15% Long, 50% Short
        MarketRegime.STRONG_BEAR:   (0.10, 0.80),  # 10% Long, 80% Short
        MarketRegime.CHOPPY:        (0.10, 0.10),  # Mínimo nos dois lados
    }
    
    long_pct, short_pct = allocations.get(regime, (0.10, 0.10))
    
    long_usdt = base_capital * long_pct
    short_usdt = base_capital * short_pct
    
    return long_pct, short_pct, long_usdt, short_usdt

# --- FUNÇÕES AUXILIARES ---

def get_free_balance(exchange, coin):
    """Busca saldo UTA Bybit"""
    try:
        resp = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
        coins = resp.get('result', {}).get('list', [{}])[0].get('coin', [])
        for c in coins:
            if c.get('coin') == coin:
                return float(c.get('availableToWithdraw') or c.get('walletBalance') or 0)
    except:
        pass
    
    try:
        balance = exchange.fetch_balance({'type': 'unified'})
        return float(balance.get('free', {}).get(coin, 0) or 0)
    except:
        pass
    return 0.0

def execute_market_order(exchange, symbol, side, amount, reduce_only=False):
    """Executa ordem com parâmetros UTA"""
    add_log(f"[ORDEM] {side.upper()} {amount:.8f} {symbol} (reduce={reduce_only})")
    try:
        # A API de Spot não aceita reduceOnly na V5 em alguns modos. Removemos preventivamente.
        if side.lower() == 'buy':
            order = exchange.create_market_buy_order(symbol, amount)
        else:
            order = exchange.create_market_sell_order(symbol, amount)
        
        add_log(f"✅ Ordem {order.get('id', 'N/A')} executada")
        return True
    except Exception as e:
        add_log(f"❌ Erro ordem: {e}")
        return False

def execute_long_short_trade(exchange, symbol, action, current_price, 
                             long_exposure, short_exposure, target_long, target_short):
    """
    Ajusta posições Long e Short para atingir targets
    action: 'ENTER_LONG', 'EXIT_LONG', 'ENTER_SHORT', 'EXIT_SHORT', 'REBALANCE'
    """
    base_coin = symbol.split('/')[0]
    
    # --- Ajusta LONG ---
    if target_long > long_exposure:
        # Precisa comprar mais
        buy_amount = (target_long - long_exposure) / current_price
        add_log(f"📈 Aumentando LONG: +${target_long - long_exposure:.2f} ({buy_amount:.8f} {base_coin})")
        success = execute_market_order(exchange, symbol, 'buy', buy_amount)
        if success:
            long_exposure = target_long
    
    elif target_long < long_exposure * 0.9:  # 10% de tolerância
        # Precisa vender parte
        sell_value = long_exposure - target_long
        coin_balance = get_free_balance(exchange, base_coin)
        sell_amount = min(sell_value / current_price, coin_balance * 0.95)
        
        if sell_amount > 0:
            add_log(f"📉 Reduzindo LONG: -${sell_value:.2f} ({sell_amount:.8f} {base_coin})")
            success = execute_market_order(exchange, symbol, 'sell', sell_amount)
            if success:
                long_exposure = target_long
    
    # --- Ajusta SHORT ---
    # Short em spot = vender moeda que não tem (não disponível em spot normal)
    # Para short real, precisa de margin/futures
    # Aqui simulamos com posição inversa
    if target_short > short_exposure:
        # Entra short vendendo parte da posição long como hedge
        short_amount = (target_short - short_exposure) / current_price
        add_log(f"🔻 Aumentando SHORT (hedge): +${target_short - short_exposure:.2f}")
        # Em spot, short = reduzir exposição líquida
        # Vendendo parte da posição long
        coin_bal = get_free_balance(exchange, base_coin)
        sell_for_hedge = min(short_amount, coin_bal * 0.30)  # Max 30% para hedge
        if sell_for_hedge > 0:
            execute_market_order(exchange, symbol, 'sell', sell_for_hedge)
            short_exposure += sell_for_hedge * current_price
    
    # Atualiza saldos
    new_coin = get_free_balance(exchange, base_coin)
    new_usdt = get_free_balance(exchange, 'USDT')
    
    return new_coin, new_usdt, long_exposure, short_exposure

# --- LOOP PRINCIPAL ---

def run_hybrid_long_short(exchange, symbol='BTC/USDT', check_interval=30):
    """
    Estratégia Principal Long/Short Híbrida
    """
    init_trade_log()
    
    add_log("=" * 70)
    add_log("🦅 ESTRATÉGIA LONG/SHORT HÍBRIDA INICIADA")
    add_log("   Modos: Trend Follow + Range Trade + Hedge Protetor")
    add_log("=" * 70)
    
    bot_state["is_running"] = True
    bot_state["status"] = "🟢 Long/Short Ativo"
    
    base_coin = symbol.split('/')[0]
    bot_state["coin_name"] = base_coin
    
    # Estado das posições
    long_exposure = 0.0  # USDT em posição long
    short_exposure = 0.0  # USDT em posição short (hedge)
    last_regime = None
    regime_stable_count = 0
    trades_this_regime = 0
    
    # Parâmetros de risco
    MAX_TOTAL_EXPOSURE = 0.90  # 90% máximo do capital
    MIN_TRADE_INTERVAL = 3  # scans entre ajustes
    last_adjustment = 0
    
    scan_count = 0
    
    try:
        while bot_state["is_running"]:
            scan_count += 1
            
            # Atualiza saldos
            coin_balance = get_free_balance(exchange, base_coin)
            usdt_balance = get_free_balance(exchange, 'USDT')
            
            # Calcula exposição atual
            try:
                ticker = exchange.fetch_ticker(symbol)
                current_price = ticker['last']
                long_exposure = coin_balance * current_price
                total_balance = usdt_balance + long_exposure
            except:
                add_log("Erro ao obter preço, aguardando...")
                time.sleep(10)
                continue
            
            bot_state["current_price"] = current_price
            bot_state["coin_balance"] = coin_balance
            bot_state["usdt_balance"] = usdt_balance
            bot_state["total_balance"] = total_balance
            
            # Busca dados OHLCV
            try:
                ohlcv_5m = exchange.fetch_ohlcv(symbol, '5m', limit=100)
                ohlcv_15m = exchange.fetch_ohlcv(symbol, '15m', limit=100)
                ohlcv_1h = exchange.fetch_ohlcv(symbol, '1h', limit=100)
            except Exception as e:
                add_log(f"Erro OHLCV: {e}")
                time.sleep(10)
                continue
            
            closes_5m = [c[4] for c in ohlcv_5m]
            closes_15m = [c[4] for c in ohlcv_15m]
            closes_1h = [c[4] for c in ohlcv_1h]
            highs = [c[2] for c in ohlcv_5m]
            lows = [c[3] for c in ohlcv_5m]
            volumes = [c[5] for c in ohlcv_5m]
            
            # Calcula indicadores
            indicators = calculate_all_indicators(
                closes_5m, closes_15m, closes_1h,
                highs, lows, volumes
            )
            
            if not indicators:
                time.sleep(check_interval)
                continue
            
            # Detecta regime
            regime, regime_info = detect_market_regime(indicators)
            
            # Estabilidade do regime
            if regime == last_regime:
                regime_stable_count += 1
            else:
                regime_stable_count = 1
                trades_this_regime = 0
                add_log(f"🔄 MUDANÇA DE REGIME: {last_regime} → {regime}")
                last_regime = regime
            
            # Calcula posições alvo
            long_pct, short_pct, target_long, target_short = calculate_position_sizes(
                regime, total_balance, current_price
            )
            
            # Atualiza dashboard
            bot_state["market_regime"] = regime.value
            bot_state["rsi"] = indicators['rsi_5m'] or 50
            bot_state["rsi_status"] = f"{regime.value} | Long:{long_pct*100:.0f}% Short:{short_pct*100:.0f}%"
            
            # Log do scan
            total_exp = (long_exposure / total_balance * 100) if total_balance > 0 else 0
            add_log(f"#{scan_count} {regime.value} | "
                   f"Preço: ${current_price:.2f} | "
                   f"Long: ${long_exposure:.0f} ({long_pct*100:.0f}%→{long_exposure/total_balance*100:.0f}%) | "
                   f"Short: ${short_exposure:.0f} ({short_pct*100:.0f}%→{short_exposure/total_balance*100:.0f}%) | "
                   f"ADX: {regime_info['adx']:.0f} | Vol: {regime_info['volatility']:.1f}%")
            
            for reason in regime_info['reasons']:
                add_log(f"   ↳ {reason}")
            
            # --- EXECUÇÃO DE TRADES ---
            can_trade = (scan_count - last_adjustment) >= MIN_TRADE_INTERVAL
            
            if can_trade and regime != MarketRegime.CHOPPY:
                
                # Verifica se precisa ajustar posições
                need_adjustment = False
                
                # Long está diferente do target?
                if abs(long_exposure - target_long) > total_balance * 0.05:  # 5% tolerância
                    need_adjustment = True
                
                # Short está diferente do target?
                if abs(short_exposure - target_short) > total_balance * 0.05:
                    need_adjustment = True
                
                if need_adjustment and trades_this_regime < 5:  # Máx 5 trades por regime
                    add_log(f"⚡ Ajustando posições para regime {regime.value}")
                    
                    new_coin, new_usdt, new_long, new_short = execute_long_short_trade(
                        exchange, symbol, 'REBALANCE', current_price,
                        long_exposure, short_exposure, target_long, target_short
                    )
                    
                    # Log do trade
                    log_trade(
                        symbol, regime.value, 'REBALANCE', 'BOTH',
                        current_price, current_price, 0, 0,
                        new_long/total_balance*100 if total_balance > 0 else 0,
                        new_short/total_balance*100 if total_balance > 0 else 0,
                        (new_long+new_short)/total_balance*100 if total_balance > 0 else 0,
                        total_balance, indicators['rsi_5m'],
                        indicators['volatility_pct'],
                        '; '.join(regime_info['reasons'])
                    )
                    
                    # Atualiza estado
                    long_exposure = new_long if new_long else long_exposure
                    bot_state["coin_balance"] = get_free_balance(exchange, base_coin)
                    bot_state["usdt_balance"] = get_free_balance(exchange, 'USDT')
                    
                    trades_this_regime += 1
                    last_adjustment = scan_count
            
            # Sleep com check
            for _ in range(check_interval):
                if not bot_state["is_running"]:
                    break
                time.sleep(1)
                
    except KeyboardInterrupt:
        add_log("Interrompido pelo usuário")
    except Exception as e:
        add_log(f"💥 ERRO CRÍTICO: {e}")
        import traceback
        add_log(traceback.format_exc())
    finally:
        # Resumo final
        coin_final = get_free_balance(exchange, base_coin)
        usdt_final = get_free_balance(exchange, 'USDT')
        try:
            ticker = exchange.fetch_ticker(symbol)
            total_final = usdt_final + (coin_final * ticker['last'])
        except:
            total_final = usdt_final
        
        add_log("=" * 70)
        add_log(f"📊 RESUMO LONG/SHORT:")
        add_log(f"   Saldo Final: ${total_final:.2f}")
        add_log(f"   USDT: ${usdt_final:.2f}")
        add_log(f"   {base_coin}: {coin_final:.8f}")
        add_log(f"   Regimes detectados: {regime_stable_count} scans")
        add_log("=" * 70)
        
        bot_state["is_running"] = False
        bot_state["status"] = "🔴 Desligado"
        add_log("Bot Long/Short Finalizado.")
