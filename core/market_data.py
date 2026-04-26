def fetch_current_price(exchange, symbol='BTC/USDT'):
    try:
        ticker = exchange.fetch_ticker(symbol)
        return ticker['last']
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
        data = {
            't': [c[0] for c in ohlcv],
            'o': [c[1] for c in ohlcv],
            'h': [c[2] for c in ohlcv],
            'l': [c[3] for c in ohlcv],
            'c': [c[4] for c in ohlcv],
            'v': [c[5] for c in ohlcv]
        }
        return data
    except Exception as e:
        print(f"Erro ao buscar OHLCV para {symbol}: {e}")
        return None

def fetch_historical_data(exchange, symbol='BTC/USDT', timeframe='5m', limit=50):
    """Retorna apenas lista de fechamentos (mantido para compatibilidade)."""
    data = fetch_ohlcv_data(exchange, symbol, timeframe, limit)
    return data['c'] if data else None

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1: return None
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(prices)-1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_ema(prices, period=9):
    if len(prices) < period: return None
    ema = sum(prices[:period]) / period
    multiplier = 2 / (period + 1)
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def calculate_macd(prices, fast=12, slow=26, signal=9):
    """Calcula MACD, Linha de Sinal e Histograma."""
    if len(prices) < slow + signal: return None, None, None
    
    # Lista de EMAs rápidas e lentas para poder calcular a EMA da diferença (Sinal)
    ema_fast_list = []
    ema_slow_list = []
    
    # Calculamos o MACD para os últimos 'signal' períodos
    macd_line_list = []
    for i in range(len(prices) - signal, len(prices)):
        p_slice = prices[:i+1]
        f = calculate_ema(p_slice, fast)
        s = calculate_ema(p_slice, slow)
        macd_line_list.append(f - s)
        
    macd_line = macd_line_list[-1]
    signal_line = calculate_ema(macd_line_list, signal)
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram
