---
name: risk-officer-guardrails
description: >-
  Use this skill whenever designing, auditing, or modifying position sizing,
  leverage limits, Stop-Loss / Take-Profit calculation, Breakeven locks,
  Trailing Stops, or daily drawdown circuit breakers.
---

# Risk Officer Guardrails (Mandatory Safety Protocol)

The Risk Officer has **absolute veto power** over every strategy in the repository. No strategy may bypass these rules.

## 1. Zero-Tolerance Rules (Banned Patterns)

1. **NO Naked Positions:** Every derivative order MUST attach a valid `stopLoss` and `takeProfit` atomically on order creation (or immediately verify and close if rejected). Strategies with `STOP LOSS: DESATIVADO` are strictly forbidden.
2. **NO Classic Martingale (Doubling on Loss):** Never increase position size after a losing trade to "recover" losses. Only Anti-Martingale (scaling with *realized profits* up to a capped tier) or Volatility-Adjusted Fractional sizing is permitted.
3. **NO Negative Risk:Reward:** Minimum gross Reward-to-Risk ratio is **1.8 : 1** (default **2.5 : 1 to 3.0 : 1**) after accounting for round-trip fees (0.04% Maker / 0.11% Taker).

## 2. Dynamic ATR Stop-Loss & Volatility Position Sizing

1. **Stop Distance ($D_{\text{SL}}$):**
   - Compute $D_{\text{SL}} = k \times \text{ATR}_{14}$ (where $k \in [1.8, 2.5]$).
   - Clamp $D_{\text{SL}}$ to $[0.40\%, 1.50\%]$ of current price so stops are neither noise-hunted nor liquidation-prone.
2. **Min-Lot vs. Risk Veto (Small Account Protection):**
   - Calculate target notional value from allowed margin risk.
   - Check `market['limits']['amount']['min'] * current_price`.
   - If the exchange's minimum lot notional exceeds $1.35 \times$ the maximum safe notional for that pair, **veto the pair** and scan lower-priced/smaller-lot assets (`XRP`, `DOGE`, `ADA`, `SOL`).

## 3. Active Position Defense (Breakeven + Server-Side Trailing Stop)

Once a position is open, the Risk Officer actively defends capital on every scan cycle:
- **+1.0R Breakeven Lock:** When unrealized profit reaches $\ge 1.0 \times D_{\text{SL}}$, move the exchange Stop-Loss to `entry_price * (1 + 0.0015)` (for Long) or `entry_price * (1 - 0.0015)` (for Short) to guarantee a fee-covered win.
- **+1.8R Stepped / ATR Trail:** As price advances beyond $+1.8R$, trail the exchange Stop-Loss behind price using `RiskOfficer.manage_open_position(...)` which calls Bybit V5's `privatePostV5PositionTradingStop`.
- **Time-Decay Exit:** If a scalping trade stagnates for $> 45$ minutes with positive net PnL ($> +0.3R$) and fading momentum, lock in profit.

## 4. Daily Portfolio Circuit Breakers

- **Daily Drawdown Breaker:** If `total_equity <= initial_equity * (1 - max_daily_loss_pct)` (default `-3%` to `-6%` depending on profile), cancel all open limit orders, log a circuit breaker alert, and stop the bot.
- **Daily Target Lock:** When `total_equity >= initial_equity * (1 + daily_target_pct)`, stop opening new risk.
