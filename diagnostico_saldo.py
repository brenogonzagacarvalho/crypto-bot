"""
Script de Diagnóstico: Encontra onde está o saldo na Bybit Unified Account
Execute com: python diagnostico_saldo.py
"""
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import ccxt

exchange = ccxt.bybit({
    'apiKey': os.getenv('BYBIT_API_KEY'),
    'secret': os.getenv('BYBIT_API_SECRET'),
    'enableRateLimit': True,
    'options': {
        'adjustForTimeDifference': True,
    }
})

print("=" * 60)
print("  DIAGNOSTICO DE SALDO - BYBIT UNIFIED ACCOUNT")
print("=" * 60)

account_types = ['unified', 'swap', 'contract', 'future', 'spot', 'funding']

for acc_type in account_types:
    try:
        balance = exchange.fetch_balance({'type': acc_type})
        usdt = balance.get('free', {}).get('USDT', 0) or 0
        btc = balance.get('free', {}).get('BTC', 0) or 0
        sol = balance.get('free', {}).get('SOL', 0) or 0
        
        if usdt > 0 or btc > 0 or sol > 0:
            print(f"\n[ENCONTRADO] Saldo em tipo '{acc_type}':")
            print(f"   USDT: {usdt}")
            print(f"   BTC:  {btc}")
            print(f"   SOL:  {sol}")
        else:
            print(f"[VAZIO] Tipo '{acc_type}': Zerado.")
    except Exception as e:
        print(f"[ERRO] Tipo '{acc_type}': {str(e)[:100]}")

print("\n--- Tentando API V5 Direta (Unified) ---")
try:
    resp = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
    coins = resp.get('result', {}).get('list', [{}])[0].get('coin', [])
    for coin in coins:
        if float(coin.get('walletBalance', 0)) > 0:
            print(f"[V5 UNIFIED] {coin['coin']}: {coin.get('walletBalance')}")
except Exception as e:
    print(f"[ERRO V5]: {str(e)[:100]}")

print("\n" + "=" * 60)
input("Pressione ENTER para fechar...")
