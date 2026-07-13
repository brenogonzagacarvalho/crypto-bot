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
    const btnStop = document.getElementById('btn-stop');
    const badge = document.getElementById('status-badge');
    const strategyButtons = document.querySelectorAll('button[id^="btn-"]:not(#btn-stop)');

    if (data.is_running) {
        strategyButtons.forEach(btn => btn.disabled = true);
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
        } else if(data.status.includes('Mín/Máx Diária')) {
            badge.style.borderColor = "#06b6d4";
            badge.style.color = "#06b6d4";
            badge.style.boxShadow = "0 0 10px rgba(6,182,212,0.4)";
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
        strategyButtons.forEach(btn => btn.disabled = false);
        btnStop.disabled = true;
        badge.textContent = data.status;
        badge.style.borderColor = "var(--border-color)";
        badge.style.color = "var(--text-secondary)";
        badge.style.boxShadow = "none";
    }

    document.getElementById('coin-label').textContent = data.coin_name || "Moeda Base";
    document.getElementById('coin-balance').textContent = parseFloat(data.coin_balance || 0).toFixed(8);
    document.getElementById('usdt-balance').textContent = parseFloat(data.usdt_balance || 0).toFixed(2);

    // Atualiza UPL (Lucro/Perda das operações abertas)
    if (data.unrealized_pnl !== undefined) {
        const pnlVal = parseFloat(data.unrealized_pnl || 0);
        const pnlEl = document.getElementById('dashboard-unrealized-pnl');
        pnlEl.textContent = `${pnlVal >= 0 ? '+' : ''}${pnlVal.toFixed(2)} USD`;
        pnlEl.className = pnlVal >= 0 ? 'pnl-positive' : 'pnl-negative';
    }

    // Atualiza Saldos de Financiamento na Tela Principal
    if (data.funding_usdt !== undefined) {
        document.getElementById('funding-usdt-balance').textContent = parseFloat(data.funding_usdt || 0).toFixed(2);
    }
    if (data.funding_btc !== undefined) {
        document.getElementById('funding-btc-balance').textContent = parseFloat(data.funding_btc || 0).toFixed(8);
    }

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
    
    if (selectedCoin === "MULTI" && strategyType !== "scalping_10x" && strategyType !== "reverse_martingale" && strategyType !== "sniper" && strategyType !== "survival" && strategyType !== "chameleon" && strategyType !== "fibonacci" && strategyType !== "daily_range") {
        alert("O modo Scanner MULTI está disponível apenas nas estratégias: Survival Scalper, Scalping 10x, Reverse Martingale, Alavancagem Sniper, Camaleão, Retração Fibonacci e Mínima/Máxima Diária.");
        return;
    }
    
    const isDerivatives = strategyType === 'sniper' || strategyType === 'martingale' || strategyType === 'trend' || strategyType === 'reverse_martingale' || strategyType === 'scalping_10x' || strategyType === 'survival' || strategyType === 'longshort_lev' || strategyType === 'double7' || strategyType === 'chameleon' || strategyType === 'fibonacci' || strategyType === 'daily_range';
    
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

// Atualiza status do bot a cada 1 segundo (não consome API pesada)
fetchInterval = setInterval(() => {
    fetchStatus();
}, 1000);

// Atualiza a tabela de posições a cada 5 segundos (evita rate limit da Bybit)
setInterval(() => {
    fetchPositions();
}, 5000);
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
    
    if (tabId === 'history') {
        fetchHistory();
    } else if (tabId === 'earn') {
        fetchEarnData();
    }
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
                body.innerHTML = '<tr><td colspan="8" style="text-align:center;">Nenhuma posição aberta.</td></tr>';
            } else {
                data.positions.forEach(pos => {
                    const tr = document.createElement('tr');
                    const isLong = pos.side.toLowerCase() === 'long';
                    const sideColor = isLong ? 'var(--crypto-green)' : 'var(--crypto-red)';
                    const pnl = parseFloat(pos.unrealizedPnl);
                    const pnlClass = pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
                    
                    const roi = pos.percentage ? parseFloat(pos.percentage) : 0;
                    const baseCoin = pos.symbol.split('/')[0];
                    const quoteCoin = pos.symbol.includes('/') ? pos.symbol.split('/')[1].split(':')[0] : 'USDT';
                    const symbolLabel = pos.symbol.replace(':USDT', '').replace('/', '');
                    
                    tr.innerHTML = `
                        <td>
                            <a href="https://www.bybit.com/en/trade/spot/${baseCoin}/${quoteCoin}" target="_blank" class="position-link" title="Ver gráfico de ${baseCoin}/${quoteCoin} na Bybit">
                                <strong>${symbolLabel} Perpétuos 🔗</strong>
                            </a><br>
                            <span style="font-size:0.75rem; color:${sideColor}">Cruzar ${pos.leverage}.00x</span>
                        </td>
                        <td><span style="color:${sideColor}">${pos.contracts} ${baseCoin}</span></td>
                        <td><strong>${parseFloat(pos.positionValue || 0).toFixed(2)} USDT</strong></td>
                        <td><strong>${parseFloat(pos.entryPrice).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 4})}</strong></td>
                        <td>${parseFloat(pos.markPrice || pos.entryPrice).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 4})}</td>
                        <td><strong style="color:#f59e0b">${pos.liquidationPrice && parseFloat(pos.liquidationPrice) > 0 ? parseFloat(pos.liquidationPrice).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 4}) : '-'}</strong></td>
                        <td class="${pnlClass}">
                            <strong>${pnl >= 0 ? '+' : ''}${pnl.toFixed(4)} USDT</strong><br>
                            <span style="font-size:0.75rem">${roi >= 0 ? '+' : ''}${roi.toFixed(2)}%</span>
                        </td>
                        <td><button class="btn btn-danger" style="padding:0.3rem 0.6rem; font-size:0.75rem; background-color:#333; border:none;" onclick="manualCloseSymbol('${pos.symbol}')">Mercado</button></td>
                    `;
                    body.appendChild(tr);
                });
            }
        }
    } catch (error) {
        console.error("Erro ao buscar posições:", error);
    }
}

