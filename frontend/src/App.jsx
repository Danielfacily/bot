import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  CircleDollarSign,
  Pause,
  Play,
  RefreshCcw,
  Shield,
  SlidersHorizontal,
  TrendingUp,
  XCircle,
  Zap
} from "lucide-react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API = import.meta.env.VITE_API_URL || "";

const RISK_PRESETS = {
  conservative: {
    label: "Conservador",
    values: {
      max_risk_per_trade_pct: 0.5,
      fixed_margin_usdt: 5,
      min_stop_loss_pct: 0.5,
      leverage: 5,
      max_auto_leverage: 8,
      max_open_positions: 3,
      max_trades_per_day: 10,
      min_signal_score: 75,
      risk_tolerance: "conservative",
      autonomous_risk_enabled: true,
      auto_leverage_enabled: true,
      trailing_stop_enabled: true,
      break_even_enabled: true
    }
  },
  balanced: {
    label: "Balanceado",
    values: {
      max_risk_per_trade_pct: 1,
      fixed_margin_usdt: 10,
      min_stop_loss_pct: 0.5,
      leverage: 10,
      max_auto_leverage: 10,
      max_open_positions: 5,
      max_trades_per_day: 20,
      min_signal_score: 70,
      risk_tolerance: "balanced",
      autonomous_risk_enabled: true,
      auto_leverage_enabled: true,
      trailing_stop_enabled: true,
      break_even_enabled: true
    }
  },
  aggressive: {
    label: "Arrojado",
    values: {
      max_risk_per_trade_pct: 1.5,
      fixed_margin_usdt: 10,
      min_stop_loss_pct: 0.5,
      leverage: 15,
      max_auto_leverage: 20,
      max_open_positions: 5,
      max_trades_per_day: 30,
      min_signal_score: 65,
      risk_tolerance: "aggressive",
      autonomous_risk_enabled: true,
      auto_leverage_enabled: true,
      trailing_stop_enabled: true,
      break_even_enabled: true
    }
  }
};

