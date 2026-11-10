# Bybit Quant Trading Desk — Agent Operating Rules (`AGENTS.md` / `CLAUDE.md`)

This repository implements an institutional-grade **Bybit V5 Quantitative Crypto Trading Bot** powered by modular **Claude & Grok Trading Desk Skills** (`core/quant_skills.py` and `.agents/skills/`).

## 1. Installed Quantitative Skills

Whenever modifying, debugging, or creating trading strategies, activate and follow these workspace skills:

1. [`desk-regime-analyst`](./.agents/skills/desk-regime-analyst/SKILL.md): Multi-timeframe (1h/15m/5m) market regime classification (`SQUEEZE_BREAKOUT`, `STRONG_UPTREND`, `STRONG_DOWNTREND`, `MEAN_REVERSION_RANGE`, `HIGH_VOL_CHOP`) and Confluence Scoring (-100 to +100).
2. [`microstructure-funding-scanner`](./.agents/skills/microstructure-funding-scanner/SKILL.md): L2 Order Book Imbalance (`OBI`), Perpetual Funding Rate Squeeze detection, Relative Volume (`RVOL`) whale flow, and ICT/SMC Liquidity Sweep detection.
3. [`risk-officer-guardrails`](./.agents/skills/risk-officer-guardrails/SKILL.md): Mandatory atomic Stop-Loss & Take-Profit, Volatility-Adjusted ATR Position Sizing, Small-Account Min-Lot Veto, Server-Side $+1R$ Breakeven Lock, Stepped/ATR Trailing Stops, and Daily Drawdown Circuit Breakers.
4. [`bybit-v5-execution-protocol`](./.agents/skills/bybit-v5-execution-protocol/SKILL.md): Maker-first `PostOnly` execution with smart fallback, dynamic precision formatting (`price_to_precision`, `amount_to_precision`), UTA BTC/USDT multi-collateral handling, and `privatePostV5PositionTradingStop` server-side stop syncing.
5. [`quant-strategy-lab`](./.agents/skills/quant-strategy-lab/SKILL.md): Blueprints and positive mathematical expectancy ($EV > 0$) specifications for all active strategies.
6. [`post-trade-journal-auditor`](./.agents/skills/post-trade-journal-auditor/SKILL.md): Post-trade CSV auditing (`Win%`, `Profit Factor`, `Expectancy`, `Max Drawdown`).

## 2. Hard Architectural Guardrails

- **Central Quant Engine:** All strategies in `strategies/*.py` MUST import indicators, regime detection, microstructure analysis, risk sizing, and execution helpers from [`core/quant_skills.py`](./core/quant_skills.py) and [`core/market_data.py`](./core/market_data.py).
- **Zero Naked Leveraged Positions:** Every derivative trade MUST include an atomic Stop-Loss (`stopLoss`) and Take-Profit (`takeProfit`). Never disable Stop-Loss.
- **No Classic Martingale:** Never double position size after a loss. Only Anti-Martingale (Paroli/Soros scaling with realized profits) or Volatility-Adjusted Fractional Kelly sizing is allowed.
- **Precision Safety:** Never use hardcoded `round(price, 2)`. Always use `exchange.price_to_precision(symbol, price)` and `exchange.amount_to_precision(symbol, amount)`.

