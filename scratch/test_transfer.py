import ccxt
import os
import sys
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('BYBIT_API_KEY')
api_secret = os.getenv('BYBIT_API_SECRET')

if not api_key or not api_secret:
    print("API keys not found in .env")
    sys.exit(1)

exchange = ccxt.bybit({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'options': {
        'adjustForTimeDifference': True,
    }
})

exchange.verbose = True

print("--- TESTING LOWERCASE transfer('USDT', 0.1, 'unified', 'funding') ---")
try:
    res = exchange.transfer('USDT', 0.1, 'unified', 'funding')
    print("Success:", res)
except Exception as e:
    print("Failed:", e)

print("\n--- TESTING UPPERCASE transfer('USDT', 0.1, 'UNIFIED', 'FUNDING') ---")
try:
    res = exchange.transfer('USDT', 0.1, 'UNIFIED', 'FUNDING')
    print("Success:", res)
except Exception as e:
    print("Failed:", e)
