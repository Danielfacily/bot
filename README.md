# Binance Futures USDT-M Trading Bot

Bot de trading algorítmico para futuros perpétuos USDT-M na Binance, com análise técnica multi-timeframe, gestão de risco dinâmica baseada em ATR e modo paper para testes seguros.

> Não existe promessa de assertividade ou lucro. Valide sempre em modo paper antes de operar com dinheiro real.

---

## Perfil Padrão

| Parâmetro | Valor |
|---|---|
| Mercado | Futuros Perpétuos USDT-M (Binance) |
| Estilo | Scalping / Swing curto |
| Timeframe primário | 15 minutos |
| Confirmação | 1 hora |
| Alavancagem padrão | 10x |
| Alavancagem máxima | 20x |
| Margem por trade | 5 a 10 USDT |
| Score mínimo | 70 / 100 |
| Stop Loss | 1.5× ATR |
| TP1 — fechar 50% | 2.0× ATR |
| TP2 — fechar restante | 3.5× ATR |
| Drawdown máximo diário | 5% |
| Trades máximos por dia | 20 |

---

## Arquitetura

```
backend/
├── app/
│   ├── config.py              # Configurações de infraestrutura (env vars)
│   ├── indicators.py          # EMA, RSI, MACD, BB, ATR, ADX, Volume Delta
│   ├── strategy_engine.py     # Análise técnica + scoring multi-timeframe
│   ├── risk_manager.py        # Gestão de risco, SL/TP dinâmico, limites diários
│   ├── order_manager.py       # Abertura/fechamento de ordens (paper e real)
│   ├── market_scanner.py      # Scanner de moedas quentes por volume/volatilidade
│   ├── main.py                # Loops principais, FastAPI app
│   ├── models/trading.py      # Modelos SQLAlchemy (Trade, Signal, Order, ...)
│   └── services/
│       ├── config_store.py    # Parâmetros de risco persistidos no banco
│       ├── state.py           # Estado global em memória + rastreamento diário
│       ├── logger.py          # Log dual: banco de dados + terminal
│       ├── ai_exit_manager.py # Gestão ativa de saída por análise de indicadores
│       └── trade_sync.py      # Sincronização de PnL com a exchange
├── trading_params.yaml        # Referência documentada de todos os parâmetros
└── requirements.txt
```

---

## Análise Técnica — Stack de Indicadores

### Tendência (2 indicadores)
- **EMA 9/21/50/200** — alinhamento de médias exponenciais no 15m e confirmação no 1h
- **ADX 14** — força da tendência; sinal penalizado em mercado lateral (ADX < 25)

### Momentum (2 indicadores)
- **MACD 12/26/9** — histograma crescente/decrescente pontua o sinal
- **RSI 14** — filtra zonas de sobrecompra/sobrevenda extremas

### Volume (2 indicadores)
- **Volume Delta** — pressão compradora (+) ou vendedora (-) estimada por candle
- **Relative Volume** — volume atual vs. média de 20 candles (>1.35x = significativo)

### Auxiliares
- **Bollinger Bands 20/2** — rompimentos de banda pontuam o sinal
- **ATR 14** — dimensiona SL e TP dinamicamente, e filtra volatilidade
- **VWAP cumulativo** — referência de preço justo intraday

### Sistema de Confluência (Score 0–100)

| Indicador / Condição | Pontos |
|---|---|
| Confirmação no 1h (bônus/penalidade) | +15 / -10 |
| Alinhamento EMA 9>21>50 (15m) | +18 |
| Rompimento de máxima / mínima (20 candles) | +16 |
| Volume acima da média (>1.35×) | +14 |
| Preço vs. VWAP | +12 |
| RSI em zona favorável | +10 |
| Candle de força (corpo >65%) | +10 |
| Mercado em tendência — ADX ≥ 25 | +9 |
| Volatilidade operável — ATR relativo | +8 |
| Volume Delta favorável | +8 |
| MACD com momentum | +6 |
| Rompimento da Bollinger Band | +5 |

**Threshold de entrada: ≥ 70 pontos** (configurável via API).

---

## Gestão de Risco

### Stop Loss Dinâmico
```
LONG : SL = entrada − (1.5 × ATR)
SHORT: SL = entrada + (1.5 × ATR)
```
Nunca inferior a 0.5% do preço de entrada, nunca abaixo do preço de liquidação.

### Take Profit Escalonado
```
TP1 = entrada ± (2.0 × ATR)  →  fechar 50% + mover SL para breakeven
TP2 = entrada ± (3.5 × ATR)  →  fechar o restante (trailing stop ativo)
```

### Trailing Stop
- Ativado após ROI ≥ 8%
- Fecha a posição se o ROI cair mais de `max(3%, 35% do pico de ROI)`

### Limites Diários (automáticos)
| Limite | Ação |
|---|---|
| Drawdown ≥ 5% do saldo do dia | Bot pausa até meia-noite UTC |
| 20 trades abertos no dia | Bot pausa até meia-noite UTC |
| Lucro ≥ 10% do saldo do dia | Bot pausa até meia-noite UTC |

### Proteção contra Liquidação
O bot recusa trades onde o Stop Loss ficaria dentro de `80% / alavancagem` do preço de liquidação.

