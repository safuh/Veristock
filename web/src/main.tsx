import React, { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { ReportsPanel } from "./ReportsPanel";

const API = "/api";

type Organization = {
  id: string;
  kind: "platform" | "client";
  legal_name: string;
  trading_name: string | null;
  timezone: string;
};
type Enrollment = {
  id: string;
  legal_name: string;
  trading_name: string | null;
  contact_name: string;
  contact_email: string;
  contact_phone: string | null;
  business_description: string | null;
  status: string;
  created_at: string;
};
type ManagedOrganization = {
  id: string;
  legal_name: string;
  trading_name: string | null;
  status: string;
  timezone: string;
  active_members: number;
};
type Branch = {
  id: string;
  code: string;
  name: string;
  town: string | null;
  county: string | null;
  status: string;
};
type CurrentUser = {
  id: string;
  identifier: string;
  organizations: Organization[];
};

async function request<T>(path: string, token: string, organizationId?: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (organizationId) headers.set("X-Organization-ID", organizationId);
  if (init.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API}${path}`, { ...init, headers, credentials: "include" });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(payload.detail ?? `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function csrfToken(): string {
  const prefix = "veristock_csrf=";
  const item = document.cookie.split("; ").find((part) => part.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : "";
}

function App() {
  const [token, setToken] = useState("");
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [activeOrg, setActiveOrg] = useState<Organization | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadIdentity = useCallback(async (accessToken: string) => {
    const identity = await request<CurrentUser>("/identity/me", accessToken);
    setUser(identity);
    const remembered = sessionStorage.getItem("veristock.organization");
    const selected = identity.organizations.find((org) => org.id === remembered)
      ?? identity.organizations[0]
      ?? null;
    setActiveOrg(selected);
  }, []);

  useEffect(() => {
    const csrf = csrfToken();
    if (!csrf) return;
    void fetch(`${API}/auth/browser/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": csrf }
    }).then(async (response) => {
      if (!response.ok) return;
      const data = await response.json() as { access_token: string };
      setToken(data.access_token);
      await loadIdentity(data.access_token);
    }).catch(() => setError("Your session could not be restored. Please sign in again."));
  }, [loadIdentity]);

  const signIn = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/auth/browser/login`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifier: email, password })
      });
      const data = await response.json() as { access_token?: string; detail?: string };
      if (!response.ok || !data.access_token) throw new Error(data.detail ?? "Sign-in failed");
      setToken(data.access_token);
      await loadIdentity(data.access_token);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to sign in");
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    const csrf = csrfToken();
    try {
      await fetch(`${API}/auth/browser/logout`, {
        method: "POST",
        credentials: "include",
        headers: { "X-CSRF-Token": csrf }
      });
    } finally {
      setToken("");
      setUser(null);
      setActiveOrg(null);
      sessionStorage.removeItem("veristock.organization");
    }
  };

  const selectOrganization = (id: string) => {
    const selected = user?.organizations.find((org) => org.id === id) ?? null;
    setActiveOrg(selected);
    if (selected) sessionStorage.setItem("veristock.organization", selected.id);
  };

  if (!token || !user) {
    return <Login email={email} password={password} setEmail={setEmail} setPassword={setPassword}
      onSubmit={signIn} busy={busy} error={error} />;
  }
  if (!activeOrg) {
    return <NoOrganization user={user} onSignOut={signOut} />;
  }
  return <Workspace token={token} user={user} organization={activeOrg}
    onSelectOrganization={selectOrganization} onSignOut={signOut} />;
}

function Login(props: {
  email: string; password: string; setEmail: (value: string) => void;
  setPassword: (value: string) => void; onSubmit: (event: React.FormEvent) => void;
  busy: boolean; error: string;
}) {
  return <main className="login-shell">
    <section className="login-brand">
      <div className="brand-mark">V</div>
      <p className="eyebrow">INVENTORY INTELLIGENCE</p>
      <h1>Know what you have.<br /><span>Trust what you count.</span></h1>
      <p className="brand-copy">One connected workspace for stocktaking, inventory visibility and operational control.</p>
      <div className="login-foot">VERISTOCK ONE <span>·</span> BUSINESS WORKSPACE</div>
    </section>
    <section className="login-panel">
      <form onSubmit={props.onSubmit} className="login-card">
        <div className="brand-mark small">V</div>
        <p className="eyebrow">WELCOME BACK</p>
        <h2>Sign in to Veristock</h2>
        <p className="muted">Use the account provided by your organization.</p>
        <label>Email address<input type="email" autoComplete="username" required value={props.email}
          onChange={(event) => props.setEmail(event.target.value)} placeholder="you@company.com" /></label>
        <label>Password<input type="password" autoComplete="current-password" required value={props.password}
          onChange={(event) => props.setPassword(event.target.value)} placeholder="Your password" /></label>
        {props.error && <div className="alert">{props.error}</div>}
        <button className="primary full" disabled={props.busy}>{props.busy ? "Signing in…" : "Sign in"}</button>
        <p className="login-help">Need an account? Contact your Veristock administrator.</p>
      </form>
    </section>
  </main>;
}

function NoOrganization({ user, onSignOut }: { user: CurrentUser; onSignOut: () => void }) {
  return <main className="center-page"><div className="empty-card">
    <div className="brand-mark small">V</div><p className="eyebrow">ACCOUNT READY</p>
    <h2>No workspace assigned yet</h2>
    <p className="muted">Signed in as {user.identifier}. Your account is not currently a member of an active organization.</p>
    <button className="secondary" onClick={onSignOut}>Sign out</button>
  </div></main>;
}

function Workspace({ token, user, organization, onSelectOrganization, onSignOut }: {
  token: string; user: CurrentUser; organization: Organization;
  onSelectOrganization: (id: string) => void; onSignOut: () => void;
}) {
  const isPlatform = organization.kind === "platform";
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand-lockup"><div className="brand-mark">V</div><div><strong>veristock</strong><small>ONE PLATFORM</small></div></div>
      <div className="workspace-label">{isPlatform ? "INTERNAL WORKSPACE" : "CLIENT WORKSPACE"}</div>
      <nav>
        {(isPlatform
          ? [["Overview", "⌂"], ["Client applications", "▤"], ["Organizations", "▦"], ["Operations", "◷"], ["Team & access", "♙"]]
          : [["Overview", "⌂"], ["Branches", "▦"], ["Inventory", "▤"], ["Sales", "↗"], ["Stocktaking", "◷"], ["Discrepancies", "⌁"], ["Forecasts", "⌁"], ["Reports", "▧"], ["Team & access", "♙"]]
        ).map(([label, icon], index) => <div className={index === 0 ? "nav-item active" : "nav-item"} key={label}>
          <span>{icon}</span>{label}{index === 0 && <i />}
        </div>)}
      </nav>
      <div className="sidebar-bottom"><div className="secure-indicator"><span /> Secure tenant session</div>
        <div className="user-mini"><div className="avatar">{user.identifier.slice(0, 1).toUpperCase()}</div>
          <div className="user-details"><strong>{user.identifier}</strong><small>{isPlatform ? "Veristock staff" : "Client user"}</small></div>
          <button className="icon-button" onClick={onSignOut} title="Sign out">↪</button>
        </div>
      </div>
    </aside>
    <main className="main-area">
      <header className="topbar">
        <div><span className="breadcrumb">Workspace</span><span className="crumb-sep">/</span><strong>{isPlatform ? "Management" : "Client portal"}</strong></div>
        <div className="topbar-right">
          {user.organizations.length > 1 && <select value={organization.id} onChange={(e) => onSelectOrganization(e.target.value)}>
            {user.organizations.map((org) => <option value={org.id} key={org.id}>{org.trading_name ?? org.legal_name}</option>)}
          </select>}
          <span className="live-dot">●</span><span className="muted">Connected</span>
        </div>
      </header>
      {isPlatform
        ? <AdminDashboard token={token} organization={organization} />
        : <ClientDashboard token={token} organization={organization} />}
    </main>
  </div>;
}

function AdminDashboard({ token, organization }: { token: string; organization: Organization }) {
  const [enrollments, setEnrollments] = useState<Enrollment[]>([]);
  const [organizations, setOrganizations] = useState<ManagedOrganization[]>([]);
  const [filter, setFilter] = useState("pending");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [requests, clients] = await Promise.all([
        request<Enrollment[]>(`/organizations/enrollments?status=${filter}`, token, organization.id),
        request<ManagedOrganization[]>("/organizations?status=all", token, organization.id)
      ]);
      setEnrollments(requests); setOrganizations(clients);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to load management data"); }
    finally { setLoading(false); }
  }, [filter, organization.id, token]);
  useEffect(() => { void refresh(); }, [refresh]);

  const review = async (id: string, action: "approve" | "reject") => {
    setNotice(""); setError("");
    try {
      await request(`/organizations/enrollments/${id}/${action}`, token, organization.id, {
        method: "POST", body: JSON.stringify({ review_note: action === "approve" ? "Approved through Veristock management portal" : "Rejected through Veristock management portal" })
      });
      setNotice(`Application ${action === "approve" ? "approved" : "rejected"} successfully.`);
      await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Review action failed"); }
  };
  const updateOrganizationStatus = async (id: string, status: "active" | "suspended") => {
    setNotice(""); setError("");
    try {
      await request(`/organizations/${id}/status`, token, organization.id, {
        method: "PATCH", body: JSON.stringify({ status })
      });
      setNotice(`Organization ${status === "active" ? "reactivated" : "suspended"} successfully.`);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to update organization");
    }
  };
  return <div className="content">
    <div className="page-heading"><div><p className="eyebrow">VERISTOCK OPERATIONS</p><h1>Good day, team.</h1>
      <p className="muted">Your overview of clients, onboarding and platform activity.</p></div>
      <button className="secondary" onClick={() => void refresh()}>↻ Refresh data</button></div>
    {notice && <div className="success">{notice}</div>}{error && <div className="alert">{error}</div>}
    <div className="stat-grid">
      <Stat label="Client organizations" value={organizations.length.toString()} hint="Registered tenants" icon="▦" />
      <Stat label="Pending applications" value={loading ? "—" : enrollments.filter((e) => e.status === "pending").length.toString()} hint="Awaiting review" icon="◷" />
      <Stat label="Active organizations" value={organizations.filter((o) => o.status === "active").length.toString()} hint="Currently enabled" icon="✓" />
      <Stat label="Suspended accounts" value={organizations.filter((o) => o.status === "suspended").length.toString()} hint="Require attention" icon="!" />
    </div>
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">ONBOARDING</p><h2>Client applications</h2><p className="muted">Review businesses requesting access to Veristock.</p></div>
        <select value={filter} onChange={(e) => setFilter(e.target.value)}><option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="all">All applications</option></select></div>
      {loading ? <div className="loading">Loading client records…</div> : enrollments.length === 0 ? <div className="empty-state"><span>✓</span><strong>No applications in this view</strong><p>New business applications will appear here.</p></div> :
        <div className="table-wrap"><table><thead><tr><th>BUSINESS</th><th>CONTACT</th><th>SUBMITTED</th><th>STATUS</th><th>ACTIONS</th></tr></thead>
          <tbody>{enrollments.map((item) => <tr key={item.id}><td><strong>{item.trading_name ?? item.legal_name}</strong><small>{item.legal_name}</small></td>
            <td>{item.contact_name}<small>{item.contact_email}</small></td><td>{new Date(item.created_at).toLocaleDateString()}</td>
            <td><span className={`status ${item.status}`}>{item.status}</span></td>
            <td>{item.status === "pending" ? <div className="actions"><button className="approve" onClick={() => void review(item.id, "approve")}>Approve</button><button className="reject" onClick={() => void review(item.id, "reject")}>Reject</button></div> : "—"}</td></tr>)}</tbody></table></div>}
    </section>
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">TENANT DIRECTORY</p><h2>Client organizations</h2><p className="muted">Organizations provisioned on the platform.</p></div></div>
      <div className="table-wrap"><table><thead><tr><th>ORGANIZATION</th><th>TIME ZONE</th><th>MEMBERS</th><th>STATUS</th><th>ACTIONS</th></tr></thead>
        <tbody>{organizations.map((org) => <tr key={org.id}><td><strong>{org.trading_name ?? org.legal_name}</strong><small>{org.legal_name}</small></td><td>{org.timezone}</td><td>{org.active_members}</td><td><span className={`status ${org.status}`}>{org.status}</span></td><td>{org.status === "active" ? <button className="reject" onClick={() => void updateOrganizationStatus(org.id, "suspended")}>Suspend</button> : org.status === "suspended" ? <button className="approve" onClick={() => void updateOrganizationStatus(org.id, "active")}>Reactivate</button> : "—"}</td></tr>)}
          {!organizations.length && <tr><td colSpan={5} className="muted">No client organizations provisioned yet.</td></tr>}</tbody></table></div>
    </section>
    <p className="footnote">Veristock internal workspace · All tenant operations are authorized by the API.</p>
  </div>;
}

