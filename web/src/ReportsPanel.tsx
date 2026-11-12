import { useCallback, useEffect, useState } from "react";

type OrganizationReport = {
  organization_id: string;
  as_of: string;
  active_item_count: number;
  active_branch_count: number;
  stocked_item_count: number;
  zero_stock_item_count: number;
  total_units_on_hand: string;
  branches: {
    branch_id: string;
    branch_code: string;
    branch_name: string;
    stocked_item_count: number;
    total_units_on_hand: string;
  }[];
};

type DemandForecast = {
  generated_at: string;
  branch_id: string | null;
  lookback_days: number;
  target_days: number;
  methodology: string;
  items: {
    item_id: string;
    sku: string | null;
    item_name: string;
    unit_code: string;
    units_sold_in_window: string;
    average_daily_demand: string;
    quantity_on_hand: string;
    days_of_cover: string | null;
    recommended_replenishment_quantity: string;
  }[];
};

type AIProviderStatus = {
  configured: boolean;
  provider: string | null;
  model: string | null;
};

type AIExecution = {
  id: string;
  operation: string;
  status: "succeeded" | "failed" | "unavailable" | string;
  provider: string | null;
  model: string | null;
  latency_ms: number | null;
  failure_code: string | null;
  created_at: string;
};

type NarrativeResponse = {
  audit_id: string;
  report_as_of: string;
  advisory_only: boolean;
  narrative: {
    summary: string;
    observations: string[];
    recommended_actions: string[];
    source_references: string[];
    run: { provider: string; model: string; model_version: string | null };
  };
};

