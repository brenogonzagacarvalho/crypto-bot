import ccxt
import os
import sys
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

def connect_to_bybit():
    api_key = os.getenv('BYBIT_API_KEY')
    api_secret = os.getenv('BYBIT_API_SECRET')

    if not api_key or not api_secret or api_key == 'sua_api_key_aqui':
        print("Erro: Credenciais da Bybit não encontradas ou inválidas.")
        print("Por favor, crie um arquivo '.env' na mesma pasta deste script com suas chaves.")
        print("Veja o arquivo '.env.example' como referência.")
        sys.exit(1)

    print("Conectando à Bybit...")
    
    # Instancia a exchange Bybit
    exchange = ccxt.bybit({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True, # Recomendado para não exceder limites da API
        'options': {
            'adjustForTimeDifference': True, # Sincroniza o horário com a Bybit automaticamente
        }
    })
    
    try:
        # Testa a conexão buscando o saldo
        balance = exchange.fetch_balance()
        print("\nConexão bem-sucedida! ✅")
        
        # Mostra os saldos disponíveis
        print("Seus saldos na Bybit:")
        has_balance = False
        for currency, amount in balance['total'].items():
            if amount > 0:
                # O formato difere dependendo da moeda (crypto tem mais casas decimais)
                print(f" - {currency}: {amount}")
                has_balance = True
                
        if not has_balance:
            print(" - Você não possui saldo em nenhuma moeda no momento.")
            
        print("\nPronto para iniciar a lógica do bot de trade!")
        
        return exchange
        
    except ccxt.AuthenticationError:
        print("\nErro de Autenticação ❌: API Key ou Secret inválidos.")
    except Exception as e:
        print(f"\nOcorreu um erro ao conectar: {e}")

if __name__ == "__main__":
    connect_to_bybit()
