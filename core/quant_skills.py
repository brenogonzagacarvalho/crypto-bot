"""
core/quant_skills.py — Motor Unificado das Skills Quantitativas (Claude & Grok Trading Desk)

Implementa em Python as skills documentadas em `.agents/skills/` e `.claude/skills/`:
1. MarketRegimeSkill (`desk-regime-analyst`):
   - Classificação de regime de mercado multi-timeframe (SQUEEZE_BREAKOUT, STRONG_UPTREND,
     STRONG_DOWNTREND, MEAN_REVERSION_RANGE, HIGH_VOL_CHOP).
   - Score de Confluência Quantitativa (-100 a +100).
2. MicrostructureSkill (`microstructure-funding-scanner`):
   - Order Book Imbalance (OBI) no Livro de Ofertas L2 da Bybit V5.
   - Taxa de Financiamento (Funding Rate) e detecção de Short/Long Squeeze.
   - Detecção de Liquidity Sweeps (Stop-Hunts / Turtle Soup) em máximas e mínimas.
3. RiskOfficerSkill (`risk-officer-guardrails`):
   - Dimensionamento de posição ajustado à volatilidade (ATR) e filtro de lote mínimo.
   - Stop-Loss e Take-Profit atômicos obrigatórios.
   - Proteção ativa: Breakeven automático em +1R e Trailing Stop Server-Side na Bybit V5.
   - Circuit Breakers de meta diária e limite de perda diária.
4. ExecutionProtocolSkill (`bybit-v5-execution-protocol`):
   - Execução Maker-First (PostOnly) com fallback inteligente (Market/IOC com TP/SL atômicos).
   - Sincronização de Stop Loss / Take Profit diretamente nos servidores da Bybit V5.
"""

import time
from core.market_data import (
    fetch_ohlcv_data,
    calculate_rsi,
    calculate_ema,
    calculate_macd,
    calculate_vwap,
    calculate_vwap_bands,
    calculate_atr,
    calculate_adx,
    calculate_bollinger_bands,
    calculate_keltner_channels,
    calculate_rvol,
    analyze_candle_anatomy,
)
from core.balance_utils import place_maker_entry
from core.shared_state import add_log

DEFAULT_SCAN_SYMBOLS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "XRP/USDT:USDT",
    "DOGE/USDT:USDT",
    "ADA/USDT:USDT",
    "BNB/USDT:USDT",
]


