def fetch_current_price(exchange, symbol='BTC/USDT'):
    """
    Busca o preço atual de um par.
    """
    try:
        ticker = exchange.fetch_ticker(symbol)
        return ticker['last']
    except Exception as e:
        print(f"Erro ao buscar preço para {symbol}: {e}")
        return None

def fetch_historical_data(exchange, symbol='BTC/USDT', timeframe='15m', limit=50):
    """
    Busca os dados históricos (Velas/Candles) para cálculo de indicadores.
    Retorna uma lista de preços de fechamento (close).
    """
    try:
        # fetch_ohlcv retorna: [ timestamp, open, high, low, close, volume ]
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        # Extrair apenas os preços de fechamento (índice 4)
        closes = [candle[4] for candle in ohlcv]
        return closes
    except Exception as e:
        print(f"Erro ao buscar histórico para {symbol}: {e}")
        return None

def calculate_rsi(prices, period=14):
    """
    Calcula o Relative Strength Index (RSI) para previsão de sobrecompra/sobrevenda.
    """
    if len(prices) < period + 1:
        return None
        
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    # Média inicial
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    # Cálculo Suavizado (Wilder's Smoothing)
    for i in range(period, len(prices)-1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    if avg_loss == 0:
        return 100
        
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_ema(prices, period=9):
    """
    Calcula a Média Móvel Exponencial (EMA).
    """
    if len(prices) < period:
        return None
        
    # Primeiro valor é uma Média Simples (SMA)
    ema = sum(prices[:period]) / period
    multiplier = 2 / (period + 1)
    
    # Aplica o multiplicador exponencial nos preços seguintes
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
        
    return ema
