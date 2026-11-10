import math


def fetch_current_price(exchange, symbol='BTC/USDT'):
    try:
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker['last'])
    except Exception as e:
        print(f"Erro ao buscar preço para {symbol}: {e}")
        return None


def fetch_ohlcv_data(exchange, symbol='BTC/USDT', timeframe='5m', limit=210):
    """
    Busca OHLCV completo para indicadores avançados.
    Retorna dicionário com listas de: timestamps, opens, highs, lows, closes, volumes
    """
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv:
            return None
        return {
            't': [float(c[0]) for c in ohlcv],
            'o': [float(c[1]) for c in ohlcv],
            'h': [float(c[2]) for c in ohlcv],
            'l': [float(c[3]) for c in ohlcv],
            'c': [float(c[4]) for c in ohlcv],
            'v': [float(c[5]) for c in ohlcv],
        }
    except Exception as e:
        print(f"Erro ao buscar OHLCV para {symbol}: {e}")
        return None


def fetch_historical_data(exchange, symbol='BTC/USDT', timeframe='5m', limit=50):
    """Retorna apenas lista de fechamentos (mantido para compatibilidade)."""
    data = fetch_ohlcv_data(exchange, symbol, timeframe, limit)
    return data['c'] if data else None


def calculate_rsi(prices, period=14):
    if not prices or len(prices) < period + 1:
        return None
    deltas = [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(prices) - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_ema(prices, period=9):
    if not prices or len(prices) < period:
        return None
    ema = sum(prices[:period]) / period
    multiplier = 2.0 / (period + 1.0)
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


def calculate_ema_series(prices, period=9):
    """Retorna a série completa de valores EMA alinhada ao final da lista de preços."""
    if not prices or len(prices) < period:
        return []
    ema = sum(prices[:period]) / period
    multiplier = 2.0 / (period + 1.0)
    series = [ema]
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
        series.append(ema)
    return series


def calculate_macd(prices, fast=12, slow=26, signal=9):
    """Calcula MACD, Linha de Sinal e Histograma de forma eficiente O(N)."""
    if not prices or len(prices) < slow + signal:
        return None, None, None

    fast_series = calculate_ema_series(prices, fast)
    slow_series = calculate_ema_series(prices, slow)

    # Alinha as duas séries pelo final
    min_len = min(len(fast_series), len(slow_series))
    if min_len < signal:
        return None, None, None

    macd_series = [
        fast_series[len(fast_series) - min_len + i] - slow_series[len(slow_series) - min_len + i]
        for i in range(min_len)
    ]
    macd_line = macd_series[-1]
    signal_line = calculate_ema(macd_series, signal)
    if signal_line is None:
        return None, None, None
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_vwap(ohlcv_data):
    """
    Calcula o Volume Weighted Average Price (VWAP) com base em dados de OHLCV.
    Usa o preço típico (High + Low + Close) / 3 de cada vela.
    """
    try:
        highs = ohlcv_data['h']
        lows = ohlcv_data['l']
        closes = ohlcv_data['c']
        volumes = ohlcv_data['v']

        if not highs or not lows or not closes or not volumes:
            return None

        typical_prices = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
        total_pv = sum(tp * v for tp, v in zip(typical_prices, volumes))
        total_v = sum(volumes)

        return total_pv / total_v if total_v > 0 else closes[-1]
    except Exception:
        return None


def calculate_vwap_bands(ohlcv_data, window=50):
    """
    Calcula VWAP institucional com bandas de desvio padrão ponderadas por volume (1SD, 2SD, 2.5SD)
    e o Z-Score atual do preço em relação à VWAP.
    """
    try:
        highs = ohlcv_data['h'][-window:]
        lows = ohlcv_data['l'][-window:]
        closes = ohlcv_data['c'][-window:]
        volumes = ohlcv_data['v'][-window:]

        if len(closes) < 10:
            return None

        typical_prices = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
        total_v = sum(volumes)
        if total_v <= 0:
            vwap = sum(typical_prices) / len(typical_prices)
            variance = sum((tp - vwap) ** 2 for tp in typical_prices) / len(typical_prices)
        else:
            vwap = sum(tp * v for tp, v in zip(typical_prices, volumes)) / total_v
            variance = sum(v * ((tp - vwap) ** 2) for tp, v in zip(typical_prices, volumes)) / total_v

        stddev = math.sqrt(max(variance, 1e-12))
        current_price = closes[-1]
        z_score = (current_price - vwap) / stddev if stddev > 0 else 0.0

        return {
            'vwap': vwap,
            'stddev': stddev,
            'upper_1sd': vwap + stddev,
            'lower_1sd': vwap - stddev,
            'upper_2sd': vwap + 2.0 * stddev,
            'lower_2sd': vwap - 2.0 * stddev,
            'upper_25sd': vwap + 2.5 * stddev,
            'lower_25sd': vwap - 2.5 * stddev,
            'z_score': z_score,
        }
    except Exception:
        return None


def calculate_atr(ohlcv_data, period=14):
    """
    Calcula o Average True Range (ATR) usando suavização de Wilder (RMA) / SMA inicial.
    """
    try:
        highs = ohlcv_data['h']
        lows = ohlcv_data['l']
        closes = ohlcv_data['c']

        if len(closes) < period + 1:
            return None

        tr_list = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            tr_list.append(tr)

        atr = sum(tr_list[:period]) / period
        for tr in tr_list[period:]:
            atr = (atr * (period - 1) + tr) / period
        return atr
    except Exception:
        return None


def calculate_adx(ohlcv_data, period=14):
    """
    Calcula o Average Directional Index (ADX), +DI e -DI para medir a força real da tendência.
    Retorna (adx, plus_di, minus_di).
    """
    try:
        highs = ohlcv_data['h']
        lows = ohlcv_data['l']
        closes = ohlcv_data['c']

        if len(closes) < period * 2:
            return 20.0, 20.0, 20.0

        tr_list = []
        plus_dm_list = []
        minus_dm_list = []

        for i in range(1, len(closes)):
            up_move = highs[i] - highs[i - 1]
            down_move = lows[i - 1] - lows[i]

            plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
            minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0

            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            tr_list.append(tr)
            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)

        tr_smooth = sum(tr_list[:period])
        plus_smooth = sum(plus_dm_list[:period])
        minus_smooth = sum(minus_dm_list[:period])

        dx_list = []
        plus_di = 0.0
        minus_di = 0.0

        for i in range(period, len(tr_list)):
            tr_smooth = tr_smooth - (tr_smooth / period) + tr_list[i]
            plus_smooth = plus_smooth - (plus_smooth / period) + plus_dm_list[i]
            minus_smooth = minus_smooth - (minus_smooth / period) + minus_dm_list[i]

            plus_di = (plus_smooth / tr_smooth * 100.0) if tr_smooth > 0 else 0.0
            minus_di = (minus_smooth / tr_smooth * 100.0) if tr_smooth > 0 else 0.0
            denom = plus_di + minus_di
            dx = (abs(plus_di - minus_di) / denom * 100.0) if denom > 0 else 0.0
            dx_list.append(dx)

        if not dx_list:
            return 20.0, plus_di, minus_di

        adx = sum(dx_list[-period:]) / min(len(dx_list), period)
        return adx, plus_di, minus_di
    except Exception:
        return 20.0, 20.0, 20.0


def calculate_bollinger_bands(prices, period=20, std_mult=2.0):
    """
    Calcula Bandas de Bollinger: (upper, middle, lower, width_pct, percent_b).
    """
    if not prices or len(prices) < period:
        return None
    window = prices[-period:]
    sma = sum(window) / period
    variance = sum((p - sma) ** 2 for p in window) / period
    std = math.sqrt(max(variance, 1e-12))
    upper = sma + std_mult * std
    lower = sma - std_mult * std
    width_pct = ((upper - lower) / sma * 100.0) if sma > 0 else 0.0
    band_range = upper - lower
    percent_b = ((prices[-1] - lower) / band_range) if band_range > 0 else 0.5
    return {
        'upper': upper,
        'middle': sma,
        'lower': lower,
        'std': std,
        'width_pct': width_pct,
        'percent_b': percent_b,
    }


def calculate_keltner_channels(ohlcv_data, period=20, atr_mult=1.5):
    """
    Calcula Canais de Keltner para detecção de TTM Volatility Squeeze (Bollinger dentro de Keltner).
    """
    if not ohlcv_data or len(ohlcv_data['c']) < period + 1:
        return None
    ema_mid = calculate_ema(ohlcv_data['c'], period=period)
    atr = calculate_atr(ohlcv_data, period=period)
    if ema_mid is None or atr is None:
        return None
    return {
        'upper': ema_mid + atr_mult * atr,
        'middle': ema_mid,
        'lower': ema_mid - atr_mult * atr,
    }


