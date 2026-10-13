"use strict";
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const inr = n => Math.round(n || 0).toLocaleString("en-IN");
const compact = n => { n = n || 0; const a = Math.abs(n); return a >= 1e7 ? (n / 1e7).toFixed(2) + " Cr" : a >= 1e5 ? (n / 1e5).toFixed(2) + " L" : a >= 1e3 ? (n / 1e3).toFixed(1) + "K" : String(Math.round(n)); };
const fdate = s => s ? new Date(s + "T00:00").toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "";
const fmonth = ym => new Date(ym + "-01T00:00").toLocaleDateString("en-GB", { month: "short", year: "numeric" });
const CAT_COLOR = { "Annual fees": "var(--s1)", "Set-up fees": "var(--s2)", "Integration": "var(--s3)", "Customisation": "var(--s4)" };
const AGE_COLOR = ["var(--a0)", "var(--a1)", "var(--a2)", "var(--a3)"];

const S = { me: null, meta: null, tab: "dashboard", month: null, split: false, filters: { status: "pending" } };

async function api(path, opt = {}) {
  const r = await fetch("/api/" + path, { method: opt.method || "GET", headers: opt.body ? { "Content-Type": "application/json" } : {}, body: opt.body ? JSON.stringify(opt.body) : undefined });
  if (r.status === 401 && path !== "login") { S.me = null; render(); throw new Error("Please sign in."); }
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
  const tabs = [["dashboard", "Dashboard"], ["estimates", "Estimates"]];
  if (can("finance")) tabs.push(["finance", "Finance desk"]);
  tabs.push(["history", "Published reports"], ["rules", "Rules"]);
  if (S.me.role === "admin") tabs.push(["admin", "Admin"]);
  app.innerHTML = `<header class="top"><span class="brand">Daily Sales Report</span>
    <nav>${tabs.map(([k, l]) => `<button data-tab="${k}" ${S.tab === k ? 'aria-current="page"' : ""}>${l}</button>`).join("")}</nav>
    <span class="who">${esc(S.me.name)} · ${esc(S.me.role)}${S.me.sm_name ? " (" + esc(S.me.sm_name) + ")" : ""}<button class="btn sm" id="out">Sign out</button></span></header>
    <main id="main"></main>`;
  app.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => { S.tab = b.dataset.tab; render(); });
  $("#out").onclick = async () => { await api("logout", { method: "POST", body: {} }); S.me = null; render(); };
  ({ dashboard, estimates, finance, history: historyTab, rules: rulesTab, admin }[S.tab])($("#main")).catch(e => $("#main").innerHTML = `<div class="err">${esc(e.message)}</div>`);
}
function renderLogin(app) {
  app.innerHTML = `<div class="login"><h1 style="margin-bottom:14px">Daily Sales Report</h1><form class="card" id="lf">
    <label class="f">Username<input name="u" autocomplete="username" required autofocus></label>
    <label class="f">Password<input name="p" type="password" autocomplete="current-password" required></label>
    <div id="le"></div><button class="btn primary">Sign in</button></form></div>`;
  $("#lf").onsubmit = async e => {
    e.preventDefault();
    try { await api("login", { method: "POST", body: { username: e.target.u.value, password: e.target.p.value } }); await boot(); }
    catch (er) { $("#le").innerHTML = `<div class="err">${esc(er.message)}</div>`; }
  };
}

