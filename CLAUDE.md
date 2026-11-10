# Bybit Quant Trading Desk — Claude Code Rules (`CLAUDE.md`)

See [`AGENTS.md`](./AGENTS.md) for the complete Trading Desk Operating Model and mandatory guardrails.

## Quick Skill Index (`.agents/skills/` & `.claude/skills/`)

- **`desk-regime-analyst`**: Market regime detection (ADX, Bollinger/Keltner Squeeze, Multi-EMA, VWAP $\pm \sigma$) & MTF Confluence Score.
- **`microstructure-funding-scanner`**: Order Book Imbalance (`OBI`), Funding Rate extremes, Relative Volume (`RVOL`), and Liquidity Sweeps.
- **`risk-officer-guardrails`**: ATR dynamic stops, Min-Lot vs Risk veto, $+1R$ Breakeven lock, Server-Side Trailing Stop, and Daily Circuit Breakers.
- **`bybit-v5-execution-protocol`**: Bybit V5 UTA `PostOnly` Maker execution, atomic TP/SL, and `privatePostV5PositionTradingStop` syncing.
- **`quant-strategy-lab`**: Strategy mathematical expectancy blueprints (`claude_alpha`, `grok_flow`, `chameleon`, `fibonacci`, `vwap_deviation`, `daily_range`, `survival`, `ema_rsi`, `candlestick_rsi`, `sniper`, `reverse_martingale`).
- **`post-trade-journal-auditor`**: Run `python .agents/skills/post-trade-journal-auditor/scripts/audit_performance.py` to audit strategy CSV logs.

