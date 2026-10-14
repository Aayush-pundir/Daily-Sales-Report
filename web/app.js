"use strict";
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const activate = (root, sel, fn) => root.querySelectorAll(sel).forEach(el => { el.onclick = () => fn(el); el.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(el); } }; });
const inr = n => Math.round(n || 0).toLocaleString("en-IN");
const compact = n => { n = n || 0; const a = Math.abs(n); return a >= 1e7 ? (n / 1e7).toFixed(2) + " Cr" : a >= 1e5 ? (n / 1e5).toFixed(2) + " L" : a >= 1e3 ? (n / 1e3).toFixed(1) + "K" : String(Math.round(n)); };
const fdate = s => s ? new Date(s + "T00:00").toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "";
const fmonth = ym => new Date(ym + "-01T00:00").toLocaleDateString("en-GB", { month: "short", year: "numeric" });
const teamHtml = t => { const [p, ...rest] = String(t).split(" & "); return `<b>${esc(p)}</b>${rest.map(r => " &amp; " + esc(r)).join("")}`; };
const CAT_COLOR = { "Annual fees": "var(--s1)", "Set-up fees": "var(--s2)", "Integration": "var(--s3)", "Customisation": "var(--s4)" };
const AGE_COLOR = ["var(--a0)", "var(--a1)", "var(--a2)", "var(--a3)"];

const S = { unread: 0, me: null, meta: null, tab: "dashboard", month: null, credit: "team", filters: { status: "pending" } };

async function api(path, opt = {}) {
  let r;
  try { r = await fetch("/api/" + path, { method: opt.method || "GET", headers: opt.body ? { "Content-Type": "application/json" } : {}, body: opt.body ? JSON.stringify(opt.body) : undefined }); }
  catch { throw new Error("Can't reach the app. Check that the Terminal window running “python3 -m dsr” is still open (if not, start it again), then refresh this page."); }
  if (r.status === 401 && path !== "login" && path !== "quick-login") { S.me = null; render(); throw new Error("Please sign in."); }
  const ct = r.headers.get("Content-Type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) { const e = new Error(data.error || "Request failed"); e.status = r.status; e.data = data; throw e; }
  return data;
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.style.display = "block"; clearTimeout(toast.t); toast.t = setTimeout(() => t.style.display = "none", 2800); }
const can = (...roles) => S.me && (S.me.role === "admin" || roles.includes(S.me.role));

/* ---------- tooltip ---------- */
const tip = document.body.appendChild(Object.assign(document.createElement("div"), { className: "tip" }));
document.addEventListener("mousemove", e => {
  const t = e.target.closest("[data-tip]");
  if (!t) { tip.style.display = "none"; return; }
  tip.innerHTML = t.dataset.tip; tip.style.display = "block";
  tip.style.left = Math.min(e.clientX + 12, innerWidth - tip.offsetWidth - 8) + "px"; tip.style.top = (e.clientY + 14) + "px";
});

/* ---------- shell ---------- */
async function boot() {
  try { S.me = await api("me"); S.meta = await api("meta"); S.month = S.meta.today.slice(0, 7); } catch { S.me = null; }
  render();
}
function render() {
  const app = $("#app");
  if (!S.me) return renderLogin(app);
  const tabs = [["dashboard", "Dashboard"], ["estimates", "Estimates"], ["followups", "Follow-ups"]];
  if (can("finance")) tabs.push(["finance", "Finance desk"]);
  tabs.push(["history", "Reports"]);
  if (S.me.role === "admin") tabs.push(["admin", "Admin"]);
  if (!tabs.some(t => t[0] === S.tab)) S.tab = "dashboard";          // e.g. someone else signed in on this page before
  app.innerHTML = `<header class="top"><span class="brand">Daily Sales Report</span>
    <nav>${tabs.map(([k, l]) => `<button data-tab="${k}" ${S.tab === k ? 'aria-current="page"' : ""}>${l}</button>`).join("")}</nav>
    <button class="bell" id="bell" aria-label="Notifications"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg><span class="badge" id="badge" ${S.unread ? "" : "hidden"}>${S.unread}</span></button><span class="who">${esc(S.me.name)} · ${esc(S.me.role)}${S.me.sm_name ? " (" + esc(S.me.sm_name) + ")" : ""}<button class="btn sm" id="out">Sign out</button></span></header>
    <main id="main"></main>`;
  app.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => { S.tab = b.dataset.tab; render(); });
  $("#bell").onclick = openNotifications; pollNotifications(true);
  $("#out").onclick = async () => { await api("logout", { method: "POST", body: {} }); S.me = null; S.tab = "dashboard"; S.fu = null; S.filters = { status: "pending" }; S.unread = 0; render(); };
  ({ dashboard, estimates, followups: followupsTab, finance, history: historyTab, admin }[S.tab])($("#main")).catch(e => $("#main").innerHTML = `<div class="err">${esc(e.message)}</div>`);
}
async function renderLogin(app) {
  $("#toast").style.display = "none";
  let quick = { enabled: false, users: [] };
  try { quick = await (await fetch("/api/quick-users")).json(); } catch { /* fall back to the password form */ }
  const passwordForm = `<form class="card" id="lf"><label class="f">Username<input name="u" autocomplete="username" required></label>
    <label class="f">Password<input name="p" type="password" autocomplete="current-password" required></label><div id="le"></div><button class="btn primary">Sign in</button></form>`;
  const initials = n => n.split(/\s+/).map(w => w[0]).slice(0, 2).join("").toUpperCase();
  const ROLE = { admin: "Administrator", finance: "Finance", sales: "Sales" };
  app.innerHTML = quick.enabled && quick.users.length
    ? `<div class="login wide"><h1 style="margin-bottom:4px">Daily Sales Report</h1><p class="muted" style="margin:0 0 16px">Click your name to continue.</p>
       ${["admin", "finance", "sales"].map(r => { const us = quick.users.filter(u => u.role === r); return us.length ? `<div class="grp">${ROLE[r]}</div><div class="people">${us.map(u => `<button class="person" data-uid="${u.id}"><span class="av ${r}">${esc(initials(u.name))}</span><span><b>${esc(u.name)}</b><br><span class="muted">${esc(ROLE[r])}${u.sm_name ? " · " + esc(u.sm_name) : ""}</span></span></button>`).join("")}</div>` : ""; }).join("")}
       <div id="le"></div><details style="margin-top:18px"><summary class="muted" style="cursor:pointer">Sign in with a password instead</summary><div style="margin-top:10px">${passwordForm}</div></details>
       <p class="muted" style="font-size:12px;margin-top:18px">Quick sign-in is on because this server is only reachable from this computer. Anyone who can open this page can pick any name, so turn it off before sharing it (see the README).</p></div>`
    : `<div class="login"><h1 style="margin-bottom:14px">Daily Sales Report</h1>${passwordForm}</div>`;
  app.querySelectorAll("[data-uid]").forEach(b => b.onclick = async () => {
    try { await api("quick-login", { method: "POST", body: { user_id: +b.dataset.uid } }); await boot(); }
    catch (er) { $("#le").innerHTML = `<div class="err">${esc(er.message)}</div>`; }
  });
  if ($("#lf")) $("#lf").onsubmit = async e => {
    e.preventDefault();
    try { await api("login", { method: "POST", body: { username: e.target.u.value, password: e.target.p.value } }); await boot(); }
    catch (er) { $("#le").innerHTML = `<div class="err">${esc(er.message)}</div>`; }
  };
}

/* ---------- notifications ---------- */
async function pollNotifications(first) {
  if (!S.me) return;
  try {
    const n = await api("notifications?limit=1"), prev = S.unread || 0;
    S.unread = n.unread; const b = $("#badge"); if (b) { b.textContent = n.unread; b.hidden = !n.unread; }
    if (!first && n.unread > prev && n.items[0]) {
      toast(n.items[0].text);
      const quiet = !$("#dlg").open && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "");
      if (quiet && ["dashboard", "finance", "estimates"].includes(S.tab)) render();   // keep every screen in step without disturbing anyone mid-edit
    }
  } catch { /* signed out or offline: try again later */ }
}
if (!window.__poll) window.__poll = setInterval(() => document.visibilityState === "visible" && pollNotifications(false), 20000);
async function openNotifications() {
  const n = await api("notifications?limit=40");
  modal("Notifications", n.items.length ? `<ul class="notes">${n.items.map(i => `<li class="${i.unread ? "unread" : ""}"><div>${esc(i.text)}</div><div class="muted">${fstamp(i.at)}</div><div class="n-act"><button class="btn sm" data-n="${i.estimate_id}">${i.open && can("finance") ? "Review &amp; decide" : "Open estimate"}</button></div></li>`).join("")}</ul>` : `<div class="muted">Nothing yet.</div>`,
    `<button class="btn primary" id="cx">Close</button>`, d => {
      $("#cx").onclick = closeModal;
      d.querySelectorAll("[data-n]").forEach(b => b.onclick = () => detail(+b.dataset.n));
    });
  await api("notifications/read", { method: "POST", body: {} }); S.unread = 0; const b = $("#badge"); if (b) b.hidden = true;
}

/* ---------- dialog helper ---------- */
function modal(title, body, footer, onOpen, wide) {
  const d = $("#dlg"); d.className = wide ? "wide" : "";
  d.innerHTML = `<div class="hd"><h3>${title}</h3><button class="btn sm" id="dx" aria-label="Close">✕</button></div><div class="bd">${body}</div><div class="ft">${footer || ""}</div>`;
  $("#dx").onclick = () => d.close(); if (!d.open) d.showModal(); if (onOpen) onOpen(d); return d;
}
const closeModal = () => $("#dlg").open && $("#dlg").close();