/* ---------- dialog helper ---------- */
function modal(title, body, footer, onOpen) {
  const d = $("#dlg");
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
  const r = await api(`report?month=${S.month}&split=${S.split ? 1 : 0}`);
  const t = r.total, nz = (a, b) => b ? Math.round(a / b * 100) : 0;
  const lastPub = r.last_published;
  el.innerHTML = `
  <div class="bar"><div style="margin-right:auto"><h2>Report as on ${fdate(r.as_on)}</h2>
      <div class="sub">${lastPub ? `Last published ${fdate(lastPub.day)} by ${esc(lastPub.published_by)}` : "Not yet published"} · amounts are estimate sub-totals (before tax)</div></div>
    <label class="f">Month<select id="mon">${monthOptions().map(m => `<option value="${m}" ${m === S.month ? "selected" : ""}>${fmonth(m)}</option>`).join("")}</select></label>
    <label class="f">Credit<select id="split"><option value="0">Team as entered</option><option value="1" ${S.split ? "selected" : ""}>Split equally per person</option></select></label>
    <a class="btn" href="/api/export.csv" download>Export CSV</a>
    ${can("finance") ? `<button class="btn primary" id="pub">Publish today's report</button>` : ""}</div>
  ${r.pending_drop_requests && can("finance") ? `<div class="attn"><button id="goDrops">${r.pending_drop_requests} drop request${r.pending_drop_requests > 1 ? "s" : ""} waiting for finance →</button></div>` : ""}
  <div class="roll">
    ${[["Opening estimates", t.opening, t.opening_n], ["New estimates raised", t.new, t.new_n, "+"], ["Converted to tax invoice", t.converted, t.converted_n, "−"], ["Dropped / written off", t.dropped, t.dropped_n, "−"], ["Closing estimates (pending)", t.closing, t.closing_n, "="]]
      .map(([l, v, n, op]) => `<div class="k">${op ? `<span class="op">${op}</span>` : ""}<div class="lab">${l}</div><div class="val num" data-tip="₹ ${inr(v)}">₹ ${compact(v)}</div><div class="cnt num">${S.split ? n.toFixed(1) : n} estimate${n === 1 ? "" : "s"}</div></div>`).join("")}
  </div>
  <div class="grid g2" style="margin-bottom:16px">
    <div class="card"><h3>Conversions vs monthly target</h3><div class="hint">Estimates converted to tax invoices (count). Dashed tick = target set by finance.</div>${trendChart(r.trend)}</div>
    <div class="card"><h3>Ageing of closing estimates</h3><div class="hint">Value still pending, by days since estimate date and fee type.</div>${ageingChart(r)}</div>
  </div>
  <div class="card" style="margin-bottom:16px"><h3>Sales manager performance</h3><div class="hint">Roll-forward per ${S.split ? "person" : "team"}. Click a row to list their pending estimates.</div>
    <div class="scroll"><table><thead><tr><th>${S.split ? "Sales manager" : "Team"}</th><th class="r">Opening</th><th class="r">+ New</th><th class="r">− Converted</th><th class="r">− Dropped</th><th class="r">Closing</th><th class="r">%</th><th>Closing by age</th></tr></thead><tbody>
    ${r.teams.map(x => `<tr data-team="${esc(x.team)}" style="cursor:pointer"><td>${esc(x.team)}</td><td class="r num">${inr(x.opening)}</td><td class="r num">${inr(x.new)}</td><td class="r num">${inr(x.converted)}</td><td class="r num">${inr(x.dropped)}</td><td class="r num"><b>${inr(x.closing)}</b></td><td class="r num">${nz(x.closing, t.closing)}%</td><td>${ageBar(x.ageing, x.closing, esc(x.team))}</td></tr>`).join("")}
    <tr class="total"><td>Total</td><td class="r num">${inr(t.opening)}</td><td class="r num">${inr(t.new)}</td><td class="r num">${inr(t.converted)}</td><td class="r num">${inr(t.dropped)}</td><td class="r num">${inr(t.closing)}</td><td class="r num">100%</td><td></td></tr></tbody></table></div></div>
  <div class="grid g2">
    <div class="card"><h3>Revenue segment report</h3><div class="hint">Same roll-forward, by fee type.</div><div class="scroll"><table><thead><tr><th></th>${S.meta.categories.map(c => `<th class="r"><i style="display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;background:${CAT_COLOR[c]}"></i>${c}</th>`).join("")}<th class="r">Total</th></tr></thead><tbody>
      ${[["Opening", "opening"], ["+ New", "new"], ["− Converted", "converted"], ["− Dropped", "dropped"], ["Closing", "closing"]].map(([l, k]) => `<tr class="${k === "closing" ? "total" : ""}"><td>${l}</td>${S.meta.categories.map(c => `<td class="r num">${inr(r.segments[k][c])}</td>`).join("")}<td class="r num">${inr(Object.values(r.segments[k]).reduce((a, b) => a + b, 0))}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="card"><h3>Largest pending estimates</h3><div class="hint">Top 10 by value.</div><div class="scroll"><table><thead><tr><th>Customer</th><th>SM</th><th class="r">Age</th><th class="r">Amount</th></tr></thead><tbody>
      ${r.pending_by_value.map(p => `<tr><td>${esc(p.customer.slice(0, 32))}</td><td>${esc(p.owners.replace("|", " & "))}</td><td class="r num">${p.age}d</td><td class="r num">${inr(p.amount)}</td></tr>`).join("")}</tbody></table></div></div>
  </div>`;
  $("#mon").onchange = e => { S.month = e.target.value; render(); };
  $("#split").onchange = e => { S.split = e.target.value === "1"; render(); };
  if ($("#pub")) $("#pub").onclick = async () => { try { await api("snapshots", { method: "POST", body: {} }); toast("Report published"); render(); } catch (e) { toast(e.message); } };
  if ($("#goDrops")) $("#goDrops").onclick = () => { S.tab = "finance"; render(); };
  el.querySelectorAll("tr[data-team]").forEach(tr => tr.onclick = () => { S.filters = { status: "pending", sm: S.split ? tr.dataset.team : tr.dataset.team.split(" & ")[0] }; S.tab = "estimates"; render(); });
}
function ageBar(ag, tot, name) {
  if (!tot) return "";
  return `<div class="seg" role="img" aria-label="${name} closing by age">${["0-30", "31-60", "61-90", "90+"].map((b, i) => ag[b] ? `<span data-tip="${b} days: ₹ ${inr(ag[b])}" style="width:${ag[b] / tot * 100}%;background:${AGE_COLOR[i]}"></span>` : "").join("")}</div>`;
}
function trendChart(tr) {
  const W = 560, H = 210, L = 30, B = 26, T = 14, max = Math.max(5, ...tr.map(x => Math.max(x.actual || 0, x.target || 0))) * 1.1;
  const bw = (W - L) / tr.length, y = v => T + (H - T - B) * (1 - v / max);
  const ticks = [0, .25, .5, .75, 1].map(f => Math.round(max / 1.1 * f));
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Conversions per month versus target">
  <g class="grid">${ticks.map(v => `<line x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join("")}</g>
  ${tr.map((x, i) => { const cx = L + bw * i + bw / 2, w = Math.min(34, bw * .55), last = i === tr.length - 1;
    return `<g data-tip="<b>${fmonth(x.month)}</b><br>Converted: ${x.actual ?? "no data recorded"}${x.from_legacy ? " (legacy figure)" : ""}<br>Target: ${x.target ?? "not set"}${x.actual_amount ? `<br>Value: ₹ ${inr(x.actual_amount)}` : ""}">
      <rect x="${cx - bw / 2}" y="${T}" width="${bw}" height="${H - T - B}" fill="transparent"/>
      ${x.actual == null ? "" : `<path d="M${cx - w / 2},${y(0)} V${y(x.actual) + 4} a4,4 0 0 1 4,-4 h${w - 8} a4,4 0 0 1 4,4 V${y(0)} Z" fill="var(--s1)" opacity="${last ? 1 : .55}"/>`}
      ${x.target ? `<line x1="${cx - w / 2 - 5}" x2="${cx + w / 2 + 5}" y1="${y(x.target)}" y2="${y(x.target)}" stroke="var(--ink)" stroke-width="2" stroke-dasharray="4 3"/>` : ""}
      <text x="${cx}" y="${x.actual == null ? y(0) - 5 : y(x.actual) - 5}" text-anchor="middle" ${last ? 'style="fill:var(--ink);font-weight:600"' : ""}>${x.actual ?? "n/a"}</text>
      <text x="${cx}" y="${H - 8}" text-anchor="middle">${fmonth(x.month).replace(" 20", " ’")}</text></g>`; }).join("")}</svg>`;
}
function ageingChart(r) {
  const B = ["0-30", "31-60", "61-90", "90+"], cats = S.meta.categories;
  const tot = B.map(b => cats.reduce((a, c) => a + r.ageing_segments[b][c], 0)), mx = Math.max(1, ...tot), W = 560, L = 56, rowH = 38;
  return `<div class="legend">${cats.map(c => `<span><i style="background:${CAT_COLOR[c]}"></i>${c}</span>`).join("")}</div>
  <svg viewBox="0 0 ${W} ${B.length * rowH + 6}" width="100%" role="img" aria-label="Ageing of pending estimates">
  ${B.map((b, i) => { let x = L; const y = i * rowH + 4;
    return `<text x="${L - 8}" y="${y + 17}" text-anchor="end">${b} d</text>` + cats.map(c => { const v = r.ageing_segments[b][c], w = v / mx * (W - L - 130); if (!v) return ""; const seg = `<rect x="${x}" y="${y + 4}" width="${Math.max(w - 2, 1)}" height="18" rx="3" fill="${CAT_COLOR[c]}" data-tip="<b>${b} days · ${c}</b><br>₹ ${inr(v)}"/>`; x += w; return seg; }).join("")
      + `<text x="${x + 6}" y="${y + 17}" style="fill:var(--ink)">₹ ${compact(tot[i])} <tspan style="fill:var(--ink3)">· ${r.ageing_count[b]}</tspan></text>`; }).join("")}</svg>`;
}

/* ---------- estimates ---------- */
async function estimates(el) {
  const f = S.filters, qs = new URLSearchParams(Object.fromEntries(Object.entries(f).filter(([, v]) => v)));
  const rows = await api("estimates?" + qs);
  const opt = (arr, cur, all) => `<option value="">${all}</option>` + arr.map(a => `<option ${a === cur ? "selected" : ""}>${esc(a)}</option>`).join("");
  el.innerHTML = `<div class="bar"><h2>Estimates <span class="muted num" style="font-weight:400;font-size:14px">${rows.length} · ₹ ${inr(rows.reduce((a, r) => a + r.total, 0))}</span></h2>
    <label class="f">Search<input id="fq" placeholder="Customer or number" value="${esc(f.q || "")}"></label>
    <label class="f">Status<select id="fs"><option value="">All</option>${["pending", "received", "dropped"].map(s => `<option ${f.status === s ? "selected" : ""}>${s}</option>`).join("")}</select></label>
    <label class="f">Sales manager<select id="fm">${opt(S.meta.sms, f.sm, "All")}</select></label>
    <label class="f">Fee type<select id="fc">${opt(S.meta.categories, f.category, "All")}</select></label>
    <label class="f">Age<select id="fb">${opt(S.meta.buckets, f.bucket, "All")}</select></label>
    ${can("sales") ? `<button class="btn primary" id="new">+ New estimate</button>` : ""}</div>
    <div class="card scroll"><table><thead><tr><th>Estimate</th><th>Date</th><th>Customer</th><th>Sales manager</th><th>Fees</th><th class="r">Amount</th><th>Status</th><th class="r">Age</th></tr></thead><tbody>
    ${rows.map(r => `<tr data-id="${r.id}" style="cursor:pointer"><td>${esc(r.number)}</td><td>${fdate(r.est_date)}</td><td>${esc(r.customer.slice(0, 38))}</td><td>${esc(r.team)}</td>
      <td>${r.categories.map(c => `<span class="legend" style="display:inline-flex;margin:0 6px 0 0"><i style="background:${CAT_COLOR[c]}"></i>${c.replace(" fees", "")}</span>`).join("")}</td>
      <td class="r num">${inr(r.total)}</td><td>${pill(r)}</td><td class="r num">${r.age ?? ""}${r.age != null ? "d" : ""}</td></tr>`).join("") || `<tr><td colspan="8" class="muted">Nothing matches these filters.</td></tr>`}</tbody></table></div>`;
  const set = (id, k) => $(id).onchange = e => { f[k] = e.target.value; render(); };
  set("#fs", "status"); set("#fm", "sm"); set("#fc", "category"); set("#fb", "bucket");
  $("#fq").onkeydown = e => { if (e.key === "Enter") { f.q = e.target.value; render(); } }; $("#fq").onblur = e => { if (e.target.value !== (f.q || "")) { f.q = e.target.value; render(); } };
  if ($("#new")) $("#new").onclick = () => editor();
  el.querySelectorAll("tr[data-id]").forEach(tr => tr.onclick = () => detail(+tr.dataset.id));
}
const pill = r => r.status === "pending" && r.drop_requested_by ? `<span class="pill dropreq">drop requested</span>` : `<span class="pill ${r.status}">${r.status}</span>`;

function editor(e) {
  const isNew = !e, mine = S.me.sm_name, cats = S.meta.categories;
  const lines = Object.fromEntries((e?.lines || []).map(l => [l.category, l.amount]));
  const own = e ? e.owners.split("|") : (mine ? [mine] : []);
  modal(isNew ? "New estimate" : "Edit " + esc(e.number), `<form class="form" id="ef">
    <label>Estimate number<input name="number" required value="${esc(e?.number || "")}" placeholder="EST-26-27/264"></label>
    <label>Estimate date<input name="est_date" type="date" required max="${S.meta.today}" value="${e?.est_date || S.meta.today}"></label>
    <label class="full">Customer<input name="customer" required value="${esc(e?.customer || "")}"></label>
    <div class="full"><div class="muted" style="font-size:12px;margin-bottom:4px">Sales manager(s) — pick more than one for a joint deal</div><div class="chips">${S.meta.sms.map(n => `<label><input type="checkbox" name="own" value="${esc(n)}" ${own.includes(n) ? "checked" : ""}>${esc(n)}</label>`).join("")}</div></div>
    <div class="full"><div class="muted" style="font-size:12px;margin-bottom:4px">Fees (₹, exclusive of tax — leave blank if not applicable)</div><div class="form">${cats.map(c => `<label><span><i style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${CAT_COLOR[c]};margin-right:5px"></i>${c}</span><input type="number" min="0" step="0.01" name="cat_${esc(c)}" value="${lines[c] ?? ""}"></label>`).join("")}</div></div>
    <label>Report month<input name="period" type="month" required max="${S.meta.today.slice(0, 7)}" value="${e?.period || S.meta.today.slice(0, 7)}"></label><div class="muted full" style="font-size:12px;margin-top:-6px">The month this estimate is counted in (normally the estimate date's month).</div>
    <label class="full">Notes<textarea name="notes" rows="2">${esc(e?.notes || "")}</textarea></label></form><div id="ee"></div>`,
    `<button class="btn" id="cx">Cancel</button><button class="btn primary" id="sv">Save</button>`, () => {
      $("#cx").onclick = closeModal;
      $("#sv").onclick = async () => {
        const f = $("#ef"); if (!f.reportValidity()) return;
        const body = { number: f.number.value, est_date: f.est_date.value, period: f.period.value, customer: f.customer.value, notes: f.notes.value, version: e?.version,
          owners: [...f.querySelectorAll("[name=own]:checked")].map(x => x.value),
          lines: cats.map(c => ({ category: c, amount: f["cat_" + c].value })).filter(l => l.amount !== "" && +l.amount !== 0) };
        try { await api(isNew ? "estimates" : "estimates/" + e.id, { method: isNew ? "POST" : "PUT", body }); closeModal(); toast("Saved"); render(); }
        catch (er) { $("#ee").innerHTML = `<div class="err">${(er.data?.errors || [er.message]).map(esc).join("<br>")}</div>`; }
      };
    });
}

async function detail(id) {
  const e = await api("estimates/" + id), mineOrAdmin = S.me.role === "admin" || (S.me.sm_name && e.owners.split("|").includes(S.me.sm_name));
  const btns = [];
  if (e.status === "pending") {
    if (can("finance")) btns.push(`<button class="btn primary" id="a-rec">Record payment…</button>`);
    if (can("finance") && e.drop_requested_by) btns.push(`<button class="btn" id="a-rej">Reject drop</button>`, `<button class="btn danger" id="a-app">Approve drop</button>`);
    else if (can("finance")) btns.push(`<button class="btn danger" id="a-drop">Drop…</button>`);
    if (S.me.role === "sales" && mineOrAdmin && !e.drop_requested_by) btns.push(`<button class="btn danger" id="a-dreq">Propose drop…</button>`);
    if (can("sales") && mineOrAdmin) btns.push(`<button class="btn" id="a-edit">Edit</button>`);
  } else if (S.me.role === "admin") btns.push(`<button class="btn" id="a-reopen">Reopen…</button>`);
  const kv = [["Customer", esc(e.customer)], ["Report month", fmonth(e.period)], ["Estimate date", fdate(e.est_date) + (e.age != null ? ` · ${e.age} days old` : "")], ["Sales manager", esc(e.owners.replace("|", " & "))],
    ...e.lines.map(l => [l.category, "₹ " + inr(l.amount)]), ["Total", `<b>₹ ${inr(e.total)}</b>`]];
  if (e.status === "received") kv.push(["Tax invoice", `${esc(e.invoice_no)} · ${fdate(e.invoice_date)}`], ["Payment received", fdate(e.closed_on) + (e.closed_approx ? " (approx., from legacy sheet)" : "")], ["Payment ref", esc(e.payment_ref || "—")]);
  if (e.status === "dropped") kv.push(["Dropped on", fdate(e.closed_on) + (e.closed_approx ? " (approx.)" : "")], ["Reason", esc(e.drop_reason || "—")]);
  if (e.drop_requested_by && e.status === "pending") kv.push(["Drop requested", `by ${esc(e.drop_requested_by)} on ${fdate(e.drop_requested_on)}: “${esc(e.drop_reason)}”`]);
  if (e.notes) kv.push(["Notes", esc(e.notes)]);
  modal(`${esc(e.number)} ${pill(e)}`, `<dl class="kv">${kv.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
    <h3 style="font-size:13px;margin-top:14px">History</h3><ul class="log">${e.audit.map(a => `<li><b>${esc(a.action)}</b> · ${esc(a.user)} · ${esc(a.at.replace("T", " "))}${a.detail ? `<br>${esc(a.detail)}` : ""}</li>`).join("")}</ul>`, btns.join(""), () => {
    const on = (id, fn) => $(id) && ($(id).onclick = fn);
    on("#a-edit", () => editor(e));
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

/* ---------- finance desk ---------- */
async function finance(el) {
  const [drops, pend, targets] = await Promise.all([api("estimates?drop_requested=1"), api("estimates?status=pending"), api("targets")]);
  const t = Object.fromEntries(targets.map(x => [x.month, x])), months = monthOptions().slice(0, 8).reverse().concat(monthOptions()[0] === S.meta.today.slice(0, 7) ? [] : []);
  const fut = (() => { const [y, m] = S.meta.today.split("-").map(Number); const o = []; for (let i = 1; i <= 2; i++) { let mm = m + i, yy = y; if (mm > 12) { mm -= 12; yy++; } o.push(`${yy}-${String(mm).padStart(2, "0")}`); } return o; })();
  el.innerHTML = `<div class="bar"><h2>Finance desk</h2></div>
  <div class="grid g2">
  <div class="card"><h3>Drop requests from sales (${drops.length})</h3><div class="hint">Approve to write the estimate off, or reject to keep it pending.</div>
    ${drops.length ? `<table><tbody>${drops.map(r => `<tr data-id="${r.id}" style="cursor:pointer"><td>${esc(r.number)}<br><span class="muted">${esc(r.customer.slice(0, 30))}</span></td><td class="r num">₹ ${inr(r.total)}</td><td style="white-space:normal;max-width:220px">“${esc(r.drop_reason)}”<br><span class="muted">${esc(r.drop_requested_by)}</span></td></tr>`).join("")}</tbody></table>` : `<div class="muted">Nothing waiting.</div>`}</div>
  <div class="card"><h3>Monthly targets</h3><div class="hint">Number of estimates expected to convert to tax invoices.</div>
    <table><thead><tr><th>Month</th><th class="r">Count</th><th class="r">Amount (₹, optional)</th><th></th></tr></thead><tbody>${[...months, ...fut].map(m => `<tr><td>${fmonth(m)}</td><td class="r"><input style="width:80px" type="number" min="0" data-t="${m}" data-k="target_count" value="${t[m]?.target_count ?? ""}"></td><td class="r"><input style="width:120px" type="number" min="0" data-t="${m}" data-k="target_amount" value="${t[m]?.target_amount ?? ""}"></td><td><button class="btn sm" data-save="${m}">Save</button></td></tr>`).join("")}</tbody></table></div></div>
  <div class="card" style="margin-top:16px"><h3>Pending — oldest first (${pend.length})</h3><div class="hint">Open an estimate to record the payment and tax invoice.</div><div class="scroll"><table><thead><tr><th>Estimate</th><th>Customer</th><th>SM</th><th class="r">Amount</th><th class="r">Age</th><th></th></tr></thead><tbody>
  ${pend.sort((a, b) => b.age - a.age).slice(0, 40).map(r => `<tr data-id="${r.id}" style="cursor:pointer"><td>${esc(r.number)}</td><td>${esc(r.customer.slice(0, 36))}</td><td>${esc(r.team)}</td><td class="r num">${inr(r.total)}</td><td class="r num">${r.age}d</td><td>${pill(r)}</td></tr>`).join("")}</tbody></table></div></div>`;
  el.querySelectorAll("tr[data-id]").forEach(tr => tr.onclick = () => detail(+tr.dataset.id));
  el.querySelectorAll("[data-save]").forEach(b => b.onclick = async () => {
    const m = b.dataset.save, g = k => el.querySelector(`[data-t="${m}"][data-k="${k}"]`).value;
    try { await api("targets", { method: "PUT", body: { month: m, target_count: g("target_count"), target_amount: g("target_amount") } }); toast("Target saved"); } catch (e) { toast(e.message); }
  });
}

/* ---------- published history ---------- */
async function historyTab(el) {
  const list = await api("snapshots");
  el.innerHTML = `<div class="bar"><h2>Published reports</h2><div class="sub">The numbers exactly as published each day — they don't change when data is edited later.</div></div>
  <div class="grid g2"><div class="card"><table><tbody>${list.map(s => `<tr data-d="${s.day}" style="cursor:pointer"><td>${fdate(s.day)}</td><td class="muted">${esc(s.published_by)}</td></tr>`).join("") || '<tr><td class="muted">Nothing published yet. Finance publishes from the dashboard.</td></tr>'}</tbody></table></div><div class="card" id="snap"><div class="muted">Pick a day.</div></div></div>`;
  el.querySelectorAll("tr[data-d]").forEach(tr => tr.onclick = async () => {
    const s = await api("snapshots/" + tr.dataset.d), r = s.data, t = r.total;
    $("#snap").innerHTML = `<h3>${fdate(s.day)} · published by ${esc(s.published_by)}</h3><dl class="kv"><dt>Opening</dt><dd class="num">₹ ${inr(t.opening)}</dd><dt>+ New</dt><dd class="num">₹ ${inr(t.new)}</dd><dt>− Converted</dt><dd class="num">₹ ${inr(t.converted)}</dd><dt>− Dropped</dt><dd class="num">₹ ${inr(t.dropped)}</dd><dt><b>Closing</b></dt><dd class="num"><b>₹ ${inr(t.closing)}</b></dd></dl>
      <table><thead><tr><th>Team</th><th class="r">Converted</th><th class="r">Closing</th></tr></thead><tbody>${r.teams.map(x => `<tr><td>${esc(x.team)}</td><td class="r num">${inr(x.converted)}</td><td class="r num">${inr(x.closing)}</td></tr>`).join("")}</tbody></table>`;
  });
}

/* ---------- rules ---------- */
async function rulesTab(el) {
  el.innerHTML = `<div class="bar"><h2>How this works</h2></div><div class="grid g2">
  <div class="card help"><h3>Who enters what</h3><ul>
   <li><b>Sales</b> raise estimates (number, date, customer, fees by type, sales manager). They can edit an estimate while it is pending, and <i>propose</i> a drop with a reason. They can see everyone's numbers.</li>
   <li><b>Finance</b> records the payment and tax invoice (which converts the estimate), approves or rejects drop requests, may drop directly with a reason, sets monthly targets and publishes the daily report.</li>
   <li><b>Admin</b> manages users and the sales-manager list, and is the only role that can reopen a closed estimate.</li></ul></div>
  <div class="card help"><h3>Rules the system enforces</h3><ul>
   <li>Estimate numbers are unique. One estimate can carry several fee lines (one per fee type); status belongs to the whole estimate.</li>
   <li>Estimate date can't be in the future; payment can't be before the estimate or in the future; a tax invoice number is mandatory to mark received.</li>
   <li>Amounts must be positive. Sales can only raise/edit estimates they are a named sales manager on.</li>
   <li>Closed (received/dropped) estimates are locked. Every change is logged; two people editing the same estimate can't overwrite each other.</li></ul></div>
  <div class="card help"><h3>How the numbers are built</h3><ul>
   <li><b>Opening</b> = estimates booked in earlier months that were still pending on the 1st. <b>New</b> = estimates booked in the month (the <i>report month</i> on each estimate, normally its date's month). <b>Converted / Dropped</b> = closed in the month (any estimate date).</li>
   <li><b>Closing = Opening + New − Converted − Dropped</b> = what is pending as on the report date. Because closure dates are stored, you can pick any past month and get the same answer the workbook would have given.</li>
   <li><b>Age</b> = report date − estimate date: 0–30, 31–60, 61–90, 90+ days.</li>
   <li>Joint deals ("A &amp; B") show as their own team row, as in the workbook; switch <i>Credit</i> to "split equally" to attribute them per person.</li></ul></div>
  <div class="card help"><h3>Daily routine</h3><ul><li>Sales update estimates through the day.</li><li>Finance records receipts and decisions.</li><li>Finance clicks <b>Publish today's report</b> — it freezes the day's numbers under <i>Published reports</i> and anyone can open the dashboard live instead of waiting for the email.</li></ul></div></div>`;
}

/* ---------- admin ---------- */
async function admin(el) {
  const [users, sms] = await Promise.all([api("users"), api("sms")]);
  el.innerHTML = `<div class="bar"><h2>Admin</h2></div><div class="grid g2">
  <div class="card"><h3>Users</h3><div class="hint">Sales users are linked to one sales manager.</div><div class="scroll"><table><thead><tr><th>User</th><th>Role</th><th>Linked SM</th><th></th></tr></thead><tbody>
    ${users.map(u => `<tr><td>${esc(u.name)} <span class="muted">${esc(u.username)}</span></td><td>${u.role}</td><td>${esc(u.sm_name || "")}</td><td>${u.active ? "" : '<span class="pill dropped">inactive</span> '}<button class="btn sm" data-u="${u.id}">Edit</button></td></tr>`).join("")}</tbody></table></div>
    <button class="btn primary" id="nu" style="margin-top:12px">+ Add user</button></div>
  <div class="card"><h3>Sales managers</h3><div class="hint">Deactivate someone who has left: history is kept, but they can't be picked on new estimates.</div>
    <table><tbody>${sms.map(s => `<tr><td>${esc(s.name)}</td><td class="r"><button class="btn sm" data-sm="${esc(s.name)}" data-on="${s.active ? 0 : 1}">${s.active ? "Deactivate" : "Reactivate"}</button></td></tr>`).join("")}</tbody></table>
    <form id="asm" class="bar" style="margin:12px 0 0"><label class="f">New sales manager<input name="n" required></label><button class="btn">Add</button></form></div></div>`;
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
  el.querySelectorAll("[data-u]").forEach(b => b.onclick = () => userForm(users.find(u => u.id == b.dataset.u)));
}
boot();
