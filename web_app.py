import os
import sys
import io

# Força UTF-8 globalmente (evita crash com emojis no Windows)
os.environ.setdefault('PYTHONUTF8', '1')
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import threading
from flask import Flask, render_template, jsonify, request
from core.connection import get_exchange, check_connection
from core.shared_state import bot_state, add_log
from core.balance_utils import get_unified_balance
from strategies.live_predictor import run_live_predictor
from strategies.sniper_leverage import run_sniper_leverage
from strategies.martingale_sniper import run_martingale_sniper
from strategies.trend_scalper import run_trend_scalper
from strategies.reverse_martingale import run_reverse_martingale
from strategies.reverse_martingale_pro import run_reverse_martingale_pro
from strategies.scalping_10x import run_scalping_10x
from strategies.survival_scalper import run_survival_scalper
from strategies.chameleon_strategy import run_chameleon_strategy
from strategies.fibonacci_retracement import run_fibonacci_strategy
import time
import logging
from datetime import datetime
import uuid

# Desativa os logs de GET 200 OK do Flask/Werkzeug
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

# Instância global da exchange
exchange = None

def init_exchange():
    """Inicializa a exchange e lê o saldo inicial."""
    global exchange
    exchange = get_exchange()
    if check_connection(exchange):
        # Lê o saldo real logo que o servidor inicia
        try:
            # Usa V5 direto para pegar a Equidade Total (saldo real completo em USD)
            resp = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
            account_data = resp.get('result', {}).get('list', [{}])[0]
            bot_state["usdt_balance"] = float(account_data.get('totalEquity', 0))
            
            coins = account_data.get('coin', [])
            for c in coins:
                if c.get('coin') == 'BTC':
                    bot_state["coin_balance"] = float(c.get('walletBalance') or 0)
                    bot_state["coin_name"] = "BTC"
            print(f"[OK] Saldo carregado: Total Equidade USD = ${bot_state['usdt_balance']:.2f}")
        except Exception as e:
            print(f"[AVISO] Não foi possível carregar saldo inicial: {e}")

@app.route('/')
def index():
    return render_template('index.html')

last_balance_update = 0

@app.route('/api/status')
def status():
    global exchange, last_balance_update
    import time
    now = time.time()
    
    if now - last_balance_update > 10:
        last_balance_update = now
        if not exchange:
            try:
                exchange = get_exchange()
            except:
                pass
        if exchange:
            try:
                # 1. Busca saldo UTA
                resp = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
                account_data = resp.get('result', {}).get('list', [{}])[0]
                bot_state["usdt_balance"] = float(account_data.get('totalEquity', 0))
                
                btc_found = False
                for c in account_data.get('coin', []):
                    if c.get('coin') == 'BTC':
                        bot_state["coin_balance"] = float(c.get('walletBalance') or 0)
                        bot_state["coin_name"] = "BTC"
                        btc_found = True
                if not btc_found:
                    bot_state["coin_balance"] = 0.0
                    bot_state["coin_name"] = "BTC"
                    
                # 2. Busca saldos de Funding para o dashboard
                funding_usdt = 0.0
                funding_btc = 0.0
                try:
                    raw_funding = exchange.fetch_balance({'type': 'funding'})
                    funding_usdt = float(raw_funding.get('total', {}).get('USDT', 0))
                    funding_btc = float(raw_funding.get('total', {}).get('BTC', 0))
                except:
                    try:
                        resp_fund = exchange.privateGetV5AssetTransferQueryAccountCoinsBalance({
                            'accountType': 'FUNDING',
                            'coin': 'USDT,BTC'
                        })
                        for c_data in resp_fund.get('result', {}).get('balance', []):
                            c_name = c_data.get('coin')
                            c_bal = float(c_data.get('walletBalance') or 0)
                            if c_name == 'USDT':
                                funding_usdt = c_bal
                            elif c_name == 'BTC':
                                funding_btc = c_bal
                    except:
                        pass
                
                bot_state["funding_usdt"] = funding_usdt
                bot_state["funding_btc"] = funding_btc
                
                # 3. Busca posições abertas reais para contar e somar PnL
                open_pos_count = 0
                total_unrealized_pnl = 0.0
                try:
                    pos_resp = exchange.fetch_positions()
                    for pos in pos_resp:
                        contracts = float(pos.get('contracts') or 0)
                        if contracts > 0:
                            open_pos_count += 1
                            total_unrealized_pnl += float(pos.get('unrealizedPnl') or 0)
                except Exception as pe:
                    pass
                
                bot_state["open_positions_count"] = open_pos_count
                bot_state["unrealized_pnl"] = total_unrealized_pnl
                
            except Exception as e:
                print(f"Erro ao atualizar saldos em background: {e}")
                
    return jsonify(bot_state)