/* ---------- dashboard ---------- */
function monthOptions() {
  const [y, m] = S.meta.today.split("-").map(Number), out = [];
  for (let i = 0; i < 18; i++) { let mm = m - i, yy = y; while (mm < 1) { mm += 12; yy--; } out.push(`${yy}-${String(mm).padStart(2, "0")}`); }
  return out;
}
async function dashboard(el) {
  const r = await api(`report?month=${S.month}&credit=${S.credit}`);
  const t = r.total, nz = (a, b) => b ? Math.round(a / b * 100) : 0;
  const lastPub = r.last_published;
  el.innerHTML = `
  <div class="bar"><div style="margin-right:auto"><h2>Report as on ${fdate(r.as_on)}</h2>
      <div class="sub">${lastPub ? `Last published ${fdate(lastPub.day)} by ${esc(lastPub.published_by)}` : "Not yet published"} · amounts are estimate sub-totals (before tax)</div></div>
    <label class="f">Month<select id="mon">${monthOptions().map(m => `<option value="${m}" ${m === S.month ? "selected" : ""}>${fmonth(m)}</option>`).join("")}</select></label>
    <label class="f">Credit<select id="split"><option value="team">Team, primary first</option><option value="primary" ${S.credit === "primary" ? "selected" : ""}>Primary salesperson only</option><option value="split" ${S.credit === "split" ? "selected" : ""}>Split equally</option></select></label>
    <a class="btn" href="/api/export.csv" download>Export CSV</a>
    ${can("finance") ? `<button class="btn primary" id="pub">Publish today's report</button>` : ""}</div>
  ${(r.pending_drop_requests && can("finance")) || r.followups_needed || r.open_change_requests ? `<div class="attn">${r.open_change_requests ? `<button id="goCr">${r.open_change_requests} change request${r.open_change_requests > 1 ? "s" : ""} waiting for finance →</button>` : ""}${r.followups_needed ? `<button id="goFu">${r.followups_needed} estimate${r.followups_needed > 1 ? "s" : ""} over 30 days with no current follow-up →</button>` : ""}${r.pending_drop_requests && can("finance") ? `<button id="goDrops">${r.pending_drop_requests} drop request${r.pending_drop_requests > 1 ? "s" : ""} waiting for finance →</button>` : ""}</div>` : ""}
  <div class="roll">
    ${[["Opening estimates", t.opening, t.opening_n, "", "", "opening"], ["New estimates raised", t.new, t.new_n, "+", "", "new"], ["Converted to tax invoice", t.converted, t.converted_n, "−", "good", "converted"], ["Dropped / written off", t.dropped, t.dropped_n, "−", "bad", "dropped"], ["Closing estimates (pending)", t.closing, t.closing_n, "=", "", "closing"]]
      .map(([l, v, n, op, tone, metric]) => `<div class="k ${tone || ""}">${op ? `<span class="op">${op}</span>` : ""}<div class="lab">${l}</div><div class="val num" data-tip="₹ ${inr(v)} — click to list these estimates">${v ? `<button class="drill big" data-metric="${metric}" data-team="" data-v="${Math.round(v)}">₹ ${compact(v)}</button>` : `₹ ${compact(v)}`}</div><div class="cnt num">${S.credit === "split" ? n.toFixed(1) : n} estimate${n === 1 ? "" : "s"}</div></div>`).join("")}
  </div>
  <div class="card" style="margin-bottom:16px"><h3>Sales manager performance</h3><div class="hint">Roll-forward per ${S.credit === "team" ? "team — the first name is the primary salesperson" : "person"}. Click a number to list the estimates behind it, or a name for that row's pending estimates.</div>
    <div class="scroll"><table><thead><tr><th>${S.credit === "team" ? "Team (primary first)" : "Sales manager"}</th><th class="r">Opening</th><th class="r">+ New</th><th class="r conv">− Converted</th><th class="r drop">− Dropped</th><th class="r">Closing</th><th class="r">%</th></tr></thead><tbody>
    ${r.teams.map(x => `<tr><td><button class="drill name" data-pending="${esc(x.team)}" title="List this row's pending estimates">${teamHtml(x.team)}</button></td><td class="r num">${dv(x.opening, "opening", x.team)}</td><td class="r num">${dv(x.new, "new", x.team)}</td><td class="r num conv${x.converted ? "" : " zero"}">${dv(x.converted, "converted", x.team)}</td><td class="r num drop${x.dropped ? "" : " zero"}">${dv(x.dropped, "dropped", x.team)}</td><td class="r num"><b>${dv(x.closing, "closing", x.team)}</b></td><td class="r num">${nz(x.closing, t.closing)}%</td></tr>`).join("")}
    <tr class="total"><td>Total</td><td class="r num">${dv(t.opening, "opening", "")}</td><td class="r num">${dv(t.new, "new", "")}</td><td class="r num conv${t.converted ? "" : " zero"}">${dv(t.converted, "converted", "")}</td><td class="r num drop${t.dropped ? "" : " zero"}">${dv(t.dropped, "dropped", "")}</td><td class="r num">${dv(t.closing, "closing", "")}</td><td class="r num">100%</td></tr></tbody></table></div></div>
  <div class="card" style="margin-bottom:16px"><h3>Closing estimates — ageing by ${S.credit === "team" ? "team" : "sales manager"}</h3><div class="hint">Pending at the report date, by days since the estimate date. Each row adds up to its Closing above. Click a number to list those estimates, or a name for that row's pending estimates.</div>
    <div class="scroll"><table><thead><tr><th>${S.credit === "team" ? "Team (primary first)" : "Sales manager"}</th>${["0-30", "31-60", "61-90", "90+"].map((b, i) => `<th class="r"><i class="dot" style="background:${AGE_COLOR[i]}"></i>${b.replace("-", "–")} days</th>`).join("")}<th class="r">Total</th><th class="r">% of total</th><th>Mix</th></tr></thead><tbody>
    ${r.teams.map(x => `<tr><td><button class="drill name" data-pending="${esc(x.team)}" title="List this row's pending estimates">${teamHtml(x.team)}</button></td>${["0-30", "31-60", "61-90", "90+"].map((b, i) => `<td class="r num${x.ageing[b] && i > 1 ? " age" + i : ""}">${dv(x.ageing[b], "closing", x.team, b)}</td>`).join("")}<td class="r num"><b>${dv(x.closing, "closing", x.team)}</b></td><td class="r num">${nz(x.closing, t.closing)}%</td><td>${ageBar(x.ageing, x.closing, esc(x.team))}</td></tr>`).join("")}
    <tr class="total"><td>Total</td>${["0-30", "31-60", "61-90", "90+"].map((b, i) => `<td class="r num${t.ageing[b] && i > 1 ? " age" + i : ""}">${dv(t.ageing[b], "closing", "", b)}</td>`).join("")}<td class="r num">${dv(t.closing, "closing", "")}</td><td class="r num">100%</td><td></td></tr>
    <tr class="share"><td>Share of closing</td>${["0-30", "31-60", "61-90", "90+"].map(b => `<td class="r num">${nz(t.ageing[b], t.closing)}%</td>`).join("")}<td class="r num">100%</td><td></td><td></td></tr></tbody></table></div></div>
  <div class="grid g2" style="margin-bottom:16px">
    <div class="card"><h3>Conversions by month</h3><div class="hint">Estimates converted to tax invoices, by the month payment was received.</div><div id="trend"></div></div>
    <div class="card"><h3>Ageing of closing estimates</h3><div class="hint">Value still pending, by days since estimate date and fee type.</div><div id="ageing"></div></div>
  </div>
  <div class="grid g2">
    <div class="card"><h3>Revenue segment report</h3><div class="hint">Same roll-forward, by fee type. Click a number to list the estimates behind it.</div><div class="scroll"><table class="compact"><thead><tr><th></th>${S.meta.categories.map(c => `<th class="r"><i style="display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;background:${CAT_COLOR[c]}"></i>${c}</th>`).join("")}<th class="r">Total</th></tr></thead><tbody>
      ${[["Opening", "opening"], ["+ New", "new"], ["− Converted", "converted"], ["− Dropped", "dropped"], ["Closing", "closing"]].map(([l, k]) => `<tr class="${k === "closing" ? "total" : ""}"><td>${l}</td>${S.meta.categories.map(c => `<td class="r num">${dvc(r.segments[k][c], k, c)}</td>`).join("")}<td class="r num">${dvc(Object.values(r.segments[k]).reduce((a, b) => a + b, 0), k, "")}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="card"><h3>Largest pending estimates</h3><div class="hint">Top 10 by value. Click one to open it.</div><div class="scroll"><table><thead><tr><th>Customer</th><th>SM</th><th class="r">Age</th><th class="r">Amount</th></tr></thead><tbody>
      ${r.pending_by_value.map(p => `<tr class="click" tabindex="0" data-id="${p.id}" title="Open this estimate"><td class="clip" title="${esc(p.customer)}">${esc(p.customer)}</td><td>${teamHtml(p.owners.replace(/\|/g, " & "))}</td><td class="r num">${p.age}d</td><td class="r num">${inr(p.amount)}</td></tr>`).join("")}</tbody></table></div></div>
  </div>`;
  S.report = r; drawCharts();
  activate(el, "tr[data-id]", tr => detail(+tr.dataset.id));
  $("#mon").onchange = e => { S.month = e.target.value; render(); };
  $("#split").onchange = e => { S.credit = e.target.value; render(); };
  if ($("#pub")) $("#pub").onclick = async () => { try { await api("snapshots", { method: "POST", body: {} }); toast("Report published"); render(); } catch (e) { toast(e.message); } };
  if ($("#goCr")) $("#goCr").onclick = () => { if (can("finance")) S.tab = "finance"; else { S.filters = { status: "pending", change_requested: "1" }; S.tab = "estimates"; } render(); };
  if ($("#goFu")) $("#goFu").onclick = () => { S.fu = { flag: "", sm: "", age: "30" }; S.tab = "followups"; render(); };
  if ($("#goDrops")) $("#goDrops").onclick = () => { S.tab = "finance"; render(); };
  const go = b => drillDown({ metric: b.dataset.metric, team: b.dataset.team, who: b.dataset.who, bucket: b.dataset.bucket, cat: b.dataset.cat, month: b.dataset.month, v: b.dataset.v }).catch(e => toast(e.message));
  el.addEventListener("click", ev => { const b = ev.target.closest("[data-metric]"); if (b && el.contains(b)) go(b); });
  el.addEventListener("keydown", ev => { const b = ev.target.closest("[data-metric]"); if (b && b.tagName !== "BUTTON" && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); go(b); } });
  el.querySelectorAll("[data-pending]").forEach(b => b.onclick = () => {      // the name: that row's own pending estimates
    const name = b.dataset.pending, mode = S.credit;
    S.filters = { status: "pending", ...(mode === "team" ? { team: name.split(" & ").join("|") } : mode === "primary" ? { primary: name } : { sm: name }) };
    S.tab = "estimates"; render();
  });
}
const keyOf = label => S.credit === "team" ? label.split(" & ").join("|") : label;          // how the server identifies a row
const dv = (v, metric, team, bucket) => v ? `<button class="drill" data-metric="${metric}" data-team="${esc(team ? keyOf(team) : "")}" data-who="${esc(team || "")}"${bucket ? ` data-bucket="${bucket}"` : ""} data-v="${Math.round(v)}" title="Show these estimates">${inr(v)}</button>` : inr(v);
const dvc = (v, metric, cat) => v ? `<button class="drill" data-metric="${metric}" data-team="" data-who="" ${cat ? `data-cat="${esc(cat)}" ` : ""}data-v="${Math.round(v)}" title="Show these estimates">${inr(v)}</button>` : inr(v);
const METRIC_LABEL = { opening: "Opening — pending on the 1st", new: "New this month", converted: "Converted (paid) this month", dropped: "Dropped this month", closing: "Closing — pending now" };
async function drillDown(d) {
  const qs = new URLSearchParams({ month: d.month || S.month, credit: S.credit, metric: d.metric, ...(d.team ? { team: d.team } : {}), ...(d.bucket ? { bucket: d.bucket } : {}), ...(d.cat ? { category: d.cat } : {}) });
  const r = await api("report/drill?" + qs), who = (d.who || "All sales managers") + (d.cat ? " · " + d.cat : "");
  const label = d.bucket ? `Pending ${d.bucket.replace("-", "–")} days` : METRIC_LABEL[d.metric];
  const note = x => d.metric === "converted" ? `Paid ${fdate(x.closed_on)}${x.invoice_no && x.invoice_no !== "(legacy)" ? " · " + esc(x.invoice_no) : ""}` : d.metric === "dropped" ? `Dropped ${fdate(x.closed_on)}` : d.metric === "new" ? `Raised ${fdate(x.est_date)}` : `${x.age} days old`;
  const split = S.credit === "split" && d.team;
  const match = d.v === undefined || Math.round(r.counted) === +d.v;
  modal(`${esc(who)} — ${label}`, `<div class="drill-sum"><b class="num">${r.count} estimate${r.count === 1 ? "" : "s"} · ₹ ${inr(r.counted)}</b> <span class="muted">${fmonth(r.month)}, as on ${fdate(r.as_on)}${split ? " · each joint estimate shows this person's equal share" : ""}${d.cat ? " · amounts are the " + esc(d.cat) + " part only" : ""}</span>
    <span class="${match ? "ok" : "bad"}">${match ? "✓ adds up to the figure you clicked" : "⚠ does not match the figure you clicked (₹ " + inr(d.v) + ")"}</span></div>
    <div class="scroll"><table><thead><tr><th>Estimate</th><th>Date</th><th>Customer</th><th>Sales manager</th><th>Fees</th><th class="r">Amount</th><th>${d.metric === "converted" ? "Payment" : d.metric === "dropped" ? "Dropped" : d.metric === "new" ? "Raised" : "Age"}</th></tr></thead><tbody>
    ${r.rows.map(x => `<tr class="click" tabindex="0" data-id="${x.id}"><td>${esc(x.number)}</td><td>${fdate(x.est_date)}</td><td class="clip" title="${esc(x.customer)}">${esc(x.customer)}</td><td>${teamHtml(x.team)}</td>
      <td><span class="fees">${x.categories.map(c => `<span><i style="background:${CAT_COLOR[c]}"></i>${c.replace(" fees", "")}</span>`).join("")}</span></td>
      <td class="r num">${inr(x.counted)}${Math.round(x.counted) !== Math.round(x.total) ? `<div class="muted" style="font-size:11px">of ${inr(x.total)}</div>` : ""}</td><td>${note(x)}</td></tr>`).join("") || `<tr><td colspan="7" class="muted">Nothing.</td></tr>`}</tbody>
    <tfoot><tr class="total"><td colspan="5">Total</td><td class="r num">${inr(r.counted)}</td><td></td></tr></tfoot></table></div>`,
    `<button class="btn primary" id="cx">Close</button>`, dlg => { $("#cx").onclick = closeModal; activate(dlg, "tr[data-id]", tr => detail(+tr.dataset.id)); }, true);
}
function ageBar(ag, tot, name) {
  if (!tot) return "";
  return `<div class="seg" role="img" aria-label="${name} closing by age">${["0-30", "31-60", "61-90", "90+"].map((b, i) => ag[b] ? `<span data-tip="${b} days: ₹ ${inr(ag[b])}" style="width:${ag[b] / tot * 100}%;background:${AGE_COLOR[i]}"></span>` : "").join("")}</div>`;
}
function drawCharts() {
  const r = S.report, a = $("#trend"), b = $("#ageing");
  if (!r || !a || !b) return;
  a.innerHTML = trendChart(r.trend, Math.max(260, a.clientWidth)); b.innerHTML = ageingChart(r, Math.max(260, b.clientWidth));
}
let resizeT; addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(drawCharts, 120); });
function trendChart(tr, W) {
  const H = 200, L = 34, B = 26, T = 18, top = Math.max(5, ...tr.map(x => x.actual)), max = Math.ceil(top * 1.1 / 4) * 4;
  const bw = (W - L) / tr.length, y = v => T + (H - T - B) * (1 - v / max);
  const ticks = [...new Set([0, .25, .5, .75, 1].map(f => Math.round(max * f)))];
  const lab = ym => fmonth(ym).replace(" 20", " ’");
  return `<svg width="${W}" height="${H}" role="img" aria-label="Conversions per month">
  <g class="grid">${ticks.map(v => `<line x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join("")}</g>
  ${tr.map((x, i) => { const cx = L + bw * i + bw / 2, w = Math.min(40, bw * .6), last = i === tr.length - 1;
    return `<g class="${x.actual ? "hit" : ""}" ${x.actual ? `data-metric="converted" data-month="${x.month}" data-team="" data-who="" data-v="${Math.round(x.actual_amount)}" tabindex="0" role="button" aria-label="${fmonth(x.month)}: ${x.actual} converted, list them"` : ""} data-tip="<b>${fmonth(x.month)}</b><br>Converted: ${x.actual}<br>Value: ₹ ${inr(x.actual_amount)}${x.actual ? "<br>Click to list them" : ""}">
      <rect x="${cx - bw / 2}" y="${T}" width="${bw}" height="${H - T - B}" fill="transparent"/>
      ${x.actual ? `<path d="M${cx - w / 2},${y(0)} V${y(x.actual) + 4} a4,4 0 0 1 4,-4 h${w - 8} a4,4 0 0 1 4,4 V${y(0)} Z" fill="var(--s1)" opacity="${last ? 1 : .6}"/>` : ""}
      <text x="${cx}" y="${y(x.actual) - 6}" text-anchor="middle" class="v">${x.actual}</text>
      <text x="${cx}" y="${H - 7}" text-anchor="middle">${lab(x.month)}</text></g>`; }).join("")}</svg>`;
}
function ageingChart(r, W) {
  const B = ["0-30", "31-60", "61-90", "90+"], cats = S.meta.categories;
  const tot = B.map(b => cats.reduce((a, c) => a + r.ageing_segments[b][c], 0)), mx = Math.max(1, ...tot), L = 54, R = 74, rowH = 36, avail = W - L - R;
  return `<div class="legend">${cats.map(c => `<span><i style="background:${CAT_COLOR[c]}"></i>${c}</span>`).join("")}</div>
  <svg width="${W}" height="${B.length * rowH + 4}" role="img" aria-label="Ageing of pending estimates">
  ${B.map((b, i) => { let x = L; const y = i * rowH + 4;
    return `<text x="${L - 10}" y="${y + 18}" text-anchor="end">${b} d</text>` + cats.map(c => { const v = r.ageing_segments[b][c], w = v / mx * avail; if (!v) return ""; const seg = `<rect class="hit" x="${x}" y="${y + 5}" width="${Math.max(w - 2, 1)}" height="18" rx="3" fill="${CAT_COLOR[c]}" data-metric="closing" data-bucket="${b}" data-cat="${esc(c)}" data-team="" data-who="" data-v="${Math.round(v)}" tabindex="0" role="button" aria-label="${b} days, ${c}: list these estimates" data-tip="<b>${b} days · ${c}</b><br>₹ ${inr(v)}<br>Click to list them"/>`; x += w; return seg; }).join("")
      + `<text x="${x + 8}" y="${y + 18}" class="v hit" data-metric="closing" data-bucket="${b}" data-team="" data-who="" data-v="${Math.round(tot[i])}" tabindex="0" role="button" data-tip="${r.ageing_count[b]} estimate${r.ageing_count[b] === 1 ? "" : "s"} · ₹ ${inr(tot[i])}<br>Click to list them">₹ ${compact(tot[i])}</text>`; }).join("")}</svg>`;
}

/* ---------- estimates ---------- */
async function estimates(el) {
  const f = S.filters, qs = new URLSearchParams(Object.fromEntries(Object.entries(f).filter(([, v]) => v)));
  const rows = await api("estimates?" + qs);
  const chipText = f.team ? `Only “${f.team.split("|").join(" & ")}” (primary first)` : f.primary ? `Only estimates where ${f.primary} is the primary salesperson` : "";
  const opt = (arr, cur, all) => `<option value="">${all}</option>` + arr.map(a => `<option ${a === cur ? "selected" : ""}>${esc(a)}</option>`).join("");
  el.innerHTML = `<div class="bar"><h2>Estimates <span class="muted num" style="font-weight:400;font-size:14px">${rows.length} · ₹ ${inr(rows.reduce((a, r) => a + r.total, 0))}</span>${chipText ? ` <span class="chip" id="chip">${esc(chipText)} <button aria-label="Clear this filter" id="chipx">✕</button></span>` : ""}</h2>
    <label class="f">Search<input id="fq" placeholder="Customer or number" value="${esc(f.q || "")}"></label>
    <label class="f">Status<select id="fs"><option value="">All</option>${["pending", "received", "dropped"].map(s => `<option ${f.status === s ? "selected" : ""}>${s}</option>`).join("")}</select></label>
    <label class="f">Sales manager<select id="fm">${opt(S.meta.sms, f.sm, "All")}</select></label>
    <label class="f">Fee type<select id="fc">${opt(S.meta.categories, f.category, "All")}</select></label>
    <label class="f">Age<select id="fb">${opt(S.meta.buckets, f.bucket, "All")}</select></label>
    <label class="f">Change requests<select id="fcr"><option value="">All</option><option value="1" ${f.change_requested === "1" ? "selected" : ""}>Awaiting finance</option></select></label>
    ${can("sales") ? `<button class="btn" id="up">Upload file…</button><button class="btn primary" id="new">+ New estimate</button>` : ""}</div>
    <div class="card scroll"><table><thead><tr><th>Estimate</th><th>Date</th><th>Customer</th><th>Sales manager</th><th>Fees</th><th class="r">Amount</th><th>Status</th><th class="r">Age</th></tr></thead><tbody>
    ${rows.map(r => `<tr class="click" tabindex="0" data-id="${r.id}"><td>${esc(r.number)}</td><td>${fdate(r.est_date)}</td><td class="clip" title="${esc(r.customer)}">${esc(r.customer)}</td><td>${teamHtml(r.team)}</td>
      <td><span class="fees">${r.categories.map(c => `<span><i style="background:${CAT_COLOR[c]}"></i>${c.replace(" fees", "")}</span>`).join("")}</span></td>
      <td class="r num">${inr(r.total)}</td><td>${pill(r)}${r.change_requested ? ' <span class="pill cr">change requested</span>' : ""}</td><td class="r num">${r.age != null ? r.age + "d" : ""}</td></tr>`).join("") || `<tr><td colspan="8" class="muted">Nothing matches these filters.</td></tr>`}</tbody></table></div>`;
  const set = (id, k) => $(id).onchange = e => { f[k] = e.target.value; render(); };
  if ($("#chipx")) $("#chipx").onclick = () => { delete f.team; delete f.primary; render(); };
  set("#fcr", "change_requested"); set("#fs", "status"); set("#fm", "sm"); set("#fc", "category"); set("#fb", "bucket");
  $("#fq").onkeydown = e => { if (e.key === "Enter") { f.q = e.target.value; render(); } }; $("#fq").onblur = e => { if (e.target.value !== (f.q || "")) { f.q = e.target.value; render(); } };
  if ($("#new")) $("#new").onclick = () => editor();
  if ($("#up")) $("#up").onclick = () => uploadDialog();
  activate(el, "tr[data-id]", tr => detail(+tr.dataset.id));
}
const pill = r => r.status === "pending" && r.drop_requested_by ? `<span class="pill dropreq">drop requested</span>` : `<span class="pill ${r.status}">${r.status}</span>`;

function editor(e, request = false) {
  const isNew = !e, mine = S.me.sm_name, cats = S.meta.categories;
  const lines = Object.fromEntries((e?.lines || []).map(l => [l.category, l.amount]));
  const own = e ? e.owners.split("|") : (mine ? [mine] : []);
  modal(isNew ? "New estimate" : (request ? "Request change · " : "Edit ") + esc(e.number), `${request ? `<p class="muted" style="margin-top:0">Change what is wrong and tell finance why. Finance reviews it; any finance person can approve or reject, and everyone is notified. Nothing changes until it is approved.</p>` : ""}<form class="form" id="ef">
    <label>Estimate number<input name="number" required value="${esc(e?.number || "")}" placeholder="EST-26-27/264"></label>
    <label>Estimate date<input name="est_date" type="date" required max="${S.meta.today}" value="${e?.est_date || S.meta.today}"></label>
    <label class="full">Customer<input name="customer" required value="${esc(e?.customer || "")}"></label>
    <label class="full">Primary salesperson<select name="primary">${S.meta.sms.map(n => `<option ${n === own[0] ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></label>
    <div class="full"><div class="muted" style="font-size:12px;margin-bottom:4px">Also credited (joint deal) — optional</div><div class="chips">${S.meta.sms.map(n => `<label><input type="checkbox" name="own" value="${esc(n)}" ${own.slice(1).includes(n) ? "checked" : ""}>${esc(n)}</label>`).join("")}</div></div>
    <div class="full"><div class="muted" style="font-size:12px;margin-bottom:4px">Fees (₹, exclusive of tax — leave blank if not applicable)</div><div class="form">${cats.map(c => `<label><span><i style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${CAT_COLOR[c]};margin-right:5px"></i>${c}</span><input type="number" min="0" step="0.01" name="cat_${esc(c)}" value="${lines[c] ?? ""}"></label>`).join("")}</div></div>
    <label>Report month<input name="period" type="month" required max="${S.meta.today.slice(0, 7)}" value="${e?.period || S.meta.today.slice(0, 7)}"></label><div class="muted full" style="font-size:12px;margin-top:-6px">The month this estimate is counted in (normally the estimate date's month).</div>
    ${isNew ? `<label class="full">Estimate PDF from finance (optional — attach it so everyone can see the source)<input type="file" name="pdf" accept=".pdf,.png,.jpg,.jpeg"></label>` : ""}
    <label class="full">Notes<textarea name="notes" rows="2">${esc(e?.notes || "")}</textarea></label>
    ${request ? `<label class="full">Why is this change needed? (finance will see this)<textarea name="reason" rows="2" required placeholder="e.g. The revised PDF from finance shows ₹2,60,000"></textarea></label>` : ""}</form><div id="ee"></div>`,
    `<button class="btn" id="cx">Cancel</button><button class="btn primary" id="sv">${request ? "Send to finance" : "Save"}</button>`, () => {
      $("#cx").onclick = closeModal;
      $("#sv").onclick = async () => {
        const f = $("#ef"); if (!f.reportValidity()) return;
        const body = { number: f.number.value, est_date: f.est_date.value, period: f.period.value, customer: f.customer.value, notes: f.notes.value, version: e?.version,
          owners: [f.primary.value, ...[...f.querySelectorAll("[name=own]:checked")].map(x => x.value)],
          lines: cats.map(c => ({ category: c, amount: f["cat_" + c].value })).filter(l => l.amount !== "" && +l.amount !== 0) };
        try {
          if (request) { await api(`estimates/${e.id}/change-requests`, { method: "POST", body: { ...body, reason: f.reason.value } }); closeModal(); toast("Sent to finance — everyone has been notified"); render(); return; }
          const r = await api(isNew ? "estimates" : "estimates/" + e.id, { method: isNew ? "POST" : "PUT", body });
          const pdf = isNew && f.pdf.files[0];
          if (pdf) { try { await api(`estimates/${r.id}/files`, { method: "POST", body: { filename: pdf.name, content: await b64(pdf) } }); } catch (er) { toast("Saved, but the file was not attached: " + er.message); } }
          closeModal(); toast("Saved"); render(); }
        catch (er) { $("#ee").innerHTML = `<div class="err">${(er.data?.errors || [er.message]).map(esc).join("<br>")}</div>`; }
      };
    });
}

const b64 = file => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(r.result.split(",")[1]); r.onerror = no; r.readAsDataURL(file); });

function uploadDialog() {
  let current = null;
  modal("Upload estimates", `<p class="help" style="margin-top:0">Upload a CSV${""} (or Excel, if the server has openpyxl) with one row per fee line: <b>Estimate Date, Estimate Number, Customer Name, Subtotal, SM, Category</b> (optional: Report Month). Use "A &amp; B" in SM for a joint deal — the first name is the primary. New estimates start as pending. <a href="/api/estimates/template.csv" download>Download template</a></p>
    <input type="file" id="uf" accept=".csv,.xlsx,.xlsm"><div id="up-res" style="margin-top:12px"></div>`,
    `<button class="btn" id="cx">Close</button><button class="btn primary" id="go" disabled>Import</button>`, () => {
      $("#cx").onclick = closeModal;
      const show = r => {
        $("#up-res").innerHTML = `<div style="margin-bottom:8px"><b>${r.valid}</b> ready to import · <b style="color:${r.invalid ? "var(--bad)" : "inherit"}">${r.invalid}</b> with problems${r.invalid ? " (these are skipped)" : ""}</div>
        <div class="scroll" style="max-height:300px"><table><thead><tr><th>Row</th><th>Estimate</th><th>Customer</th><th>SM</th><th class="r">Total</th><th></th></tr></thead><tbody>
        ${r.rows.map(x => `<tr><td>${x.row}</td><td>${esc(x.number)}</td><td>${esc((x.customer || "").slice(0, 26))}</td><td>${esc(x.team)}</td><td class="r num">${inr(x.total)}</td><td style="white-space:normal">${x.ok ? '<span class="pill received">ok</span>' : `<span class="pill msg dropped">${esc(x.errors.join(" "))}</span>`}</td></tr>`).join("")}</tbody></table></div>`;
      };
      $("#uf").onchange = async e => {
        const f = e.target.files[0]; if (!f) return; $("#go").disabled = true;
        try { current = { filename: f.name, content: await b64(f) }; const r = await api("estimates/upload", { method: "POST", body: current }); show(r); $("#go").disabled = !r.valid; $("#go").textContent = `Import ${r.valid} estimate${r.valid === 1 ? "" : "s"}`; }
        catch (er) { $("#up-res").innerHTML = `<div class="err">${esc(er.message)}</div>`; }
      };
      $("#go").onclick = async () => {
        try { const r = await api("estimates/upload", { method: "POST", body: { ...current, commit: true } }); closeModal(); toast(`Imported ${r.imported} estimate${r.imported === 1 ? "" : "s"}`); render(); }
        catch (er) { $("#up-res").innerHTML = `<div class="err">${esc(er.message)}</div>`; }
      };
    });
}

const FLAG = { none: ["dropped", "No follow-up yet"], overdue: ["dropreq", "Follow-up overdue"], ok: ["received", "On track"] };
const timeline = (list, age) => list.length ? `<ol class="tl">${list.map((f, i) => `<li class="${i === list.length - 1 ? "last" : ""}"><div class="tl-h"><b>${fdate(f.on_date)}</b><span class="kind">${esc(f.kind)}</span><span class="muted">${esc(f.by_user)}${f.contact ? " · with " + esc(f.contact) : ""}</span></div>
  <div class="tl-n">${esc(f.note)}</div>${f.next_date ? `<div class="tl-x">Next follow-up: <b>${fdate(f.next_date)}</b></div>` : ""}</li>`).join("")}</ol>` : `<div class="tl-empty">No follow-up has been logged${age != null ? ` — pending for ${age} days` : ""}.</div>`;
const canFollow = e => S.me.role !== "sales" || (S.me.sm_name && e.owners.split("|").includes(S.me.sm_name));

async function followupsTab(el) {
  const DEF = { q: "", sm: S.me.role === "sales" ? S.me.sm_name || "" : "", cat: "", flag: "", age: "30", sort: "worst" };
  const F = S.fu = Object.assign({}, DEF, S.fu || {});
  const rows = (await api("followups?min_age=" + F.age)).map(r => ({ ...r, extra: r.followups.map(f => `${f.note} ${f.contact || ""} ${f.by_user}`).join(" ") }));
  const FSORT = { worst: ["Worst first (no follow-up, then overdue)", null], ...Object.fromEntries(["oldest", "newest", "high", "low", "az", "za", "number", "sm"].map(k => [k, SORTS[k]])),
    most: ["Most follow-ups", (a, b) => b.followups.length - a.followups.length], fewest: ["Fewest follow-ups", (a, b) => a.followups.length - b.followups.length],
    lastold: ["Last follow-up: longest ago", (a, b) => (a.last || "").localeCompare(b.last || "")], nextsoon: ["Next follow-up: soonest", (a, b) => (a.next || "9999").localeCompare(b.next || "9999")] };
  const extra = `<label class="f">Older than<select id="t-age">${opts([30, 60, 90].map(d => [String(d), d + " days"]), F.age)}</select></label>
    <label class="f">Show<select id="t-flag">${opts(Object.entries(FLAG).map(([k, v]) => [k, v[1]]), F.flag, "All")}</select></label>`;
  const sortMenu = Object.keys(FSORT).map(k => [k, FSORT[k][0]]);
  el.innerHTML = `<div class="bar"><div style="margin-right:auto"><h2>Follow-ups on pending estimates</h2><div class="sub">Every pending estimate older than ${F.age} days, with the full timeline of follow-ups.</div></div></div>
    <div class="toolbar"><label class="f grow">Search<input id="t-q" type="search" placeholder="Number, customer, name or notes…" value="${esc(F.q)}" autocomplete="off"></label>
    <label class="f">Sales manager<select id="t-sm">${opts(S.meta.sms, F.sm, "All")}</select></label>
    <label class="f">Fee type<select id="t-cat">${opts(S.meta.categories, F.cat, "All")}</select></label>${extra}
    <label class="f">Sort by<select id="t-sort">${opts(sortMenu, F.sort)}</select></label><button class="btn" id="t-reset" title="Clear the search, filters and sorting">Reset</button></div>
    <div class="attn" id="fu-chips" style="margin-bottom:16px"></div><div class="list" id="fu-list"></div>`;
  const paint = () => {
    const base = rows.filter(r => passes({ ...F, bucket: "" }, r)), vis = base.filter(r => !F.flag || r.flag === F.flag);
    if (F.sort !== "worst") vis.sort(FSORT[F.sort][1]);
    const n = k => base.filter(r => r.flag === k).length;
    $("#fu-chips").innerHTML = `<span class="pill dropped">${n("none")} with no follow-up</span><span class="pill dropreq">${n("overdue")} overdue</span><span class="pill received">${n("ok")} on track</span><span class="muted" style="align-self:center">${vis.length}${vis.length !== rows.length ? " of " + rows.length : ""} estimates · ₹ ${inr(vis.reduce((a, r) => a + r.total, 0))}</span>`;
    $("#fu-list").innerHTML = vis.map(r => `<div class="card fu"><div class="fu-h"><div class="grow"><b>${esc(r.number)}</b> · <span title="${esc(r.customer)}">${esc(r.customer)}</span>
      <div class="muted">${teamHtml(r.team)} · ₹ ${inr(r.total)} · <b>${r.age} days</b> pending · ${r.followups.length} follow-up${r.followups.length === 1 ? "" : "s"}${r.next ? " · next " + fdate(r.next) : ""}</div></div>
      <span class="pill ${FLAG[r.flag][0]}">${FLAG[r.flag][1]}</span>
      <button class="btn sm" data-open="${r.id}">Open</button>${canFollow(r) ? `<button class="btn sm primary" data-log="${r.id}">Log follow-up</button>` : ""}</div>${timeline(r.followups, r.age)}</div>`).join("") || `<div class="muted card">${rows.length ? "Nothing matches the search and filters." : "No pending estimate is older than this."}</div>`;
    el.querySelectorAll("[data-open]").forEach(b => b.onclick = () => detail(+b.dataset.open));
    el.querySelectorAll("[data-log]").forEach(b => b.onclick = () => followupForm(rows.find(r => r.id == b.dataset.log)));
  };
  let t; $("#t-q").oninput = e => { clearTimeout(t); t = setTimeout(() => { F.q = e.target.value; paint(); }, 120); };
  [["#t-sm", "sm"], ["#t-cat", "cat"], ["#t-flag", "flag"], ["#t-sort", "sort"]].forEach(([id, k]) => $(id).onchange = e => { F[k] = e.target.value; paint(); });
  $("#t-age").onchange = e => { F.age = e.target.value; render(); };
  $("#t-reset").onclick = () => { S.fu = { ...DEF }; render(); };
  paint();
}
function followupForm(e) {
  modal("Log follow-up · " + esc(e.number), `<form class="form" id="ff2">
    <label>Date<input type="date" name="on_date" required min="${e.est_date}" max="${S.meta.today}" value="${S.meta.today}"></label>
    <label>How<select name="kind">${["Call", "Email", "WhatsApp", "Meeting", "Other"].map(k => `<option>${k}</option>`).join("")}</select></label>
    <label class="full">Spoke to (optional)<input name="contact" placeholder="Name / role at the customer"></label>
    <label class="full">What was discussed / their response<textarea name="note" rows="3" required placeholder="e.g. Customer confirmed PO is with their finance team; payment promised by month end"></textarea></label>
    <label class="full">Next follow-up on (optional)<input type="date" name="next_date" min="${S.meta.today}"></label></form><div id="ee"></div>`,
    `<button class="btn" id="cx">Cancel</button><button class="btn primary" id="go">Save follow-up</button>`, () => {
      $("#cx").onclick = closeModal;
      $("#go").onclick = async () => { const f = $("#ff2"); if (!f.reportValidity()) return;
        try { await api(`estimates/${e.id}/followups`, { method: "POST", body: Object.fromEntries(new FormData(f)) }); closeModal(); toast("Follow-up logged"); render(); }
        catch (er) { $("#ee").innerHTML = `<div class="err">${(er.data?.errors || [er.message]).map(esc).join("<br>")}</div>`; } };
    });
}

const FIELD = { number: "Estimate number", est_date: "Estimate date", period: "Report month", customer: "Customer", owners: "Sales manager(s)", notes: "Notes", lines: "Fees" };
const fv = (f, v) => f === "lines" ? (v.map(([c, a]) => `${esc(c)} ₹${inr(a)}`).join(", ") || "—") : f === "owners" ? esc(v.join(" & ")) : f === "est_date" ? fdate(v) : f === "period" ? fmonth(v) : (esc(v) || "—");
const diffTable = ch => `<table class="diff"><tbody>${Object.entries(ch).map(([f, c]) => `<tr><th>${FIELD[f]}</th><td class="old">${fv(f, c.old)}</td><td class="arrow">→</td><td class="new">${fv(f, c.new)}</td></tr>`).join("")}</tbody></table>`;
const fstamp = at => (at || "").replace("T", " ").slice(0, 16);
async function crDecide(cr, decision, after) {
  const run = async note => { try { await api(`change-requests/${cr.id}/decision`, { method: "POST", body: { decision, note } }); closeModal(); toast(decision === "approve" ? "Change approved and applied" : "Change rejected"); (after || render)(); } catch (er) { const x = $("#ee"); if (x) x.innerHTML = `<div class="err">${esc(er.message)}</div>`; else toast(er.message); } };
  if (decision === "approve") return run("");
  modal("Reject change · " + esc(cr.number), `<p class="muted" style="margin-top:0">${esc(cr.requested_by)} asked: ${esc(cr.summary)}</p><label class="f" style="font-size:13px">Why is it rejected? (sales will see this)<textarea id="rs" rows="3"></textarea></label><div id="ee"></div>`,
    `<button class="btn" id="cx">Cancel</button><button class="btn danger" id="go">Reject</button>`, () => { $("#cx").onclick = closeModal; $("#go").onclick = () => run($("#rs").value); });
}
const crCard = (cr, actions = true) => `<div class="cr"><div><b>${esc(cr.requested_by)}</b> <span class="muted">asked for a change · ${fstamp(cr.requested_at)}</span></div><div class="cr-why">“${esc(cr.reason)}”</div>${diffTable(cr.changes)}${actions && can("finance") ? `<div class="cr-act"><button class="btn sm primary" data-cr-ok="${cr.id}">Approve &amp; apply</button><button class="btn sm danger" data-cr-no="${cr.id}">Reject…</button></div>` : ""}</div>`;

async function detail(id) {
  const e = await api("estimates/" + id), mineOrAdmin = S.me.role === "admin" || (S.me.sm_name && e.owners.split("|").includes(S.me.sm_name));
  const openReq = (e.change_requests || []).find(r => r.status === "open");
  const btns = [];
  if (e.status === "pending") {
    if (can("finance")) btns.push(`<button class="btn primary" id="a-rec">Record payment…</button>`);
    if (can("finance") && e.drop_requested_by) btns.push(`<button class="btn" id="a-rej">Reject drop</button>`, `<button class="btn danger" id="a-app">Approve drop</button>`);
    else if (can("finance")) btns.push(`<button class="btn danger" id="a-drop">Drop…</button>`);
    if (S.me.role === "sales" && mineOrAdmin && !e.drop_requested_by) btns.push(`<button class="btn danger" id="a-dreq">Propose drop…</button>`);
    if (can("finance")) btns.push(`<button class="btn" id="a-edit">Edit</button>`);
    if (S.me.role === "sales" && mineOrAdmin && !openReq) btns.push(`<button class="btn" id="a-req">Request change…</button>`);
    if (can("finance") || mineOrAdmin) btns.push(`<button class="btn" id="a-fu">Log follow-up</button>`);
  } else if (S.me.role === "admin") btns.push(`<button class="btn" id="a-reopen">Reopen…</button>`);
  const kv = [["Customer", esc(e.customer)], ["Report month", fmonth(e.period)], ["Estimate date", fdate(e.est_date) + (e.age != null ? ` · ${e.age} days old` : "")], ["Primary salesperson", esc(e.owners.split("|")[0])], ...(e.owners.includes("|") ? [["Also credited", esc(e.owners.split("|").slice(1).join(", "))]] : []),
    ...e.lines.map(l => [l.category, "₹ " + inr(l.amount)]), ["Total", `<b>₹ ${inr(e.total)}</b>`]];
  if (e.status === "received") kv.push(["Tax invoice", `${esc(e.invoice_no)} · ${fdate(e.invoice_date)}`], ["Payment received", fdate(e.closed_on) + (e.closed_approx ? " (approx., from legacy sheet)" : "")], ["Payment ref", esc(e.payment_ref || "—")]);
  if (e.status === "dropped") kv.push(["Dropped on", fdate(e.closed_on) + (e.closed_approx ? " (approx.)" : "")], ["Reason", esc(e.drop_reason || "—")]);
  if (e.drop_requested_by && e.status === "pending") kv.push(["Drop requested", `by ${esc(e.drop_requested_by)} on ${fdate(e.drop_requested_on)}: “${esc(e.drop_reason)}”`]);
  if (e.notes) kv.push(["Notes", esc(e.notes)]);
  kv.push(["Documents", (e.files.map(f => `<a href="/api/estimates/${e.id}/files/${f.id}">${esc(f.name)}</a> <span class="muted">${Math.round(f.size / 1024)} KB · ${esc(f.uploaded_by)}</span>`).join("<br>") || '<span class="muted">none</span>') + (can("sales") && mineOrAdmin || can("finance") ? `<br><label class="btn sm" style="display:inline-block;margin-top:6px;cursor:pointer">Attach estimate PDF/image<input type="file" id="att" accept=".pdf,.png,.jpg,.jpeg" hidden></label>` : "")]);
  modal(`${esc(e.number)} ${pill(e)}`, `${openReq ? `<div class="banner"><b>Change requested — waiting for finance</b>${crCard(openReq)}${openReq.requested_by === S.me.name || S.me.role === "admin" ? `<div class="cr-act"><button class="btn sm" id="cr-wd">Withdraw request</button></div>` : ""}</div>` : ""}${(e.change_requests || []).filter(r => r.status === "rejected").slice(0, 1).map(r => `<div class="banner rej"><b>Last change request was rejected</b> by ${esc(r.decided_by)}: ${esc(r.decision_note)}</div>`).join("")}<dl class="kv">${kv.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
    <h3 style="font-size:13px;margin-top:14px">Follow-ups (${e.followups.length})</h3>${timeline(e.followups, e.status === "pending" && e.age > 30 ? e.age : null)}
    <h3 style="font-size:13px;margin-top:14px">History</h3><ul class="log">${e.audit.map(a => `<li><b>${esc(a.action)}</b> · ${esc(a.user)} · ${esc(a.at.replace("T", " "))}${a.detail ? `<br>${esc(a.detail)}` : ""}</li>`).join("")}</ul>`, btns.join(""), () => {
    const on = (id, fn) => $(id) && ($(id).onclick = fn);
    on("#a-edit", () => editor(e)); on("#a-req", () => editor(e, true)); on("#a-fu", () => followupForm(e));
    if (openReq) { $("#dlg").querySelector("[data-cr-ok]")?.addEventListener("click", () => crDecide(openReq, "approve")); $("#dlg").querySelector("[data-cr-no]")?.addEventListener("click", () => crDecide(openReq, "reject"));
      on("#cr-wd", async () => { try { await api(`change-requests/${openReq.id}/withdraw`, { method: "POST", body: {} }); closeModal(); toast("Request withdrawn"); render(); } catch (er) { toast(er.message); } }); }
    if ($("#att")) $("#att").onchange = async ev => { const f = ev.target.files[0]; if (!f) return; try { await api(`estimates/${e.id}/files`, { method: "POST", body: { filename: f.name, content: await b64(f) } }); toast("Attached"); detail(e.id); } catch (er) { toast(er.message); } };
    on("#a-rec", () => payForm(e)); on("#a-app", () => reasonForm(e, "drop-decision", "Approve drop", { decision: "approve" }, e.drop_reason));
    on("#a-rej", () => reasonForm(e, "drop-decision", "Reject drop request", { decision: "reject" }, "", true));
    on("#a-drop", () => reasonForm(e, "drop-decision", "Drop estimate", { decision: "approve" }));
    on("#a-dreq", () => reasonForm(e, "drop-request", "Propose drop"));
    on("#a-reopen", () => reasonForm(e, "reopen", "Reopen estimate"));
  });
}
function reasonForm(e, act, title, extra = {}, prefill = "", optional = false) {
  modal(title + " · " + esc(e.number), `<label class="f" style="font-size:13px">Reason${optional ? " (optional)" : ""}<textarea id="rs" rows="3">${esc(prefill || "")}</textarea></label><div id="ee"></div>`,
    `<button class="btn" id="cx">Cancel</button><button class="btn primary" id="go">Confirm</button>`, () => {
      $("#cx").onclick = () => detail(e.id);
      $("#go").onclick = () => submit(e, act, { ...extra, reason: $("#rs").value });
    });
}
function payForm(e) {
  modal("Record payment · " + esc(e.number), `<p class="muted" style="margin-top:0">Marks ₹ ${inr(e.total)} from ${esc(e.customer)} as converted to a tax invoice.</p><form class="form" id="pf">
    <label>Tax invoice number<input name="invoice_no" required></label><label>Invoice date<input type="date" name="invoice_date" max="${S.meta.today}" value="${S.meta.today}"></label>
    <label>Payment received on<input type="date" name="received_on" required min="${e.est_date}" max="${S.meta.today}" value="${S.meta.today}"></label><label>Bank / UTR reference<input name="payment_ref"></label></form><div id="ee"></div>`,
    `<button class="btn" id="cx">Cancel</button><button class="btn primary" id="go">Mark received</button>`, () => {
      $("#cx").onclick = () => detail(e.id);
      $("#go").onclick = () => { const f = $("#pf"); if (f.reportValidity()) submit(e, "receive", Object.fromEntries(new FormData(f))); };
    });
}
async function submit(e, act, body) {
  try { await api(`estimates/${e.id}/${act}`, { method: "POST", body: { ...body, version: e.version } }); closeModal(); toast("Done"); render(); }
  catch (er) { const x = $("#ee"); if (x) x.innerHTML = `<div class="err">${esc(er.message)}</div>`; else toast(er.message); if (er.status === 409) setTimeout(() => detail(e.id), 900); }
}

/* ---------- shared search / filter / sort bar ---------- */
const ageOf = d => Math.round((new Date(S.meta.today + "T00:00") - new Date(d + "T00:00")) / 864e5);
const bucketOf = a => a <= 30 ? "0-30" : a <= 60 ? "31-60" : a <= 90 ? "61-90" : "90+";
const SORTS = {
  oldest: ["Oldest first", (a, b) => b.age - a.age], newest: ["Newest first", (a, b) => a.age - b.age],
  high: ["Amount: high to low", (a, b) => b.total - a.total], low: ["Amount: low to high", (a, b) => a.total - b.total],
  az: ["Customer A–Z", (a, b) => a.customer.localeCompare(b.customer)], za: ["Customer Z–A", (a, b) => b.customer.localeCompare(a.customer)],
  number: ["Estimate number", (a, b) => a.number.localeCompare(b.number, undefined, { numeric: true })], sm: ["Sales manager A–Z", (a, b) => a.team.localeCompare(b.team) || b.age - a.age],
};
const passes = (F, it) => (!F.q || [it.number, it.customer, it.team, it.extra || ""].join(" ").toLowerCase().includes(F.q.toLowerCase().trim()))
  && (!F.sm || it.owners.split("|").includes(F.sm)) && (!F.cat || it.categories.includes(F.cat)) && (!F.bucket || bucketOf(it.age) === F.bucket);
const opts = (arr, cur, all) => (all ? `<option value="">${all}</option>` : "") + arr.map(a => { const [v, l] = Array.isArray(a) ? a : [a, a]; return `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(l)}</option>`; }).join("");
function toolbar(F, { sorts, bucket = true, extra = "" }) {
  return `<div class="toolbar"><label class="f grow">Search<input id="t-q" type="search" placeholder="Estimate no., customer, sales manager…" value="${esc(F.q)}" autocomplete="off"></label>
    <label class="f">Sales manager<select id="t-sm">${opts(S.meta.sms, F.sm, "All")}</select></label>
    <label class="f">Fee type<select id="t-cat">${opts(S.meta.categories, F.cat, "All")}</select></label>
    ${bucket ? `<label class="f">Age<select id="t-b">${opts(S.meta.buckets.map(b => [b, b.replace("-", "–") + " days"]), F.bucket, "All")}</select></label>` : ""}
    ${extra}<label class="f">Sort by<select id="t-sort">${opts(sorts.map(k => [k, SORTS[k]?.[0] || k]), F.sort)}</select></label>
    <button class="btn" id="t-reset" title="Clear the search, filters and sorting">Reset</button></div>`;
}
function bindToolbar(root, F, defaults, paint, refetch) {
  let t; $("#t-q", root).oninput = e => { clearTimeout(t); t = setTimeout(() => { F.q = e.target.value; paint(); }, 120); };
  [["#t-sm", "sm"], ["#t-cat", "cat"], ["#t-b", "bucket"], ["#t-sort", "sort"]].forEach(([id, k]) => { const x = $(id, root); if (x) x.onchange = e => { F[k] = e.target.value; paint(); }; });
  $("#t-reset", root).onclick = () => { Object.assign(F, defaults); refetch(); };
}

/* ---------- finance desk ---------- */
async function finance(el) {
  const [drops, pend, crs] = await Promise.all([api("estimates?drop_requested=1"), api("estimates?status=pending"), api("change-requests?status=open")]);
  const DEF = { q: "", sm: "", cat: "", bucket: "", sort: "oldest", limit: 50 }, F = S.fd = Object.assign({}, DEF, S.fd || {});
  const items = {
    cr: crs.map(c => ({ ...c, team: c.owners.split("|").join(" & "), age: c.est_date ? ageOf(c.est_date) : 0, extra: `${c.reason} ${c.requested_by}` })),
    dr: drops.map(d => ({ ...d, extra: `${d.drop_reason || ""} ${d.drop_requested_by || ""}` })), pd: pend,
  };
  el.innerHTML = `<div class="bar"><h2>Finance desk</h2></div>${toolbar(F, { sorts: ["oldest", "newest", "high", "low", "az", "za", "number", "sm"] })}
    <div class="card" id="fd-cr" style="margin-bottom:16px"></div><div class="card" id="fd-dr" style="margin-bottom:16px"></div><div class="card" id="fd-pd"></div>`;
  const shown = (arr, label) => `${arr.length}${arr.length !== items[label].length ? " of " + items[label].length : ""}`;
  const paint = () => {
    const by = SORTS[F.sort][1], cr = items.cr.filter(x => passes(F, x)).sort(by), dr = items.dr.filter(x => passes(F, x)).sort(by), pd = items.pd.filter(x => passes(F, x)).sort(by);
    $("#fd-cr").innerHTML = `<h3>Change requests from sales (${shown(cr, "cr")})</h3><div class="hint">Any finance person can approve (the change is applied immediately) or reject with a reason. Sales and finance are notified either way.</div>
      ${cr.length ? `<div class="list">${cr.map(x => `<div class="item" style="display:block"><div style="display:flex;gap:12px;justify-content:space-between"><div><b>${esc(x.number)}</b> · <span title="${esc(x.customer)}">${esc(x.customer)}</span> <span class="muted">· ${teamHtml(x.team)} · ₹ ${inr(x.total)}</span></div><button class="btn sm" data-open="${x.estimate_id}">Open estimate</button></div>${crCard(x)}</div>`).join("")}</div>` : `<div class="muted">${items.cr.length ? "Nothing matches the search and filters." : "Nothing waiting."}</div>`}`;
    $("#fd-dr").innerHTML = `<h3>Drop requests from sales (${shown(dr, "dr")})</h3><div class="hint">Open a request to approve it (writes the estimate off) or reject it (keeps it pending).</div>
      ${dr.length ? `<div class="list">${dr.map(r => `<div class="item click" tabindex="0" data-id="${r.id}"><div class="grow"><b>${esc(r.number)}</b> · <span title="${esc(r.customer)}">${esc(r.customer)}</span> <span class="muted">· ${teamHtml(r.team)}</span><div class="muted">“${esc(r.drop_reason)}” — ${esc(r.drop_requested_by)}, ${fdate(r.drop_requested_on)}</div></div><div class="num"><b>₹ ${inr(r.total)}</b></div></div>`).join("")}</div>` : `<div class="muted">${items.dr.length ? "Nothing matches the search and filters." : "Nothing waiting."}</div>`}`;
    const page = pd.slice(0, F.limit);
    $("#fd-pd").innerHTML = `<h3>Pending estimates (${shown(pd, "pd")}) <span class="muted num" style="font-weight:400">· ₹ ${inr(pd.reduce((a, r) => a + r.total, 0))}</span></h3><div class="hint">Open an estimate to record the payment and tax invoice. Sorted by “${esc(SORTS[F.sort][0])}”.</div>
      <div class="scroll"><table><thead><tr><th>Estimate</th><th>Customer</th><th>Sales manager</th><th>Fees</th><th class="r">Amount</th><th class="r">Age</th><th></th></tr></thead><tbody>
      ${page.map(r => `<tr class="click" tabindex="0" data-id="${r.id}"><td>${esc(r.number)}</td><td class="clip" title="${esc(r.customer)}">${esc(r.customer)}</td><td>${teamHtml(r.team)}</td><td><span class="fees">${r.categories.map(c => `<span><i style="background:${CAT_COLOR[c]}"></i>${c.replace(" fees", "")}</span>`).join("")}</span></td><td class="r num">${inr(r.total)}</td><td class="r num">${r.age}d</td><td>${pill(r)}${r.change_requested ? ' <span class="pill cr">change requested</span>' : ""}</td></tr>`).join("") || `<tr><td colspan="7" class="muted">Nothing matches the search and filters.</td></tr>`}</tbody></table></div>
      ${pd.length > page.length ? `<div style="margin-top:12px"><button class="btn" id="more">Show ${Math.min(50, pd.length - page.length)} more (${pd.length - page.length} left)</button></div>` : ""}`;
    activate(el, "tr[data-id], .item[data-id]", x => detail(+x.dataset.id));
    el.querySelectorAll("[data-open]").forEach(b => b.onclick = () => detail(+b.dataset.open));
    el.querySelectorAll("[data-cr-ok]").forEach(b => b.onclick = () => crDecide(crs.find(c => c.id == b.dataset.crOk), "approve"));
    el.querySelectorAll("[data-cr-no]").forEach(b => b.onclick = () => crDecide(crs.find(c => c.id == b.dataset.crNo), "reject"));
    if ($("#more")) $("#more").onclick = () => { F.limit += 50; paint(); };
  };
  bindToolbar(el, F, DEF, () => { F.limit = DEF.limit; paint(); }, () => render()); paint();
}

/* ---------- published history ---------- */
async function historyTab(el) {
  const list = await api("snapshots");
  el.innerHTML = `<div class="bar"><h2>Published reports</h2><div class="sub">The numbers exactly as published each day — they don't change when data is edited later.</div></div>
  <div class="grid g2"><div class="card"><table><tbody>${list.map(s => `<tr class="click" tabindex="0" data-d="${s.day}"><td>${fdate(s.day)}</td><td class="muted">${esc(s.published_by)}</td></tr>`).join("") || '<tr><td class="muted">Nothing published yet. Finance publishes from the dashboard.</td></tr>'}</tbody></table></div><div class="card" id="snap"><div class="muted">Pick a day.</div></div></div>`;
  activate(el, "tr[data-d]", async tr => {
    const s = await api("snapshots/" + tr.dataset.d), r = s.data, t = r.total;
    $("#snap").innerHTML = `<h3>${fdate(s.day)} · published by ${esc(s.published_by)}</h3><dl class="kv"><dt>Opening</dt><dd class="num">₹ ${inr(t.opening)}</dd><dt>+ New</dt><dd class="num">₹ ${inr(t.new)}</dd><dt>− Converted</dt><dd class="num">₹ ${inr(t.converted)}</dd><dt>− Dropped</dt><dd class="num">₹ ${inr(t.dropped)}</dd><dt><b>Closing</b></dt><dd class="num"><b>₹ ${inr(t.closing)}</b></dd></dl>
      <table><thead><tr><th>Team</th><th class="r">Converted</th><th class="r">Closing</th></tr></thead><tbody>${r.teams.map(x => `<tr><td>${esc(x.team)}</td><td class="r num">${inr(x.converted)}</td><td class="r num">${inr(x.closing)}</td></tr>`).join("")}</tbody></table>`;
  });
}

/* ---------- admin ---------- */
async function admin(el) {
  const [users, sms, keys, hook] = await Promise.all([api("users"), api("sms"), api("keys"), api("webhook")]);
  el.innerHTML = `<div class="bar"><h2>Admin</h2></div><div class="grid g2">
  <div class="card"><h3>Users</h3><div class="hint">Sales users are linked to one sales manager.</div><div class="scroll"><table><thead><tr><th>User</th><th>Role</th><th>Linked SM</th><th></th></tr></thead><tbody>
    ${users.map(u => `<tr><td>${esc(u.name)} <span class="muted">${esc(u.username)}</span></td><td>${u.role}</td><td>${esc(u.sm_name || "")}</td><td>${u.active ? "" : '<span class="pill dropped">inactive</span> '}<button class="btn sm" data-u="${u.id}">Edit</button></td></tr>`).join("")}</tbody></table></div>
    <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap"><button class="btn primary" id="nu">+ Add user</button><button class="btn" id="bulk" title="Creates a sales login for every sales manager who doesn't have one yet">Create logins for all sales managers</button></div></div>
  <div class="card"><h3>Sales managers</h3><div class="hint">Deactivate someone who has left: history is kept, but they can't be picked on new estimates.</div>
    <div class="scroll"><table><tbody>${sms.map(s => `<tr><td>${esc(s.name)}</td><td class="r"><button class="btn sm" data-sm="${esc(s.name)}" data-on="${s.active ? 0 : 1}">${s.active ? "Deactivate" : "Reactivate"}</button></td></tr>`).join("")}</tbody></table></div>
    <form id="asm" class="bar" style="margin:12px 0 0"><label class="f">New sales manager<input name="n" required></label><button class="btn">Add</button></form></div>
  <div class="card"><h3>API access (CRM / other systems)</h3><div class="hint">Each system gets its own key. <b>read</b>: reports and estimates · <b>sales</b>: also create/edit estimates and upload · <b>finance</b>: also record payments and drops. See docs/API.md.</div>
    <div class="scroll"><table><tbody>${keys.map(k => `<tr><td>${esc(k.name)} <span class="muted">${esc(k.prefix)}…</span></td><td>${k.role}</td><td class="muted">${k.last_used ? "used " + esc(k.last_used.slice(0, 10)) : "never used"}</td><td class="r"><button class="btn sm" data-key="${k.id}" data-on="${k.active ? 0 : 1}">${k.active ? "Revoke" : "Restore"}</button></td></tr>`).join("") || '<tr><td class="muted">No keys yet.</td></tr>'}</tbody></table></div>
    <form id="ak" class="bar" style="margin:12px 0 0"><label class="f">System name<input name="n" required placeholder="CRM"></label><label class="f">Role<select name="r"><option>read</option><option selected>sales</option><option>finance</option></select></label><button class="btn">Create key</button></form></div>
  <div class="card"><h3>Webhook</h3><div class="hint">We POST estimate events (created, updated, drop_requested, received, dropped, reopened) to this URL, signed with HMAC-SHA256 in <code>X-DSR-Signature</code>.</div>
    <form id="wh" class="form"><label class="full">URL (https)<input name="u" value="${esc(hook.url)}" placeholder="https://crm.example.com/hooks/dsr"></label><label class="full">Signing secret ${hook.has_secret ? "(set — leave blank to keep)" : ""}<input name="s" type="password" autocomplete="new-password"></label><div class="full"><button class="btn primary">Save webhook</button></div></form></div></div>`;
  $("#ak").onsubmit = async e => { e.preventDefault(); try { const r = await api("keys", { method: "POST", body: { name: e.target.n.value, role: e.target.r.value } });
    modal("API key created", `<p>Copy this now — it is shown only once.</p><input readonly style="width:100%" value="${esc(r.token)}" onfocus="this.select()">`, `<button class="btn primary" id="cx">Done</button>`, () => $("#cx").onclick = () => { closeModal(); render(); }); } catch (er) { toast(er.message); } };
  el.querySelectorAll("[data-key]").forEach(b => b.onclick = async () => { await api("keys", { method: "PUT", body: { id: +b.dataset.key, active: b.dataset.on === "1" } }); render(); });
  $("#wh").onsubmit = async e => { e.preventDefault(); try { await api("webhook", { method: "PUT", body: { url: e.target.u.value, secret: e.target.s.value } }); toast("Webhook saved"); } catch (er) { toast(er.message); } };
  $("#asm").onsubmit = async e => { e.preventDefault(); try { await api("sms", { method: "POST", body: { name: e.target.n.value } }); S.meta = await api("meta"); render(); } catch (er) { toast(er.message); } };
  el.querySelectorAll("[data-sm]").forEach(b => b.onclick = async () => { await api("sms", { method: "POST", body: { name: b.dataset.sm, active: b.dataset.on === "1" } }); S.meta = await api("meta"); render(); });
  const userForm = u => modal(u ? "Edit user" : "Add user", `<form class="form" id="uf">
    <label>Name<input name="name" required value="${esc(u?.name || "")}"></label><label>Username<input name="username" required ${u ? "disabled" : ""} value="${esc(u?.username || "")}"></label>
    <label>Role<select name="role">${["sales", "finance", "admin"].map(r => `<option ${u?.role === r ? "selected" : ""}>${r}</option>`).join("")}</select></label>
    <label>Linked sales manager (sales only)<select name="sm_name"><option value="">—</option>${S.meta.sms.map(s => `<option ${u?.sm_name === s ? "selected" : ""}>${esc(s)}</option>`).join("")}</select></label>
    <label>${u ? "New password (leave blank to keep)" : "Password (min 8)"}<input name="password" type="password" autocomplete="new-password" ${u ? "" : "required"}></label>
    ${u ? `<label>Active<select name="active"><option value="1">Yes</option><option value="0" ${u.active ? "" : "selected"}>No</option></select></label>` : ""}</form><div id="ee"></div>`,
    `<button class="btn" id="cx">Cancel</button><button class="btn primary" id="go">Save</button>`, () => {
      $("#cx").onclick = closeModal;
      $("#go").onclick = async () => { const f = $("#uf"); if (!f.reportValidity()) return;
        const body = { id: u?.id, name: f.name.value, username: u ? u.username : f.username.value, role: f.role.value, sm_name: f.sm_name.value, password: f.password.value, active: u ? f.active.value === "1" : true };
        try { await api("users", { method: u ? "PUT" : "POST", body }); closeModal(); toast("Saved"); render(); } catch (er) { $("#ee").innerHTML = `<div class="err">${esc(er.message)}</div>`; } };
    });
  $("#nu").onclick = () => userForm();
  $("#bulk").onclick = async () => { try { const r = await api("users/bulk-sales", { method: "POST", body: {} }); toast(r.created.length ? `Created ${r.created.length} sales login${r.created.length > 1 ? "s" : ""}` : "Every sales manager already has a login"); render(); } catch (er) { toast(er.message); } };
  el.querySelectorAll("[data-u]").forEach(b => b.onclick = () => userForm(users.find(u => u.id == b.dataset.u)));
}
boot();
