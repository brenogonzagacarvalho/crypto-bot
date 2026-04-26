let fetchInterval;

async function fetchStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        updateUI(data);
    } catch (error) {
        console.error("Erro ao buscar status:", error);
    }
}

function updateUI(data) {
    // Atualiza Botões e Status
    const btnStart = document.getElementById('btn-start');
    const btnSniper = document.getElementById('btn-sniper');
    const btnMartingale = document.getElementById('btn-martingale');
    const btnTrend = document.getElementById('btn-trend');
    const btnStop = document.getElementById('btn-stop');
    const badge = document.getElementById('status-badge');

    if (data.is_running) {
        btnStart.disabled = true;
        btnSniper.disabled = true;
        btnMartingale.disabled = true;
        btnTrend.disabled = true;
        btnStop.disabled = false;
        badge.textContent = data.status;
        
        if(data.status.includes('Sniper')) {
            badge.style.borderColor = "#f97316";
            badge.style.color = "#f97316";
            badge.style.boxShadow = "0 0 10px rgba(249,115,22,0.4)";
        } else if(data.status.includes('Martingale') && !data.status.includes('Rev')) {
            badge.style.borderColor = "#8b5cf6";
            badge.style.color = "#8b5cf6";
            badge.style.boxShadow = "0 0 10px rgba(139,92,246,0.4)";
        } else if(data.status.includes('Scalper')) {
            badge.style.borderColor = "#3b82f6";
            badge.style.color = "#3b82f6";
            badge.style.boxShadow = "0 0 10px rgba(59,130,246,0.4)";
        } else if(data.status.includes('Rev. Martingale')) {
            badge.style.borderColor = "#ef4444";
            badge.style.color = "#ef4444";
            badge.style.boxShadow = "0 0 10px rgba(239,68,68,0.4)";
        } else if(data.status.includes('Scalping (10x)')) {
            badge.style.borderColor = "#10b981";
            badge.style.color = "#10b981";
            badge.style.boxShadow = "0 0 10px rgba(16,185,129,0.4)";
        } else {
            badge.style.borderColor = "var(--crypto-green)";
            badge.style.color = "var(--crypto-green)";
            badge.style.boxShadow = "0 0 10px var(--crypto-green-glow)";
        }
    } else {
        btnStart.disabled = false;
        btnSniper.disabled = false;
        btnMartingale.disabled = false;
        btnTrend.disabled = false;
        btnStop.disabled = true;
        badge.textContent = data.status;
        badge.style.borderColor = "var(--border-color)";
        badge.style.color = "var(--text-secondary)";
        badge.style.boxShadow = "none";
    }

    // Atualiza Saldos
    document.getElementById('coin-label').textContent = data.coin_name || "Moeda Base";
    document.getElementById('coin-balance').textContent = parseFloat(data.coin_balance || 0).toFixed(8);
    document.getElementById('usdt-balance').textContent = parseFloat(data.usdt_balance || 0).toFixed(2);

    // Atualiza Mercado
    const priceEl = document.getElementById('current-price');
    // Efeito de piscar se mudar
    const oldPrice = parseFloat(priceEl.textContent);
    const newPrice = parseFloat(data.current_price);
    
    priceEl.textContent = newPrice.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    
    if (newPrice > oldPrice && oldPrice > 0) {
        priceEl.style.color = "var(--crypto-green)";
        setTimeout(() => priceEl.style.color = "", 500);
    } else if (newPrice < oldPrice && oldPrice > 0) {
        priceEl.style.color = "var(--crypto-red)";
        setTimeout(() => priceEl.style.color = "", 500);
    }

    // Atualiza RSI/EMA - label dinâmico dependendo da estratégia
    const indicatorLabel = document.getElementById('indicator-label');
    const isScalper = data.status && data.status.includes('Scalper');
    if (isScalper) {
        indicatorLabel.textContent = 'EMA9 (Médias)';
        document.getElementById('rsi-value').textContent = parseFloat(data.rsi).toFixed(0);
    } else {
        indicatorLabel.textContent = 'RSI (14)';
        document.getElementById('rsi-value').textContent = parseFloat(data.rsi).toFixed(1);
    }
    document.getElementById('rsi-status').textContent = data.rsi_status;

    // Atualiza Logs
    const terminal = document.getElementById('terminal-logs');
    terminal.innerHTML = '';
    data.logs.forEach(log => {
        const p = document.createElement('p');
        p.className = 'log-line';
        // Colore logs específicos
        if(log.includes('SINAL') || log.includes('PREVISÃO')) p.style.color = '#fbbf24';
        if(log.includes('ORDEM')) p.style.color = '#38bdf8';
        if(log.includes('Erro')) p.style.color = '#ef4444';
        p.textContent = log;
        terminal.appendChild(p);
    });
    // Rola para o final
    terminal.scrollTop = terminal.scrollHeight;
}