async function apiRequest<T>(
  path: string,
  token: string,
  organizationId: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  headers.set("X-Organization-ID", organizationId);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`/api${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(payload.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function formatNumber(value: string | number): string {
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function statusLabel(status: string): string {
  return status.replaceAll("_", " ");
}

export function ReportsPanel({
  token,
  organizationId,
}: {
  token: string;
  organizationId: string;
}) {
  const [report, setReport] = useState<OrganizationReport | null>(null);
  const [executions, setExecutions] = useState<AIExecution[]>([]);
  const [forecast, setForecast] = useState<DemandForecast | null>(null);
  const [providerStatus, setProviderStatus] = useState<AIProviderStatus | null>(null);
  const [narrative, setNarrative] = useState<NarrativeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [snapshot, activity, aiStatus, demand] = await Promise.all([
        apiRequest<OrganizationReport>(
          "/reports/inventory/summary", token, organizationId,
        ),
        apiRequest<AIExecution[]>(
          "/reports/ai-executions?limit=10", token, organizationId,
        ),
        apiRequest<AIProviderStatus>(
          "/reports/ai-provider/status", token, organizationId,
        ),
        apiRequest<DemandForecast>(
          "/reports/inventory/demand-forecast?lookback_days=30&target_days=14",
          token,
          organizationId,
        ),
      ]);
      setReport(snapshot);
      setExecutions(activity);
      setProviderStatus(aiStatus);
      setForecast(demand);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load reports");
    } finally {
      setLoading(false);
    }
  }, [organizationId, token]);

  useEffect(() => { void refresh(); }, [refresh]);

  const generateNarrative = async () => {
    setGenerating(true);
    setError("");
    setNotice("");
    try {
      const result = await apiRequest<NarrativeResponse>(
        "/reports/inventory/narrative", token, organizationId, { method: "POST" },
      );
      setNarrative(result);
      setNotice("Advisory narrative generated from the current inventory snapshot.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Narrative generation failed");
      await refresh();
    } finally {
      setGenerating(false);
    }
  };

  return (
    <section className="panel" aria-labelledby="reports-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">REPORTING & INTELLIGENCE</p>
          <h2 id="reports-heading">Inventory report</h2>
          <p className="muted">A tenant-scoped snapshot with traceable metrics and AI activity.</p>
        </div>
        <button className="secondary" onClick={() => void refresh()} disabled={loading}>
          {loading ? "Refreshing…" : "↻ Refresh report"}
        </button>
      </div>

      {error && <div className="alert" role="alert">{error}</div>}
      {notice && <div className="success" role="status">{notice}</div>}

      {loading && !report ? <div className="loading">Loading reporting data…</div> : report && (
        <>
          <div className="stat-grid client-stats">
            <div className="stat-card"><div className="stat-top"><span>Active items</span><i>▤</i></div><strong>{formatNumber(report.active_item_count)}</strong><small>Catalogue items</small></div>
            <div className="stat-card"><div className="stat-top"><span>Zero-stock items</span><i>!</i></div><strong>{formatNumber(report.zero_stock_item_count)}</strong><small>Need replenishment review</small></div>
            <div className="stat-card"><div className="stat-top"><span>Stocked items</span><i>✓</i></div><strong>{formatNumber(report.stocked_item_count)}</strong><small>Items with available stock</small></div>
            <div className="stat-card"><div className="stat-top"><span>Total units</span><i>▦</i></div><strong>{formatNumber(report.total_units_on_hand)}</strong><small>Across active branches</small></div>
          </div>
          <p className="footnote">Snapshot as of {new Date(report.as_of).toLocaleString()} · {report.active_branch_count} active branches</p>

          <div className="panel-heading">
            <div><h3>Branch stock position</h3><p className="muted">Stock totals are calculated by the application, not generated by AI.</p></div>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>BRANCH</th><th>CODE</th><th>STOCKED ITEMS</th><th>UNITS ON HAND</th></tr></thead>
              <tbody>
                {report.branches.map((branch) => (
                  <tr key={branch.branch_id}>
                    <td><strong>{branch.branch_name}</strong></td>
                    <td>{branch.branch_code}</td>
                    <td>{formatNumber(branch.stocked_item_count)}</td>
                    <td>{formatNumber(branch.total_units_on_hand)}</td>
                  </tr>
                ))}
                {!report.branches.length && <tr><td colSpan={4} className="muted">No active branches are available for reporting.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div className="panel-heading">
        <div><p className="eyebrow">DEMAND PLANNING</p><h3>Sales-velocity forecast</h3>
          <p className="muted">Deterministic 30-day trailing average, with a 14-day stock coverage target. Suggestions do not create purchase orders or change inventory.</p></div>
      </div>
      {forecast && <>
        <div className="table-wrap">
          <table>
            <thead><tr><th>ITEM</th><th>SOLD / 30 DAYS</th><th>AVG. DAILY</th><th>ON HAND</th><th>DAYS COVER</th><th>SUGGESTED QTY</th></tr></thead>
            <tbody>
              {forecast.items.map((item) => (
                <tr key={item.item_id}>
                  <td><strong>{item.item_name}</strong><small className="muted">{item.sku ?? "No SKU"}</small></td>
                  <td>{formatNumber(item.units_sold_in_window)}</td>
                  <td>{formatNumber(item.average_daily_demand)} {item.unit_code}/day</td>
                  <td>{formatNumber(item.quantity_on_hand)}</td>
                  <td>{item.days_of_cover === null ? "—" : formatNumber(item.days_of_cover)}</td>
                  <td><strong>{formatNumber(item.recommended_replenishment_quantity)}</strong></td>
                </tr>
              ))}
              {!forecast.items.length && <tr><td colSpan={6} className="muted">No active items are available for forecasting.</td></tr>}
            </tbody>
          </table>
        </div>
        <p className="footnote">{forecast.methodology}</p>
      </>}
      <div className="panel-heading">
        <div><p className="eyebrow">AI-ASSISTED ANALYSIS</p><h3>Inventory narrative</h3>
          <p className="muted">AI can explain authorized report metrics. It cannot change stock or post transactions.</p>
          {providerStatus && <p className="footnote" role="status">
            AI provider: {providerStatus.configured
              ? `configured · ${providerStatus.provider} / ${providerStatus.model}`
              : "not configured"}
          </p>}</div>
        <button className="primary" disabled={generating || loading || !report} onClick={() => void generateNarrative()}>
          {generating ? "Generating…" : "Generate narrative"}
        </button>
      </div>
      {narrative && (
        <div className="empty-card">
          <p className="eyebrow">ADVISORY ONLY · {narrative.narrative.run.provider} / {narrative.narrative.run.model}</p>
          <p>{narrative.narrative.summary}</p>
          {narrative.narrative.observations.length > 0 && <>
            <strong>Observations</strong>
            <ul>{narrative.narrative.observations.map((item, index) => <li key={index}>{item}</li>)}</ul>
          </>}
          {narrative.narrative.recommended_actions.length > 0 && <>
            <strong>Suggested actions for review</strong>
            <ul>{narrative.narrative.recommended_actions.map((item, index) => <li key={index}>{item}</li>)}</ul>
          </>}
          <small className="muted">Audit reference: {narrative.audit_id}</small>
        </div>
      )}

      <div className="panel-heading">
        <div><p className="eyebrow">GOVERNANCE</p><h3>Recent AI activity</h3>
          <p className="muted">Execution metadata for this organization only.</p></div>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>DATE</th><th>OPERATION</th><th>PROVIDER / MODEL</th><th>STATUS</th><th>LATENCY</th></tr></thead>
          <tbody>
            {executions.map((entry) => (
              <tr key={entry.id}>
                <td>{new Date(entry.created_at).toLocaleString()}</td>
                <td>{statusLabel(entry.operation)}</td>
                <td>{[entry.provider, entry.model].filter(Boolean).join(" / ") || "Not configured"}</td>
                <td><span className={`status ${entry.status}`}>{statusLabel(entry.status)}</span></td>
                <td>{entry.latency_ms === null ? "—" : `${entry.latency_ms} ms`}</td>
              </tr>
            ))}
            {!executions.length && <tr><td colSpan={5} className="muted">No AI executions recorded for this organization.</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="footnote">Audit records contain operational metadata and source references, not prompts or generated report text.</p>
    </section>
  );
}
