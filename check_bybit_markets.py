import ccxt

def listar_mercados_bybit():
    print("🔍 Consultando mercados SPOT disponíveis na Bybit...\n")
    
    exchange = ccxt.bybit({
        'options': {
            'defaultType': 'spot',
        }
    })
    
    try:
        markets = exchange.load_markets()
        
        # Filtrar apenas mercados SPOT com USDT
        spot_usdt = [
            symbol for symbol, info in markets.items()
            if info.get('spot') == True
            and symbol.endswith('/USDT')
            and info.get('active') == True
        ]
        
        spot_usdt.sort()
        
        print(f"✅ Total de pares SPOT/USDT disponíveis: {len(spot_usdt)}\n")
        print("=" * 40)
        
        # Top moedas populares para verificar primeiro
        populares = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'BNB/USDT',
                     'ADA/USDT', 'AVAX/USDT', 'DOT/USDT', 'MATIC/USDT', 'DOGE/USDT',
                     'LINK/USDT', 'UNI/USDT', 'ATOM/USDT', 'LTC/USDT', 'TRX/USDT']
        
        print("🌟 MOEDAS POPULARES DISPONÍVEIS:")
        for p in populares:
            status = "✅" if p in spot_usdt else "❌"
            print(f"  {status} {p}")
        
        print("\n📋 TODOS OS PARES SPOT/USDT (primeiros 50):")
        for i, symbol in enumerate(spot_usdt[:50]):
            print(f"  {i+1:2d}. {symbol}")
        
        if len(spot_usdt) > 50:
            print(f"\n  ... e mais {len(spot_usdt) - 50} pares.")
            
    except Exception as e:
        print(f"❌ Erro ao consultar API: {e}")

if __name__ == "__main__":
    listar_mercados_bybit()
