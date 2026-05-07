import csv, sys
sys.stdout.reconfigure(encoding='utf-8')

files = [
    'logs/sniper_trades.csv',
    'logs/scalping_10x_trades.csv',
    'logs/leveraged_long_short.csv',
    'logs/survival_trades.csv',
    'logs/survival_market_data.csv',
    'logs/scalping_10x_market_data.csv',
    'logs/leveraged_long_short_market_data.csv',
    'logs/sniper_market_data.csv',
    'logs/scalping_trades.csv',
    'logs/leveraged_long_short_trades.csv',
    'logs/sniper_trades.csv',
    'logs/reverse_martingale_trades.csv',
]

for f in files:
    print(f'\n{"="*60}')
    print(f'  {f}')
    print(f'{"="*60}')
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            reader = csv.DictReader(fh)
            rows = [r for r in reader if r.get('Tipo', '') not in ['SCAN', '']]
            if not rows:
                print('  (nenhuma entrada/saída registrada)')
                continue
            for r in rows[-20:]:
                tipo = r.get('Tipo', '')
                moeda = r.get('Moeda', '')
                direcao = r.get('Direção', r.get('Side', ''))
                preco = r.get('Preço', r.get('Entry_Price', ''))
                status = r.get('Status', '')
                detalhes = r.get('Detalhes', r.get('Reason', ''))
                data = r.get('Data/Hora', r.get('Timestamp', ''))
                pnl = r.get('PnL $', r.get('PnL_USDT', ''))
                saldo = r.get('Saldo USD', '')
                print(f'  {data} | {moeda} | {tipo} | {direcao} | ${preco} | {status} | PnL: {pnl} | Saldo: ${saldo} | {detalhes}')
    except Exception as e:
        print(f'  Erro: {e}')
