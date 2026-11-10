---
name: desk-regime-analyst
description: >-
  Use this skill when analyzing market structure, classifying market regimes
  (Uptrend, Downtrend, Mean-Reversion Range, Volatility Squeeze, or Choppy),
  or computing multi-timeframe technical confluence scores for crypto trading strategies.
---

# Desk Regime Analyst (Claude & Grok Quant Skill)

This skill defines the quantitative market regime classification and multi-timeframe (MTF) confluence scoring protocol used by the trading bot's strategy engine (`core/quant_skills.py`).

## 1. Market Regime Taxonomy

Every asset scanned must be classified into one of five mutually exclusive regimes before any strategy can generate an entry signal:

| Regime | Conditions | Allowed Strategy Archetypes |
| :--- | :--- | :--- |
| `SQUEEZE_BREAKOUT` | Bollinger Band Width inside Keltner Channel (or BB Width < 1.8%) followed by expansion + RVOL > 1.5 + ADX rising | Volatility Breakout (`claude_quant_alpha`, `chameleon`) |
| `STRONG_UPTREND` | Price > EMA9 > EMA21 > EMA50 > EMA200 (5m), HTF (1h) Price > EMA50, ADX >= 22, Price > VWAP | Trend Pullback & Momentum (`ema_rsi`, `fibonacci`, `sniper`, `chameleon`) |
| `STRONG_DOWNTREND` | Price < EMA9 < EMA21 < EMA50 < EMA200 (5m), HTF (1h) Price < EMA50, ADX >= 22, Price < VWAP | Short Trend Pullback & Momentum (`ema_rsi`, `fibonacci`, `sniper`, `chameleon`) |
| `MEAN_REVERSION_RANGE` | ADX < 22, BB Width > 1.2%, Price oscillating around EMA200/VWAP without HTF breakout | VWAP Sigma Reversion, Liquidity Sweep YHL, Candlestick + RSI |
| `HIGH_VOL_CHOP` | ATR(14)/Price > 2.5% on 5m with ADX < 15 (erratic whipsaw) or spread/illiquidity spike | **NO TRADING (Hard Veto)** |

## 2. Multi-Timeframe (MTF) Confluence Scoring (-100 to +100)

Never rely on a single indicator (such as raw 1m RSI) to trigger leveraged trades. Compute a composite Confluence Score across 5 dimensions:

1. **HTF Macro Alignment (1h & 15m) [±25 pts]:**
   - `+25` if 1h Close > EMA50 and 15m EMA21 > EMA50.
   - `-25` if 1h Close < EMA50 and 15m EMA21 < EMA50.
2. **LTF Trend & VWAP Structure (5m) [±25 pts]:**
   - `+25` if Close > EMA200 and Close > VWAP.
   - `-25` if Close < EMA200 and Close < VWAP.
3. **Momentum & Oscillator Timing (RSI 14 + MACD Histogram) [±20 pts]:**
   - Trend mode: Pullback into RSI 38–52 (for Long) or 48–62 (for Short) with MACD histogram turning in trend direction.
   - Reversion mode: Extreme RSI (< 28 for Long, > 72 for Short) with hook/inflection (`rsi_curr > rsi_prev` for Long).
4. **Volatility & Volume Confirmation (RVOL & BB/Keltner) [±15 pts]:**
   - Relative Volume `RVOL = vol[-2] / SMA(vol, 20)`. Require `RVOL >= 1.2` for breakouts and exhaustion sweeps.
5. **Microstructure & Candle Anatomy [±15 pts]:**
   - Closed candle (`index -2`) rejection wick ratio (`wick / body >= 1.5`), engulfing structure, and Order Book Imbalance (`OBI`).

## 3. Implementation Reference

Always import and call the shared implementation in [`core/quant_skills.py`](../../core/quant_skills.py):
- `MarketRegimeSkill.analyze_asset(exchange, symbol, ltf='5m', htf='1h')`
- Always evaluate candle patterns on the **last closed candle (`index -2`)** to prevent intra-bar repainting.