async function request(path, options = {}) {
  const response = await fetch(`${API}/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function formatMoney(value) {
  return Number(value || 0).toLocaleString("pt-BR", { style: "currency", currency: "USD" });
}

function formatNumber(value, digits = 2) {
  return Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: digits });
}

function App() {
  const [status, setStatus] = useState(null);
  const [hotCoins, setHotCoins] = useState([]);
  const [signals, setSignals] = useState([]);
  const [trades, setTrades] = useState([]);
  const [logs, setLogs] = useState([]);
  const [performance, setPerformance] = useState(null);
  const [risk, setRisk] = useState(null);
  const [riskDraft, setRiskDraft] = useState(null);
  const [riskDirty, setRiskDirty] = useState(false);
  const [account, setAccount] = useState(null);
  const [backtest, setBacktest] = useState(null);
  const [selectedSymbol, setSelectedSymbol] = useState("BTCUSDT");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const riskDirtyRef = useRef(false);

  const markDirty = (value) => {
    riskDirtyRef.current = value;
    setRiskDirty(value);
  };

  const loadAll = async ({ silent = false } = {}) => {
    try {
      if (!silent) setError("");
      const [statusData, hotData, signalData, tradeData, logData, riskData, accountData, performanceData] = await Promise.all([
        request("/status"),
        request("/scanner/hot?limit=20"),
        request("/signals?limit=25"),
        request("/trades?limit=40&mode=current"),
        request("/logs?limit=80"),
        request("/config/risk"),
        request("/account/balance").catch((err) => ({ connected: false, message: err.message })),
        request("/performance/summary?mode=current").catch(() => null)
      ]);
      setStatus(statusData);
      setHotCoins(hotData);
      setSignals(signalData);
      setTrades(tradeData);
      setLogs(logData);
      setRisk(riskData);
      setPerformance(performanceData);
      if (!riskDirtyRef.current) setRiskDraft(riskData);
      setAccount(accountData);
      if (hotData[0]?.symbol) setSelectedSymbol((current) => current || hotData[0].symbol);
    } catch (err) {
      if (!silent) setError("Não foi possível atualizar os dados agora.");
    }
  };

  useEffect(() => {
    loadAll();
    const timer = setInterval(() => loadAll({ silent: true }), 30000);
    return () => clearInterval(timer);
  }, []);

  const openTrades = useMemo(() => trades.filter((trade) => trade.status === "open"), [trades]);
  const rejectedSignals = useMemo(() => signals.filter((signal) => !signal.accepted), [signals]);

  const control = async (payload) => {
    setLoading(true);
    try {
      const next = await request("/control", { method: "POST", body: JSON.stringify(payload) });
      setStatus(next);
      await loadAll();
    } finally {
      setLoading(false);
    }
  };

  const runSignal = async () => {
    setLoading(true);
    try {
      await request(`/signals/run?symbol=${selectedSymbol}&timeframe=15m`, { method: "POST" });
      await loadAll();
    } finally {
      setLoading(false);
    }
  };

  const runBacktest = async () => {
    setLoading(true);
    try {
      const result = await request("/backtests/run", {
        method: "POST",
        body: JSON.stringify({ symbol: selectedSymbol, timeframe: "15m", limit: 500, initial_balance: 10000 })
      });
      setBacktest(result);
    } finally {
      setLoading(false);
    }
  };

  const saveRisk = async (event) => {
    event.preventDefault();
    if (!riskDraft) return;
    setLoading(true);
    try {
      const result = await request("/config/risk", { method: "POST", body: JSON.stringify(riskDraft) });
      setRisk(result.config);
      setRiskDraft(result.config);
      markDirty(false);
      await loadAll();
    } finally {
      setLoading(false);
    }
  };

  const updateRiskDraft = (key, value) => {
    setRiskDraft((current) => ({ ...current, [key]: value }));
    markDirty(true);
  };

  const applyPreset = (presetKey) => {
    const preset = RISK_PRESETS[presetKey];
    if (!preset) return;
    setRiskDraft((current) => ({ ...(current || {}), ...preset.values }));
    markDirty(true);
  };

  const discardRisk = () => {
    setRiskDraft(risk);
    markDirty(false);
  };

  const closeTrade = async (tradeId) => {
    setLoading(true);
    try {
      await request(`/trades/${tradeId}/close`, { method: "POST" });
      await loadAll();
    } finally {
      setLoading(false);
    }
  };

  const closeAllTrades = async () => {
    const ok = window.confirm("Fechar todas as posições abertas agora?");
    if (!ok) return;
    setLoading(true);
    try {
      setError("");
      const result = await request("/trades/close-all", { method: "POST" });
      if (result.errors?.length) {
        setError(`Algumas posições não fecharam: ${result.errors.map((item) => `${item.symbol} ${item.error}`).join(" | ")}`);
      }
      await loadAll();
    } catch (err) {
      setError(`Falha ao fechar todas as posições: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const acceptSignal = async (signal) => {
    const ok = window.confirm(`Abrir posição manual para ${signal.symbol} ${signal.direction}?`);
    if (!ok) return;
    setLoading(true);
    try {
      await request(`/signals/${signal.id}/force-open`, { method: "POST" });
      await loadAll();
    } catch (err) {
      setError(`Aceite manual bloqueado: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <span className="eyebrow">USDT-M Futures</span>
          <h1>Trading Bot Control</h1>
        </div>
        <div className="topbar-actions">
          <div className={`mode ${status?.mainnet_enabled ? "danger" : "safe"}`}>
            <Shield size={18} />
            {status?.exchange || "testnet"} / {status?.mode || "paper"}
          </div>
          <button className="icon-button" onClick={() => loadAll()} title="Atualizar painel">
            <RefreshCcw size={16} />
          </button>
        </div>
      </header>

      {error && <div className="notice"><AlertTriangle size={18} />{error}</div>}

      <section className="summary-grid">
        <ControlPanel status={status} loading={loading} onControl={control} />
        <Metric icon={<CircleDollarSign size={18} />} label={account?.connected ? "Valor da carteira" : "Saldo paper"} value={formatMoney(account?.connected ? account.wallet_balance : status?.balance)} />
        <Metric icon={<CircleDollarSign size={18} />} label="Disponível" value={formatMoney(account?.connected ? account.available_balance : status?.balance)} />
        <Metric icon={<TrendingUp size={18} />} label="PnL não realizado" value={formatMoney(account?.unrealized_pnl)} tone={Number(account?.unrealized_pnl || 0) < 0 ? "bad" : "good"} />
        <Metric icon={<TrendingUp size={18} />} label="PnL do dia" value={formatMoney(status?.daily_pnl)} tone={Number(status?.daily_pnl || 0) < 0 ? "bad" : "good"} />
        <Metric icon={<Activity size={18} />} label={status?.mode === "paper" ? "Posições paper" : "Posições Binance"} value={`${status?.open_positions || 0}/${status?.max_open_positions || 30}`} />
      </section>

      <PerformanceStrip performance={performance} />

      {account && !account.connected && (
        <div className="notice">
          <AlertTriangle size={18} />
          {account.message}
        </div>
      )}

      <RiskPanel
        draft={riskDraft}
        saved={risk}
        dirty={riskDirty}
        loading={loading}
        onChange={updateRiskDraft}
        onPreset={applyPreset}
        onDiscard={discardRisk}
        onSubmit={saveRisk}
      />

      <section className="workspace market-only">
        <MarketPanel hotCoins={hotCoins} selectedSymbol={selectedSymbol} onSelect={setSelectedSymbol} />
      </section>

      <section className="workspace wide-left">
        <SignalsPanel rows={signals} rejectedCount={rejectedSignals.length} loading={loading} onAccept={acceptSignal} />
        <TradesPanel
          mode={status?.mode}
          trades={trades}
          openTrades={openTrades}
          canCloseAll={Boolean(openTrades.length || status?.open_positions)}
          loading={loading}
          onClose={closeTrade}
          onCloseAll={closeAllTrades}
        />
      </section>

      <LogsPanel logs={logs} />
    </main>
  );
}

function ControlPanel({ status, loading, onControl }) {
  return (
    <div className="panel control-panel">
      <div className="panel-title">
        <Activity size={18} />
        Operação
      </div>
      <div className="robot-state">
        <span className={status?.running ? "dot on" : "dot"} />
        <strong>{status?.running ? "Ligado" : "Desligado"}</strong>
      </div>
      <div className="button-row">
        <button className="primary" disabled={loading || status?.kill_switch} onClick={() => onControl({ running: true })}>
          <Play size={17} /> Iniciar
        </button>
        <button disabled={loading} onClick={() => onControl({ running: false })}>
          <Pause size={17} /> Parar
        </button>
        <button className="danger" disabled={loading} onClick={() => onControl({ kill_switch: true })}>
          <AlertTriangle size={17} /> Kill
        </button>
        <button disabled={loading} onClick={() => onControl({ kill_switch: false })}>
          <XCircle size={17} /> Reset
        </button>
      </div>
    </div>
  );
}

function Metric({ icon, label, value, tone }) {
  return (
    <div className={`panel metric ${tone || ""}`}>
      <span>{icon}{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function PerformanceStrip({ performance }) {
  if (!performance) return null;
  return (
    <section className="performance-strip">
      <MiniStat label="Fechadas lucro" value={performance.wins || 0} tone="good" />
      <MiniStat label="Fechadas prejuízo" value={performance.losses || 0} tone="bad" />
      <MiniStat label="Win rate" value={`${formatNumber(performance.win_rate || 0, 1)}%`} />
      <MiniStat label="PnL fechado" value={formatMoney(performance.closed_pnl)} tone={Number(performance.closed_pnl || 0) < 0 ? "bad" : "good"} />
      <MiniStat label="PnL aberto" value={formatMoney(performance.open_pnl)} tone={Number(performance.open_pnl || 0) < 0 ? "bad" : "good"} />
    </section>
  );
}

function MiniStat({ label, value, tone }) {
  return (
    <div className={`mini-stat ${tone || ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function RiskPanel({ draft, saved, dirty, loading, onChange, onPreset, onDiscard, onSubmit }) {
  return (
    <section className="panel operation-panel">
      <div className="panel-title">
        <SlidersHorizontal size={18} />
        Gestão de risco
        {dirty && <span className="pending">rascunho não salvo</span>}
      </div>

      <div className="preset-row">
        {Object.entries(RISK_PRESETS).map(([key, preset]) => (
          <button key={key} type="button" className={draft?.risk_tolerance === preset.values.risk_tolerance ? "primary" : ""} onClick={() => onPreset(key)}>
            {preset.label}
          </button>
        ))}
      </div>

      {draft && (
        <form className="operation-form" onSubmit={onSubmit}>
          <FieldNumber label="Risco por trade" suffix="%" min="0.05" max="5" step="0.05" value={draft.max_risk_per_trade_pct} onChange={(value) => onChange("max_risk_per_trade_pct", value)} />
          <FieldNumber label="Margem entrada" suffix="USDT" min="1" max="500" step="1" value={draft.fixed_margin_usdt} onChange={(value) => onChange("fixed_margin_usdt", value)} />
          <FieldNumber label="Stop mínimo" suffix="%" min="0.1" max="10" step="0.1" value={draft.min_stop_loss_pct} onChange={(value) => onChange("min_stop_loss_pct", value)} />
          <FieldNumber label="Alav. fixa" suffix="x" min="1" max="20" step="1" value={draft.leverage} onChange={(value) => onChange("leverage", value)} />
          <FieldNumber label="Teto auto" suffix="x" min="1" max="20" step="1" value={draft.max_auto_leverage} onChange={(value) => onChange("max_auto_leverage", value)} />
          <FieldNumber label="Máx. posições" min="1" max="30" step="1" value={draft.max_open_positions} onChange={(value) => onChange("max_open_positions", value)} />
          <label className="select-field">
            <span>Tolerância</span>
            <select value={draft.risk_tolerance} onChange={(event) => onChange("risk_tolerance", event.target.value)}>
              <option value="conservative">Conservadora</option>
              <option value="balanced">Balanceada</option>
              <option value="aggressive">Arrojada</option>
            </select>
          </label>
          <div className="toggle-stack">
            <Toggle label="Risco autônomo" checked={draft.autonomous_risk_enabled} onChange={(value) => onChange("autonomous_risk_enabled", value)} />
            <Toggle label="Auto alavancagem" checked={draft.auto_leverage_enabled} onChange={(value) => onChange("auto_leverage_enabled", value)} />
            <Toggle label="Trailing stop" checked={draft.trailing_stop_enabled} onChange={(value) => onChange("trailing_stop_enabled", value)} />
            <Toggle label="Break-even" checked={draft.break_even_enabled} onChange={(value) => onChange("break_even_enabled", value)} />
          </div>
          <div className="risk-compare">
            <span>Salvo: {saved ? `${saved.max_risk_per_trade_pct}% risco / ${saved.max_auto_leverage}x teto / ${saved.max_open_positions} posições` : "-"}</span>
            <span>Rascunho: {draft.max_risk_per_trade_pct}% risco / {draft.max_auto_leverage}x teto / {draft.max_open_positions} posições</span>
          </div>
          <div className="operation-actions">
            <button className="primary" disabled={loading || !dirty} type="submit">
              <CheckCircle2 size={17} /> Salvar parâmetros
            </button>
            <button type="button" disabled={loading || !dirty} onClick={onDiscard}>Descartar</button>
          </div>
        </form>
      )}
    </section>
  );
}

function MarketPanel({ hotCoins, selectedSymbol, onSelect }) {
  return (
    <div className="panel table-panel">
      <div className="panel-title">
        <BarChart3 size={18} />
        Moedas quentes
      </div>
      <table>
        <thead>
          <tr><th>Ativo</th><th>Score</th><th>Variação</th><th>Volume</th><th>Spread</th></tr>
        </thead>
        <tbody>
          {hotCoins.map((coin) => (
            <tr key={coin.symbol} onClick={() => onSelect(coin.symbol)} className={selectedSymbol === coin.symbol ? "selected" : ""}>
              <td><strong>{coin.symbol}</strong></td>
              <td>{formatNumber(coin.score)}</td>
              <td>{formatNumber(coin.price_change_pct)}%</td>
              <td>{formatMoney(coin.quote_volume)}</td>
              <td>{formatNumber(coin.spread_pct, 4)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ActionPanel({ selectedSymbol, hotCoins, setSelectedSymbol, loading, runSignal, runBacktest, backtest }) {
  return (
    <div className="panel action-panel">
      <div className="panel-title">
        <Zap size={18} />
        Ação manual
      </div>
      <label>
        Ativo
        <select value={selectedSymbol} onChange={(event) => setSelectedSymbol(event.target.value)}>
          {[selectedSymbol, ...hotCoins.map((coin) => coin.symbol)].filter(Boolean).filter((value, index, arr) => arr.indexOf(value) === index).map((symbol) => (
            <option key={symbol}>{symbol}</option>
          ))}
        </select>
      </label>
      <div className="button-row">
        <button className="primary" disabled={loading} onClick={runSignal}>Gerar sinal</button>
        <button disabled={loading} onClick={runBacktest}>Backtest 15m</button>
      </div>
      {backtest && (
        <div className="backtest">
          <b>Backtest {backtest.symbol}</b>
          <span>Win rate: {backtest.win_rate}%</span>
          <span>PnL: {formatMoney(backtest.pnl)}</span>
          <span>Drawdown: {backtest.drawdown}%</span>
          <span>Trades: {backtest.trades_count}</span>
        </div>
      )}
    </div>
  );
}

function TradesPanel({ mode, trades, openTrades, canCloseAll, loading, onClose, onCloseAll }) {
  return (
    <div className="panel table-panel">
      <div className="panel-title table-title">
        {mode === "paper" ? "Trades paper" : "Trades Testnet"}
        <button className="small danger" disabled={loading || !canCloseAll} onClick={onCloseAll}>Fechar todas</button>
      </div>
      <table>
        <thead><tr><th>Ativo</th><th>Lado</th><th>Status</th><th>Entrada</th><th>PnL</th><th></th></tr></thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={trade.id}>
              <td><strong>{trade.symbol}</strong></td>
              <td>{trade.side}</td>
              <td><StatusPill value={trade.status} /></td>
              <td>{formatNumber(trade.entry_price, 6)}</td>
              <td>{formatMoney(trade.pnl)}</td>
              <td>{trade.status === "open" && <button className="small" disabled={loading} onClick={() => onClose(trade.id)}>Fechar</button>}</td>
            </tr>
          ))}
          {!openTrades.length && <tr><td colSpan="6">Sem posições abertas agora.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function LogsPanel({ logs }) {
  return (
    <section className="panel logs">
      <div className="panel-title">Logs em tempo real</div>
      {logs.map((log) => (
        <div className={`log ${log.level}`} key={log.id}>
          <span>{new Date(log.created_at).toLocaleTimeString("pt-BR")}</span>
          <b>{log.source}</b>
          <p>{log.message}</p>
        </div>
      ))}
    </section>
  );
}

function FieldNumber({ label, suffix, value, onChange, ...props }) {
  return (
    <label className="field-number">
      <span>{label}</span>
      <div>
        <input type="number" value={value ?? ""} onChange={(event) => onChange(Number(event.target.value))} {...props} />
        {suffix && <b>{suffix}</b>}
      </div>
    </label>
  );
}

function Toggle({ label, checked, onChange }) {
  return (
    <label className="toggle-row">
      <input type="checkbox" checked={Boolean(checked)} onChange={(event) => onChange(event.target.checked)} />
      {label}
    </label>
  );
}

function SignalsPanel({ rows, rejectedCount, loading, onAccept }) {
  return (
    <div className="panel table-panel">
      <div className="panel-title">
        Sinais
        <span className="soft-pill">{rejectedCount} pendentes</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>Ativo</th>
            <th>Direção</th>
            <th>Score</th>
            <th>Alvo</th>
            <th>Status</th>
            <th>Motivo</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td><strong>{row.symbol}</strong></td>
              <td>{row.direction}</td>
              <td><Score value={row.score} /></td>
              <td>{formatCell(row, "target")}</td>
              <td>{row.accepted ? <StatusPill value="aceito" /> : <StatusPill value="rejeitado" />}</td>
              <td className="reason-cell">{row.rejection_reason || "-"}</td>
              <td>
                {!row.accepted && (
                  <button className="small primary" disabled={loading} onClick={() => onAccept(row)}>
                    Aceitar
                  </button>
                )}
              </td>
            </tr>
          ))}
          {!rows.length && <tr><td colSpan="7">Nenhum registro ainda.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function Score({ value }) {
  const score = Number(value || 0);
  const tone = score >= 70 ? "good" : score >= 55 ? "warn" : "bad";
  return <span className={`score ${tone}`}>{formatNumber(score)}</span>;
}

function StatusPill({ value }) {
  const normalized = String(value || "").toLowerCase();
  const tone = normalized.includes("open") || normalized.includes("aceito") || normalized.includes("filled") ? "good" : normalized.includes("rejeitado") || normalized.includes("error") ? "bad" : "";
  return <span className={`status-pill ${tone}`}>{value}</span>;
}

function formatCell(row, key) {
  if (key === "target") {
    const value = row.features?.target_move_pct;
    return value ? `${formatNumber(value, 2)}%` : "-";
  }
  if (key === "ml_probability") {
    return row[key] ? `${formatNumber(row[key] * 100, 1)}%` : "-";
  }
  if (typeof row[key] === "boolean") return row[key] ? "Sim" : "Não";
  return String(row[key] ?? "-");
}

createRoot(document.getElementById("root")).render(<App />);
