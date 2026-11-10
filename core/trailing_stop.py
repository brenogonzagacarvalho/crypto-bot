class TrailingStopEngine:
    """
    Engine de Trailing Stop Inteligente com suporte a sincronização Server-Side Bybit V5.
    - Acompanha o preço, ativa Breakeven em +1R e ajusta o stop loss dinamicamente.
    """

    def __init__(self, exchange, symbol, initial_stop_pct=1.0, mode='hybrid'):
        self.exchange = exchange
        self.symbol = symbol
        self.mode = mode
        self.initial_stop_pct = initial_stop_pct

        self.highest_price = 0.0
        self.lowest_price = float('inf')
        self.current_stop = 0.0
        self.entry_price = 0.0
        self.position_side = None
        self.position_size = 0.0
        self.is_active = False

        self.times_adjusted = 0
        self.initial_stop = 0.0

        self.min_adjustment_pct = 0.12
        self.confirmation_bars = 2
        self.price_history = []

    @property
    def current_stop_price(self):
        """Alias seguro para compatibilidade com todas as estratégias."""
        return self.current_stop

    @current_stop_price.setter
    def current_stop_price(self, val):
        self.current_stop = val

    def activate(self, entry_price, position_side, position_size, current_stop):
        self.entry_price = float(entry_price)
        self.position_side = str(position_side).upper()
        if self.position_side == 'BUY':
            self.position_side = 'LONG'
        elif self.position_side == 'SELL':
            self.position_side = 'SHORT'
        self.position_size = float(position_size)
        self.current_stop = float(current_stop)
        self.initial_stop = float(current_stop)
        self.is_active = True
        self.times_adjusted = 0

        if self.position_side == 'LONG':
            self.highest_price = self.entry_price
        else:
            self.lowest_price = self.entry_price
        return True

    def deactivate(self):
        self.is_active = False
        self.highest_price = 0.0
        self.lowest_price = float('inf')
        self.price_history = []

    def sync_to_exchange(self, new_stop_price):
        """Sincroniza o novo Stop Loss diretamente no servidor da Bybit V5."""
        if not self.exchange or not self.symbol or new_stop_price <= 0:
            return False
        try:
            market = self.exchange.market(self.symbol)
            bybit_symbol = market['id'] if market else self.symbol.replace('/', '').split(':')[0]
            sl_formatted = self.exchange.price_to_precision(self.symbol, new_stop_price)
            self.exchange.privatePostV5PositionTradingStop({
                'category': 'linear',
                'symbol': bybit_symbol,
                'stopLoss': str(sl_formatted),
                'slTriggerBy': 'MarkPrice',
                'positionIdx': 0,
            })
            return True
        except Exception:
            return False

    def update_price(self, current_price, atr=None, sync_exchange=True):
        if not self.is_active:
            return self.current_stop, False

        current_price = float(current_price)
        self.price_history.append(current_price)
        if len(self.price_history) > 100:
            self.price_history.pop(0)

        should_adjust = False
        new_stop = self.current_stop

        if self.position_side == 'LONG':
            if current_price > self.highest_price:
                self.highest_price = current_price

                if self.mode == 'percent':
                    new_stop = self.calculate_percent_stop_long(current_price)
                elif self.mode == 'hybrid':
                    new_stop = self.calculate_hybrid_stop_long(current_price, atr)
                elif self.mode == 'stepped':
                    new_stop = self.calculate_stepped_stop_long(current_price)

                if new_stop > self.current_stop + (self.current_stop * self.min_adjustment_pct / 100.0):
                    should_adjust = True
                    self.current_stop = new_stop
                    self.times_adjusted += 1
                    if sync_exchange:
                        self.sync_to_exchange(self.current_stop)
        else:
            if current_price < self.lowest_price:
                self.lowest_price = current_price

                if self.mode == 'percent':
                    new_stop = self.calculate_percent_stop_short(current_price)
                elif self.mode == 'hybrid':
                    new_stop = self.calculate_hybrid_stop_short(current_price, atr)
                elif self.mode == 'stepped':
                    new_stop = self.calculate_stepped_stop_short(current_price)

                if new_stop < self.current_stop - (self.current_stop * self.min_adjustment_pct / 100.0):
                    should_adjust = True
                    self.current_stop = new_stop
                    self.times_adjusted += 1
                    if sync_exchange:
                        self.sync_to_exchange(self.current_stop)

        return self.current_stop, should_adjust

    def calculate_percent_stop_long(self, current_price):
        return current_price - (current_price * (self.initial_stop_pct / 100.0))

    def calculate_percent_stop_short(self, current_price):
        return current_price + (current_price * (self.initial_stop_pct / 100.0))

    def calculate_atr_stop_long(self, current_price, atr):
        return current_price - (atr * 1.8)

    def calculate_atr_stop_short(self, current_price, atr):
        return current_price + (atr * 1.8)

    def calculate_hybrid_stop_long(self, current_price, atr=None):
        percent_stop = self.calculate_percent_stop_long(current_price)
        stepped_stop = self.calculate_stepped_stop_long(current_price)
        best = max(percent_stop, stepped_stop)
        if atr:
            atr_stop = self.calculate_atr_stop_long(current_price, atr)
            return max(best, atr_stop)
        return best

    def calculate_hybrid_stop_short(self, current_price, atr=None):
        percent_stop = self.calculate_percent_stop_short(current_price)
        stepped_stop = self.calculate_stepped_stop_short(current_price)
        best = min(percent_stop, stepped_stop)
        if atr:
            atr_stop = self.calculate_atr_stop_short(current_price, atr)
            return min(best, atr_stop)
        return best

    def calculate_stepped_stop_long(self, current_price):
        profit_pct = ((current_price - self.entry_price) / self.entry_price) * 100.0
        if profit_pct >= 0.20:
            steps = int(profit_pct / 0.20)
            protected_profit = (steps * 0.20) - 0.05
            protected_profit = max(0.15, protected_profit)
            return self.entry_price * (1.0 + protected_profit / 100.0)
        return self.initial_stop

    def calculate_stepped_stop_short(self, current_price):
        profit_pct = ((self.entry_price - current_price) / self.entry_price) * 100.0
        if profit_pct >= 0.20:
            steps = int(profit_pct / 0.20)
            protected_profit = (steps * 0.20) - 0.05
            protected_profit = max(0.15, protected_profit)
            return self.entry_price * (1.0 - protected_profit / 100.0)
        return self.initial_stop

    def should_execute_stop(self, current_price):
        if not self.is_active:
            return False
        if self.position_side == 'LONG':
            return current_price <= self.current_stop
        else:
            return current_price >= self.current_stop
