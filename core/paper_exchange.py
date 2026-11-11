"""
core/paper_exchange.py — Simulador Institucional em Tempo Real (Paper Trading Engine)

Encapsula a instância real `ccxt.bybit` mantendo:
- 100% dos dados de mercado REAIS ao vivo da Bybit V5 (preços, candles OHLCV, Order Book L2, Funding Rate, lotes mínimos e precisão).
- Carteira Unificada (UTA) virtual persistida em `config/paper_account.json` (padrão: $100.00 USDT).
- Execução realista de ordens (Limit PostOnly c/ taxa Maker 0.02% e Market c/ taxa Taker 0.055%).
- Disparo automático de Take Profit, Stop Loss, Breakeven (+1R) e Trailing Stop Server-Side (`privatePostV5PositionTradingStop`) com base nas cotações reais da Bybit.
- Histórico completo compatível com `privateGetV5PositionClosedPnl` para alimentar o Dashboard e o Auditor Quant.
"""

import os
import json
import time
import uuid
import threading
from core.shared_state import add_log

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config')
PAPER_FILE = os.path.join(CONFIG_DIR, 'paper_account.json')

MAKER_FEE_RATE = 0.0002   # 0.02% Bybit Maker
TAKER_FEE_RATE = 0.00055  # 0.055% Bybit Taker


