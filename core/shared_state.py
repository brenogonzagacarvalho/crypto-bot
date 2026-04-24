from datetime import datetime

# Dicionário em memória para compartilhar dados entre a Thread do Bot e a Thread do Servidor Flask
bot_state = {
    "is_running": False,
    "status": "🔴 Desligado",
    "current_price": 0.0,
    "rsi": 0.0,
    "rsi_status": "Neutro",
    "coin_name": "BTC",
    "coin_balance": 0.0,
    "usdt_balance": 0.0,
    "logs": []
}

def add_log(message):
    """Adiciona um log com data e hora ao estado global"""
    timestamp = datetime.now().strftime('%H:%M:%S')
    log_entry = f"[{timestamp}] {message}"
    
    print(log_entry) # Mantém o print no terminal também
    
    bot_state["logs"].append(log_entry)
    
    # Mantém apenas os últimos 30 logs para não pesar a memória
    if len(bot_state["logs"]) > 30:
        bot_state["logs"].pop(0)
