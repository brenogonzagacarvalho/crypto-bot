import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_current_price

def run_grid_trading_simulated(exchange, symbol='BTC/USDT', grids=5, grid_spacing=0.01):
    """
    Simula um Grid Trading simples.
    grid_spacing = 0.01 significa 1% de distância entre as ordens.
    """
    print(f"\n[GRID TRADING - SIMULAÇÃO] Iniciando malha para {symbol}")
    print("Calculando o centro do Grid com o preço atual...")
    
    initial_price = fetch_current_price(exchange, symbol)
    if not initial_price:
        print("Erro ao obter preço inicial.")
        return
        
    print(f"Preço Central: ${initial_price:.2f}")
    
    # Gera a malha de preços
    buy_orders = []
    sell_orders = []
    
    for i in range(1, grids + 1):
        # Calcula N% abaixo
        buy_price = initial_price * (1 - (grid_spacing * i))
        buy_orders.append(buy_price)
        
        # Calcula N% acima
        sell_price = initial_price * (1 + (grid_spacing * i))
        sell_orders.append(sell_price)
        
    print("\n--- Ordens de Venda (Limit) que seriam criadas ---")
    for price in reversed(sell_orders):
        print(f"Vender a: ${price:.2f}")
        
    print("-------------------------------------------------")
    print(f"Preço Atual: ${initial_price:.2f}")
    print("-------------------------------------------------")
    
    print("--- Ordens de Compra (Limit) que seriam criadas ---")
    for price in buy_orders:
        print(f"Comprar a: ${price:.2f}")
        
    print("\nNo modo real, o bot deixaria essas ordens posicionadas no livro de ofertas (Order Book).")
    print("O grid só funciona bem se houver saldo suficiente na corretora para suportar todas essas ordens simultâneas.")
    print("Simulação concluída. (Nenhuma ordem real foi enviada).")