---

## Configuração

### 1. Infraestrutura (.env)

```bash
cp .env.example .env
```

Principais variáveis:

```env
# Credenciais da Binance (obrigatório para testnet/live)
BINANCE_API_KEY=sua_api_key
BINANCE_API_SECRET=seu_api_secret

# Modo de operação: paper | testnet | live
TRADING_MODE=paper
EXCHANGE_MODE=testnet

# Alavancagem (perfil padrão: 10-20x)
DEFAULT_LEVERAGE=10
MAX_LEVERAGE=20

# Margem por trade (USDT)
MIN_MARGIN_USDT=5.0
MAX_MARGIN_USDT=10.0

# Score mínimo de confiança
MIN_SIGNAL_SCORE=70.0

# Limites diários
MAX_DAILY_LOSS_PCT=5.0
MAX_TRADES_PER_DAY=20

# Segurança: nunca altere sem validação completa
ENABLE_MAINNET=false
DRY_RUN_FORCE=true
```

### 2. Parâmetros de Trading (API — tempo real)

```bash
curl -X POST http://localhost:8000/api/config/risk \
  -H "Content-Type: application/json" \
  -d '{
    "leverage": 10,
    "max_auto_leverage": 15,
    "fixed_margin_usdt": 10,
    "min_signal_score": 70,
    "atr_stop_multiplier": 1.5,
    "atr_tp1_multiplier": 2.0,
    "atr_tp2_multiplier": 3.5,
    "max_daily_loss_pct": 5.0,
    "max_trades_per_day": 20,
    "trailing_stop_enabled": true,
    "risk_tolerance": "balanced"
  }'
```

Consulte `backend/trading_params.yaml` para a referência completa de todos os parâmetros.

---

## Iniciando com Docker

```bash
# Construir e iniciar
docker-compose up --build

# Iniciar o bot (parado por padrão)
curl -X POST http://localhost:8000/api/control \
  -H "Content-Type: application/json" \
  -d '{"running": true}'

# Parar o bot
curl -X POST http://localhost:8000/api/control \
  -H "Content-Type: application/json" \
  -d '{"running": false}'

# Kill switch de emergência
curl -X POST http://localhost:8000/api/control \
  -H "Content-Type: application/json" \
  -d '{"kill_switch": true}'
```

---

## API — Endpoints Principais

| Método | Endpoint | Descrição |
|---|---|---|
| GET | `/api/status` | Status do bot, saldo, posições abertas |
| POST | `/api/control` | Iniciar/parar o bot (`running`, `kill_switch`) |
| GET | `/api/signals` | Últimos sinais gerados |
| POST | `/api/signals/run?symbol=BTCUSDT` | Gerar sinal manual |
| GET | `/api/trades` | Histórico de trades |
| GET | `/api/performance/summary` | Win rate, PnL, profit factor |
| POST | `/api/config/risk` | Atualizar parâmetros de risco |
| GET | `/api/config/risk` | Configuração de risco ativa |
| GET | `/api/account/balance` | Saldo na exchange |
| POST | `/api/trades/close-all` | Fechar todas as posições |
| GET | `/api/logs` | Últimos eventos logados |
| POST | `/api/backtests/run` | Executar backtest |

---

## Modos de Operação

| Modo | `TRADING_MODE` | `EXCHANGE_MODE` | Ordens reais |
|---|---|---|---|
| **Paper** | `paper` | qualquer | Nunca — simulação local completa |
| **Testnet** | `testnet` | `testnet` | Sim, na Binance Futures Testnet |
| **Live** | `live` | `mainnet` | Sim, com dinheiro real |

> **Ordem recomendada: paper → testnet → live.**

---

## Monitoramento no Terminal

Logs em tempo real com nível e contexto:

```
2026-05-11 14:32:01 | INFO     | [STRATEGY] Trade paper aberto. | {'symbol': 'BTCUSDT', 'side': 'LONG', 'score': 82.0, ...}
2026-05-11 14:45:15 | WARNING  | [PAPER] Stop loss paper executado. | {'symbol': 'BTCUSDT', 'exit': 68420.5}
```

Sumário diário impresso automaticamente a meia-noite UTC:

```
──────────────────────────────────────────────────────────
  SUMÁRIO DIÁRIO — 11/05/2026
──────────────────────────────────────────────────────────
  Saldo atual     : 1023.40 USDT
  PnL do dia      : +23.40 USDT  (2.34%)
  Drawdown do dia : 0.80%
  Trades fechados : 12  |  Abertos: 1
  Vitórias: 8  |  Derrotas: 4  |  Win Rate: 66.7%
  Profit Factor   : 2.15
──────────────────────────────────────────────────────────
```

---

## Segurança

- `DRY_RUN_FORCE=true` bloqueia qualquer ordem real mesmo em testnet/live
- `ENABLE_MAINNET=false` bloqueia acesso à mainnet como failsafe adicional
- API keys nunca aparecem em logs (sanitizadas automaticamente)
- Kill switch (`/api/control {"kill_switch": true}`) para parada de emergência imediata
- Stop Loss obrigatório — nenhuma posição é aberta sem SL definido
- Proteção automática contra liquidação em todas as entradas
