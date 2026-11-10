---
name: quant-strategy-lab
description: >-
  Use this skill when creating new trading strategies, refactoring existing
  strategies, or optimizing entry/exit logic for positive mathematical expectancy.
---

# Quant Strategy Lab (Claude & Grok Strategy Blueprints)

Every strategy in [`strategies/`](../../strategies/) must have a clear quantitative edge, positive expected value ($EV > 0$), and full integration with [`core/quant_skills.py`](../../core/quant_skills.py).

## 1. Mathematical Expectancy Formula

Before deploying or modifying any strategy, verify its theoretical expectancy per trade:

$$EV = (W \times R_{\text{win}}) - ((1 - W) \times R_{\text{loss}}) - F_{\text{roundtrip}}$$

Where:
- $W$: Expected Win Rate (e.g., $0.42$ for trend/breakout, $0.58$ for mean-reversion).
- $R_{\text{win}} / R_{\text{loss}}$: Net Reward-to-Risk ratio (minimum $2.0$ for trend/breakout, $1.8$ for mean-reversion).
- $F_{\text{roundtrip}}$: Fee drag in $R$-multiples.

## 2. Approved Strategy Lineup

| Strategy ID | File | Core Edge / Blueprint |
| :--- | :--- | :--- |
| `claude_alpha` | `strategies/claude_quant_alpha.py` | **Claude Quant Alpha:** Bollinger/Keltner Volatility Squeeze + ADX Acceleration + MTF Confluence Score ($\ge 65$) + Volatility-Adjusted Kelly sizing |
| `grok_flow` | `strategies/grok_whale_flow.py` | **Grok Whale Flow & Funding Squeeze:** Order Book Imbalance ($\|\text{OBI}\| \ge 0.18$) + Relative Volume Spike ($\text{RVOL} \ge 1.5$) + Funding Rate Squeeze / Liquidity Sweep |
| `chameleon` | `strategies/chameleon_strategy.py` | **Camaleão Adaptive Regime:** Dynamically switches between Trend Pullback (in `STRONG_UPTREND`/`DOWNTREND`) and VWAP/Wick Mean Reversion (in `RANGE`) |
| `fibonacci` | `strategies/fibonacci_retracement.py` | **Fibonacci Golden Pocket (61.8%–78.6%):** Structural swing detection + HTF EMA/VWAP alignment + Rejection Wick + OBI confirmation |
| `vwap_deviation` | `strategies/vwap_deviation_scalper.py` | **Institutional VWAP $\pm 2\sigma$ Reversion:** Statistical Z-Score deviation ($\|Z\| \ge 2.0$) + RSI inflection + Exhaustion candle + Atomic ATR SL |
| `daily_range` | `strategies/daily_range_scalper.py` | **YHL Liquidity Sweep (ICT Turtle Soup):** Sweeps Yesterday's High/Low or 24h range extreme and reclaims inside with volume confirmation |
| `survival` | `strategies/survival_scalper.py` | **Survival Micro-Account Compounder:** Smart min-lot filter + MTF Trend/Reversion confluence + rapid Breakeven lock at $+0.8R$ |
| `ema_rsi` | `strategies/ema_rsi_scalper.py` | **EMA 9/21/50 + RSI + ADX Momentum:** High-velocity trend pullback/crossover filtered by $\text{ADX} \ge 20$ and Order Book Imbalance |
| `candlestick_rsi` | `strategies/candlestick_rsi_scalper.py` | **Price Action Pinbar/Engulfing + RSI + RVOL:** Closed-candle institutional price action patterns at Bollinger/VWAP extremes |
| `sniper` | `strategies/sniper_leverage.py` | **High-Conviction Confluence Sniper:** Waits for extreme multi-indicator alignment ($\text{Score} \ge 70$) with precision ATR stops |
| `reverse_martingale` | `strategies/reverse_martingale_pro.py` | **Anti-Martingale Soros Pro:** Scales position size *only* using realized profits from consecutive wins (4-tier Paroli engine) with server-side stepped trailing stops |
| `spot` | `strategies/live_predictor.py` | **Spot Multi-Factor Predictor:** Unleveraged Spot accumulation/rotation using MTF Confluence Score and trailing protection |
| `longshort_lev` | `strategies/hybrid_long_short_leverage.py` | **Regime-Weighted Long/Short Futures:** Dynamic delta-adjusted allocation across market regimes |

## 3. Standard Strategy Loop Architecture

Every strategy loop in `strategies/*.py` must follow this 5-step cycle:
1. **Health & Equity Check:** Read UTA balance via `get_available_margin_usd(exchange)`, update `bot_state["usdt_balance"]`, and check `RiskOfficer.check_daily_limits(...)`.
2. **Open Position Sync & Active Defense:** Fetch open positions, reconcile closed positions via `get_closed_pnl_details`, and call `RiskOfficer.manage_open_position(...)` to enforce $+1R$ Breakeven and server-side Trailing Stops.
3. **Market Regime & Microstructure Scan:** Call `MarketRegimeSkill.analyze_asset(...)` and `MicrostructureSkill.analyze_microstructure(...)`.
4. **Signal Evaluation & Risk Veto:** Verify strategy entry criteria + `RiskOfficer.calculate_order_sizing(...)` (which enforces min-lot safety and atomic TP/SL).
5. **Execution & Audit Logging:** Execute via `ExecutionProtocolSkill.execute_smart_order(...)` and record structured CSV + terminal logs.

