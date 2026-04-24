import time
import sys
import os
import csv
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_historical_data, fetch_current_price

def calculate_sma(prices, period):
    """Calcula a Simple Moving Average (Média Móvel Simples)"""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def log_trend_decision(symbol, price, fast_ma, slow_ma, action):
    """Salva a decisão de tendência em um arquivo CSV para auditoria e histórico."""
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    
    log_file = os.path.join(logs_dir, 'trend_history.csv')
    file_exists = os.path.isfile(log_file)
    
    try:
        with open(log_file, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['Timestamp', 'Symbol', 'Price', 'Fast_MA', 'Slow_MA', 'Action'])
                
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            writer.writerow([timestamp, symbol, f"{price:.2f}", f"{fast_ma:.2f}", f"{slow_ma:.2f}", action])
    except Exception as e:
        print(f"Erro ao salvar log: {e}")

def run_trend_following_simulated(exchange, symbol='BTC/USDT', fast_period=9, slow_period=21, check_interval=60):
    """
    Simula uma estratégia de cruzamento de médias móveis no gráfico de 1 minuto.
    Grava as tendências e decisões num arquivo CSV de logs.
    """
    print(f"\n[TREND 1M - SIMULAÇÃO E LOG] Monitorando {symbol} a cada 1 Minuto")
    print(f"Estratégia: Cruzamento MA Rápida ({fast_period}) vs MA Lenta ({slow_period})")
    print("Os dados serão salvos na pasta 'logs/trend_history.csv'")
    print("Pressione Ctrl+C para parar.\n")
    
    current_position = None  # Pode ser 'LONG' (comprado) ou None
    
    try:
        while True:
            # Puxamos dados de velas de 1 MINUTO
            closes = fetch_historical_data(exchange, symbol, timeframe='1m', limit=50)
            
            if not closes or len(closes) < slow_period:
                print("Aguardando mais dados do mercado...")
                time.sleep(check_interval)
                continue
            
            fast_ma = calculate_sma(closes, fast_period)
            slow_ma = calculate_sma(closes, slow_period)
            current_price = closes[-1]
            
            # Identifica a tendência atual visualmente
            trend_str = "ALTA 🔼" if fast_ma > slow_ma else "BAIXA 🔽"
            
            print(f"[{symbol}] Preço: ${current_price:.2f} | MA Rápida: {fast_ma:.2f} | MA Lenta: {slow_ma:.2f} | Tendência: {trend_str}")
            
            action_taken = "Wait/No Position"
            
            # Lógica de Cruzamento
            if fast_ma > slow_ma and current_position != 'LONG':
                print(">>> SINAL DE COMPRA! MA Rápida cruzou para cima da MA Lenta.")
                print(">>> [SIMULAÇÃO] Executando ordem de COMPRA a Mercado e registrando no log.")
                current_position = 'LONG'
                action_taken = "BUY"
                
            elif fast_ma < slow_ma and current_position == 'LONG':
                print(">>> SINAL DE VENDA! MA Rápida cruzou para baixo da MA Lenta.")
                print(">>> [SIMULAÇÃO] Executando ordem de VENDA a Mercado e registrando no log.")
                current_position = None
                action_taken = "SELL"
            elif current_position == 'LONG':
                action_taken = "HOLD Position"
                
            # Grava no log a cada minuto independentemente se cruzou ou não (para ter o histórico completo da tendência)
            log_trend_decision(symbol, current_price, fast_ma, slow_ma, action_taken)
                
            time.sleep(check_interval)
            
    except KeyboardInterrupt:
        print("\nTrend Following finalizado pelo usuário.")
