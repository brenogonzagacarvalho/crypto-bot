import sys
import os
import ccxt
import json

sys.path.append('c:/Users/Carvalho/Dev/ganharDolar/crypto-bot')

from bybit_bot import connect_to_bybit

try:
    exchange = connect_to_bybit()
    print("Testing closed PNL fetch for DOGE/USDT...")
    # Fetch using CCXT's V5 endpoint mapped function
    resp = exchange.privateGetV5PositionClosedPnl({
        'category': 'linear',
        'symbol': 'DOGEUSDT',
        'limit': 3
    })
    print(json.dumps(resp, indent=2))
except Exception as e:
    print("Error:", e)
