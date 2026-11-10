# Bybit Quant Trading Desk 🤖📈 (Claude & Grok Skills Edition)

Um robô quantitativo de negociação automatizada para **Bybit V5 (Unified Trading Account - UTA)** com interface Desktop/Web em tempo real, arquitetura de **Skills Agênticas (`Claude` & `Grok`)** e motor institucional de risco e execução (`core/quant_skills.py`).

---

## 🧩 Agent Skills Instaladas (`.agents/skills/` & `.claude/skills/`)

O repositório incorpora 6 skills especializadas inspiradas nos ecossistemas **Claude Trading Skills (`claude-trader`)** e **Grok Trading Desk (`hypergrok-trading-desk` / `PumpGrok`)**:

1. **`desk-regime-analyst`**: Classificação multi-timeframe (15m + 5m/3m) de regime de mercado (`STRONG_BULL`, `STRONG_BEAR`, `RANGING`, `SQUEEZE_BUILDUP`, `CHOPPY_NO_TRADE`), detector de **TTM Volatility Squeeze** (Bollinger vs Keltner), **ADX (14)** e **VWAP Institucional com Bandas ($\pm 1\sigma, \pm 2\sigma, \pm 3\sigma$)**.
2. **`microstructure-funding-scanner`**: Leitura de microestrutura L2 (**Order Book Imbalance - OBI**), detecção de **Spoofing / Liquidez Rasa**, **Funding Rate Squeeze** e **Volume Relativo (`RVOL`)**.
3. **`risk-officer-guardrails`**: Dimensionamento baseado na distância real do Stop Loss (`calc_position_size`), trava de perda máxima diária (**Daily Drawdown Circuit Breaker**), filtro de correlação de portfólio e alavancagem adaptativa segura.
4. **`bybit-v5-execution-protocol`**: Execução atômica na Bybit V5 com `stopLoss`, `takeProfit`, `slTriggerBy: MarkPrice` na própria ordem de abertura, formatação dinâmica de precisão (`price_to_precision` / `amount_to_precision`) e sincronização real do **Trailing Stop** na corretora (`privatePostV5PositionTradingStop`).
5. **`quant-strategy-lab`**: Padrões de arquitetura para criação e refatoração de estratégias sem bloqueio de thread, sem Martingale tóxico e com expectativa matemática positiva ($EV > 0$).
6. **`post-trade-journal-auditor`**: Auditoria estatística pós-trade (`Win Rate`, `Profit Factor`, `Expectancy`, `Sharpe`, `Max Drawdown`) com script CLI em `.agents/skills/post-trade-journal-auditor/scripts/audit_performance.py`.

---

## 🚀 Estratégias Quantitativas Ativas

### Novas Estratégias Flagship (Claude & Grok)
1. **🤖 Claude Quant Alpha (`strategies/claude_quant_alpha.py`)**
   - **Tese**: Combina o **TTM Volatility Squeeze Breakout** e **Trend Pullback** com filtro Macro 15m (`EMA 200` + `ADX`) e **Exhaustion Reversion** na banda de $\pm 2.2\sigma$ da VWAP quando o mercado está lateral (`RANGING`).
2. **🧠 Grok Whale Flow (`strategies/grok_whale_flow.py`)**
   - **Tese**: Detecta agressão institucional no livro de ofertas (**OBI L2**), **Funding Rate Squeeze** (short/long squeeze contra posicionamento sobrecarregado do varejo) e **Liquidity Sweep** com ignição de volume (`RVOL >= 1.3x`).

### Estratégias Refatoradas com `core/quant_skills.py`
3. **📐 Retração Fibonacci 61.8% OTF (`strategies/fibonacci_retracement.py`)**: Swing High/Low dinâmico, confluência com banda Golden Pocket (`50% - 65%`), `RVOL`, `OBI` e `TrailingStopEngine` sincronizado na Bybit.
4. **🦎 Camaleão Quant (`strategies/chameleon_strategy.py`)**: Alterna automaticamente entre **Trend Pullback** (`ADX >= 22`) e **VWAP Mean Reversion** (`RANGING`) em velas de 3m com confirmação macro de 15m.
5. **🌊 VWAP Z-Score Mean Reversion (`strategies/vwap_deviation_scalper.py`)**: Opera Long e Short em desvios estatísticos ($\pm 2.0\sigma$) da VWAP com rejeição de pavio e Stop Loss nativo baseado em `ATR`.
6. **📐 Liquidez Diária PDH/PDL Sweep (`strategies/daily_range_scalper.py`)**: Opera armadilhas de liquidez (*Stop Hunts / SFP*) nas máximas e mínimas do dia anterior (`PDH`/`PDL`) tanto na ponta compradora quanto vendedora.
7. **⚡ EMA Ribbon + RSI + ADX (`strategies/ema_rsi_scalper.py`)**: Scalper bidirecional (Long & Short) com alinhamento de `EMA 9 > EMA 21 > EMA 50`, `ADX >= 20`, `RVOL` e Stop Loss estrutural.
8. **🕯️ Candlestick + RSI + RVOL (`strategies/candlestick_rsi_scalper.py`)**: Reconhecimento anatômico de padrões (*Hammer*, *Shooting Star*, *Bullish/Bearish Engulfing*) nos extremos de RSI e bandas de Bollinger com ciclo completo de gerenciamento de posição.
9. **⚔️ Survival Scalper (`strategies/survival_scalper.py`)**: Projetado para contas pequenas com alavancagem adaptativa controlada (`8x-12x`), Stop Loss obrigatório na corretora e validação de lote mínimo Bybit V5.
10. **🎯 Sniper RVOL (`strategies/sniper_leverage.py`)** & **🔥 Anti-Martingale Pro (`strategies/reverse_martingale_pro.py`)**: Operações de convicção máxima e piramidação apenas com lucro acumulado da banca, com `TrailingStopEngine` sincronizado na Bybit.

*(Estratégias tóxicas ou quebradas como Martingale Clássico, Dobrar em 7 Dias e algoritmos sem Stop Loss foram removidas para proteção da conta).*

---

## ▶️ Como Usar

### Aplicativo Desktop ou Dashboard Web
```bash
python desktop_app.py
# ou via navegador em http://127.0.0.1:5000:
python web_app.py
```

### Auditoria Quantitativa de Performance
```bash
python .agents/skills/post-trade-journal-auditor/scripts/audit_performance.py --csv trade_history.csv
```