class MarketRegimeSkill:
    """
    Skill 1: Desk Regime Analyst
    Classifica o regime de mercado e calcula um Score de Confluência (-100 a +100).
    """

    @staticmethod
    def analyze_asset(exchange, symbol, ltf='5m', htf='1h', limit=210):
        ohlcv_ltf = fetch_ohlcv_data(exchange, symbol, timeframe=ltf, limit=limit)
        if not ohlcv_ltf or len(ohlcv_ltf['c']) < 60:
            return None

        closes = ohlcv_ltf['c']
        current_price = closes[-1]

        rsi = calculate_rsi(closes, period=14)
        prev_rsi = calculate_rsi(closes[:-1], period=14) if len(closes) > 16 else rsi
        ema9 = calculate_ema(closes, period=9)
        ema21 = calculate_ema(closes, period=21)
        ema50 = calculate_ema(closes, period=50)
        ema200 = calculate_ema(closes, period=200) or ema50
        macd_line, signal_line, macd_hist = calculate_macd(closes)
        prev_macd_hist = calculate_macd(closes[:-1])[2] if len(closes) > 36 else macd_hist

        vwap_info = calculate_vwap_bands(ohlcv_ltf, window=min(80, len(closes)))
        vwap = vwap_info['vwap'] if vwap_info else calculate_vwap(ohlcv_ltf)
        z_score = vwap_info['z_score'] if vwap_info else 0.0

        atr = calculate_atr(ohlcv_ltf, period=14)
        adx, plus_di, minus_di = calculate_adx(ohlcv_ltf, period=14)
        bb = calculate_bollinger_bands(closes, period=20, std_mult=2.0)
        kc = calculate_keltner_channels(ohlcv_ltf, period=20, atr_mult=1.5)
        rvol = calculate_rvol(ohlcv_ltf, period=20)
        candle = analyze_candle_anatomy(ohlcv_ltf, idx=-2)

        if any(v is None for v in (rsi, ema9, ema21, ema50, ema200, macd_hist, vwap, atr, bb)):
            return None

        # Detecção de TTM Volatility Squeeze (Bollinger dentro de Keltner ou BB Width comprimida)
        is_squeeze = False
        if kc:
            is_squeeze = (bb['upper'] <= kc['upper'] and bb['lower'] >= kc['lower']) or (bb['width_pct'] < 1.6)
        else:
            is_squeeze = bb['width_pct'] < 1.6

        # Verifica se houve compressão recente nas últimas 5 velas seguida de expansão
        bb_prev = calculate_bollinger_bands(closes[:-3], period=20, std_mult=2.0)
        was_squeezed = (bb_prev['width_pct'] < 1.8) if bb_prev else False
        squeeze_Expanding = (was_squeezed and bb['width_pct'] > bb_prev['width_pct'] * 1.08 and rvol >= 1.2)

        # Filtro Macro HTF (1h)
        htf_trend = 'NEUTRAL'
        htf_ema50 = None
        htf_rsi = 50.0
        if htf and htf != ltf:
            ohlcv_htf = fetch_ohlcv_data(exchange, symbol, timeframe=htf, limit=100)
            if ohlcv_htf and len(ohlcv_htf['c']) >= 55:
                htf_closes = ohlcv_htf['c']
                htf_ema50 = calculate_ema(htf_closes, period=50)
                htf_ema21 = calculate_ema(htf_closes, period=21)
                htf_rsi = calculate_rsi(htf_closes, period=14) or 50.0
                if htf_ema50 and htf_ema21:
                    if current_price > htf_ema50 and htf_ema21 >= htf_ema50 * 0.998:
                        htf_trend = 'UPTREND'
                    elif current_price < htf_ema50 and htf_ema21 <= htf_ema50 * 1.002:
                        htf_trend = 'DOWNTREND'
        else:
            htf_trend = 'UPTREND' if current_price > ema200 else 'DOWNTREND'

        # Cálculo do Confluence Score (-100 a +100)
        score = 0.0
        reasons = []

        # 1. Alinhamento HTF (±25)
        if htf_trend == 'UPTREND':
            score += 25.0
            reasons.append("HTF Alta")
        elif htf_trend == 'DOWNTREND':
            score -= 25.0
            reasons.append("HTF Baixa")

        # 2. Alinhamento EMAs e VWAP no LTF (±30)
        if current_price > ema200 and ema9 > ema21:
            score += 18.0
            if ema21 > ema50:
                score += 5.0
            reasons.append("EMA Stack Bull")
        elif current_price < ema200 and ema9 < ema21:
            score -= 18.0
            if ema21 < ema50:
                score -= 5.0
            reasons.append("EMA Stack Bear")

        if current_price > vwap:
            score += 7.0
        else:
            score -= 7.0

        # 3. Momentum MACD & DI (±20)
        if macd_hist > 0:
            score += 10.0 if (prev_macd_hist is not None and macd_hist >= prev_macd_hist) else 5.0
        else:
            score -= 10.0 if (prev_macd_hist is not None and macd_hist <= prev_macd_hist) else 5.0

        if plus_di > minus_di:
            score += 10.0
        else:
            score -= 10.0

        # 4. Oscilador RSI & Anatomia do Candle (±25)
        if rsi < 32 and rsi > prev_rsi:
            score += 15.0
            reasons.append(f"RSI Reversão Alta ({rsi:.1f})")
        elif rsi > 68 and rsi < prev_rsi:
            score -= 15.0
            reasons.append(f"RSI Reversão Baixa ({rsi:.1f})")
        elif 45 <= rsi <= 65 and current_price > ema21:
            score += 10.0
        elif 35 <= rsi <= 55 and current_price < ema21:
            score -= 10.0

        if candle:
            if candle['pattern_bias'] == 'BULLISH':
                score += 10.0
                reasons.append(candle['pattern_name'])
            elif candle['pattern_bias'] == 'BEARISH':
                score -= 10.0
                reasons.append(candle['pattern_name'])

        score = max(-100.0, min(100.0, score))

        # Classificação do Regime
        atr_pct = (atr / current_price) * 100.0 if current_price > 0 else 0.0
        if atr_pct > 2.8 and adx < 15:
            regime = 'HIGH_VOL_CHOP'
        elif squeeze_Expanding or (is_squeeze and adx >= 20 and rvol >= 1.4):
            regime = 'SQUEEZE_BREAKOUT'
        elif adx >= 21 and current_price > ema50 and ema21 >= ema50 and htf_trend != 'DOWNTREND':
            regime = 'STRONG_UPTREND'
        elif adx >= 21 and current_price < ema50 and ema21 <= ema50 and htf_trend != 'UPTREND':
            regime = 'STRONG_DOWNTREND'
        else:
            regime = 'MEAN_REVERSION_RANGE'

        return {
            'symbol': symbol,
            'ohlcv_ltf': ohlcv_ltf,
            'current_price': current_price,
            'regime': regime,
            'htf_trend': htf_trend,
            'htf_rsi': htf_rsi,
            'confluence_score': score,
            'reasons': reasons,
            'rsi': rsi,
            'prev_rsi': prev_rsi,
            'ema9': ema9,
            'ema21': ema21,
            'ema50': ema50,
            'ema200': ema200,
            'macd_line': macd_line,
            'signal_line': signal_line,
            'macd_hist': macd_hist,
            'prev_macd_hist': prev_macd_hist,
            'vwap': vwap,
            'vwap_bands': vwap_info,
            'z_score': z_score,
            'atr': atr,
            'atr_pct': atr_pct,
            'adx': adx,
            'plus_di': plus_di,
            'minus_di': minus_di,
            'bb': bb,
            'kc': kc,
            'is_squeeze': is_squeeze,
            'squeeze_expanding': squeeze_Expanding,
            'rvol': rvol,
            'candle': candle,
        }


