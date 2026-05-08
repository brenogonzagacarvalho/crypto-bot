def get_unified_balance(exchange, coin='USDT'):
    """
    Busca saldo na conta Unified Trading Account (UTA) da Bybit via API V5 direta.
    """
    # Tentativa 1: API V5 direta - mais confiável para UTA
    try:
        resp = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
        account_data = resp.get('result', {}).get('list', [{}])[0]
        
        # Se for USDT, a equidade total é a representação mais real do saldo na Bybit UTA
        if coin == 'USDT' and account_data.get('totalEquity'):
            return float(account_data.get('totalEquity'))
            
        coins = account_data.get('coin', [])
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


def get_available_margin_usd(exchange):
    """
    Retorna o saldo REAL disponível para abrir posições de Futuros (Derivativos)
    na conta UTA da Bybit. Usa o campo 'totalAvailableBalance' que já considera
    haircuts e margens travadas.
    """
    try:
        resp = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
        account = resp.get('result', {}).get('list', [{}])[0]
        
        total_equity = float(account.get('totalEquity', 0))
        
        # Tenta pegar o available. Se a Bybit reportar 0 (comum para BTC não-colateralizado explicitamente), usamos a equidade
        available = float(account.get('totalAvailableBalance') or 0)
        if available <= 0.01 and total_equity > 0:
            available = total_equity
            
        return available, total_equity
    except Exception as e:
        from core.shared_state import add_log
        add_log(f"Falha de conexão com a API de saldo: {e}")
        return None, None


def enable_btc_collateral(exchange):
    """
    Habilita BTC como moeda de colateral para Derivativos na Bybit UTA.
    Sem isso, o BTC na carteira NÃO pode ser usado como margem para Futuros.
    """
    try:
        exchange.privatePostV5AccountSetCollateralSwitch({
            'coin': 'BTC',
            'collateralSwitch': 'ON'
        })
        return True
    except Exception as e:
        # Se já estiver habilitado, ignora o erro
        return False


def place_maker_entry(exchange, symbol, side, amount, price, tp_price, sl_price, max_wait=15):
    """
    Coloca uma ordem Limit PostOnly (taxa maker 0.02%) com TP e SL embutidos.
    
    - PostOnly garante que a ordem vai para o livro como maker
    - Se não preencher em max_wait segundos, cancela
    - Retorna (order, filled) - order é o dict, filled é True/False
    
    Args:
        side: 'buy' ou 'sell'
        price: preço limite (usar preço de mercado atual)
        tp_price: take profit
        sl_price: stop loss
        max_wait: tempo máximo de espera em segundos
    """
    import time
    
    params = {
        'timeInForce': 'PostOnly',
        'takeProfit': str(tp_price),
        'stopLoss': str(sl_price),
    }
    
    try:
        try:
            # Formata amount e price para a precisão correta da exchange
            market = exchange.market(symbol)
            min_amount = market['limits']['amount']['min']
            
            # Garante que o amount não seja menor que o mínimo antes de formatar
            if amount < min_amount:
                amount = min_amount
                
            amount = float(exchange.amount_to_precision(symbol, amount))
            price = float(exchange.price_to_precision(symbol, price))
            
            # Check secundário após amount_to_precision (que pode arredondar para baixo)
            if amount < min_amount:
                amount = min_amount
        except:
            pass
            
        order = exchange.create_order(
            symbol=symbol,
            type='limit',
            side=side,
            amount=amount,
            price=price,
            params=params
        )
        
        order_id = order.get('id')
        if not order_id:
            return order, False
        
        # Aguarda preenchimento
        for i in range(max_wait):
            time.sleep(1)
            try:
                status = exchange.fetch_order(order_id, symbol)
                order_status = status.get('status', '')
                
                if order_status == 'closed':
                    return status, True  # Preenchida!
                elif order_status == 'canceled' or order_status == 'cancelled':
                    return status, False  # PostOnly rejeitada (seria taker)
                elif order_status == 'rejected':
                    return status, False
            except:
                continue
        
        # Timeout: cancela a ordem
        try:
            exchange.cancel_order(order_id, symbol)
        except:
            pass
        
        return order, False
        
    except Exception as e:
        from core.shared_state import add_log
        err_msg = str(e)
        if "110007" in err_msg or "ab not enough" in err_msg:
            add_log(f"⚠️ Saldo Insuficiente ({symbol}): O lote mínimo exige mais margem do que o saldo atual.")
        else:
            add_log(f"⚠️ Erro ao colocar ordem Maker ({symbol}): {e}")
        return None, False

def get_closed_pnl(exchange, symbol, limit=1):
    """
    Busca o PnL exato da última posição fechada usando a API V5 da Bybit.
    Inclui todas as taxas (funding, taker/maker fees).
    """
    try:
        # ccxt formata symbol como 'BTC/USDT:USDT' mas a Bybit espera 'BTCUSDT' (ccxt normalmente traduz, mas para chamadas diretas pode precisar do id)
        market = exchange.market(symbol)
        bybit_symbol = market['id'] if market else symbol.replace('/', '').split(':')[0]
        
        resp = exchange.privateGetV5PositionClosedPnl({
            'category': 'linear',
            'symbol': bybit_symbol,
            'limit': limit
        })
        closed_list = resp.get('result', {}).get('list', [])
        if closed_list:
            return float(closed_list[0].get('closedPnl', 0))
    except Exception as e:
        from core.shared_state import add_log
        add_log(f"⚠️ Erro ao buscar PnL fechado: {e}")
    return 0.0