@app.route('/api/balance')
def refresh_balance():
    """Rota para ler o saldo atual da Bybit a qualquer momento."""
    global exchange
    if not exchange:
        exchange = get_exchange()
    try:
        resp = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
        account_data = resp.get('result', {}).get('list', [{}])[0]
        
        total_equity = float(account_data.get('totalEquity', 0))
        bot_state["usdt_balance"] = total_equity
        
        coins = account_data.get('coin', [])
        result = {'USDT': total_equity} # Envia a equidade como USDT para a interface
        
        for c in coins:
            val = float(c.get('walletBalance') or 0)
            if val > 0:
                result[c['coin']] = val
                if c['coin'] == 'BTC':
                    bot_state["coin_balance"] = val
                    bot_state["coin_name"] = "BTC"
                    
        return jsonify({"balances": result, "status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/positions')
def get_positions():
    """Busca todas as posições abertas na Bybit."""
    global exchange
    if not exchange:
        exchange = get_exchange()
    try:
        # Busca posições linear (USDT Perpetuals)
        positions = exchange.fetch_positions(params={'category': 'linear', 'settleCoin': 'USDT'})
        open_positions = []
        for p in positions:
            if float(p.get('contracts', 0) or 0) > 0:
                info = p.get('info', {})
                liq_price = info.get('liqPrice') or p.get('liquidationPrice') or 0
                initial_margin = info.get('positionIM') or p.get('initialMargin') or 0
                unrealized_pnl = float(p.get('unrealizedPnl') or 0)
                mark_price = info.get('markPrice') or 0
                position_value = info.get('positionValue') or 0
                
                try:
                    margin_float = float(initial_margin)
                    roi = (unrealized_pnl / margin_float * 100) if margin_float > 0 else 0
                except:
                    roi = 0

                open_positions.append({
                    "symbol": p['symbol'],
                    "side": p['side'],
                    "contracts": p['contracts'],
                    "entryPrice": p['entryPrice'],
                    "unrealizedPnl": unrealized_pnl,
                    "leverage": p['leverage'],
                    "liquidationPrice": liq_price,
                    "percentage": roi,
                    "initialMargin": initial_margin,
                    "markPrice": mark_price,
                    "positionValue": position_value
                })
        return jsonify({"positions": open_positions, "status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/close_all', methods=['POST'])
def close_all():
    """Fecha todas as posições abertas imediatamente."""
    global exchange
    if not exchange:
        exchange = get_exchange()
    try:
        positions = exchange.fetch_positions(params={'category': 'linear', 'settleCoin': 'USDT'})
        closed = 0
        for p in positions:
            contracts = float(p.get('contracts', 0) or 0)
            if contracts > 0:
                close_side = 'sell' if p['side'].lower() == 'long' else 'buy'
                exchange.create_order(
                    symbol=p['symbol'],
                    type='market',
                    side=close_side,
                    amount=contracts,
                    params={'reduceOnly': True}
                )
                add_log(f"MANUAL: Posição {p['symbol']} fechada via Dashboard.")
                closed += 1
        return jsonify({"message": f"{closed} posições fechadas com sucesso.", "status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/close_symbol', methods=['POST'])
def close_symbol():
    """Fecha uma posição específica a mercado."""
    global exchange
    if not exchange:
        exchange = get_exchange()
    try:
        data = request.get_json() or {}
        symbol = data.get('symbol')
        if not symbol:
            return jsonify({"error": "Símbolo não fornecido"}), 400
            
        positions = exchange.fetch_positions(params={'category': 'linear', 'settleCoin': 'USDT'})
        for p in positions:
            if p['symbol'] == symbol:
                contracts = float(p.get('contracts', 0) or 0)
                if contracts > 0:
                    close_side = 'sell' if p['side'].lower() == 'long' else 'buy'
                    exchange.create_order(
                        symbol=p['symbol'],
                        type='market',
                        side=close_side,
                        amount=contracts,
                        params={'reduceOnly': True}
                    )
                    add_log(f"MANUAL: Posição {p['symbol']} fechada via Dashboard.")
                    return jsonify({"message": f"Posição de {symbol} fechada com sucesso.", "status": "ok"})
                    
        return jsonify({"message": f"Nenhuma posição ativa encontrada para {symbol}.", "status": "error"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/earn/balances')
def get_earn_balances():
    global exchange
    if not exchange:
        exchange = get_exchange()
    try:
        import json
        
        # 1. Busca saldo da conta Unificada (UTA)
        resp_unified = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
        account_unified = resp_unified.get('result', {}).get('list', [{}])[0]
        unified_total = float(account_unified.get('totalEquity', 0))
        
        unified_details = {'USDT': unified_total}
        for coin_info in account_unified.get('coin', []):
            coin_name = coin_info.get('coin')
            coin_bal = float(coin_info.get('walletBalance') or 0)
            if coin_bal > 0:
                unified_details[coin_name] = coin_bal
                
        # 2. Busca saldo da conta de Financiamento (Funding)
        funding_balance = {}
        try:
            raw_funding = exchange.fetch_balance({'type': 'funding'})
            for coin, balance_info in raw_funding.get('total', {}).items():
                if balance_info > 0:
                    funding_balance[coin] = balance_info
        except Exception as fe:
            print(f"Erro ao obter saldo funding via fetch_balance: {fe}")
            try:
                resp_fund = exchange.privateGetV5AssetTransferQueryAccountCoinsBalance({
                    'accountType': 'FUNDING',
                    'coin': 'USDT,BTC,ETH,SOL'
                })
                for c_data in resp_fund.get('result', {}).get('balance', []):
                    c_name = c_data.get('coin')
                    c_bal = float(c_data.get('walletBalance') or 0)
                    if c_bal > 0:
                        funding_balance[c_name] = c_bal
            except Exception as fe2:
                print(f"Erro ao obter saldo funding via implicit API: {fe2}")
                funding_balance = {'USDT': 0.0, 'BTC': 0.0, 'ETH': 0.0, 'SOL': 0.0}

        for c in ['USDT', 'BTC', 'ETH', 'SOL']:
            if c not in unified_details:
                unified_details[c] = 0.0
            if c not in funding_balance:
                funding_balance[c] = 0.0

        return jsonify({
            "unified": unified_details,
            "funding": funding_balance,
            "status": "ok"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/earn/transfer', methods=['POST'])
def execute_earn_transfer():
    global exchange
    if not exchange:
        exchange = get_exchange()
    try:
        data = request.json or {}
        coin = data.get('coin', 'USDT').upper()
        amount = float(data.get('amount', 0))
        direction = data.get('direction')
        
        if amount <= 0:
            return jsonify({"error": "Quantidade inválida"}), 400
            
        if direction == 'UNIFIED_TO_FUNDING':
            from_acc = 'unified'
            to_acc = 'funding'
            dir_text = "UTA ➡️ Financiamento"
        elif direction == 'FUNDING_TO_UNIFIED':
            from_acc = 'funding'
            to_acc = 'unified'
            dir_text = "Financiamento ➡️ UTA"
        else:
            return jsonify({"error": "Direção de transferência inválida"}), 400
            
        add_log(f"Iniciando transferência de {amount} {coin} ({dir_text})...")
        
        transfer_res = exchange.transfer(coin, amount, from_acc, to_acc)
        transfer_id = transfer_res.get('id') or 'N/A'
        add_log(f"Sucesso! Transferidos {amount} {coin} ({dir_text}). ID: {transfer_id}")
        
        return jsonify({"message": f"Transferência de {amount} {coin} concluída!", "status": "ok", "result": transfer_res})
    except Exception as e:
        err_msg = str(e)
        add_log(f"[ERRO] Falha na transferência: {err_msg}")
        return jsonify({"error": err_msg}), 500

@app.route('/api/earn/opportunities')
def get_earn_opportunities():
    opportunities = [
        {"id": "flexible_usdt", "name": "Flexible Savings (Poupança Flexível)", "coin": "USDT", "apy": 11.5, "type": "Flexível", "min_invest": 0.1},
        {"id": "flexible_usdc", "name": "Flexible Savings (Poupança Flexível)", "coin": "USDC", "apy": 8.5, "type": "Flexível", "min_invest": 0.1},
        {"id": "flexible_btc", "name": "Flexible Savings (Poupança Flexível)", "coin": "BTC", "apy": 1.5, "type": "Flexível", "min_invest": 0.0001},
        {"id": "flexible_eth", "name": "Flexible Savings (Poupança Flexível)", "coin": "ETH", "apy": 2.2, "type": "Flexível", "min_invest": 0.001},
        {"id": "flexible_sol", "name": "Flexible Savings (Poupança Flexível)", "coin": "SOL", "apy": 4.5, "type": "Flexível", "min_invest": 0.01},
        {"id": "dual_btc_1d", "name": "Dual Asset BTC/USDT (1 Dia)", "coin": "BTC", "apy": 120.0, "type": "Dual Asset", "min_invest": 0.005},
        {"id": "dual_eth_1d", "name": "Dual Asset ETH/USDT (1 Dia)", "coin": "ETH", "apy": 135.0, "type": "Dual Asset", "min_invest": 0.05},
    ]
    return jsonify({"opportunities": opportunities, "status": "ok"})

@app.route('/api/earn/investments')
def get_earn_investments():
    try:
        import json
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'earn_investments.json')
        if not os.path.exists(file_path):
            return jsonify({"investments": [], "status": "ok"})
        with open(file_path, 'r', encoding='utf-8') as f:
            investments = json.load(f)
        return jsonify({"investments": investments, "status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/earn/invest', methods=['POST'])
def invest_earn():
    global exchange
    if not exchange:
        exchange = get_exchange()
    try:
        import json
        import uuid
        data = request.json or {}
        product_id = data.get('product_id')
        product_name = data.get('product_name')
        coin = data.get('coin', 'USDT').upper()
        amount = float(data.get('amount', 0))
        apy = float(data.get('apy', 0))
        
        if amount <= 0:
            return jsonify({"error": "Quantidade inválida"}), 400
            
        add_log(f"Iniciando alocação em Earn: {amount} {coin} no {product_name}...")
        
        try:
            transfer_res = exchange.transfer(coin, amount, 'unified', 'funding')
            add_log(f"Transferido {amount} {coin} para carteira de Financiamento (Earn).")
        except Exception as te:
            add_log(f"[ERRO] Falha ao transferir fundos para Earn: {te}")
            return jsonify({"error": f"Erro de transferência Bybit: {te}"}), 500
            
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'earn_investments.json')
        investments = []
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                investments = json.load(f)
                
        new_inv = {
            "id": str(uuid.uuid4()),
            "product_id": product_id,
            "product_name": product_name,
            "coin": coin,
            "amount": amount,
            "apy": apy,
            "timestamp": int(time.time()),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        investments.append(new_inv)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(investments, f, indent=2, ensure_ascii=False)
            
        add_log(f"[SUCESSO] Investido {amount} {coin} em {product_name}!")
        
        return jsonify({"message": f"Investimento de {amount} {coin} realizado!", "status": "ok", "investment": new_inv})
    except Exception as e:
        err_msg = str(e)
        add_log(f"[ERRO FATAL] Falha ao investir: {err_msg}")
        return jsonify({"error": err_msg}), 500

@app.route('/api/earn/redeem', methods=['POST'])
def redeem_earn():
    global exchange
    if not exchange:
        exchange = get_exchange()
    try:
        import json
        data = request.json or {}
        investment_id = data.get('id')
        
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'earn_investments.json')
        if not os.path.exists(file_path):
            return jsonify({"error": "Investimento não encontrado"}), 404
            
        with open(file_path, 'r', encoding='utf-8') as f:
            investments = json.load(f)
            
        target_inv = None
        for inv in investments:
            if inv['id'] == investment_id:
                target_inv = inv
                break
                
        if not target_inv:
            return jsonify({"error": "Investimento não localizado"}), 404
            
        coin = target_inv['coin']
        amount = target_inv['amount']
        product_name = target_inv['product_name']
        
        add_log(f"Iniciando resgate de {amount} {coin} de {product_name}...")
        
        try:
            transfer_res = exchange.transfer(coin, amount, 'funding', 'unified')
            add_log(f"Transferido {amount} {coin} de volta para a carteira de Trade (UTA).")
        except Exception as te:
            add_log(f"[ERRO] Falha ao transferir fundos de volta: {te}")
            return jsonify({"error": f"Erro de transferência Bybit: {te}"}), 500
            
        investments = [inv for inv in investments if inv['id'] != investment_id]
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(investments, f, indent=2, ensure_ascii=False)
            
        add_log(f"[SUCESSO] Resgatado {amount} {coin} com sucesso!")
        
        return jsonify({"message": f"Resgate de {amount} {coin} concluído com sucesso!", "status": "ok"})
    except Exception as e:
        err_msg = str(e)
        add_log(f"[ERRO FATAL] Falha ao resgatar: {err_msg}")
        return jsonify({"error": err_msg}), 500

@app.route('/api/earn/auto-invest', methods=['POST'])
def auto_invest_earn():
    global exchange
    if not exchange:
        exchange = get_exchange()
    try:
        import json
        import uuid
        import time
        
        # 1. Tenta consolidar BRL se houver no Funding (move para UTA para trading)
        funding_brl = 0.0
        try:
            raw_funding = exchange.fetch_balance({'type': 'funding'})
            funding_brl = float(raw_funding.get('total', {}).get('BRL', 0))
        except:
            try:
                resp_fund = exchange.privateGetV5AssetTransferQueryAccountCoinsBalance({
                    'accountType': 'FUNDING',
                    'coin': 'BRL'
                })
                for c_data in resp_fund.get('result', {}).get('balance', []):
                    if c_data.get('coin') == 'BRL':
                        funding_brl = float(c_data.get('walletBalance') or 0)
            except:
                pass
                
        if funding_brl >= 5.0:
            add_log(f"[AUTO-INVEST] Identificado {funding_brl:.2f} BRL em Financiamento. Transferindo para Trade (UTA) para converter...")
            try:
                exchange.transfer('BRL', funding_brl, 'funding', 'unified')
                time.sleep(1.5)
            except Exception as e:
                add_log(f"[AUTO-INVEST AVISO] Não foi possível transferir BRL para UTA: {e}")
                
        # 2. Busca saldos iniciais na UTA
        resp_unified = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
        account_unified = resp_unified.get('result', {}).get('list', [{}])[0]
        
        unified_balances = {}
        for coin_info in account_unified.get('coin', []):
            coin_name = coin_info.get('coin')
            coin_bal = float(coin_info.get('walletBalance') or 0)
            if coin_bal > 0:
                unified_balances[coin_name] = coin_bal
                
        # 3. Se houver BRL >= 5.0 na UTA, converte automaticamente para USDT
        unified_brl = unified_balances.get('BRL', 0.0)
        if unified_brl >= 5.0:
            try:
                add_log(f"[AUTO-INVEST] Conversão automática ativa: Convertendo {unified_brl:.2f} BRL para USDT...")
                ticker = exchange.fetch_ticker('USDT/BRL')
                price = float(ticker['last'])
                amount_usdt = (unified_brl / price) * 0.985 # 1.5% margem de segurança para variação do book e taxas
                amount_precision = float(exchange.amount_to_precision('USDT/BRL', amount_usdt))
                
                if amount_precision > 0:
                    add_log(f"[AUTO-INVEST] Enviando ordem de mercado de compra: {amount_precision:.2f} USDT/BRL (Preço: {price:.4f})...")
                    order = exchange.create_order('USDT/BRL', 'market', 'buy', amount_precision)
                    add_log(f"[AUTO-INVEST] Conversão concluída! Comprados {amount_precision:.2f} USDT.")
                    time.sleep(2.0) # Espera sincronizar saldos
                    
                    # Atualiza novamente os saldos da UTA pós-conversão
                    resp_unified = exchange.privateGetV5AccountWalletBalance({'accountType': 'UNIFIED'})
                    account_unified = resp_unified.get('result', {}).get('list', [{}])[0]
                    unified_balances = {}
                    for coin_info in account_unified.get('coin', []):
                        coin_name = coin_info.get('coin')
                        coin_bal = float(coin_info.get('walletBalance') or 0)
                        if coin_bal > 0:
                            unified_balances[coin_name] = coin_bal
            except Exception as e:
                add_log(f"[AUTO-INVEST ERRO] Falha ao converter BRL para USDT: {e}")

        # 4. Lista de oportunidades de Earn com limites
        opps = {
            "USDT": {"id": "flexible_usdt", "name": "Flexible Savings (Poupança Flexível)", "apy": 11.5, "min_invest": 0.1},
            "USDC": {"id": "flexible_usdc", "name": "Flexible Savings (Poupança Flexível)", "apy": 8.5, "min_invest": 0.1},
            "BTC": {"id": "flexible_btc", "name": "Flexible Savings (Poupança Flexível)", "apy": 1.5, "min_invest": 0.0001},
            "ETH": {"id": "flexible_eth", "name": "Flexible Savings (Poupança Flexível)", "apy": 2.2, "min_invest": 0.001},
            "SOL": {"id": "flexible_sol", "name": "Flexible Savings (Poupança Flexível)", "apy": 4.5, "min_invest": 0.01}
        }
        
        invested_list = []
        errors_list = []
        
        add_log("[AUTO-INVEST] Analisando saldos elegíveis para investimento automático...")
        
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'earn_investments.json')
        investments = []
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                investments = json.load(f)
                
        # 5. Varre os saldos disponíveis e investe
        for coin, balance in unified_balances.items():
            if coin in opps:
                opp = opps[coin]
                if balance >= opp["min_invest"]:
                    add_log(f"[AUTO-INVEST] Identificado saldo de {balance:.8f} {coin} na UTA. Alocando automático...")
                    try:
                        transfer_res = exchange.transfer(coin, balance, 'unified', 'funding')
                        add_log(f"[AUTO-INVEST] Sucesso! Transferidos {balance:.8f} {coin} para carteira de Financiamento.")
                        
                        new_inv = {
                            "id": str(uuid.uuid4()),
                            "product_id": opp["id"],
                            "product_name": opp["name"],
                            "coin": coin,
                            "amount": balance,
                            "apy": opp["apy"],
                            "timestamp": int(time.time()),
                            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        investments.append(new_inv)
                        invested_list.append(f"{balance:.6f} {coin}")
                    except Exception as te:
                        err_msg = f"Falha na transferência de {coin}: {te}"
                        add_log(f"[AUTO-INVEST ERRO] {err_msg}")
                        errors_list.append(err_msg)
                else:
                    add_log(f"[AUTO-INVEST] Saldo de {balance:.8f} {coin} é inferior ao mínimo necessário ({opp['min_invest']} {coin}). Ignorado.")
                    
        if invested_list:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(investments, f, indent=2, ensure_ascii=False)
            msg = f"Investimento automático concluído para: {', '.join(invested_list)}."
        else:
            msg = "Nenhum saldo elegível de cripto/fiat encontrado para investimento automático."
            
        return jsonify({
            "status": "ok",
            "message": msg,
            "invested": invested_list,
            "errors": errors_list
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/history')
def get_history():
    import csv
    import glob
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    all_trades = []
    
    # Busca todos os arquivos CSV em logs
    csv_files = glob.glob(os.path.join(log_dir, '*.csv'))
    for file_path in csv_files:
        if 'market_data' in file_path or 'trend_history' in file_path:
            continue # Ignora arquivos de log de mercado
            
        strategy_name = os.path.basename(file_path).replace('.csv', '').replace('_trades', '').capitalize()
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Normalização de nomes de colunas
                    tipo = (row.get('Tipo') or row.get('Action') or '').upper()
                    if tipo == 'SCAN':
                        continue
                        
                    data_hora = row.get('Data/Hora') or row.get('Timestamp') or ''
                    if not data_hora: continue
                    
                    moeda = row.get('Moeda') or row.get('Symbol') or '-'
                    direcao = row.get('Direção') or row.get('Side') or '-'
                    preco = row.get('Preço') or row.get('Entry_Price') or '-'
                    valor = row.get('Valor ($)') or row.get('Quantidade') or row.get('Tamanho $') or row.get('Size') or '-'
                    status = row.get('Status') or '-'
                    detalhes = row.get('Detalhes') or row.get('Reason') or '-'
                    alavancagem = row.get('Alavancagem', '-')
                    
                    pnl = row.get('PnL $') or row.get('PnL_USDT')
                    lucro = '-'
                    if pnl and pnl not in ['0', '0.0', '0.00']:
                        try:
                            lucro = f"${float(pnl):+.4f}"
                        except:
                            lucro = pnl
                    elif tipo in ['SAÍDA', 'SAIDA', 'CLOSE'] or 'WIN' in status or 'LOSS' in status or 'LUCRO' in status or 'META' in status:
                        if detalhes.startswith('+$') or detalhes.startswith('-$'):
                            lucro = detalhes
                        elif detalhes.startswith('$+') or detalhes.startswith('$-'):
                            lucro = detalhes.replace('$+', '+$').replace('$-', '-$')
                        elif 'Lucro:' in detalhes:
                            lucro = detalhes.split('Lucro:')[1].strip()
                            
                    trade = {
                        'data': data_hora,
                        'estrategia': strategy_name,
                        'moeda': moeda,
                        'tipo': tipo,
                        'direcao': direcao,
                        'preco': preco,
                        'valor': valor,
                        'alavancagem': alavancagem,
                        'status': status,
                        'detalhes': detalhes,
                        'lucro': lucro
                    }
                    all_trades.append(trade)
        except Exception as e:
            print(f"Erro lendo {file_path}: {e}")
            
    # Ordena da mais recente para a mais antiga
    all_trades.sort(key=lambda x: x['data'], reverse=True)
    
    return jsonify({"history": all_trades, "status": "ok"})

@app.route('/api/start', methods=['POST'])
def start_bot():
    global exchange
    
    if bot_state["is_running"]:
        return jsonify({"message": "Bot já está rodando!"}), 400
        
    if not exchange:
        exchange = get_exchange()
        if not check_connection(exchange):
            add_log("Falha ao conectar na Bybit. Verifique as credenciais.")
            return jsonify({"message": "Erro de conexão"}), 500
            
    bot_state["logs"] = [] # Limpa logs antigos
    
    data = request.get_json() or {}
    strategy = data.get('strategy', 'spot')
    symbol = data.get('symbol', 'BTC/USDT:USDT')
    
    estrategias_multi = ['survival', 'reverse_martingale', 'scalping_10x', 'sniper', 'chameleon', 'fibonacci']
    if symbol == 'MULTI' and strategy not in estrategias_multi:
        add_log(f"⚠️ A estratégia '{strategy}' não suporta MULTI. Usando BTC por padrão.")
        symbol = 'BTC/USDT:USDT'
    
    if strategy == 'sniper':
        add_log(f"Comando de INICIAR SNIPER recebido para {symbol}...")
        thread = threading.Thread(target=run_sniper_leverage, args=(exchange, symbol))
    elif strategy == 'martingale':
        add_log(f"Comando de INICIAR MARTINGALE recebido para {symbol}...")
        thread = threading.Thread(target=run_martingale_sniper, args=(exchange, symbol))
    elif strategy == 'trend':
        add_log(f"Comando de INICIAR TREND SCALPER recebido para {symbol}...")
        thread = threading.Thread(target=run_trend_scalper, args=(exchange, symbol))
    elif strategy == 'reverse_martingale':
        add_log(f"Comando de INICIAR REVERSE MARTINGALE PRO recebido para {symbol}...")
        thread = threading.Thread(target=run_reverse_martingale_pro, args=(exchange, symbol))
    elif strategy == 'scalping_10x':
        add_log(f"Comando de INICIAR SCALPING 10X recebido para {symbol}...")
        thread = threading.Thread(target=run_scalping_10x, args=(exchange, symbol))
    elif strategy == 'survival':
        add_log(f"Comando de INICIAR SURVIVAL SCALPER recebido para {symbol}...")
        thread = threading.Thread(target=run_survival_scalper, args=(exchange, symbol))
    elif strategy == 'longshort':
        from strategies.hybrid_long_short import run_hybrid_long_short
        add_log(f"Comando de INICIAR LONG/SHORT HÍBRIDO recebido para {symbol}...")
        thread = threading.Thread(target=run_hybrid_long_short, args=(exchange, symbol))
    elif strategy == 'longshort_lev':
        from strategies.hybrid_long_short_leverage import run_leveraged_long_short
        add_log(f"Comando de INICIAR LONG/SHORT ALAVANCADO recebido para {symbol}...")
        thread = threading.Thread(target=run_leveraged_long_short, args=(exchange, symbol))
    elif strategy == 'double7':
        from strategies.double_in_7_days import run_double_7
        add_log(f"Comando de INICIAR DOBRAR EM 7 DIAS recebido para {symbol}...")
        thread = threading.Thread(target=run_double_7, args=(exchange, symbol))
    elif strategy == 'chameleon':
        # Garante formato linear perpetual (ex: ETH/USDT -> ETH/USDT:USDT)
        if symbol != 'MULTI' and ':' not in symbol:
            symbol = symbol.split('/')[0] + '/USDT:USDT'
        add_log(f"Comando de INICIAR CAMALEÃO recebido para {symbol}...")
        thread = threading.Thread(target=run_chameleon_strategy, args=(exchange, symbol))
    elif strategy == 'fibonacci':
        # Garante formato linear perpetual (ex: ETH/USDT -> ETH/USDT:USDT)
        if symbol != 'MULTI' and ':' not in symbol:
            symbol = symbol.split('/')[0] + '/USDT:USDT'
        add_log(f"Comando de INICIAR FIBONACCI recebido para {symbol}...")
        thread = threading.Thread(target=run_fibonacci_strategy, args=(exchange, symbol))
    else:
        add_log(f"Comando de INICIAR SPOT recebido para {symbol}...")
        thread = threading.Thread(target=run_live_predictor, args=(exchange, symbol))
        
    thread.daemon = True
    thread.start()
    
    return jsonify({"message": "Bot iniciado com sucesso"})

@app.route('/api/stop', methods=['POST'])
def stop_bot():
    if not bot_state["is_running"]:
        return jsonify({"message": "Bot já está parado."}), 400
        
    add_log("Comando de PARAR recebido. Aguardando ciclo terminar...")
    bot_state["is_running"] = False
    
    return jsonify({"message": "Bot está sendo desligado..."})

if __name__ == '__main__':
    print("Iniciando Servidor Web do Bot...")
    print("Conectando na Bybit e carregando saldo...")
    init_exchange()
    print("Acesse http://127.0.0.1:5000 no seu navegador!")
    app.run(host='127.0.0.1', port=5000, debug=False)