type InventorySummary = {
  item_count: number;
  branch_count: number;
  stocked_item_count: number;
  total_units_on_hand: string;
};
type StockBalance = {
  item_id: string;
  sku: string | null;
  item_name: string;
  branch_id: string;
  branch_code: string;
  branch_name: string;
  quantity_on_hand: string;
  unit_code: string;
};

type InventoryItem = {
  id: string; sku: string | null; barcode: string | null; name: string;
  base_unit_code: string; status: string;
};
type SaleRecord = {
  id: string; branch_id: string; reference: string | null; status: string;
  posted_at: string; lines: { item_id: string; quantity: string; unit_code: string }[];
};
type StocktakeRecord = {
  id: string; branch_id: string; reference: string; blind_count: boolean;
  status: string; created_at: string; item_count: number;
};
type StocktakeScopeItem = {
  item_id: string; sku: string; barcode: string; name: string; unit_code: string;
};
type StocktakeReviewItem = {
  stocktake_id: string;
  reference: string;
  branch_id: string;
  branch_name: string;
  submitted_at: string | null;
  round_number: number;
  item_count: number;
  variance_count: number;
  shortage_count: number;
  surplus_count: number;
};
type StocktakeDecision = {
  id: string;
  stocktake_id: string;
  round_id: string;
  action: string;
  reason_code: string | null;
  reason: string | null;
  actor_user_id: string;
  created_at: string;
};

