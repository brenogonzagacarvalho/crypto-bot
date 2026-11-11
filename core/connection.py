import ccxt
import os
from dotenv import load_dotenv
from core.paper_exchange import PaperExchangeWrapper

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(ENV_PATH, override=True)

_paper_instance = None


def has_valid_credentials():
    """Verifica se BYBIT_API_KEY e BYBIT_API_SECRET foram preenchidos no .env."""
    load_dotenv(ENV_PATH, override=True)
    api_key = (os.getenv('BYBIT_API_KEY') or '').strip()
    api_secret = (os.getenv('BYBIT_API_SECRET') or '').strip()
    placeholders = {'', 'sua_api_key_aqui', 'seu_api_secret_aqui', 'your_api_key', 'your_api_secret'}
    return api_key not in placeholders and api_secret not in placeholders


def _create_raw_bybit(require_auth=True):
    load_dotenv(ENV_PATH, override=True)
    api_key = (os.getenv('BYBIT_API_KEY') or '').strip()
    api_secret = (os.getenv('BYBIT_API_SECRET') or '').strip()

    cfg = {
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
        },
    }
    if has_valid_credentials():
        cfg['apiKey'] = api_key
        cfg['secret'] = api_secret
    elif require_auth:
        return None

    exchange = ccxt.bybit(cfg)
    try:
        exchange.load_markets()
    except Exception as e:
        print(f"Aviso ao carregar mercados: {e}")
    return exchange


def get_exchange(raise_on_missing=False, mode=None):
    """
    Retorna a instância da exchange de acordo com o modo ativo ('LIVE' ou 'PAPER').
    - No modo 'PAPER' (Conta de Teste), usa cotações/orderbook 100% reais da Bybit
      com saldo e execução simulados em tempo real (`PaperExchangeWrapper`).
    """
    global _paper_instance
    from core.shared_state import bot_state

    active_mode = (mode or bot_state.get("account_mode", "LIVE")).upper()
    if active_mode == "PAPER":
        if _paper_instance is None:
            raw = _create_raw_bybit(require_auth=False)
            _paper_instance = PaperExchangeWrapper(raw, default_balance=100.0)
        return _paper_instance

    if not has_valid_credentials():
        print("\n[AVISO] Credenciais da Bybit ainda não configuradas no arquivo '.env'.")
        print(f"Edite o arquivo: {ENV_PATH} ou use a Conta de Teste pelo Dashboard Web em http://127.0.0.1:5000")
        if raise_on_missing:
            raise RuntimeError("Credenciais da Bybit não configuradas no .env")
        return None

    return _create_raw_bybit(require_auth=True)


def check_connection(exchange):
    """
    Testa a conexão com a Bybit (ou Simulador Paper) e exibe o saldo sem derrubar o servidor.
    """
    if exchange is None:
        return False
    try:
        if getattr(exchange, 'is_paper', False):
            resp = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
            eq = float(resp['result']['list'][0]['totalEquity'])
            print(f"\n=== 🧪 Conta de Teste (Simulador Real-Time Bybit) Ativa! Saldo: ${eq:.2f} USDT ===\n")
            return True

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
