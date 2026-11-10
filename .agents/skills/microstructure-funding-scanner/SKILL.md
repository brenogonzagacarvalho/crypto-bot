---
name: microstructure-funding-scanner
description: >-
  Use this skill when implementing or debugging Order Book Imbalance (OBI),
  Perpetual Funding Rate squeeze filters, Relative Volume (RVOL) whale detection,
  or Liquidity Sweep (Stop-Hunt) setups on Bybit V5 perpetuals.
---

# Microstructure & Funding Scanner (HyperGrok & PumpGrok Skill)

Retail indicators (EMA, RSI) lag price action. Institutional crypto bots combine technical structure with **market microstructure** from the order book, volume flow, and perpetual swap funding rates.

## 1. Order Book Imbalance (OBI)

Before executing an entry on Bybit Linear Perpetuals, inspect the L2 Order Book top $N$ levels (default $N = 20$):

$$\text{OBI} = \frac{\sum_{i=1}^{N} V_{\text{bid}, i} - \sum_{i=1}^{N} V_{\text{ask}, i}}{\sum_{i=1}^{N} V_{\text{bid}, i} + \sum_{i=1}^{N} V_{\text{ask}, i}} \in [-1.0, +1.0]$$

- **Bullish Absorption / Bid Wall ($\text{OBI} \ge +0.15$):** Buyers dominate passive liquidity; favors `LONG` entries and vetoes weak `SHORT` scalps.
- **Bearish Supply / Ask Wall ($\text{OBI} \le -0.15$):** Sellers dominate passive liquidity; favors `SHORT` entries and vetoes weak `LONG` scalps.
- **Spread Sanity Check:** If $\frac{\text{Ask}_1 - \text{Bid}_1}{\text{MidPrice}} > 0.08\%$, veto scalping entries due to slippage risk.

## 2. Perpetual Funding Rate & Squeeze Detection

Perpetual futures funding rates measure crowded positioning:
- **Crowded Shorts ($\text{Funding Rate} < -0.015\%$):** Shorts are paying longs heavily. If price reclaims VWAP with `RVOL > 1.3`, a **Short Squeeze (`LONG`)** has high asymmetric payoff.
- **Crowded Longs ($\text{Funding Rate} > +0.030\%$):** Overleveraged longs are paying shorts. Avoid chasing late `LONG` breakouts; favor `SHORT` mean-reversion or liquidity sweep setups when momentum stalls.

## 3. Liquidity Sweeps (ICT / SMC Stop-Hunts)

Instead of placing blind limit orders at static support/resistance (like yesterday's low/high), wait for a **Liquidity Sweep + Rejection**:
1. **Bullish Sweep (Turtle Soup Long):**
   - Candle low pierces below key Swing Low (or Yesterday's Low $L_{\text{prev}}$), triggering retail stop-losses.
   - Candle **closes back above** the swept level ($C > L_{\text{prev}}$) with a lower wick $\ge 1.2 \times \text{body}$ and elevated volume (`RVOL >= 1.1`).
2. **Bearish Sweep (Turtle Soup Short):**
   - Candle high pierces above key Swing High (or Yesterday's High $H_{\text{prev}}$).
   - Candle **closes back below** the swept level ($C < H_{\text{prev}}$) with an upper wick $\ge 1.2 \times \text{body}$.

## 4. Implementation Reference

Use `MicrostructureSkill` in [`core/quant_skills.py`](../../core/quant_skills.py):
- `MicrostructureSkill.get_orderbook_imbalance(exchange, symbol, limit=20)`
- `MicrostructureSkill.get_funding_rate(exchange, symbol)`
- `MicrostructureSkill.detect_liquidity_sweep(ohlcv_data, lookback=24)`

