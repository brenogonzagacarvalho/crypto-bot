---
name: post-trade-journal-auditor
description: >-
  Use this skill when auditing trading performance, analyzing CSV trade logs in
  logs/, computing Win Rate, Profit Factor, Expectancy, or diagnosing losing streaks.
---

# Post-Trade Journal & Performance Auditor

This skill provides a repeatable workflow to audit all strategy logs in `logs/*.csv` and evaluate quantitative metrics before adjusting strategy parameters.

## 1. Key Performance Metrics

When auditing any strategy log in `logs/`, compute:
- **Win Rate ($W$):** $\frac{N_{\text{wins}}}{N_{\text{total}}}$
- **Profit Factor ($PF$):** $\frac{\sum \text{Gross Wins}}{\left|\sum \text{Gross Losses}\right|}$ (Target: $PF \ge 1.35$)
- **Average Win / Average Loss Ratio ($R_{\text{realized}}$):** $\frac{\text{Avg Win}}{\left|\text{Avg Loss}\right|}$
- **Net Expectancy per Trade ($EV$):** $\frac{\text{Net PnL}}{N_{\text{total}}}$
- **Maximum Drawdown ($MDD$):** Largest peak-to-trough drop in cumulative PnL.

## 2. Running the Automated Performance Audit

Run the helper script bundled with this skill to generate a complete report across all CSV logs:

```powershell
python .agents/skills/post-trade-journal-auditor/scripts/audit_performance.py
```

## 3. Diagnostic Rules for Strategy Tuning

- **High Win Rate ($>60\%$) but Negative Net PnL ($PF < 1.0$):** Stop-losses are too wide relative to Take-Profit, or positions were held without an active $+1R$ Breakeven lock.
- **Low Win Rate ($<30\%$) with Rapid Stop-Outs:** Strategy is entering during `HIGH_VOL_CHOP` or against HTF trend/Order Book Imbalance. Increase `min_adx` or require HTF EMA50 alignment.
- **High Scan Count with Zero Fills:** `PostOnly` limit price is lagging fast momentum breakouts; enable `allow_market_fallback=True` in `ExecutionProtocolSkill.execute_smart_order` for breakout strategies.

