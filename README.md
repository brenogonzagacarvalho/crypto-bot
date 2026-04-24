# Bybit Trade Bot 🤖📈

Um robô de trading automatizado focado na exchange **Bybit**, encapsulado em um aplicativo Desktop nativo. O bot possui interface gráfica, integração com Unified Trading Account (UTA) e múltiplas estratégias de operações que variam do formato super conservador até alavancagem extrema em derivativos.

## 🚀 Funcionalidades

- **Dashboard Gráfico Local:** Interface construída com HTML/CSS/JS renderizada via `pywebview` e servida em `Flask`, rodando direto na sua máquina (sem necessidade de servidor em nuvem).
- **Múltiplas Estratégias:** Algoritmos variados para diferentes perfis de risco e metas de lucro.
- **Suporte a Derivativos (Futuros):** Operações com alavancagem de até 100x configuradas automaticamente pelo bot.
- **Integração V5 Bybit:** Conexão robusta utilizando a API v5 e suporte nativo à Carteira Unificada (Unified Trading Account).
- **Gerenciamento de Risco:** Ordens de Stop Loss (SL) e Take Profit (TP) enviadas na mesma transação.

## 🧠 Estratégias Inclusas

1. **Spot (Seguro):** Opera no mercado à vista identificando tendências, sem risco de liquidação.
2. **Scalping 10x ($15/sem):** Estratégia de consistência que visa pequenos lucros frequentes, operando com 10x de alavancagem e SL extremamente rigoroso para proteger o capital (ideal para bancas pequenas).
3. **Trend Scalper (EMA):** Utiliza cruzamento de médias móveis exponenciais (EMA 9 e EMA 21) para surfar as ondas de tendência.
4. **Martingale RSI:** Estratégia de alto risco que usa o Martingale clássico, dobrando a posição após um _loss_ (baseado em suportes e resistências via RSI).
5. **Reverse Martingale ($100/dia):** Altíssimo risco/retorno. Opera com 100x de alavancagem e dobra a mão **apenas quando ganha** (Soros). Em 5-6 vitórias consecutivas transforma $1 em $100, arriscando apenas $1 inicial.
6. **Alavancagem Sniper:** Entradas do tipo All-In focadas em topos/fundos extremos.

## ⚙️ Instalação e Configuração

### 1. Pré-requisitos
- Python 3.9+ instalado
- Conta na Bybit com API Keys geradas (permissões de Leitura e Trade em Spot e Contratos).

### 2. Clonando o Repositório
```bash
git clone https://github.com/SEU_USUARIO/crypto-bot.git
cd crypto-bot
```

### 3. Instalando Dependências
Instale as bibliotecas necessárias para rodar o projeto:
```bash
pip install flask ccxt pywebview
```

### 4. Configurando Variáveis de Ambiente
Crie um arquivo chamado `.env` na raiz do projeto (mesmo local do `desktop_app.py`) com as suas chaves da Bybit:

```env
BYBIT_API_KEY=sua_api_key_aqui
BYBIT_API_SECRET=seu_api_secret_aqui
```

## ▶️ Como Usar

Para rodar o bot como um **Aplicativo Desktop**, execute:

```bash
python desktop_app.py
```
Uma janela nativa se abrirá. Escolha o par de moedas, selecione a estratégia desejada nos botões inferiores e acompanhe os logs em tempo real no terminal integrado.

*(Você também pode utilizar `python web_app.py` caso prefira acessar a interface pelo navegador padrão em `http://localhost:5000`)*

## 📦 Compilando para Executável (.exe)
Se desejar gerar um arquivo `.exe` para rodar sem precisar abrir o terminal, basta executar o script de build:
```bash
build_exe.bat
```
*(Certifique-se de ter o `pyinstaller` instalado: `pip install pyinstaller`)*

## ⚠️ Aviso Legal (Disclaimer)

**Este software é para fins educacionais e experimentais.**
O uso de robôs de negociação, especialmente utilizando alta alavancagem (derivativos), envolve risco extremo de perda de capital (risco de liquidação). O autor não se responsabiliza por perdas financeiras resultantes do uso deste software. Gerencie seu risco de forma responsável.