class MicrostructureSkill:
    """
    Skill 2: Microstructure & Funding Scanner (HyperGrok / PumpGrok)
    Analisa Order Book Imbalance (OBI), Taxa de Financiamento (Funding Rate) e Liquidity Sweeps.
    """

    @staticmethod
    def get_orderbook_imbalance(exchange, symbol, limit=20):
        try:
            ob = exchange.fetch_order_book(symbol, limit=limit)
            bids = ob.get('bids', [])[:limit]
            asks = ob.get('asks', [])[:limit]
            if not bids or not asks:
                return {'obi': 0.0, 'spread_pct': 0.0, 'bias': 'NEUTRAL'}

            bid_vol = sum(float(b[1]) for b in bids)
            ask_vol = sum(float(a[1]) for a in asks)
            total_vol = bid_vol + ask_vol
            obi = ((bid_vol - ask_vol) / total_vol) if total_vol > 0 else 0.0

            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            mid_price = (best_bid + best_ask) / 2.0
            spread_pct = ((best_ask - best_bid) / mid_price * 100.0) if mid_price > 0 else 0.0

            bias = 'NEUTRAL'
            if obi >= 0.14:
                bias = 'BULLISH'
            elif obi <= -0.14:
                bias = 'BEARISH'

            return {
                'obi': obi,
                'bid_vol': bid_vol,
                'ask_vol': ask_vol,
                'spread_pct': spread_pct,
                'best_bid': best_bid,
                'best_ask': best_ask,
                'bias': bias,
            }
        except Exception:
            return {'obi': 0.0, 'spread_pct': 0.0, 'bias': 'NEUTRAL'}

    @staticmethod
    def get_funding_rate(exchange, symbol):
        try:
            ticker = exchange.fetch_ticker(symbol)
            info = ticker.get('info', {}) or {}
            fr_raw = info.get('fundingRate')
            if fr_raw is None and hasattr(exchange, 'fetch_funding_rate'):
                fr_obj = exchange.fetch_funding_rate(symbol)
                fr_raw = fr_obj.get('fundingRate', 0.0)
            fr_pct = float(fr_raw or 0.0) * 100.0

            squeeze_bias = 'NEUTRAL'
            if fr_pct <= -0.012:
                # Shorts pagando muito -> propenso a Short Squeeze (Alta)
                squeeze_bias = 'SHORT_SQUEEZE_BULLISH'
            elif fr_pct >= 0.030:
                # Longs super-alavancados -> propenso a Long Flush (Baixa)
                squeeze_bias = 'LONG_FLUSH_BEARISH'

            return {'funding_rate_pct': fr_pct, 'squeeze_bias': squeeze_bias}
        except Exception:
            return {'funding_rate_pct': 0.0, 'squeeze_bias': 'NEUTRAL'}

    @staticmethod
    def detect_liquidity_sweep(ohlcv_data, lookback=24):
        """
        Detecta varredura de liquidez (Stop-Hunt / ICT Turtle Soup) nas últimas `lookback` velas.
        """
        if not ohlcv_data or len(ohlcv_data['c']) < lookback + 4:
            return {'sweep_type': None, 'swept_level': None, 'wick_ratio': 0.0}

        # Níveis estruturais anteriores às últimas 2 velas
        prior_highs = ohlcv_data['h'][-(lookback + 2):-2]
        prior_lows = ohlcv_data['l'][-(lookback + 2):-2]
        swing_high = max(prior_highs)
        swing_low = min(prior_lows)

        # Avalia vela fechada (-2) e vela atual (-1)
        for idx in (-2, -1):
            o = ohlcv_data['o'][idx]
            h = ohlcv_data['h'][idx]
            l = ohlcv_data['l'][idx]
            c = ohlcv_data['c'][idx]
            body = max(abs(c - o), (h - l) * 0.05, 1e-8)
            lower_wick = min(o, c) - l
            upper_wick = h - max(o, c)

            # Bullish Sweep: furou o swing_low e fechou de volta acima dele com rejeição
            if l < swing_low and c > swing_low and (lower_wick / body) >= 1.1:
                return {
                    'sweep_type': 'BULLISH_SWEEP',
                    'swept_level': swing_low,
                    'wick_ratio': lower_wick / body,
                    'swing_high': swing_high,
                    'swing_low': swing_low,
                }
            # Bearish Sweep: furou o swing_high e fechou de volta abaixo dele com rejeição
            if h > swing_high and c < swing_high and (upper_wick / body) >= 1.1:
                return {
                    'sweep_type': 'BEARISH_SWEEP',
                    'swept_level': swing_high,
                    'wick_ratio': upper_wick / body,
                    'swing_high': swing_high,
                    'swing_low': swing_low,
                }

        return {
            'sweep_type': None,
            'swept_level': None,
            'wick_ratio': 0.0,
            'swing_high': swing_high,
            'swing_low': swing_low,
        }


