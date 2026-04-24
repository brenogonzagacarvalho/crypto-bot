import ccxt
import os
import sys
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

def get_exchange():
    """
    Retorna uma instância configurada da Bybit pronta para uso.
    """
    api_key = os.getenv('BYBIT_API_KEY')
    api_secret = os.getenv('BYBIT_API_SECRET')

    if not api_key or not api_secret or api_key == 'sua_api_key_aqui':
        print("\n[ERRO] Credenciais da Bybit não encontradas ou inválidas.")
        print("Verifique seu arquivo '.env'.")
        sys.exit(1)
    
    # Instancia a exchange Bybit
    exchange = ccxt.bybit({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True, 
        'options': {
            'adjustForTimeDifference': True, # Previne erro 10002 de timestamp
        }
    })
    
    return exchange

def check_connection(exchange):
    """
    Testa a conexão e exibe o saldo.
    """
    try:
        balance = exchange.fetch_balance()
        print("\n=== Conexão com Bybit Bem-Sucedida! ✅ ===")
        print("Saldos disponíveis:")
        has_balance = False
        for currency, amount in balance['total'].items():
            if amount > 0:
                print(f" - {currency}: {amount}")
                has_balance = True
                
        if not has_balance:
            print(" - Sem saldo no momento.")
        print("==========================================\n")
        return True
    except Exception as e:
        print(f"\n[ERRO FATAL] Falha ao conectar: {e}")
        return False