async function manualCloseSymbol(symbol) {
    if (!confirm(`Tem certeza que deseja fechar a posição de ${symbol} agora?`)) return;
    
    try {
        const response = await fetch('/api/close_symbol', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol: symbol })
        });
        const data = await response.json();
        alert(data.message || data.error);
        fetchPositions();
    } catch (error) {
        alert("Erro ao fechar posição.");
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

async function fetchHistory() {
    try {
        const response = await fetch('/api/history');
        const data = await response.json();
        
        const body = document.getElementById('history-body');
        
        if (data.history) {
            body.innerHTML = '';
            
            if (data.history.length === 0) {
                body.innerHTML = '<tr><td colspan="8" style="text-align:center;">Nenhum histórico encontrado.</td></tr>';
            } else {
                data.history.forEach(trade => {
                    const tr = document.createElement('tr');
                    
                    const direcaoClass = trade.direcao.includes('LONG') ? 'side-long' : (trade.direcao.includes('SHORT') ? 'side-short' : '');
                    
                    let lucroHTML = '-';
                    if (trade.lucro && trade.lucro !== '-') {
                        const isPositive = trade.lucro.includes('+') || !trade.lucro.includes('-');
                        const colorClass = isPositive ? 'pnl-positive' : 'pnl-negative';
                        lucroHTML = `<span class="${colorClass}">${trade.lucro}</span>`;
                    }
                    
                    let tipoHTML = '-';
                    if (trade.tipo === 'ENTRADA') {
                        tipoHTML = `<span class="badge" style="background: rgba(59, 130, 246, 0.2); color: #3b82f6; border: 1px solid rgba(59, 130, 246, 0.4); padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;">Abertura 📥</span>`;
                    } else if (trade.tipo === 'SAÍDA' || trade.tipo === 'SAIDA') {
                        tipoHTML = `<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.75rem;">Fechamento 📤</span>`;
                    } else {
                        tipoHTML = trade.tipo || '-';
                    }
                    
                    tr.innerHTML = `
                        <td>${trade.data}</td>
                        <td>${trade.estrategia}</td>
                        <td>${tipoHTML}</td>
                        <td><strong>${trade.moeda}</strong></td>
                        <td class="${direcaoClass}">${trade.direcao}</td>
                        <td>$${parseFloat(trade.preco).toFixed(2)}</td>
                        <td>${trade.status}</td>
                        <td>${lucroHTML}</td>
                    `;
                    body.appendChild(tr);
                });
            }
        }
    } catch (error) {
        console.error("Erro ao buscar histórico:", error);
    }
}

// --- BYBIT EARN LOGIC ---
let earnData = {
    unified: {},
    funding: {},
    opportunities: [],
    investments: []
};
let earnYieldInterval;

async function fetchEarnData() {
    try {
        // 1. Saldos de Unified e Funding
        const resBal = await fetch('/api/earn/balances');
        const dataBal = await resBal.json();
        if (dataBal.status === 'ok') {
            earnData.unified = dataBal.unified;
            earnData.funding = dataBal.funding;
            updateEarnBalancesUI();
        }

        // 2. Oportunidades
        const resOpp = await fetch('/api/earn/opportunities');
        const dataOpp = await resOpp.json();
        if (dataOpp.status === 'ok') {
            earnData.opportunities = dataOpp.opportunities;
            renderEarnOpportunities();
        }

        // 3. Investimentos ativos
        await fetchActiveInvestments();
    } catch (err) {
        console.error("Erro ao buscar dados do Bybit Earn:", err);
    }
}

function updateEarnBalancesUI() {
    // Atualiza saldos da UTA
    document.getElementById('earn-unified-usdt').textContent = parseFloat(earnData.unified.USDT || 0).toFixed(2);
    document.getElementById('earn-unified-btc').textContent = parseFloat(earnData.unified.BTC || 0).toFixed(8);
    document.getElementById('earn-unified-eth').textContent = parseFloat(earnData.unified.ETH || 0).toFixed(8);
    document.getElementById('earn-unified-sol').textContent = parseFloat(earnData.unified.SOL || 0).toFixed(8);

    // Atualiza saldos de Financiamento
    document.getElementById('earn-funding-usdt').textContent = parseFloat(earnData.funding.USDT || 0).toFixed(2);
    document.getElementById('earn-funding-btc').textContent = parseFloat(earnData.funding.BTC || 0).toFixed(8);
    document.getElementById('earn-funding-eth').textContent = parseFloat(earnData.funding.ETH || 0).toFixed(8);
    document.getElementById('earn-funding-sol').textContent = parseFloat(earnData.funding.SOL || 0).toFixed(8);
}

function renderEarnOpportunities(filterCoin = '') {
    const body = document.getElementById('earn-opportunities-body');
    body.innerHTML = '';
    
    const filtered = earnData.opportunities.filter(opp => {
        if (!filterCoin) return true;
        return opp.coin.toLowerCase().includes(filterCoin.toLowerCase());
    });

    if (filtered.length === 0) {
        body.innerHTML = `<tr><td colspan="6" style="text-align:center;">Nenhum produto encontrado.</td></tr>`;
        return;
    }

    filtered.forEach(opp => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${opp.name}</strong></td>
            <td><span class="badge" style="border-color: #14b8a6; color: #14b8a6;">${opp.coin}</span></td>
            <td><strong style="color: var(--crypto-green); font-size: 1.1rem;">${opp.apy.toFixed(1)}% a.a.</strong></td>
            <td><span style="color: var(--text-secondary);">${opp.type}</span></td>
            <td>${opp.min_invest} ${opp.coin}</td>
            <td>
                <button class="btn btn-primary" style="background-color: #14b8a6; border-color: #14b8a6; padding: 0.4rem 1rem; font-size: 0.85rem;" onclick="investEarn('${opp.id}', '${opp.name}', '${opp.coin}', ${opp.apy}, ${opp.min_invest})">Investir</button>
            </td>
        `;
        body.appendChild(tr);
    });
}

function filterEarnProducts() {
    const val = document.getElementById('earn-search').value;
    renderEarnOpportunities(val);
}

async function fetchActiveInvestments() {
    try {
        const res = await fetch('/api/earn/investments');
        const data = await res.json();
        if (data.status === 'ok') {
            earnData.investments = data.investments;
            renderActiveInvestments();
            
            // Inicia o atualizador de rendimento em tempo real ao segundo
            if (earnYieldInterval) clearInterval(earnYieldInterval);
            if (earnData.investments.length > 0) {
                earnYieldInterval = setInterval(updateYieldsRealtime, 1000);
            }
        }
    } catch (err) {
        console.error("Erro ao carregar investimentos:", err);
    }
}

function renderActiveInvestments() {
    const body = document.getElementById('active-earn-body');
    body.innerHTML = '';

    if (earnData.investments.length === 0) {
        body.innerHTML = '<tr><td colspan="6" style="text-align:center; padding: 1.5rem;">Nenhum investimento ativo no momento.</td></tr>';
        return;
    }

    earnData.investments.forEach(inv => {
        const tr = document.createElement('tr');
        tr.id = `inv-row-${inv.id}`;
        
        // Determina formato decimal
        const decimals = inv.coin === 'USDT' || inv.coin === 'USDC' ? 4 : 8;
        
        tr.innerHTML = `
            <td>
                <strong>${inv.product_name}</strong><br>
                <span style="font-size:0.75rem; color:var(--text-secondary)">Moeda: ${inv.coin}</span>
            </td>
            <td><strong>${parseFloat(inv.amount).toFixed(decimals)} ${inv.coin}</strong></td>
            <td><strong style="color:var(--crypto-green)">${parseFloat(inv.apy).toFixed(1)}% APY</strong></td>
            <td><span style="font-size:0.85rem;">${inv.date}</span></td>
            <td><strong style="color: var(--crypto-green);" id="yield-display-${inv.id}">Calculating...</strong></td>
            <td>
                <button class="btn btn-danger" style="padding:0.4rem 0.8rem; font-size:0.8rem;" onclick="redeemEarn('${inv.id}')">Resgatar</button>
            </td>
        `;
        body.appendChild(tr);
    });
    
    // Atualiza imediatamente
    updateYieldsRealtime();
}

function updateYieldsRealtime() {
    const now = Math.floor(Date.now() / 1000);
    earnData.investments.forEach(inv => {
        const el = document.getElementById(`yield-display-${inv.id}`);
        if (!el) return;

        const secondsElapsed = Math.max(0, now - inv.timestamp);
        // APY dividido por 100, e pelo total de segundos num ano (365 dias)
        const secondsInYear = 365 * 24 * 60 * 60;
        const interestRatePerSecond = (inv.apy / 100) / secondsInYear;
        const interestEarned = inv.amount * interestRatePerSecond * secondsElapsed;

        const decimals = inv.coin === 'USDT' || inv.coin === 'USDC' ? 8 : 12;
        el.textContent = `+${interestEarned.toFixed(decimals)} ${inv.coin}`;
    });
}

function setTransferMax() {
    const coin = document.getElementById('transfer-coin').value;
    const direction = document.getElementById('transfer-direction').value;
    let maxVal = 0;

    if (direction === 'UNIFIED_TO_FUNDING') {
        maxVal = earnData.unified[coin] || 0;
    } else {
        maxVal = earnData.funding[coin] || 0;
    }

    document.getElementById('transfer-amount').value = maxVal;
}

async function submitTransfer() {
    const coin = document.getElementById('transfer-coin').value;
    const direction = document.getElementById('transfer-direction').value;
    const amount = parseFloat(document.getElementById('transfer-amount').value);

    if (isNaN(amount) || amount <= 0) {
        alert("Por favor, informe um valor válido maior que zero.");
        return;
    }

    try {
        const res = await fetch('/api/earn/transfer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ coin, direction, amount })
        });
        const data = await res.json();
        if (data.error) {
            alert("Falha na transferência:\n" + data.error);
        } else {
            alert(data.message);
            document.getElementById('transfer-amount').value = '';
            fetchEarnData();
        }
    } catch (err) {
        console.error("Erro na transferência:", err);
        alert("Erro de conexão ao efetuar transferência.");
    }
}

async function investEarn(productId, productName, coin, apy, minInvest) {
    const available = earnData.unified[coin] || 0;
    
    const amountStr = prompt(
        `Investir em: ${productName} (${coin})\n` +
        `APY: ${apy}% ao ano\n` +
        `Saldo disponível para Trade (UTA): ${available} ${coin}\n` +
        `Mínimo de investimento: ${minInvest} ${coin}\n\n` +
        `Informe o valor que deseja transferir e alocar:`
    );

    if (amountStr === null) return;
    const amount = parseFloat(amountStr);

    if (isNaN(amount) || amount <= 0) {
        alert("Valor inválido.");
        return;
    }

    if (amount < minInvest) {
        alert(`O valor mínimo para este produto é ${minInvest} ${coin}.`);
        return;
    }

    if (amount > available) {
        alert(`Saldo insuficiente. Você tem apenas ${available} ${coin} disponível.`);
        return;
    }

    try {
        const res = await fetch('/api/earn/invest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                product_id: productId,
                product_name: productName,
                coin: coin,
                amount: amount,
                apy: apy
            })
        });
        const data = await res.json();
        if (data.error) {
            alert("Erro ao investir:\n" + data.error);
        } else {
            alert(data.message);
            fetchEarnData();
        }
    } catch (err) {
        console.error("Erro no investimento:", err);
        alert("Erro de rede ao investir.");
    }
}

async function redeemEarn(investmentId) {
    if (!confirm("Confirmar resgate deste investimento? O valor alocado será transferido de volta para a sua conta de Trade (UTA).")) return;

    try {
        const res = await fetch('/api/earn/redeem', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: investmentId })
        });
        const data = await res.json();
        if (data.error) {
            alert("Erro ao resgatar:\n" + data.error);
        } else {
            alert(data.message);
            fetchEarnData();
        }
    } catch (err) {
        console.error("Erro no resgate:", err);
        alert("Erro de rede ao resgatar.");
    }
}

async function startAutoEarn() {
    if (!confirm("Você deseja que o bot identifique as moedas com saldo disponível na sua conta de Negociação (UTA) e as aloque automaticamente no Bybit Earn?")) return;

    try {
        const res = await fetch('/api/earn/auto-invest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        if (data.error) {
            alert("Erro no Auto-Invest:\n" + data.error);
        } else {
            alert(data.message);
            fetchEarnData();
        }
    } catch (err) {
        console.error("Erro no Auto-Invest:", err);
        alert("Erro de rede ao auto-investir.");
    }
}
