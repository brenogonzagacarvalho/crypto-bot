import sys
from core.connection import get_exchange, check_connection
from strategies.alerts import run_alerts
from strategies.trend_algo import run_trend_following_simulated
from strategies.grid_algo import run_grid_trading_simulated
from strategies.live_predictor import run_live_predictor

def show_menu():
    print("\n===================================")
    print("🤖 MENU DO BOT DE CRIPTO (BYBIT)")
    print("===================================")
    print("1. Iniciar Alertas de Preço")
    print("2. Iniciar Trend Following (1 Minuto + Gravar CSV)")
    print("3. Iniciar Grid Trading (Modo Simulação)")
    print("4. ⚠️ Bot LIVE: Previsão e Transações REAIS")
    print("5. Sair")
    print("===================================")
    
    choice = input("Escolha a estratégia desejada (1-5): ")
    return choice

def main():
    print("Iniciando Bot...")
    exchange = get_exchange()
    
    if not check_connection(exchange):
        return
        
    while True:
        choice = show_menu()
        
        symbol = 'BTC/USDT'
        
        if choice == '1':
            try:
                target_h = float(input("Qual o preço alvo para Alta (Ex: 70000)? [Deixe vazio para pular]: ") or 0)
                target_l = float(input("Qual o preço alvo para Baixa (Ex: 60000)? [Deixe vazio para pular]: ") or 0)
                
                run_alerts(
                    exchange, 
                    symbol=symbol, 
                    target_high=target_h if target_h > 0 else None, 
                    target_low=target_l if target_l > 0 else None
                )
            except ValueError:
                print("Valor inválido. Tente novamente.")
                
        elif choice == '2':
            print("\nAviso: O Trend Following requer buscar dezenas de candles do histórico, aguarde...")
            run_trend_following_simulated(exchange, symbol=symbol)
            
        elif choice == '3':
            run_grid_trading_simulated(exchange, symbol=symbol)
            
        elif choice == '4':
            print("\n🚨 AVISO: MODO LIVE ATIVADO! Dinheiro real será movimentado.")
            run_live_predictor(exchange, symbol=symbol)
            
        elif choice == '5':
            print("Encerrando bot. Até mais!")
            sys.exit(0)
        else:
            print("Opção inválida. Escolha entre 1 e 5.")

if __name__ == '__main__':
    main()
