import ccxt
import time
import datetime
import sys

def fetch_prices():
    # Usando a exchange Binance (mas sem API key para dados públicos)
    exchange = ccxt.binance()
    
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
    
    print(f"--- Preços em {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    
    try:
        for symbol in symbols:
            ticker = exchange.fetch_ticker(symbol)
            price = ticker['last']
            print(f"{symbol}: ${price:.2f}")
    except Exception as e:
        print(f"Erro ao buscar dados: {e}")

if __name__ == "__main__":
    
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        fetch_prices()
        sys.exit(0)

    print("Iniciando monitoramento de preços (Ctrl+C para parar)...")
    while True:
        fetch_prices()
        # Aguarda 60 segundos antes da próxima verificação
        time.sleep(60)