class RiskOfficerSkill:
    """
    Skill 3: Risk Officer Guardrails
    Calcula tamanho de posição seguro, impõe TP/SL atômicos e gerencia Breakeven + Trailing Stop Server-Side.
    """

    @staticmethod
    def calculate_order_sizing(
        exchange,
        symbol,
        side,
        entry_price,
        atr,
        collateral_usd,
        leverage,
        risk_margin_pct=0.12,
        atr_sl_mult=2.0,
        rr_ratio=2.5,
        min_sl_pct=0.0045,
        max_sl_pct=0.015,
        custom_sl_price=None,
        custom_tp_price=None,
    ):
        """
        Retorna dicionário com (valid, amount, entry_price, tp_price, sl_price, sl_dist_pct, reason).
        """
        if collateral_usd is None or collateral_usd < 0.50:
            return {'valid': False, 'reason': f'Margem insuficiente (${collateral_usd or 0:.2f})'}

        # 1. Distância do Stop Loss dinâmica por ATR limitada entre min_sl_pct e max_sl_pct
        raw_dist = (atr * atr_sl_mult) if (atr and atr > 0) else (entry_price * 0.007)
        sl_dist = max(entry_price * min_sl_pct, min(entry_price * max_sl_pct, raw_dist))

        is_buy = str(side).lower() in ('buy', 'long')
        if custom_sl_price is not None and custom_sl_price > 0:
            sl_price = custom_sl_price
            sl_dist = abs(entry_price - sl_price)
        else:
            sl_price = (entry_price - sl_dist) if is_buy else (entry_price + sl_dist)

        if custom_tp_price is not None and custom_tp_price > 0:
            tp_price = custom_tp_price
        else:
            tp_price = (entry_price + sl_dist * rr_ratio) if is_buy else (entry_price - sl_dist * rr_ratio)

        # 2. Dimensionamento da Margem Alocada
        margin_to_use = max(1.0, collateral_usd * risk_margin_pct)
        margin_to_use = min(margin_to_use, collateral_usd * 0.85)
        target_notional_usd = margin_to_use * leverage
        raw_amount = target_notional_usd / entry_price

        # 3. Verificação do Lote Mínimo da Bybit vs Exposição Segura
        try:
            market = exchange.market(symbol)
            min_amount = float(market['limits']['amount']['min'] or 0)
            min_notional = min_amount * entry_price
            max_safe_notional = collateral_usd * 0.90 * leverage

            if min_notional > max(target_notional_usd * 1.45, 25.0) and min_notional > max_safe_notional:
                return {
                    'valid': False,
                    'reason': f"Lote mínimo (${min_notional:.2f}) excede margem segura (${target_notional_usd:.2f})",
                }

            if raw_amount < min_amount:
                if (min_notional / leverage) <= collateral_usd * 0.92:
                    raw_amount = min_amount
                else:
                    return {
                        'valid': False,
                        'reason': f"Saldo insuficiente para lote mínimo de {min_amount} {symbol}",
                    }

            amount = float(exchange.amount_to_precision(symbol, raw_amount))
            if amount < min_amount:
                amount = min_amount
            entry_fmt = float(exchange.price_to_precision(symbol, entry_price))
            tp_fmt = float(exchange.price_to_precision(symbol, tp_price))
            sl_fmt = float(exchange.price_to_precision(symbol, sl_price))
        except Exception:
            amount = round(raw_amount, 6)
            entry_fmt = entry_price
            tp_fmt = tp_price
            sl_fmt = sl_price

        sl_dist_pct = (abs(entry_fmt - sl_fmt) / entry_fmt) * 100.0 if entry_fmt > 0 else 0.5
        return {
            'valid': True,
            'amount': amount,
            'margin_usd': (amount * entry_fmt) / leverage,
            'notional_usd': amount * entry_fmt,
            'entry_price': entry_fmt,
            'tp_price': tp_fmt,
            'sl_price': sl_fmt,
            'sl_dist': abs(entry_fmt - sl_fmt),
            'sl_dist_pct': sl_dist_pct,
            'reason': 'OK',
        }

    @staticmethod
    def manage_open_position(exchange, symbol, pos, meta_dict):
        """
        Defesa ativa para posição aberta:
        - Move SL para Breakeven (+0.16% cobrindo taxas) ao atingir +1R ou +0.35% de avanço a favor.
        - Faz Stepped Trailing Stop Server-Side ao atingir +1.6R.
        """
        try:
            contracts = float(pos.get('contracts') or 0)
            if contracts <= 0:
                return
            entry_price = float(pos.get('entryPrice') or meta_dict.get('entry_price') or 0)
            mark_price = float(pos.get('markPrice') or pos.get('info', {}).get('markPrice') or entry_price)
            if entry_price <= 0 or mark_price <= 0:
                return

            side = str(pos.get('side', meta_dict.get('side', 'LONG'))).upper()
            is_long = side in ('LONG', 'BUY')

            sl_dist = meta_dict.get('sl_dist') or (entry_price * 0.006)
            current_sl = meta_dict.get('current_sl') or meta_dict.get('sl_price') or 0.0

            move_fav = (mark_price - entry_price) if is_long else (entry_price - mark_price)
            move_pct = (move_fav / entry_price) * 100.0
            r_multiple = (move_fav / sl_dist) if sl_dist > 0 else 0.0

            new_sl = None
            reason_label = None

            # Estágio 2: Trailing Stop Progressivo (>= 1.6R ou >= 0.60% de lucro na moeda)
            if r_multiple >= 1.6 or move_pct >= 0.60:
                # Protege 65% do movimento conquistado
                locked_move = move_fav * 0.65
                candidate_sl = (entry_price + locked_move) if is_long else (entry_price - locked_move)
                if is_long and (current_sl <= 0 or candidate_sl > current_sl * 1.0012):
                    new_sl = candidate_sl
                    reason_label = f"🛡️ Trailing Stop (+{r_multiple:.1f}R)"
                elif not is_long and (current_sl <= 0 or candidate_sl < current_sl * 0.9988):
                    new_sl = candidate_sl
                    reason_label = f"🛡️ Trailing Stop (+{r_multiple:.1f}R)"

            # Estágio 1: Breakeven Lock (>= 1.0R ou >= 0.32% de lucro na moeda)
            elif (r_multiple >= 1.0 or move_pct >= 0.32) and not meta_dict.get('breakeven_locked'):
                fee_buffer = entry_price * 0.0016  # 0.16% cobre taxas e garante micro-lucro
                candidate_sl = (entry_price + fee_buffer) if is_long else (entry_price - fee_buffer)
                if is_long and (current_sl <= 0 or candidate_sl > current_sl):
                    new_sl = candidate_sl
                    meta_dict['breakeven_locked'] = True
                    reason_label = "🔒 Breakeven (+Taxas) Ativado"
                elif not is_long and (current_sl <= 0 or candidate_sl < current_sl):
                    new_sl = candidate_sl
                    meta_dict['breakeven_locked'] = True
                    reason_label = "🔒 Breakeven (+Taxas) Ativado"

            if new_sl is not None:
                if ExecutionProtocolSkill.update_server_stop_loss(exchange, symbol, new_sl):
                    sl_fmt = float(exchange.price_to_precision(symbol, new_sl))
                    meta_dict['current_sl'] = sl_fmt
                    add_log(f"{reason_label} em {symbol}: Stop Loss movido para ${sl_fmt:.4f} na Bybit!")
        except Exception:
            pass