async function startBot(strategyType = 'spot') {
    const selectedCoin = document.getElementById('coin-selector').value;
    
    if (selectedCoin === "MULTI" && strategyType !== "scalping_10x" && strategyType !== "reverse_martingale" && strategyType !== "sniper") {
        alert("O modo Scanner MULTI (BTC, ETH, SOL) está disponível apenas nas novas estratégias: Scalping 10x, Reverse Martingale e Alavancagem Sniper.");
        return;
    }
    
    const isDerivatives = strategyType === 'sniper' || strategyType === 'martingale' || strategyType === 'trend' || strategyType === 'reverse_martingale' || strategyType === 'scalping_10x' || strategyType === 'survival';
    
    let symbol = "";
    if (selectedCoin === "MULTI") {
        symbol = "MULTI";
    } else {
        symbol = isDerivatives ? `${selectedCoin}/USDT:USDT` : `${selectedCoin}/USDT`;
    }
    
    
    try {
        await fetch('/api/start', { 
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ strategy: strategyType, symbol: symbol })
        });
        fetchStatus();
    } catch (error) {
        alert("Erro ao iniciar bot");
    }
}

async function stopBot() {
    try {
        await fetch('/api/stop', { method: 'POST' });
        fetchStatus();
    } catch (error) {
        alert("Erro ao parar bot");
    }
}

// Atualiza a cada 1 segundo
fetchInterval = setInterval(() => {
    fetchStatus();
    fetchPositions();
}, 1000);
fetchStatus(); // Busca inicial
fetchPositions();

// --- NOVAS FUNÇÕES PARA ABAS E POSIÇÕES ---

function switchTab(tabId) {
    // Esconde todos os conteúdos
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    // Desativa todos os botões
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

    // Mostra o selecionado
    document.getElementById('tab-' + tabId).classList.add('active');
    document.getElementById('tab-btn-' + tabId).classList.add('active');
}

async function fetchPositions() {
    try {
        const response = await fetch('/api/positions');
        const data = await response.json();
        
        const body = document.getElementById('positions-body');
        const posCount = document.getElementById('pos-count');
        
        if (data.positions) {
            posCount.textContent = data.positions.length;
            body.innerHTML = '';
            
            if (data.positions.length === 0) {
                body.innerHTML = '<tr><td colspan="6" style="text-align:center;">Nenhuma posição aberta.</td></tr>';
            } else {
                data.positions.forEach(pos => {
                    const tr = document.createElement('tr');
                    const sideClass = pos.side.toLowerCase() === 'long' ? 'side-long' : 'side-short';
                    const pnl = parseFloat(pos.unrealizedPnl);
                    const pnlClass = pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
                    
                    tr.innerHTML = `
                        <td><strong>${pos.symbol}</strong></td>
                        <td class="${sideClass}">${pos.side}</td>
                        <td>${pos.leverage}x</td>
                        <td>${pos.contracts}</td>
                        <td>$${parseFloat(pos.entryPrice).toFixed(2)}</td>
                        <td class="${pnlClass}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(4)} USDT</td>
                    `;
                    body.appendChild(tr);
                });
            }
        }
    } catch (error) {
        console.error("Erro ao buscar posições:", error);
    }
}

async function manualCloseAll() {
    if (!confirm("Tem certeza que deseja fechar TODAS as posições abertas agora?")) return;
    
    try {
        const response = await fetch('/api/close_all', { method: 'POST' });
        const data = await response.json();
        alert(data.message);
        fetchPositions();
    } catch (error) {
        alert("Erro ao fechar posições.");
    }
}
