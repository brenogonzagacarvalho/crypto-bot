def get_unified_balance(exchange, coin='USDT'):
    """
    Busca saldo na conta Unified Trading Account (UTA) da Bybit via API V5 direta.
    """
    # Tentativa 1: API V5 direta - mais confiável para UTA
    try:
        resp = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
        coins = resp.get('result', {}).get('list', [{}])[0].get('coin', [])
        for c in coins:
            if c.get('coin') == coin:
                # availableToWithdraw é o saldo livre para operar
                val = c.get('availableToWithdraw') or c.get('walletBalance') or '0'
                return float(val)
    except:
        pass

    # Tentativa 2: Endpoints ccxt padrão
    account_types = ['unified', 'swap', 'contract', 'spot']
    for acc_type in account_types:
        try:
            balance = exchange.fetch_balance({'type': acc_type})
            val = balance.get('free', {}).get(coin)
            if val is not None and float(val) > 0:
                return float(val)
        except:
            continue

    return 0.0

