import time
import sys
import os

# Adiciona a raiz do projeto ao path para conseguir importar o core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.market_data import fetch_current_price

def run_alerts(exchange, symbol='BTC/USDT', target_high=None, target_low=None, check_interval=10):
    """
    Monitora o preço e emite alertas no console se os limites forem atingidos.
    """
    print(f"\n[ALERTA] Iniciando monitoramento para {symbol}")
    if target_high:
        print(f" - Alerta de Alta configurado para: ${target_high}")
    if target_low:
        print(f" - Alerta de Baixa configurado para: ${target_low}")
    print("Pressione Ctrl+C para parar.\n")
    
    try:
        while True:
            current_price = fetch_current_price(exchange, symbol)
            
            if current_price is None:
                time.sleep(check_interval)
                continue
                
            print(f"Preço atual {symbol}: ${current_price:.2f}")
            
            if target_high and current_price >= target_high:
                print(f"🔔 ALERTA DE ALTA! {symbol} rompeu ${target_high}! Preço atual: ${current_price}")
                # Beep sonoro (funciona no terminal Windows)
                print('\a')
                
            if target_low and current_price <= target_low:
                print(f"🔔 ALERTA DE BAIXA! {symbol} caiu abaixo de ${target_low}! Preço atual: ${current_price}")
                print('\a')
                
            time.sleep(check_interval)
            
    except KeyboardInterrupt:
        print("\nMonitoramento de alertas finalizado pelo usuário.")
