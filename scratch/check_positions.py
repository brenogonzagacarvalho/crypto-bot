from core.connection import get_exchange
import json

def check_account():
    exchange = get_exchange()
    print("--- Verificando Posições Abertas ---")
    try:
        # Busca posições em USDT (Perpetuals) - Especificando categoria e settleCoin para Bybit V5
        positions = exchange.fetch_positions(params={'category': 'linear', 'settleCoin': 'USDT'})
        open_positions = []
        for p in positions:
            # No Bybit V5/CCXT, contratos > 0 indica posição aberta
            contracts = float(p.get('contracts', 0) or 0)
            if contracts > 0:
                open_positions.append(p)
        
        if not open_positions:
            print("Nenhuma posição aberta encontrada.")
        else:
            for p in open_positions:
                print(f"Símbolo: {p['symbol']}")
                print(f"  Lado: {p['side']}")
                print(f"  Tamanho: {p['contracts']} contratos")
                print(f"  Preço Entrada: {p['entryPrice']}")
                print(f"  P&L Não Realizado: {p['unrealizedPnl']} USDT")
                print("-" * 20)

        print("\n--- Verificando Ordens Abertas (Stop Loss / Take Profit) ---")
        open_orders = exchange.fetch_open_orders()
        if not open_orders:
            print("Nenhuma ordem pendente encontrada.")
        else:
            for o in open_orders:
                print(f"Ordem: {o['symbol']} | Tipo: {o['type']} | Lado: {o['side']} | Preço: {o['price']}")

    except Exception as e:
        print(f"Erro no diagnóstico: {e}")

if __name__ == "__main__":
    check_account()
