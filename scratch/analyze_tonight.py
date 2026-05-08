import csv
import os
import glob

log_dir = 'c:/Users/Carvalho/Dev/ganharDolar/crypto-bot/logs/'
files = glob.glob(os.path.join(log_dir, '*.csv'))

targets = ['2026-05-07 20', '2026-05-07 21', '2026-05-07 22', '2026-05-07 23', '2026-05-08 00', '2026-05-08 01']

for f in files:
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            reader = csv.DictReader(fh)
            rows = []
            for r in reader:
                data = r.get('Data/Hora', r.get('Timestamp', r.get('Time', '')))
                if any(t in data for t in targets):
                    rows.append(r)
            
            if rows:
                print(f'\n{"="*60}')
                print(f'  {os.path.basename(f)}')
                print(f'{"="*60}')
                total_pnl = 0.0
                wins = 0
                losses = 0
                for r in rows:
                    tipo = r.get('Tipo', r.get('Action', ''))
                    if tipo == 'SCAN': continue
                    
                    pnl_str = r.get('Detalhes', '')
                    if pnl_str.startswith('$'):
                        pnl_str = pnl_str.replace('$', '').replace('+', '').strip()
                        if pnl_str:
                            try:
                                pnl_val = float(pnl_str)
                                total_pnl += pnl_val
                                if pnl_val > 0:
                                    wins += 1
                                elif pnl_val < 0:
                                    losses += 1
                            except ValueError:
                                pass
                print(f'Total Trades: {wins+losses} (Wins: {wins}, Losses: {losses})')
                print(f'Net PnL: ${total_pnl:.4f}')
    except Exception as e:
        print(f'Erro in {f}: {e}')