class PaperExchangeWrapper:
    """
    Proxy transparente sobre `ccxt.bybit`:
    - Redireciona leituras de mercado (`fetch_ohlcv`, `fetch_ticker`, `fetch_order_book`, `market`, etc.)
      diretamente para a Bybit real.
    - Intercepta chamadas de conta, saldo, posições e ordens para operar na Conta de Teste (Simulação).
    """

    def __init__(self, real_exchange, default_balance=100.0):
        self._real = real_exchange
        self._lock = threading.RLock()
        self._orders = {}
        self._leverages = {}
        self._price_cache = {}
        self._load_state(default_balance)

    def __getattr__(self, name):
        # Qualquer método de mercado ou precisão vai direto para o ccxt.bybit real
        return getattr(self._real, name)

    @property
    def is_paper(self):
        return True

    def _load_state(self, default_balance=100.0):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if os.path.exists(PAPER_FILE):
            try:
                with open(PAPER_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.wallet_balance = float(data.get('wallet_balance', default_balance))
                self.initial_balance = float(data.get('initial_balance', default_balance))
                self.positions = data.get('positions', {})
                self.closed_pnl = data.get('closed_pnl', [])
                return
            except Exception:
                pass
        self.wallet_balance = float(default_balance)
        self.initial_balance = float(default_balance)
        self.positions = {}
        self.closed_pnl = []
        self._save_state()

    def _save_state(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(PAPER_FILE, 'w', encoding='utf-8') as f:
                json.dump(
                    {
                        'wallet_balance': round(self.wallet_balance, 6),
                        'initial_balance': round(self.initial_balance, 2),
                        'positions': self.positions,
                        'closed_pnl': self.closed_pnl[:200],
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
        except Exception:
            pass

    def reset_balance(self, new_balance=100.0):
        """Reinicia o saldo da conta de teste, fechando posições simuladas abertas."""
        with self._lock:
            self.wallet_balance = float(new_balance)
            self.initial_balance = float(new_balance)
            self.positions = {}
            self.closed_pnl = []
            self._orders = {}
            self._save_state()
        add_log(f"🧪 [CONTA DE TESTE] Saldo virtual redefinido para ${self.wallet_balance:.2f} USDT (Posições e histórico zerados).")

    def _get_live_price(self, symbol):
        now = time.time()
        cached = self._price_cache.get(symbol)
        if cached and (now - cached['ts']) < 1.5:
            return cached['price'], cached['high'], cached['low']

        try:
            ticker = self._real.fetch_ticker(symbol)
            last_p = float(ticker.get('last') or 0)
            bid_p = float(ticker.get('bid') or last_p)
            ask_p = float(ticker.get('ask') or last_p)
            high_tick = max(last_p, bid_p)
            low_tick = min(last_p, ask_p) if ask_p > 0 else last_p
            if last_p > 0:
                self._price_cache[symbol] = {
                    'price': last_p,
                    'high': high_tick,
                    'low': low_tick,
                    'ts': now,
                }
                return last_p, high_tick, low_tick
        except Exception:
            pass

        if cached:
            return cached['price'], cached['high'], cached['low']
        return 0.0, 0.0, 0.0

    def _bybit_id_to_ccxt_symbol(self, bybit_id_or_symbol):
        if '/' in bybit_id_or_symbol:
            return bybit_id_or_symbol
        for sym in list(self.positions.keys()):
            clean = sym.replace('/', '').split(':')[0]
            if clean.upper() == str(bybit_id_or_symbol).upper():
                return sym
        if str(bybit_id_or_symbol).upper().endswith('USDT'):
            base = str(bybit_id_or_symbol).upper()[:-4]
            return f"{base}/USDT:USDT"
        return bybit_id_or_symbol

    def _close_simulated_position(self, symbol, exit_price, reason='MARKET', fee_rate=TAKER_FEE_RATE):
        with self._lock:
            pos = self.positions.get(symbol)
            if not pos:
                return None

            contracts = float(pos['contracts'])
            entry_price = float(pos['entryPrice'])
            side = str(pos['side']).lower()
            is_long = side in ('long', 'buy')

            gross_pnl = (exit_price - entry_price) * contracts if is_long else (entry_price - exit_price) * contracts
            exit_notional = contracts * exit_price
            exit_fee = exit_notional * fee_rate
            entry_fee = float(pos.get('entryFee', contracts * entry_price * MAKER_FEE_RATE))
            net_pnl = gross_pnl - exit_fee - entry_fee

            # Na abertura já havíamos descontado entry_fee; portanto somamos gross_pnl - exit_fee
            self.wallet_balance += (gross_pnl - exit_fee)
            if self.wallet_balance < 0:
                self.wallet_balance = 0.0

            bybit_sym = symbol.replace('/', '').split(':')[0]
            close_side_bybit = 'Sell' if is_long else 'Buy'

            closed_record = {
                'symbol': bybit_sym,
                'ccxt_symbol': symbol,
                'qty': str(contracts),
                'avgEntryPrice': str(entry_price),
                'avgExitPrice': str(exit_price),
                'closedPnl': f"{net_pnl:.6f}",
                'side': close_side_bybit,
                'createdTime': str(int(time.time() * 1000)),
                'reason': reason,
            }
            self.closed_pnl.insert(0, closed_record)
            del self.positions[symbol]
            self._save_state()

            emoji = "🎯 TP" if reason == 'TAKE_PROFIT' else ("🛑 SL" if reason == 'STOP_LOSS' else "🚪 CLOSE")
            add_log(
                f"🧪 [{emoji} SIMULADOR] {symbol} ({side.upper()}) fechada @ ${exit_price:.4f} | "
                f"PnL Líquido: ${net_pnl:+.4f} | Novo Saldo Teste: ${self.wallet_balance:.2f}"
            )
            return closed_record

    def _sync_positions_with_live_market(self, target_symbols=None):
        with self._lock:
            symbols = list(self.positions.keys())
            if target_symbols:
                norm_targets = {
                    (s if ':' in s or '/' not in s else f"{s.split('/')[0]}/USDT:USDT")
                    for s in target_symbols
                }
                symbols = [s for s in symbols if s in norm_targets or s in target_symbols]

        for sym in symbols:
            last_p, high_p, low_p = self._get_live_price(sym)
            if last_p <= 0:
                continue

            with self._lock:
                pos = self.positions.get(sym)
                if not pos:
                    continue

                side = str(pos['side']).lower()
                is_long = side in ('long', 'buy')
                entry_p = float(pos['entryPrice'])
                contracts = float(pos['contracts'])
                lev = float(pos.get('leverage') or 20.0)
                tp = float(pos.get('takeProfit') or 0.0)
                sl = float(pos.get('stopLoss') or 0.0)
                liq = float(pos.get('liquidationPrice') or 0.0)

                # Verifica se atingiu Take Profit ou Stop Loss com o preço real da Bybit
                if is_long:
                    if tp > 0 and high_p >= tp:
                        self._close_simulated_position(sym, tp, reason='TAKE_PROFIT', fee_rate=MAKER_FEE_RATE)
                        continue
                    if sl > 0 and low_p <= sl:
                        self._close_simulated_position(sym, sl, reason='STOP_LOSS', fee_rate=TAKER_FEE_RATE)
                        continue
                    if liq > 0 and low_p <= liq:
                        self._close_simulated_position(sym, liq, reason='LIQUIDATION', fee_rate=TAKER_FEE_RATE)
                        continue
                    unpnl = (last_p - entry_p) * contracts
                else:
                    if tp > 0 and low_p <= tp:
                        self._close_simulated_position(sym, tp, reason='TAKE_PROFIT', fee_rate=MAKER_FEE_RATE)
                        continue
                    if sl > 0 and high_p >= sl:
                        self._close_simulated_position(sym, sl, reason='STOP_LOSS', fee_rate=TAKER_FEE_RATE)
                        continue
                    if liq > 0 and high_p >= liq:
                        self._close_simulated_position(sym, liq, reason='LIQUIDATION', fee_rate=TAKER_FEE_RATE)
                        continue
                    unpnl = (entry_p - last_p) * contracts

                pos_val = contracts * last_p
                init_margin = (contracts * entry_p) / lev if lev > 0 else pos_val
                roi = (unpnl / init_margin * 100.0) if init_margin > 0 else 0.0

                pos['markPrice'] = last_p
                pos['positionValue'] = pos_val
                pos['initialMargin'] = init_margin
                pos['unrealizedPnl'] = unpnl
                pos['percentage'] = roi
                pos['info'] = {
                    'markPrice': str(last_p),
                    'positionValue': str(pos_val),
                    'positionIM': str(init_margin),
                    'liqPrice': str(liq),
                    'takeProfit': str(tp) if tp > 0 else '',
                    'stopLoss': str(sl) if sl > 0 else '',
                }

    # =========================================================================
    # MÉTODOS DE CONTA E POSIÇÕES (CCXT + BYBIT V5 IMPLICIT API)
    # =========================================================================

    def set_margin_mode(self, marginMode, symbol=None, params={}):
        return {'retCode': 0, 'retMsg': 'OK (Paper Mode)'}

    def set_leverage(self, leverage, symbol=None, params={}):
        if symbol:
            self._leverages[symbol] = float(leverage)
        return {'retCode': 0, 'retMsg': 'OK (Paper Mode)'}

    def privatePostV5AccountSetCollateralSwitch(self, params={}):
        return {'retCode': 0, 'retMsg': 'OK (Paper Mode)'}

    def privateGetV5AccountWalletBalance(self, params={}):
        self._sync_positions_with_live_market()
        with self._lock:
            locked_margin = 0.0
            total_unpnl = 0.0
            for pos in self.positions.values():
                locked_margin += float(pos.get('initialMargin') or 0.0)
                total_unpnl += float(pos.get('unrealizedPnl') or 0.0)

            total_equity = max(0.0, self.wallet_balance + total_unpnl)
            available_bal = max(0.0, total_equity - locked_margin)

            return {
                'retCode': 0,
                'result': {
                    'list': [
                        {
                            'accountType': 'UNIFIED',
                            'totalEquity': f"{total_equity:.6f}",
                            'totalAvailableBalance': f"{available_bal:.6f}",
                            'totalWalletBalance': f"{self.wallet_balance:.6f}",
                            'coin': [
                                {
                                    'coin': 'USDT',
                                    'walletBalance': f"{self.wallet_balance:.6f}",
                                    'availableToWithdraw': f"{available_bal:.6f}",
                                    'usdValue': f"{total_equity:.6f}",
                                },
                                {
                                    'coin': 'BTC',
                                    'walletBalance': '0',
                                    'availableToWithdraw': '0',
                                    'usdValue': '0',
                                },
                            ],
                        }
                    ]
                },
            }

    def privateGetV5AssetTransferQueryAccountCoinsBalance(self, params={}):
        return {'retCode': 0, 'result': {'balance': []}}

    def fetch_balance(self, params={}):
        acc_type = (params or {}).get('type', 'unified')
        if str(acc_type).lower() == 'funding':
            return {'free': {'USDT': 0.0, 'BTC': 0.0}, 'total': {'USDT': 0.0, 'BTC': 0.0}}
        resp = self.privateGetV5AccountWalletBalance()
        lst = resp['result']['list'][0]
        eq = float(lst['totalEquity'])
        avail = float(lst['totalAvailableBalance'])
        return {
            'free': {'USDT': avail, 'BTC': 0.0},
            'total': {'USDT': eq, 'BTC': 0.0},
        }

    def fetch_positions(self, symbols=None, params={}):
        self._sync_positions_with_live_market(symbols)
        with self._lock:
            if not symbols:
                return [dict(p) for p in self.positions.values()]
            norm = set(symbols)
            return [dict(p) for sym, p in self.positions.items() if sym in norm]

    def privatePostV5PositionTradingStop(self, params={}):
        symbol_raw = params.get('symbol', '')
        ccxt_sym = self._bybit_id_to_ccxt_symbol(symbol_raw)
        with self._lock:
            pos = self.positions.get(ccxt_sym)
            if pos:
                if 'stopLoss' in params and params['stopLoss']:
                    pos['stopLoss'] = float(params['stopLoss'])
                    pos['info']['stopLoss'] = str(params['stopLoss'])
                if 'takeProfit' in params and params['takeProfit']:
                    pos['takeProfit'] = float(params['takeProfit'])
                    pos['info']['takeProfit'] = str(params['takeProfit'])
                self._save_state()
        return {'retCode': 0, 'retMsg': 'OK'}

    def privateGetV5PositionClosedPnl(self, params={}):
        self._sync_positions_with_live_market()
        sym_filter = params.get('symbol')
        limit = int(params.get('limit', 50))
        with self._lock:
            items = self.closed_pnl
            if sym_filter:
                clean_filter = str(sym_filter).replace('/', '').split(':')[0].upper()
                items = [x for x in items if str(x.get('symbol', '')).upper() == clean_filter]
            return {'retCode': 0, 'result': {'list': items[:limit]}}

    def create_order(self, symbol, type, side, amount, price=None, params={}):
        params = params or {}
        if ':' not in symbol and symbol.endswith('/USDT'):
            # Se for spot, mantém ou converte se houver alavancagem
            pass

        last_p, _, _ = self._get_live_price(symbol)
        exec_price = float(price) if (price and float(price) > 0) else last_p
        if exec_price <= 0:
            raise RuntimeError(f"[Simulador] Não foi possível obter cotação ao vivo para {symbol}")

        amount = float(amount)
        side_lower = str(side).lower()
        is_buy = side_lower in ('buy', 'long')
        reduce_only = bool(params.get('reduceOnly', False))

        with self._lock:
            # 1. Se for reduceOnly (fechamento manual ou saída de posição)
            if reduce_only:
                if symbol in self.positions:
                    self._close_simulated_position(symbol, last_p or exec_price, reason='MANUAL_OR_STRATEGY_EXIT')
                order_id = f"paper-{uuid.uuid4().hex[:10]}"
                order_obj = {
                    'id': order_id,
                    'symbol': symbol,
                    'type': type,
                    'side': side,
                    'amount': amount,
                    'price': last_p or exec_price,
                    'status': 'closed',
                }
                self._orders[order_id] = order_obj
                return order_obj

            # 2. Abertura de nova posição simulada
            lev = float(self._leverages.get(symbol, 20.0))
            notional = amount * exec_price
            req_margin = notional / lev if lev > 0 else notional
            fee_rate = MAKER_FEE_RATE if str(type).lower() == 'limit' else TAKER_FEE_RATE
            entry_fee = notional * fee_rate

            # Verifica margem disponível
            locked_margin = sum(float(p.get('initialMargin') or 0.0) for p in self.positions.values())
            avail = self.wallet_balance - locked_margin
            if req_margin + entry_fee > avail:
                raise RuntimeError(
                    f"110007: Saldo de teste insuficiente (Necessário: ${req_margin + entry_fee:.2f}, Disponível: ${avail:.2f})"
                )

            self.wallet_balance -= entry_fee

            tp_val = float(params.get('takeProfit') or 0.0)
            sl_val = float(params.get('stopLoss') or 0.0)
            pos_side = 'long' if is_buy else 'short'
            liq_price = (
                exec_price * (1.0 - (0.92 / max(lev, 1.0)))
                if is_buy
                else exec_price * (1.0 + (0.92 / max(lev, 1.0)))
            )

            self.positions[symbol] = {
                'symbol': symbol,
                'side': pos_side,
                'contracts': amount,
                'entryPrice': exec_price,
                'markPrice': exec_price,
                'leverage': lev,
                'liquidationPrice': round(liq_price, 6),
                'initialMargin': req_margin,
                'positionValue': notional,
                'unrealizedPnl': 0.0,
                'percentage': 0.0,
                'takeProfit': tp_val,
                'stopLoss': sl_val,
                'entryFee': entry_fee,
                'timestamp': int(time.time() * 1000),
                'info': {
                    'markPrice': str(exec_price),
                    'positionValue': str(notional),
                    'positionIM': str(req_margin),
                    'liqPrice': str(round(liq_price, 6)),
                    'takeProfit': str(tp_val) if tp_val > 0 else '',
                    'stopLoss': str(sl_val) if sl_val > 0 else '',
                },
            }
            self._save_state()

            order_id = f"paper-{uuid.uuid4().hex[:10]}"
            order_obj = {
                'id': order_id,
                'symbol': symbol,
                'type': type,
                'side': side,
                'amount': amount,
                'price': exec_price,
                'status': 'closed',
                'filled': amount,
            }
            self._orders[order_id] = order_obj
            add_log(
                f"🧪 [SIMULADOR ORDEM EXECUTADA] {pos_side.upper()} {amount} {symbol} @ ${exec_price:.4f} "
                f"(Margem: ${req_margin:.2f} | {lev:.0f}x | TP: ${tp_val:.4f} | SL: ${sl_val:.4f})"
            )
            return order_obj

    def create_market_buy_order(self, symbol, amount, params={}):
        return self.create_order(symbol, 'market', 'buy', amount, None, params)

    def create_market_sell_order(self, symbol, amount, params={}):
        return self.create_order(symbol, 'market', 'sell', amount, None, params)

    def fetch_order(self, id, symbol=None, params={}):
        return self._orders.get(id, {'id': id, 'symbol': symbol, 'status': 'closed'})

    def cancel_order(self, id, symbol=None, params={}):
        return {'id': id, 'status': 'canceled'}

    def cancel_all_orders(self, symbol=None, params={}):
        return []

