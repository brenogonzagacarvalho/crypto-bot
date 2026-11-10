---
name: bybit-v5-execution-protocol
description: >-
  Use this skill when writing or troubleshooting CCXT / Bybit V5 API calls for
  Unified Trading Account (UTA) balances, Maker PostOnly orders, atomic TP/SL,
  server-side trailing stops, and precision formatting.
---

# Bybit V5 Execution Protocol (UTA & Derivatives)

This skill standardizes all interactions with Bybit's V5 API via `ccxt` in [`core/balance_utils.py`](../../core/balance_utils.py) and [`core/quant_skills.py`](../../core/quant_skills.py).

## 1. Symbol Normalization & Precision

- **Linear Perpetuals:** Always format symbols as `BASE/USDT:USDT` (e.g., `BTC/USDT:USDT`, `SOL/USDT:USDT`).
- **Spot:** Format as `BASE/USDT` (e.g., `BTC/USDT`).
- **Precision Formatting:** NEVER use `round(price, 2)`! Coins like `DOGE`, `ADA`, and `XRP` trade at sub-dollar prices with 4–5 decimals. Always use:
  ```python
  amount = float(exchange.amount_to_precision(symbol, raw_amount))
  price = float(exchange.price_to_precision(symbol, raw_price))
  tp_str = exchange.price_to_precision(symbol, raw_tp)
  sl_str = exchange.price_to_precision(symbol, raw_sl)
  ```

## 2. Maker-First (`PostOnly`) Atomic Entry with Fallback

Bybit Taker fee is `0.055%` per leg (`0.11%` round-trip), whereas Maker fee is `0.02%` (`0.04%` round-trip).
1. Use `place_maker_entry(exchange, symbol, side, amount, price, tp_price, sl_price, max_wait=12)` which attaches `'takeProfit': str(tp_price)` and `'stopLoss': str(sl_price)` atomically on the entry order.
2. For high-velocity breakout/sweep signals where `PostOnly` is rejected because price moved 1 tick, `ExecutionProtocolSkill.execute_smart_order(...)` supports a controlled IOC/Market fallback **with atomic `takeProfit` and `stopLoss`** attached in `params`.

## 3. Server-Side TP/SL Modification (`privatePostV5PositionTradingStop`)

Never rely solely on in-memory Python variables for trailing stops (if the process restarts or disconnects, in-memory stops vanish). Always sync updated Stop-Loss / Take-Profit levels directly to Bybit V5:

```python
market = exchange.market(symbol)
exchange.privatePostV5PositionTradingStop({
    'category': 'linear',
    'symbol': market['id'],
    'stopLoss': str(exchange.price_to_precision(symbol, new_sl)),
    'slTriggerBy': 'MarkPrice',
    'positionIdx': 0  # One-Way Mode
})
```

## 4. UTA Collateral & Closed PnL Reconciliation

- Call `enable_btc_collateral(exchange)` at strategy startup so BTC holdings in Unified Trading Account contribute to available margin.
- When a position closes, wait `2.5s` for Bybit V5 settlement and query `get_closed_pnl_details(exchange, symbol)` (`privateGetV5PositionClosedPnl`) to log the exact net PnL after funding and trading fees.

