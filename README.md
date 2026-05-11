# Binance Futures USDT-M Trading Bot

MVP local para estudo, backtesting e paper trading em Binance Futures USDT-M. O projeto prioriza gestão de risco, auditoria, modo Testnet e bloqueios contra operação real acidental.

Não existe promessa de assertividade ou lucro. Use como laboratório técnico. Antes de qualquer ordem real, valide na Testnet, revise permissões da chave e entenda o risco de liquidação em futuros.

## O que vem neste MVP

- Backend FastAPI com healthcheck, controle do robô, scanner, sinais, trades, logs, risco e backtest.
- Dashboard React para iniciar/parar, acionar kill switch, ver saldo paper, PnL, posições, moedas quentes, sinais, trades, backtest e logs.
- PostgreSQL para histórico e auditoria.
- Redis disponível para filas/cache.
- Docker Compose para subir tudo localmente.
- Integração preparada para Binance Futures USDT-M Testnet.
- Paper trading como padrão, com entrada, stop, take profit e PnL simulados.
- Mainnet bloqueado por padrão e exigindo `ENABLE_MAINNET=true`.
- Chaves somente via `.env`.

## Rodar localmente

1. Copie o arquivo de ambiente:

```bash
cp .env.example .env
```

2. Suba os containers:

```bash
docker compose up --build
```

3. Abra:

- Dashboard: http://localhost:5173
- Backend healthcheck: http://localhost:8000/api/health
- Documentação da API: http://localhost:8000/docs

## Modos de operação

Padrão seguro:

```env
EXCHANGE_MODE=testnet
TRADING_MODE=paper
DRY_RUN_FORCE=true
ENABLE_MAINNET=false
```

Para validar ordens reais na Testnet, configure suas chaves de Testnet e altere conscientemente:

```env
TRADING_MODE=testnet
DRY_RUN_FORCE=false
EXCHANGE_MODE=testnet
ENABLE_MAINNET=false
```

Mainnet continua bloqueado. Para liberar Mainnet, é necessário:

```env
EXCHANGE_MODE=mainnet
TRADING_MODE=live
ENABLE_MAINNET=true
DRY_RUN_FORCE=false
```

Use chave sem permissão de saque. O frontend nunca recebe o API Secret.

## Saldo da carteira

O dashboard mostra o saldo paper enquanto `BINANCE_API_KEY` e `BINANCE_API_SECRET` estiverem vazios. Para mostrar o saldo real da carteira Futures usada pelo robo, preencha as chaves no `.env` e reinicie:

```bash
docker compose down
docker compose up --build
```

Com `EXCHANGE_MODE=testnet`, o saldo consultado e da Binance Futures Testnet configurada em `BINANCE_TESTNET_BASE_URL`.

## Endpoints principais

- `GET /api/health`: status básico do backend.
- `GET /api/status`: estado do robô, modo, saldo paper e posições.
- `GET /api/account/balance`: saldo USDT da carteira Binance Futures configurada.
- `POST /api/control`: iniciar/parar e ativar/desativar kill switch.
- `GET /api/scanner/hot`: ranking de moedas quentes.
- `POST /api/signals/run?symbol=BTCUSDT&timeframe=15m`: gera sinal manual.
- `GET /api/signals`: últimos sinais.
- `GET /api/trades`: trades simulados e reais registrados.
- `POST /api/trades/{id}/close`: fechamento manual de trade paper.
- `GET /api/config/risk`: configuração de risco ativa.
- `POST /api/backtests/run`: executa backtest simples.
- `GET /api/logs`: eventos auditáveis.

## Estratégia inicial

O motor calcula score de 0 a 100 usando:

- EMA 9, 21, 50 e 200
- RSI
- MACD
- Bollinger Bands
- ATR
- VWAP
- Volume relativo
- Volume Profile simplificado
- Rompimento de máxima/mínima
- Candle de força
- Candle de rejeição
- Volatilidade relativa

Entradas só passam se também forem aprovadas pelo risco:

- Sem posição duplicada no ativo.
- Limite de posições abertas.
- Limite diário de perda, lucro e operações.
- Risco/retorno mínimo via stop por ATR e take profit maior.
- Stop distante da zona estimada de liquidação.
- Alavancagem limitada a 20x.
- Isolated margin por padrão.

## Banco de dados

As tabelas criadas automaticamente incluem:

- `trades`
- `orders`
- `positions`
- `signals`
- `candles`
- `metrics`
- `configurations`
- `logs`
- `backtests`
- `daily_performance`

## Worker

O backend já roda loops leves de scanner e estratégia para facilitar o MVP. Também há um serviço `worker` preparado em perfil separado:

```bash
docker compose --profile worker up --build
```

Em uma evolução natural, o worker pode assumir filas Redis, execução de estratégia por símbolo e reconciliação de posições.

## Próximos passos recomendados

- Persistir configurações de risco editadas pelo dashboard.
- Implementar reconciliação completa de posições reais na Testnet.
- Adicionar autenticação local no dashboard.
- Expandir backtest com taxas, slippage e funding.
- Adicionar testes automatizados do motor de risco e estratégia.
- Treinar o classificador com histórico suficiente de sinais e trades fechados.
