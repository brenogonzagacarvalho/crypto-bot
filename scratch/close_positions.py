from core.connection import get_exchange
import time

def close_all_positions():
    exchange = get_exchange()
    print("--- Iniciando Fechamento de Posições ---")
    try:
        # Busca posições abertas
        positions = exchange.fetch_positions(params={'category': 'linear', 'settleCoin': 'USDT'})
        
        closed_count = 0
        for p in positions:
            contracts = float(p.get('contracts', 0) or 0)
            if contracts > 0:
                symbol = p['symbol']
                side = p['side']
                # Para fechar um LONG, enviamos um SELL. Para um SHORT, um BUY.
                close_side = 'sell' if side.lower() == 'long' else 'buy'
                
                print(f"Fechando {symbol} ({side}) de {contracts} contratos...")
                
                # Ordem a mercado para fechar a posição
                exchange.create_order(
                    symbol=symbol,
                    type='market',
                    side=close_side,
                    amount=contracts,
                    params={'reduceOnly': True}
                )
                print(f"[OK] {symbol} fechado.")
                closed_count += 1
                time.sleep(0.5) # Pequeno delay entre ordens

        if closed_count == 0:
            print("Nenhuma posição para fechar.")
        else:
            print(f"\nSucesso: {closed_count} posições encerradas.")

    except Exception as e:
        print(f"Erro ao fechar posições: {e}")

if __name__ == "__main__":
    close_all_positions()
