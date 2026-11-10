import sys
from core.connection import get_exchange, check_connection
from strategies.claude_quant_alpha import run_claude_quant_alpha
from strategies.grok_whale_flow import run_grok_whale_flow
from strategies.chameleon_strategy import run_chameleon_strategy
from strategies.fibonacci_retracement import run_fibonacci_strategy
from strategies.vwap_deviation_scalper import run_vwap_deviation_strategy
from strategies.daily_range_scalper import run_daily_range_strategy
from strategies.live_predictor import run_live_predictor


def show_menu():
    print("\n====================================================")
    print("🤖 BYBIT QUANT DESK CLI (SKILLS CLAUDE & GROK)")
    print("====================================================")
    print("1. 🤖 Claude Quant Alpha (TTM Squeeze + MTF + VWAP)")
    print("2. 🧠 Grok Whale Flow (Order Book Imbalance + Squeeze)")
    print("3. 🦎 Camaleão Quant (Regime Adaptativo 3M)")
    print("4. 📐 Retração Fibonacci 61.8% (OTF Golden Pocket)")
    print("5. 🌊 VWAP Z-Score Mean Reversion")
    print("6. 📐 Liquidez Diária (PDH/PDL Sweep)")
    print("7. 🛡️ Spot Predictor (Sem Alavancagem)")
    print("8. Sair")
    print("====================================================")

    return input("Escolha a estratégia desejada (1-8): ").strip()


def main():
    print("Iniciando Quant Desk CLI...")
    exchange = get_exchange()

    if not check_connection(exchange):
        return

    while True:
        choice = show_menu()
        if choice == '8':
            print("Encerrando bot. Até mais!")
            sys.exit(0)

        coin = input("Moeda ou MULTI [Padrão: MULTI]: ").strip().upper() or "MULTI"
        symbol = "MULTI" if coin == "MULTI" else f"{coin}/USDT:USDT"

        if choice == '1':
            run_claude_quant_alpha(exchange, symbol=symbol)
        elif choice == '2':
            run_grok_whale_flow(exchange, symbol=symbol)
        elif choice == '3':
            run_chameleon_strategy(exchange, symbol=symbol)
        elif choice == '4':
            run_fibonacci_strategy(exchange, symbol=symbol)
        elif choice == '5':
            run_vwap_deviation_strategy(exchange, symbol=symbol)
        elif choice == '6':
            run_daily_range_strategy(exchange, symbol=symbol)
        elif choice == '7':
            spot_sym = "BTC/USDT" if coin == "MULTI" else f"{coin}/USDT"
            run_live_predictor(exchange, symbol=spot_sym)
        else:
            print("Opção inválida. Escolha entre 1 e 8.")


if __name__ == '__main__':
    main()