class ExecutionProtocolSkill:
    """
    Skill 4: Bybit V5 Execution Protocol
    Configura alavancagem/margem, executa ordens Maker-First com fallback atômico e atualiza stops no servidor.
    """

    @staticmethod
    def setup_symbol_derivatives(exchange, symbol, leverage, margin_mode='cross'):
        try:
            exchange.set_margin_mode(margin_mode, symbol)
        except Exception:
            pass
        try:
            exchange.set_leverage(leverage, symbol)
            return True
        except Exception:
            return False

    @staticmethod
    def update_server_stop_loss(exchange, symbol, new_sl_price, new_tp_price=None):
        try:
            market = exchange.market(symbol)
            bybit_symbol = market['id'] if market else symbol.replace('/', '').split(':')[0]
            sl_str = str(exchange.price_to_precision(symbol, new_sl_price))
            payload = {
                'category': 'linear',
                'symbol': bybit_symbol,
                'stopLoss': sl_str,
                'slTriggerBy': 'MarkPrice',
                'positionIdx': 0,
            }
            if new_tp_price is not None and new_tp_price > 0:
                payload['takeProfit'] = str(exchange.price_to_precision(symbol, new_tp_price))
            exchange.privatePostV5PositionTradingStop(payload)
            return True
        except Exception:
            return False

    @staticmethod
    def execute_smart_order(
        exchange,
        symbol,
        side,
        amount,
        entry_price,
        tp_price,
        sl_price,
        allow_market_fallback=True,
        max_wait=10,
    ):
        """
        Tenta entrar via Limit PostOnly (taxa Maker 0.02%) com TP e SL atômicos.
        Se o mercado estiver rápido e rejeitar a PostOnly, usa fallback controlado a mercado
        com TP e SL atômicos embutidos.
        """
        side_norm = 'buy' if str(side).lower() in ('buy', 'long') else 'sell'
        order, filled = place_maker_entry(
            exchange,
            symbol,
            side_norm,
            amount,
            entry_price,
            tp_price,
            sl_price,
            max_wait=max_wait,
        )
        if filled:
            return order, True

        if not allow_market_fallback:
            return order, False

        # Fallback: Execução imediata com TP e SL atômicos anexados
        try:
            amount_fmt = float(exchange.amount_to_precision(symbol, amount))
            tp_str = str(exchange.price_to_precision(symbol, tp_price))
            sl_str = str(exchange.price_to_precision(symbol, sl_price))
            params = {
                'takeProfit': tp_str,
                'stopLoss': sl_str,
                'tpTriggerBy': 'MarkPrice',
                'slTriggerBy': 'MarkPrice',
            }
            mkt_order = exchange.create_order(
                symbol=symbol,
                type='market',
                side=side_norm,
                amount=amount_fmt,
                params=params,
            )
            add_log(f"⚡ Ordem executada (Smart Fallback c/ TP/SL Atômico) em {symbol}!")
            return mkt_order, True
        except Exception as e:
            add_log(f"⚠️ Erro no Smart Execution ({symbol}): {e}")
            return None, False