def calculate_rvol(ohlcv_data, period=20):
    """
    Calcula o Volume Relativo (RVOL) comparando o último candle fechado (-2) e o atual (-1)
    com a média móvel de volume.
    """
    try:
        vols = ohlcv_data['v']
        if len(vols) < period + 2:
            return 1.0
        avg_vol = sum(vols[-(period + 2):-2]) / period
        if avg_vol <= 0:
            return 1.0
        closed_rvol = vols[-2] / avg_vol
        live_rvol = vols[-1] / avg_vol
        return max(closed_rvol, live_rvol)
    except Exception:
        return 1.0


def analyze_candle_anatomy(ohlcv_data, idx=-2):
    """
    Analisa a anatomia do candle fechado (por padrão idx=-2 para evitar repintura)
    e identifica padrões institucionais de Price Action (Pinbar/Hammer, Shooting Star, Engulfing).
    """
    if not ohlcv_data or len(ohlcv_data['c']) < abs(idx) + 2:
        return None

    o = ohlcv_data['o'][idx]
    h = ohlcv_data['h'][idx]
    l = ohlcv_data['l'][idx]
    c = ohlcv_data['c'][idx]

    o_prev = ohlcv_data['o'][idx - 1]
    h_prev = ohlcv_data['h'][idx - 1]
    l_prev = ohlcv_data['l'][idx - 1]
    c_prev = ohlcv_data['c'][idx - 1]

    candle_range = max(h - l, 1e-8)
    body = max(abs(c - o), candle_range * 0.05)
    real_body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    lower_wick_ratio = lower_wick / body
    upper_wick_ratio = upper_wick / body

    is_bullish = c > o
    is_bearish = c < o

    # Martelo / Pinbar de Alta: pavio inferior >= 1.8x corpo e fechamento na metade superior
    is_hammer = (lower_wick >= 1.8 * body) and (upper_wick <= 0.35 * candle_range)
    # Estrela Cadente / Pinbar de Baixa: pavio superior >= 1.8x corpo e fechamento na metade inferior
    is_shooting_star = (upper_wick >= 1.8 * body) and (lower_wick <= 0.35 * candle_range)

    # Engolfo de Alta / Baixa
    prev_body = abs(c_prev - o_prev)
    is_bullish_engulfing = (
        (c_prev < o_prev)
        and (c > o)
        and (c >= o_prev)
        and (o <= c_prev)
        and (real_body >= prev_body * 0.9)
    )
    is_bearish_engulfing = (
        (c_prev > o_prev)
        and (c < o)
        and (o >= c_prev)
        and (c <= o_prev)
        and (real_body >= prev_body * 0.9)
    )

    pattern_name = None
    pattern_bias = None
    if is_bullish_engulfing:
        pattern_name = "Engolfo de Alta"
        pattern_bias = "BULLISH"
    elif is_hammer:
        pattern_name = "Martelo (Pinbar Alta)"
        pattern_bias = "BULLISH"
    elif is_bearish_engulfing:
        pattern_name = "Engolfo de Baixa"
        pattern_bias = "BEARISH"
    elif is_shooting_star:
        pattern_name = "Estrela Cadente (Pinbar Baixa)"
        pattern_bias = "BEARISH"

    return {
        'open': o,
        'high': h,
        'low': l,
        'close': c,
        'body': body,
        'range': candle_range,
        'upper_wick': upper_wick,
        'lower_wick': lower_wick,
        'lower_wick_ratio': lower_wick_ratio,
        'upper_wick_ratio': upper_wick_ratio,
        'is_bullish': is_bullish,
        'is_bearish': is_bearish,
        'is_hammer': is_hammer,
        'is_shooting_star': is_shooting_star,
        'is_bullish_engulfing': is_bullish_engulfing,
        'is_bearish_engulfing': is_bearish_engulfing,
        'pattern_name': pattern_name,
        'pattern_bias': pattern_bias,
    }
