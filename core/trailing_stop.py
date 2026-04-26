import time
import threading

class TrailingStopEngine:
    """
    Engine de Trailing Stop Inteligente
    - Acompanha o preço e ajusta o stop loss dinamicamente
    """
    
    def __init__(self, exchange, symbol, initial_stop_pct=1.0, mode='hybrid'):
        self.exchange = exchange
        self.symbol = symbol
        self.mode = mode
        self.initial_stop_pct = initial_stop_pct
        
        self.highest_price = 0
        self.lowest_price = float('inf')
        self.current_stop = 0
        self.entry_price = 0
        self.position_side = None
        self.position_size = 0
        self.is_active = False
        
        self.times_adjusted = 0
        self.initial_stop = 0
        
        self.min_adjustment_pct = 0.15
        self.confirmation_bars = 2
        self.price_history = []
        
    def activate(self, entry_price, position_side, position_size, current_stop):
        self.entry_price = entry_price
        self.position_side = position_side
        self.position_size = position_size
        self.current_stop = current_stop
        self.initial_stop = current_stop
        self.is_active = True
        self.times_adjusted = 0
        
        if position_side == 'LONG':
            self.highest_price = entry_price
        else:
            self.lowest_price = entry_price
        return True
    
    def deactivate(self):
        self.is_active = False
        self.highest_price = 0
        self.lowest_price = float('inf')
        self.price_history = []
        
    def update_price(self, current_price, atr=None):
        if not self.is_active:
            return self.current_stop, False
            
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
                
                if new_stop > self.current_stop + (self.current_stop * self.min_adjustment_pct / 100):
                    should_adjust = True
                    self.current_stop = new_stop
                    self.times_adjusted += 1
        else:
            if current_price < self.lowest_price:
                self.lowest_price = current_price
                
                if self.mode == 'percent':
                    new_stop = self.calculate_percent_stop_short(current_price)
                elif self.mode == 'hybrid':
                    new_stop = self.calculate_hybrid_stop_short(current_price, atr)
                elif self.mode == 'stepped':
                    new_stop = self.calculate_stepped_stop_short(current_price)
                
                if new_stop < self.current_stop - (self.current_stop * self.min_adjustment_pct / 100):
                    should_adjust = True
                    self.current_stop = new_stop
                    self.times_adjusted += 1
        
        return self.current_stop, should_adjust
    
    def calculate_percent_stop_long(self, current_price):
        return current_price - (current_price * (self.initial_stop_pct / 100))
    
    def calculate_percent_stop_short(self, current_price):
        return current_price + (current_price * (self.initial_stop_pct / 100))
    
    def calculate_atr_stop_long(self, current_price, atr):
        return current_price - (atr * 2.0)
    
    def calculate_atr_stop_short(self, current_price, atr):
        return current_price + (atr * 2.0)
    
    def calculate_hybrid_stop_long(self, current_price, atr=None):
        percent_stop = self.calculate_percent_stop_long(current_price)
        if atr:
            atr_stop = self.calculate_atr_stop_long(current_price, atr)
            return max(percent_stop, atr_stop)
        return percent_stop
    
    def calculate_hybrid_stop_short(self, current_price, atr=None):
        percent_stop = self.calculate_percent_stop_short(current_price)
        if atr:
            atr_stop = self.calculate_atr_stop_short(current_price, atr)
            return min(percent_stop, atr_stop)
        return percent_stop
    
    def calculate_stepped_stop_long(self, current_price):
        profit_pct = ((current_price - self.entry_price) / self.entry_price) * 100
        if profit_pct > 0:
            steps = int(profit_pct)
            protected_profit = steps * 0.7
            return self.entry_price + (self.entry_price * protected_profit / 100)
        return self.initial_stop
    
    def calculate_stepped_stop_short(self, current_price):
        profit_pct = ((self.entry_price - current_price) / self.entry_price) * 100
        if profit_pct > 0:
            steps = int(profit_pct)
            protected_profit = steps * 0.7
            return self.entry_price - (self.entry_price * protected_profit / 100)
        return self.initial_stop
    
    def should_execute_stop(self, current_price):
        if not self.is_active:
            return False
        if self.position_side == 'LONG':
            return current_price <= self.current_stop
        else:
            return current_price >= self.current_stop
