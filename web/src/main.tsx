import React, { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

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
      <div className="table-wrap"><table><thead><tr><th>ORGANIZATION</th><th>TIME ZONE</th><th>MEMBERS</th><th>STATUS</th></tr></thead>
        <tbody>{organizations.map((org) => <tr key={org.id}><td><strong>{org.trading_name ?? org.legal_name}</strong><small>{org.legal_name}</small></td><td>{org.timezone}</td><td>{org.active_members}</td><td><span className={`status ${org.status}`}>{org.status}</span></td></tr>)}
          {!organizations.length && <tr><td colSpan={4} className="muted">No client organizations provisioned yet.</td></tr>}</tbody></table></div>
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

function ClientDashboard({ token, organization }: { token: string; organization: Organization }) {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [summary, setSummary] = useState<InventorySummary | null>(null);
  const [balances, setBalances] = useState<StockBalance[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    setLoading(true);
    void Promise.all([
      request<Branch[]>("/branches", token, organization.id),
      request<InventorySummary>("/inventory/summary", token, organization.id),
      request<StockBalance[]>("/inventory/balances", token, organization.id)
    ]).then(([branchRows, inventorySummary, stockRows]) => {
      setBranches(branchRows);
      setSummary(inventorySummary);
      setBalances(stockRows);
    }).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "Unable to load organization data");
    }).finally(() => setLoading(false));
  }, [organization.id, token]);
  const name = organization.trading_name ?? organization.legal_name;
  return <div className="content">
    <div className="page-heading"><div><p className="eyebrow">CLIENT WORKSPACE</p><h1>Welcome to {name}.</h1>
      <p className="muted">Your organization’s inventory and stocktaking workspace.</p></div><span className="status active">Account active</span></div>
    {error && <div className="alert">{error}</div>}
    <div className="client-banner"><div><p className="eyebrow">YOUR ORGANIZATION</p><h2>{name}</h2><p>{organization.legal_name} <span>·</span> {organization.timezone}</p></div><div className="banner-icon">▦</div></div>
    <div className="stat-grid client-stats">
      <Stat label="Active branches" value={loading ? "—" : String(summary?.branch_count ?? branches.length)} hint="Registered locations" icon="⌖" />
      <Stat label="Inventory items" value={loading ? "—" : String(summary?.item_count ?? 0)} hint="Active catalogue items" icon="▤" />
      <Stat label="Stocked item types" value={loading ? "—" : String(summary?.stocked_item_count ?? 0)} hint="Items with balances" icon="▦" />
      <Stat label="Units on hand" value={loading ? "—" : Number(summary?.total_units_on_hand ?? 0).toLocaleString()} hint="Across all branches" icon="✓" />
    </div>
    <div className="section-title"><div><h2>Inventory overview</h2><p className="muted">Current stock balances recorded for your organization.</p></div></div>
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">STOCK POSITION</p><h2>Stock by branch and item</h2></div><span className="count-pill">{balances.length} balances</span></div>
      {loading ? <div className="loading">Loading inventory…</div> : balances.length === 0 ?
        <div className="empty-state"><span>▤</span><strong>No stock balances recorded yet</strong><p>Once your catalogue and opening stock are entered, your stock position will appear here.</p></div> :
        <div className="table-wrap"><table><thead><tr><th>ITEM</th><th>SKU</th><th>BRANCH</th><th>ON HAND</th><th>UNIT</th></tr></thead>
          <tbody>{balances.map((row) => <tr key={row.item_id + row.branch_id}><td><strong>{row.item_name}</strong></td><td>{row.sku ?? "—"}</td><td>{row.branch_name} <small>{row.branch_code}</small></td><td><strong>{Number(row.quantity_on_hand).toLocaleString()}</strong></td><td>{row.unit_code}</td></tr>)}</tbody></table></div>}
    </section>
    <div className="section-title"><div><h2>More from Veristock</h2><p className="muted">Additional workspace modules are being connected to the platform.</p></div></div>
    <div className="feature-grid">
      <Feature icon="↗" title="Sales" description="Record sales and keep your stock position current." state="Sales workflow in progress" />
      <Feature icon="◷" title="Stocktaking" description="View scheduled counts, assignments and submissions." state="Stocktaking module planned" />
      <Feature icon="⌁" title="Discrepancies" description="Review count variances and reconciliation outcomes." state="Reconciliation module planned" />
      <Feature icon="⌁" title="Forecasts" description="Demand trends and replenishment recommendations." state="Forecasting module planned" />
      <Feature icon="▧" title="Reports" description="Your approved stocktaking and inventory reports." state="Reporting module planned" />
    </div>
    <section className="panel">
      <div className="panel-heading"><div><p className="eyebrow">LOCATIONS</p><h2>Your branches</h2><p className="muted">Branches registered under this organization.</p></div>
        <span className="count-pill">{branches.length} locations</span></div>
      {loading ? <div className="loading">Loading branches…</div> : branches.length === 0 ?
        <div className="empty-state"><span>⌖</span><strong>No branches added yet</strong><p>Your organization administrator can add the first location.</p></div> :
        <div className="branch-grid">{branches.map((branch) => <div className="branch-card" key={branch.id}><div className="branch-icon">⌖</div><div><strong>{branch.name}</strong><small>{branch.code} · {[branch.town, branch.county].filter(Boolean).join(", ")}</small></div><span className={`status ${branch.status}`}>{branch.status}</span></div>)}</div>}
    </section>
    <p className="footnote">Your data is isolated to {name}. You cannot access another organization’s records.</p>
  </div>;
}

function Stat({ label, value, hint, icon }: { label: string; value: string; hint: string; icon: string }) {
  return <div className="stat-card"><div className="stat-top"><span>{label}</span><i>{icon}</i></div><strong>{value}</strong><small>{hint}</small></div>;
}
function Feature({ icon, title, description, state }: { icon: string; title: string; description: string; state: string }) {
  return <div className="feature-card"><div className="feature-icon">{icon}</div><h3>{title}</h3><p>{description}</p><span>{state} <b>→</b></span></div>;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