function ClientDashboard({ token, organization }: { token: string; organization: Organization }) {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [summary, setSummary] = useState<InventorySummary | null>(null);
  const [balances, setBalances] = useState<StockBalance[]>([]);
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [sales, setSales] = useState<SaleRecord[]>([]);
  const [stocktakes, setStocktakes] = useState<StocktakeRecord[]>([]);
  const [reviewQueue, setReviewQueue] = useState<StocktakeReviewItem[]>([]);
  const [reviewAccess, setReviewAccess] = useState<boolean | null>(null);
  const [reviewingStocktakeId, setReviewingStocktakeId] = useState<string | null>(null);
  const [rejectingStocktakeId, setRejectingStocktakeId] = useState<string | null>(null);
  const [rejectionReasonCode, setRejectionReasonCode] = useState("variance_unexplained");
  const [rejectionReason, setRejectionReason] = useState("");
  const [decisionHistory, setDecisionHistory] = useState<Record<string, StocktakeDecision[]>>({});
  const [historyStocktakeId, setHistoryStocktakeId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [itemName, setItemName] = useState("");
  const [itemSku, setItemSku] = useState("");
  const [itemBarcode, setItemBarcode] = useState("");
  const [itemUnit, setItemUnit] = useState("EA");
  const [openingBranch, setOpeningBranch] = useState("");
  const [openingItem, setOpeningItem] = useState("");
  const [openingQuantity, setOpeningQuantity] = useState("0");
  const [saleBranch, setSaleBranch] = useState("");
  const [saleItem, setSaleItem] = useState("");
  const [saleQuantity, setSaleQuantity] = useState("1");
  const [saleReference, setSaleReference] = useState("");
  const [stocktakeBranch, setStocktakeBranch] = useState("");
  const [stocktakeReference, setStocktakeReference] = useState("");
  const [activeStocktake, setActiveStocktake] = useState<string | null>(null);
  const [stocktakeScope, setStocktakeScope] = useState<StocktakeScopeItem[]>([]);
  const [countValues, setCountValues] = useState<Record<string, string>>({});
  const [recordedCounts, setRecordedCounts] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [branchRows, inventorySummary, stockRows, itemRows, saleRows, stocktakeRows] =
        await Promise.all([
          request<Branch[]>("/branches", token, organization.id),
          request<InventorySummary>("/inventory/summary", token, organization.id),
          request<StockBalance[]>("/inventory/balances", token, organization.id),
          request<InventoryItem[]>("/inventory/items", token, organization.id),
          request<SaleRecord[]>("/sales", token, organization.id),
          request<StocktakeRecord[]>("/stocktakes", token, organization.id),
        ]);
      setBranches(branchRows);
      setSummary(inventorySummary);
      setBalances(stockRows);
      setItems(itemRows);
      setSales(saleRows);
      setStocktakes(stocktakeRows);
      try {
        const queue = await request<StocktakeReviewItem[]>(
          "/stocktakes/review-queue", token, organization.id,
        );
        setReviewQueue(queue);
        setReviewAccess(true);
      } catch (reason) {
        const message = reason instanceof Error ? reason.message : "";
        if (/permission|forbidden|403/i.test(message)) {
          setReviewQueue([]);
          setReviewAccess(false);
        } else {
          throw reason;
        }
      }
      setOpeningBranch((current) => current || branchRows[0]?.id || "");
      setSaleBranch((current) => current || branchRows[0]?.id || "");
      setStocktakeBranch((current) => current || branchRows[0]?.id || "");
      setOpeningItem((current) => current || itemRows[0]?.id || "");
      setSaleItem((current) => current || itemRows[0]?.id || "");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load organization data");
    } finally {
      setLoading(false);
    }
  }, [organization.id, token]);

  useEffect(() => { void refresh(); }, [refresh]);

  const perform = async (action: () => Promise<void>, success: string) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(success);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The operation could not be completed");
    } finally {
      setBusy(false);
    }
  };

  const createItem = () => perform(async () => {
    await request<InventoryItem>("/inventory/items", token, organization.id, {
      method: "POST",
      body: JSON.stringify({
        name: itemName, sku: itemSku || null, barcode: itemBarcode || null,
        base_unit_code: itemUnit,
      }),
    });
    setItemName(""); setItemSku(""); setItemBarcode("");
  }, "Inventory item created.");

  const recordOpening = () => perform(async () => {
    await request("/inventory/opening-balances", token, organization.id, {
      method: "POST",
      body: JSON.stringify({
        branch_id: openingBranch, item_id: openingItem, quantity: openingQuantity,
        idempotency_key: crypto.randomUUID(),
      }),
    });
  }, "Opening stock recorded in the movement ledger.");

  const postSale = () => perform(async () => {
    await request("/sales", token, organization.id, {
      method: "POST",
      body: JSON.stringify({
        branch_id: saleBranch, reference: saleReference || null,
        idempotency_key: crypto.randomUUID(),
        lines: [{ item_id: saleItem, quantity: saleQuantity,
          unit_code: items.find((item) => item.id === saleItem)?.base_unit_code ?? "EA" }],
      }),
    });
    setSaleReference("");
    setSaleQuantity("1");
  }, "Sale posted and stock balance updated.");

  const createStocktake = () => perform(async () => {
    const created = await request<StocktakeRecord>("/stocktakes", token, organization.id, {
      method: "POST",
      body: JSON.stringify({
        branch_id: stocktakeBranch, reference: stocktakeReference, blind_count: true,
      }),
    });
    const scope = await request<StocktakeScopeItem[]>(
      `/stocktakes/${created.id}/scope`, token, organization.id,
    );
    setActiveStocktake(created.id);
    setStocktakeScope(scope);
    setCountValues({});
    setRecordedCounts(new Set());
    setStocktakeReference("");
  }, "Stocktake opened. Expected quantities are hidden from counters.");

  const recordCount = (item: StocktakeScopeItem) => perform(async () => {
    const quantity = countValues[item.item_id];
    if (quantity === undefined || quantity.trim() === "") {
      throw new Error("Enter a physical quantity before saving this count.");
    }
    await request(`/stocktakes/${activeStocktake}/observations`, token, organization.id, {
      method: "POST",
      body: JSON.stringify({
        item_id: item.item_id, counted_quantity: quantity, unit_code: item.unit_code,
        idempotency_key: crypto.randomUUID(),
      }),
    });
    setRecordedCounts((current) => new Set(current).add(item.item_id));
  }, `Count recorded for ${item.name}.`);

  const submitStocktake = () => perform(async () => {
    if (!activeStocktake) return;
    await request(`/stocktakes/${activeStocktake}/submit`, token, organization.id, {
      method: "POST", body: JSON.stringify({}),
    });
    setActiveStocktake(null);
    setStocktakeScope([]);
  }, "Count round submitted for review.");

  const approveStocktake = (stocktakeId: string) => perform(async () => {
    setReviewingStocktakeId(stocktakeId);
    try {
      await request(
        `/stocktakes/${encodeURIComponent(stocktakeId)}/approve`,
        token,
        organization.id,
        { method: "POST" },
      );
      setDecisionHistory((current) => {
        const next = { ...current };
        delete next[stocktakeId];
        return next;
      });
    } finally {
      setReviewingStocktakeId(null);
    }
  }, "Stocktake approved and ledger reconciliation completed.");

  const rejectStocktake = (stocktakeId: string) => perform(async () => {
    if (rejectionReason.trim().length < 10) {
      throw new Error("Explain why this count is being rejected (at least 10 characters).");
    }
    setReviewingStocktakeId(stocktakeId);
    try {
      await request(
        `/stocktakes/${encodeURIComponent(stocktakeId)}/reject`,
        token,
        organization.id,
        {
          method: "POST",
          body: JSON.stringify({
            reason_code: rejectionReasonCode,
            reason: rejectionReason.trim(),
          }),
        },
      );
      setRejectingStocktakeId(null);
      setRejectionReason("");
      setDecisionHistory((current) => {
        const next = { ...current };
        delete next[stocktakeId];
        return next;
      });
    } finally {
      setReviewingStocktakeId(null);
    }
  }, "Stocktake rejected. A new count round is now open.");

  const toggleDecisionHistory = async (stocktakeId: string) => {
    if (historyStocktakeId === stocktakeId) {
      setHistoryStocktakeId(null);
      return;
    }
    setHistoryStocktakeId(stocktakeId);
    setError("");
    try {
      const history = await request<StocktakeDecision[]>(
        `/stocktakes/${encodeURIComponent(stocktakeId)}/decisions`,
        token,
        organization.id,
      );
      setDecisionHistory((current) => ({ ...current, [stocktakeId]: history }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load decision history");
    }
  };

  const name = organization.trading_name ?? organization.legal_name;
  return <div className="content">
    <div className="page-heading"><div><p className="eyebrow">CLIENT WORKSPACE</p><h1>Welcome to {name}.</h1>
      <p className="muted">Manage stock, record sales and complete physical counts.</p></div>
      <button className="secondary" onClick={() => void refresh()}>↻ Refresh</button></div>
    {error && <div className="alert">{error}</div>}{notice && <div className="success">{notice}</div>}
    <div className="client-banner"><div><p className="eyebrow">YOUR ORGANIZATION</p><h2>{name}</h2>
      <p>{organization.legal_name} <span>·</span> {organization.timezone}</p></div><div className="banner-icon">▦</div></div>
    <div className="stat-grid client-stats">
      <Stat label="Active branches" value={loading ? "—" : String(summary?.branch_count ?? branches.length)} hint="Registered locations" icon="⌖" />
      <Stat label="Inventory items" value={loading ? "—" : String(summary?.item_count ?? 0)} hint="Active catalogue items" icon="▤" />
      <Stat label="Stocked item types" value={loading ? "—" : String(summary?.stocked_item_count ?? 0)} hint="Items with balances" icon="▦" />
      <Stat label="Units on hand" value={loading ? "—" : Number(summary?.total_units_on_hand ?? 0).toLocaleString()} hint="Across all branches" icon="✓" />
    </div>

    <ReportsPanel token={token} organizationId={organization.id} />

    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">CATALOGUE</p><h2>Inventory items</h2>
        <p className="muted">Create and maintain the items your organization counts and sells.</p></div></div>
      <div className="operation-form">
        <label>Item name<input value={itemName} onChange={(e) => setItemName(e.target.value)} placeholder="e.g. Maize flour 2kg" /></label>
        <label>SKU<input value={itemSku} onChange={(e) => setItemSku(e.target.value)} placeholder="Optional SKU" /></label>
        <label>Barcode<input value={itemBarcode} onChange={(e) => setItemBarcode(e.target.value)} placeholder="Optional barcode" /></label>
        <label>Base unit<input value={itemUnit} onChange={(e) => setItemUnit(e.target.value.toUpperCase())} maxLength={24} /></label>
        <button className="primary" disabled={busy || itemName.trim().length < 2} onClick={() => void createItem()}>Add item</button>
      </div>
      <div className="table-wrap"><table><thead><tr><th>ITEM</th><th>SKU</th><th>BARCODE</th><th>UNIT</th><th>STATUS</th></tr></thead>
        <tbody>{items.map((item) => <tr key={item.id}><td><strong>{item.name}</strong></td><td>{item.sku ?? "—"}</td><td>{item.barcode ?? "—"}</td><td>{item.base_unit_code}</td><td><span className={`status ${item.status}`}>{item.status}</span></td></tr>)}
          {!items.length && <tr><td colSpan={5} className="muted">No catalogue items yet.</td></tr>}</tbody></table></div>
    </section>

    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">OPENING STOCK</p><h2>Enter opening balances</h2>
        <p className="muted">Opening quantities create auditable stock movements and cannot overwrite an existing balance.</p></div></div>
      <div className="operation-form">
        <label>Branch<select value={openingBranch} onChange={(e) => setOpeningBranch(e.target.value)}>
          {branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}</select></label>
        <label>Item<select value={openingItem} onChange={(e) => setOpeningItem(e.target.value)}>
          {items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>Quantity<input type="number" min="0.0001" step="0.0001" value={openingQuantity} onChange={(e) => setOpeningQuantity(e.target.value)} /></label>
        <button className="primary" disabled={busy || !openingBranch || !openingItem} onClick={() => void recordOpening()}>Record opening stock</button>
      </div>
    </section>

    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">SALES LEDGER</p><h2>Record a sale</h2>
        <p className="muted">Posting a sale atomically creates stock-out movements.</p></div></div>
      <div className="operation-form">
        <label>Branch<select value={saleBranch} onChange={(e) => setSaleBranch(e.target.value)}>
          {branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}</select></label>
        <label>Item<select value={saleItem} onChange={(e) => setSaleItem(e.target.value)}>
          {items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>Quantity<input type="number" min="0.0001" step="0.0001" value={saleQuantity} onChange={(e) => setSaleQuantity(e.target.value)} /></label>
        <label>Receipt/reference<input value={saleReference} onChange={(e) => setSaleReference(e.target.value)} placeholder="Optional reference" /></label>
        <button className="primary" disabled={busy || !saleBranch || !saleItem} onClick={() => void postSale()}>Post sale</button>
      </div>
      <div className="table-wrap"><table><thead><tr><th>REFERENCE</th><th>POSTED</th><th>ITEM LINES</th><th>STATUS</th></tr></thead>
        <tbody>{sales.map((sale) => <tr key={sale.id}><td>{sale.reference ?? sale.id.slice(0, 8)}</td>
          <td>{new Date(sale.posted_at).toLocaleString()}</td><td>{sale.lines.length}</td>
          <td><span className={`status ${sale.status}`}>{sale.status}</span></td></tr>)}
          {!sales.length && <tr><td colSpan={4} className="muted">No sales posted yet.</td></tr>}</tbody></table></div>
    </section>

    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">PHYSICAL VERIFICATION</p><h2>Stocktaking</h2>
        <p className="muted">Create a blind count from a frozen expected-stock snapshot.</p></div></div>
      <div className="operation-form">
        <label>Branch<select value={stocktakeBranch} onChange={(e) => setStocktakeBranch(e.target.value)}>
          {branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}</select></label>
        <label>Stocktake reference<input value={stocktakeReference} onChange={(e) => setStocktakeReference(e.target.value)} placeholder="e.g. COUNT-NOV-01" /></label>
        <button className="primary" disabled={busy || !stocktakeBranch || stocktakeReference.trim().length < 2} onClick={() => void createStocktake()}>Start blind stocktake</button>
      </div>
      {activeStocktake && <div className="count-workspace">
        <div className="panel-heading"><div><p className="eyebrow">ACTIVE COUNT</p><h2>Record physical quantities</h2>
          <p className="muted">Expected stock is hidden. Record every scoped item, including zero quantities.</p></div>
          <button className="primary" disabled={busy || !stocktakeScope.length || recordedCounts.size !== stocktakeScope.length} onClick={() => void submitStocktake()}>Submit count round</button></div>
        {stocktakeScope.map((item) => <div className="count-row" key={item.item_id}>
          <div><strong>{item.name}</strong><small>{item.sku || item.barcode || item.item_id.slice(0, 8)} · {item.unit_code}</small></div>
          <input aria-label={`Count for ${item.name}`} type="number" min="0" step="0.0001"
            value={countValues[item.item_id] ?? ""} onChange={(e) => setCountValues((current) => ({ ...current, [item.item_id]: e.target.value }))} />
          <button className="secondary" disabled={busy || recordedCounts.has(item.item_id) || countValues[item.item_id] === undefined || countValues[item.item_id].trim() === ""}
            onClick={() => void recordCount(item)}>{recordedCounts.has(item.item_id) ? "Count saved" : "Save count"}</button>
        </div>)}
      </div>}
      <div className="table-wrap"><table><thead><tr><th>REFERENCE</th><th>CREATED</th><th>ITEMS</th><th>STATUS</th></tr></thead>
        <tbody>{stocktakes.map((record) => <tr key={record.id}><td>{record.reference}</td>
          <td>{new Date(record.created_at).toLocaleDateString()}</td><td>{record.item_count}</td>
          <td><span className={`status ${record.status}`}>{record.status}</span></td></tr>)}
          {!stocktakes.length && <tr><td colSpan={4} className="muted">No stocktakes created yet.</td></tr>}</tbody></table></div>
      {reviewAccess && <div className="review-queue">
        <div className="panel-heading"><div><p className="eyebrow">SUPERVISOR WORKFLOW</p><h3>Submitted counts awaiting review</h3>
          <p className="muted">Review the latest submitted round. Approval posts variances to the stock ledger; rejection opens a new count round.</p></div>
          <span className="count-pill">{reviewQueue.length} pending</span></div>
        <div className="table-wrap"><table><thead><tr><th>STOCKTAKE</th><th>BRANCH</th><th>ROUND</th><th>ITEMS</th><th>VARIANCES</th><th>SHORT / SURPLUS</th><th>REVIEW</th></tr></thead>
          <tbody>{reviewQueue.map((entry) => <tr key={entry.stocktake_id}>
            <td><strong>{entry.reference}</strong><small>{entry.submitted_at ? new Date(entry.submitted_at).toLocaleString() : "Submission time unavailable"}</small></td>
            <td>{entry.branch_name}</td><td>{entry.round_number}</td><td>{entry.item_count}</td>
            <td><strong>{entry.variance_count}</strong></td><td>{entry.shortage_count} / {entry.surplus_count}</td>
            <td><div className="review-actions">
              <button className="approve" disabled={busy || reviewingStocktakeId === entry.stocktake_id} onClick={() => void approveStocktake(entry.stocktake_id)}>
                {reviewingStocktakeId === entry.stocktake_id ? "Saving…" : "Approve"}
              </button>
              <button className="reject" disabled={busy || reviewingStocktakeId === entry.stocktake_id} onClick={() => {
                setRejectingStocktakeId((current) => current === entry.stocktake_id ? null : entry.stocktake_id);
                setRejectionReason("");
              }}>Reject</button>
              <button className="secondary" disabled={busy} onClick={() => void toggleDecisionHistory(entry.stocktake_id)}>
                {historyStocktakeId === entry.stocktake_id ? "Hide history" : "History"}
              </button>
            </div>
            {rejectingStocktakeId === entry.stocktake_id && <div className="reject-form">
              <label>Reason code<select value={rejectionReasonCode} onChange={(event) => setRejectionReasonCode(event.target.value)}>
                <option value="variance_unexplained">Variance unexplained</option>
                <option value="evidence_insufficient">Evidence insufficient</option>
                <option value="counting_procedure">Counting procedure</option>
                <option value="scope_or_unit_error">Scope or unit error</option>
                <option value="other">Other</option>
              </select></label>
              <label>Explanation<textarea rows={3} minLength={10} maxLength={500} value={rejectionReason} onChange={(event) => setRejectionReason(event.target.value)} placeholder="Explain what needs to be corrected (10–500 characters)." /></label>
              <button className="reject" disabled={busy || rejectionReason.trim().length < 10} onClick={() => void rejectStocktake(entry.stocktake_id)}>Confirm rejection and reopen count</button>
            </div>}
            {historyStocktakeId === entry.stocktake_id && <div className="decision-history">
              {(decisionHistory[entry.stocktake_id] ?? []).map((decision) => <div key={decision.id}>
                <strong>{decision.action.replaceAll("_", " ")}</strong>
                <small>{decision.reason_code ? statusLabel(decision.reason_code) : "No reason required"} · {new Date(decision.created_at).toLocaleString()}</small>
                {decision.reason && <p>{decision.reason}</p>}
              </div>)}
              {decisionHistory[entry.stocktake_id]?.length === 0 && <p className="muted">No supervisor decisions recorded yet.</p>}
              {!decisionHistory[entry.stocktake_id] && <p className="muted">Loading decision history…</p>}
            </div>}
            </td>
          </tr>)}
          {!reviewQueue.length && <tr><td colSpan={7} className="muted">No submitted stocktakes are awaiting a decision.</td></tr>}</tbody></table></div>
      </div>}
    </section>

    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">STOCK POSITION</p><h2>Stock by branch and item</h2></div>
        <span className="count-pill">{balances.length} balances</span></div>
      {loading ? <div className="loading">Loading inventory…</div> : balances.length === 0 ?
        <div className="empty-state"><span>▤</span><strong>No stock balances recorded yet</strong><p>Enter opening stock to establish the current stock position.</p></div> :
        <div className="table-wrap"><table><thead><tr><th>ITEM</th><th>SKU</th><th>BRANCH</th><th>ON HAND</th><th>UNIT</th></tr></thead>
          <tbody>{balances.map((row) => <tr key={row.item_id + row.branch_id}><td><strong>{row.item_name}</strong></td><td>{row.sku ?? "—"}</td><td>{row.branch_name} <small>{row.branch_code}</small></td><td><strong>{Number(row.quantity_on_hand).toLocaleString()}</strong></td><td>{row.unit_code}</td></tr>)}</tbody></table></div>}
    </section>
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">LOCATIONS</p><h2>Your branches</h2></div><span className="count-pill">{branches.length} locations</span></div>
      {branches.length === 0 ? <div className="empty-state">No branches registered yet.</div> :
        <div className="branch-grid">{branches.map((branch) => <div className="branch-card" key={branch.id}><div className="branch-icon">⌖</div>
          <div><strong>{branch.name}</strong><small>{branch.code} · {[branch.town, branch.county].filter(Boolean).join(", ")}</small></div>
          <span className={`status ${branch.status}`}>{branch.status}</span></div>)}</div>}
    </section>
    <p className="footnote">Your data is isolated to {name}. All stock changes are recorded through the organization-scoped ledger.</p>
  </div>;
}

function Stat({ label, value, hint, icon }: { label: string; value: string; hint: string; icon: string }) {
  return <div className="stat-card"><div className="stat-top"><span>{label}</span><i>{icon}</i></div><strong>{value}</strong><small>{hint}</small></div>;
}
type InstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
};

function PwaInstallPrompt() {
  const [installEvent, setInstallEvent] = useState<InstallPromptEvent | null>(null);
  const [offline, setOffline] = useState(!navigator.onLine);
  useEffect(() => {
    const onInstall = (event: Event) => {
      event.preventDefault();
      setInstallEvent(event as InstallPromptEvent);
    };
    const onOnline = () => setOffline(false);
    const onOffline = () => setOffline(true);
    window.addEventListener("beforeinstallprompt", onInstall);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("beforeinstallprompt", onInstall);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);
  const install = async () => {
    if (!installEvent) return;
    await installEvent.prompt();
    await installEvent.userChoice;
    setInstallEvent(null);
  };
  return <>
    {offline && <div className="offline-banner" role="status">You are offline. Veristock can open its app shell, but live business data requires a connection.</div>}
    {installEvent && <button className="pwa-install" onClick={() => void install()}>Install Veristock</button>}
  </>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><><App /><PwaInstallPrompt /></></React.StrictMode>);
