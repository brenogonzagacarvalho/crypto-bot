import ccxt
import os
from dotenv import load_dotenv

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(ENV_PATH, override=True)


def has_valid_credentials():
    """Verifica se BYBIT_API_KEY e BYBIT_API_SECRET foram preenchidos no .env."""
    load_dotenv(ENV_PATH, override=True)
    api_key = (os.getenv('BYBIT_API_KEY') or '').strip()
    api_secret = (os.getenv('BYBIT_API_SECRET') or '').strip()
    placeholders = {'', 'sua_api_key_aqui', 'seu_api_secret_aqui', 'your_api_key', 'your_api_secret'}
    return api_key not in placeholders and api_secret not in placeholders


def get_exchange(raise_on_missing=False):
    """
    Retorna uma instância configurada da Bybit pronta para uso,
    ou None caso as credenciais ainda não tenham sido configuradas no .env.
    """
    load_dotenv(ENV_PATH, override=True)
    api_key = (os.getenv('BYBIT_API_KEY') or '').strip()
    api_secret = (os.getenv('BYBIT_API_SECRET') or '').strip()

    if not has_valid_credentials():
        print("\n[AVISO] Credenciais da Bybit ainda não configuradas no arquivo '.env'.")
        print(f"Edite o arquivo: {ENV_PATH} ou configure pelo Dashboard Web em http://127.0.0.1:5000")
        if raise_on_missing:
            raise RuntimeError("Credenciais da Bybit não configuradas no .env")
        return None

    exchange = ccxt.bybit({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'urls': {
            'api': {
                'public': 'https://api.bytick.com',
                'private': 'https://api.bytick.com',
            },
        },
        'options': {
            'adjustForTimeDifference': True,
            'recvWindow': 60000,
            'defaultType': 'spot',
        }
    })

    try:
        exchange.load_markets()
    except Exception as e:
        print(f"Aviso ao carregar mercados: {e}")

    return exchange


def check_connection(exchange):
    """
    Testa a conexão com a Bybit e exibe o saldo sem derrubar o servidor.
    """
    if exchange is None:
        return False
    try:
        balance = exchange.fetch_balance()
        print("\n=== Conexão com Bybit Bem-Sucedida! ✅ ===")
        print("Saldos disponíveis:")
        has_balance = False
        for currency, amount in balance.get('total', {}).items():
            if amount and amount > 0:
                print(f" - {currency}: {amount}")
                has_balance = True

        if not has_balance:
            print(" - Sem saldo no momento.")
        print("==========================================\n")
        return True
    except Exception as e:
        print(f"\n[AVISO] Falha ao autenticar na Bybit: {e}")
        return False
