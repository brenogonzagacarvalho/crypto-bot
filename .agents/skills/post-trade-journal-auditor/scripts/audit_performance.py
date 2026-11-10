"""
Automated Post-Trade Performance Auditor (Claude & Grok Quant Desk Skill)
Scans all CSV trade logs in logs/ and computes Win Rate, Profit Factor,
Expectancy, and Max Drawdown per strategy.
"""

import csv
import glob
import os
import re
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
LOG_DIR = os.path.join(ROOT_DIR, 'logs')

PNL_REGEX = re.compile(r'([+-]?\$?\d+\.\d+)')


def extract_pnl(row: dict) -> float | None:
    for col in ('PnL_USDT', 'PnL $', 'PnL', 'Detalhes', 'Reason'):
        val = str(row.get(col, '') or '').strip()
        if not val:
            continue
        if col in ('PnL_USDT', 'PnL $', 'PnL'):
            try:
                v = float(val.replace('$', '').replace('+', ''))
                if v != 0:
                    return v
            except ValueError:
                pass
        if '$' in val or 'LUCRO' in str(row.get('Status', '')) or 'LOSS' in str(row.get('Status', '')):
            m = re.search(r'([+-])\s*\$?\s*(\d+\.\d+)', val)
            if m:
                sign = -1.0 if m.group(1) == '-' else 1.0
                return sign * float(m.group(2))
    return None


def audit_csv(filepath: str) -> dict | None:
    pnls = []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                tipo = str(row.get('Tipo', row.get('Action', ''))).upper()
                if tipo in ('SCAN', 'ENTRADA', 'ENTRY', 'DETECT', 'LIMITE_ENVIADA', ''):
                    continue
                pnl = extract_pnl(row)
                if pnl is not None and pnl != 0.0:
                    pnls.append(pnl)
    except Exception:
        return None

    if not pnls:
        return None

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    net_pnl = sum(pnls)

    # Max Drawdown calculation
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    return {
        'file': os.path.basename(filepath),
        'trades': len(pnls),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': (len(wins) / len(pnls)) * 100.0,
        'gross_win': gross_win,
        'gross_loss': gross_loss,
        'net_pnl': net_pnl,
        'profit_factor': (gross_win / gross_loss) if gross_loss > 0 else float('inf'),
        'expectancy': net_pnl / len(pnls),
        'max_dd': max_dd,
    }


def main():
    print("=" * 88)
    print("📊 QUANT TRADING DESK — POST-TRADE PERFORMANCE AUDIT")
    print("=" * 88)
    if not os.path.exists(LOG_DIR):
        print(f"Nenhum diretório de logs encontrado em {LOG_DIR}")
        return

    files = sorted(glob.glob(os.path.join(LOG_DIR, '*.csv')))
    results = []
    for f in files:
        res = audit_csv(f)
        if res:
            results.append(res)

    if not results:
        print("Nenhum trade fechado com PnL registrado nos arquivos CSV ainda.")
        return

    header = f"{'Arquivo CSV':<28} | {'Trades':>6} | {'Win%':>6} | {'PF':>6} | {'Net PnL':>10} | {'Expect.':>9} | {'Max DD':>8}"
    print(header)
    print("-" * len(header))
    for r in sorted(results, key=lambda x: x['net_pnl'], reverse=True):
        pf_str = f"{r['profit_factor']:.2f}" if r['profit_factor'] != float('inf') else "INF"
        print(
            f"{r['file']:<28} | {r['trades']:>6d} | {r['win_rate']:>5.1f}% | "
            f"{pf_str:>6} | ${r['net_pnl']:>+8.4f} | ${r['expectancy']:>+7.4f} | ${r['max_dd']:>7.4f}"
        )
    print("=" * 88)


if __name__ == '__main__':
    main()

