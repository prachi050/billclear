// BillClear front end. Plain JavaScript, no build step.
// The page and the WebMCP tools call the same /api endpoints, so an AI agent
// can only do what a person can do here, and sending needs a person's approval.

const $ = (s) => document.querySelector(s);
const money = (n) => "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

let currentId = null;
let filter = "all";
const today = () => new Date().toISOString().slice(0, 10);
const prettyDate = (d) => new Date(d + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
function toast(t) {
  const el = document.createElement("div");
  el.className = "toast"; el.setAttribute("role", "status"); el.textContent = t;
  document.body.appendChild(el); setTimeout(() => el.remove(), 2500);
}
async function loadSummary() {
  const s = await api("/api/summary");
  const stat = (n, l, hot) => `<div class="stat ${hot ? "hot" : ""}"><div class="n">${n}</div><div class="l">${l}</div></div>`;
  $("#summary").innerHTML =
    stat(money(s.total_due), `still due on ${s.bills_due} bill${s.bills_due === 1 ? "" : "s"}`) +
    stat(s.needs_attention, "need a closer look", s.needs_attention > 0) +
    stat(s.overdue, "past due date", s.overdue > 0) +
    stat(s.next_due ? prettyDate(s.next_due) : "None", "next due date");
}
async function loadHistory() {
  const { appeals } = await api("/api/appeals");
  const el = $("#history-panel");
  if (!appeals.length) { el.innerHTML = ""; return; }
  el.innerHTML = `<div class="card"><h2>Your appeals</h2><ul class="hist">${appeals.map((a) => `
    <li><span><b>${esc(a.claim_id)}</b> &middot; ${esc(a.reason)}</span>
    <span class="meta">${esc(a.status === "sent" ? "Marked as sent (demo)" : a.status === "approved" ? "Approved, not sent" : "Draft")}</span></li>`).join("")}</ul></div>`;
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
  filter = b.dataset.f;
  document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
  loadList();
}));
// Appeal ids the person approved by clicking the button on this page.
// An agent tool can never add to this set.
const approvedByPerson = new Set();

// ---------- Statement list ----------
async function loadList() {
  let { claims } = await api("/api/claims");
  if (filter === "paid") claims = claims.filter((c) => c.paid);
  if (filter === "attention") claims = claims.filter((c) => !c.paid && c.flag_types.some((t) => t !== "not_a_bill"));
  if (!claims.length) { $("#claims").innerHTML = '<li class="empty">Nothing here.</li>'; return; }
  $("#claims").innerHTML = claims.map((c) => {
    const due = c.paid ? '<span class="pill paid">paid</span>' : c.due_date
      ? `<span class="due ${c.due_date < today() ? "over" : ""}">${c.due_date < today() ? "Past due" : "Due"} ${prettyDate(c.due_date)}</span>` : "";
    const pills = c.flag_types.map((t) => {
      const action = t !== "not_a_bill" ? " action" : "";
      return `<span class="pill${action}">${esc(t.replace(/_/g, " "))}</span>`;
    }).join("");
    return `<li><button class="claim" data-id="${esc(c.id)}" aria-current="${c.id === currentId}">
      <b>${esc(c.provider)}</b>
      <span class="meta">${esc(c.service_date)} &middot; ${esc(c.doc_type === "EOB" ? "Not a bill (EOB)" : "Bill")}</span><br>
      <span class="meta">Billed ${money(c.billed)} &middot; You owe ${money(c.patient_owes)}</span><br>${due} ${pills}</button></li>`;
  }).join("");
  document.querySelectorAll(".claim").forEach((b) => b.addEventListener("click", () => showClaim(b.dataset.id)));
}

// ---------- Upload: photo in, claim out ----------
function showUpload(r) {
  const el = $("#upload-result");
  if (!r.ok) {
    el.innerHTML = `<div class="flag action"><b>I could not read this reliably</b>${r.problems.map(esc).join("<br>")}<br>Nothing was added, because I will not guess at numbers. Try a clearer photo.</div>`;
    return;
  }
  const f = r.found;
  el.innerHTML = `<div class="flag"><b>Read with ${esc(r.reader)}</b>${esc(f.provider)} &middot; ${esc(f.service_date)} &middot; ${f.charges.length} line item${f.charges.length === 1 ? "" : "s"} &middot; you owe ${money(f.patient_owes)}.
    The amounts add up, so it was added to your list.</div>`;
}
async function sendImage(blob, type) {
  $("#upload-result").textContent = "Reading...";
  const res = await fetch("/api/upload", { method: "POST", headers: { "Content-Type": type }, body: blob });
  const r = await res.json();
  if (!res.ok) { $("#upload-result").innerHTML = `<div class="flag action">${esc(r.detail || "Upload failed")}</div>`; return null; }
  showUpload(r);
  if (r.ok) { await loadList(); loadSummary(); showClaim(r.claim_id); }
  return r;
}
async function useSample(name) {
  $("#upload-result").textContent = "Reading...";
  const r = await api(`/api/upload-sample/${encodeURIComponent(name)}`, { method: "POST" });
  showUpload(r);
  if (r.ok) { await loadList(); loadSummary(); showClaim(r.claim_id); }
  return r;
}
$("#file").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) sendImage(f, f.type); e.target.value = ""; });
document.querySelectorAll("#samples button").forEach((b) => b.addEventListener("click", () => useSample(b.dataset.s)));

// ---------- Statement detail ----------
async function showClaim(id) {
  currentId = id;
  const d = await api(`/api/claims/${encodeURIComponent(id)}`);
  const { claim, charges, flags, owed, next_steps } = d;
  const explained = await Promise.all(charges.map((ch) => api(`/api/charges/${ch.id}/explain`)));
  $("#detail-panel").innerHTML = `
    <div class="card">
      <h2>${esc(claim.provider)}</h2>
      <p class="meta">${esc(claim.id)} &middot; ${esc(claim.service_date)} &middot; <span class="status">${esc(claim.status)}</span></p>
      ${flags.map((f) => `<div class="flag ${f.severity === "action" ? "action" : ""}"><b>${esc(f.title)}</b>${esc(f.detail)}</div>`).join("") || "<p>Nothing unusual spotted.</p>"}
    </div>
    <div class="card">
      <h2>What you owe and why</h2>
      <table>
        <tr><td>Billed by provider</td><td class="num">${money(owed.billed)}</td></tr>
        <tr><td>Plan discount</td><td class="num">-${money(owed.plan_discount)}</td></tr>
        <tr><td>Amount your plan allows</td><td class="num">${money(owed.allowed)}</td></tr>
        <tr><td>Plan paid</td><td class="num">${money(owed.plan_paid)}</td></tr>
        <tr><th>You owe</th><th class="num">${money(owed.you_owe)}</th></tr>
      </table>
      <p>${esc(owed.why)}</p>
    </div>
    <div class="card">
      <h2>Line items in plain words</h2>
      <table>${explained.map((e) => `<tr><td><b>${esc(e.title)}</b> <span class="meta">(${esc(e.charge.code)})</span>
        <p class="explain">${esc(e.plain)}</p></td><td class="num">${money(e.charge.amount)}</td></tr>`).join("")}</table>
    </div>
    <div class="card" id="ai-card">
      <h2>AI explanation <span class="meta" id="ai-model"></span></h2>
      <p id="ai-text" class="meta">Loading...</p>
      <div id="ai-check"></div>
      <div class="row"><button class="ghost" id="ai-demo">Show a wrong number the checker would catch</button></div>
    </div>
    <div class="card">
      <h2>Questions you could ask</h2>
      <ul>${next_steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
      <div class="row"><button class="primary" id="draft">Draft an appeal letter</button></div>
      <div id="appeal-area"></div>
    </div>`;
  if (claim.doc_type === "BILL") {
    const b = document.createElement("button");
    b.className = "ghost"; b.id = "paid";
    b.textContent = claim.paid ? "Mark as unpaid" : "I paid this bill";
    b.onclick = async () => { await api(`/api/claims/${encodeURIComponent(id)}/paid`, { method: "POST", body: { paid: !claim.paid } }); toast(claim.paid ? "Marked as unpaid" : "Marked as paid"); refresh(id); };
    $("#draft").parentElement.appendChild(b);
  }
  $("#draft").addEventListener("click", () => draftAppeal(id));
  const runAI = async (corrupt) => {
    try {
      const r = await api(`/api/claims/${encodeURIComponent(id)}/ai-explain` + (corrupt ? `?corrupt=${corrupt}` : ""));
      $("#ai-model").textContent = "(" + r.model + ")";
      $("#ai-text").textContent = r.explanation;
      $("#ai-check").innerHTML = r.check.ok
        ? '<div class="flag"><b>Numbers checked</b>Every amount in this explanation matches the statement.</div>'
        : r.check.mismatches.map((m) => `<div class="flag action"><b>Number does not match</b>${esc(m.message)} Do not rely on this explanation.</div>`).join("");
    } catch (e) { $("#ai-text").textContent = "Explanation unavailable."; }
  };
  $("#ai-demo").addEventListener("click", () => runAI("wrong_owes"));
  runAI();
  loadList(); loadSummary(); loadHistory();
}

function refresh(id) { showClaim(id); }

// ---------- Appeal: draft, edit, approve (person only), send ----------
async function draftAppeal(claimId, note) {
  const a = await api("/api/appeals/draft", { method: "POST", body: { claim_id: claimId, note } });
  renderAppeal(a);
  return a;
}

function renderAppeal(a) {
  const area = $("#appeal-area");
  if (!area) return;
  const approved = approvedByPerson.has(a.id);
  const sent = a.status === "sent";
  area.innerHTML = `
    <h3>${esc(a.reason)}</h3>
    <div class="step" aria-label="Progress"><span class="on">1 Draft</span><span class="${approved || sent ? "on" : ""}">2 You approve</span><span class="${sent ? "on" : ""}">3 Send</span></div>
    <p class="meta">Read it, change anything you like, then approve it yourself. Nothing is sent without your approval.</p>
    <textarea id="appeal-body" aria-label="Appeal letter text" ${sent ? "disabled" : ""}>${esc(a.body)}</textarea>
    <div class="row">
      <button class="ghost" id="save" ${sent ? "disabled" : ""}>Save edits</button>
      <button class="primary" id="approve" ${sent || approved ? "disabled" : ""}>${approved ? "Approved by you" : "I have read this and approve it"}</button>
      <button class="ghost" id="dl">Download letter</button>
      <button class="primary" id="send" ${approved && !sent ? "" : "disabled"}>${sent ? "Marked as sent (demo)" : "Send (demo)"}</button>
    </div>
    <p class="meta" id="appeal-msg"></p>`;
  const msg = (t) => ($("#appeal-msg").textContent = t);
  $("#save").onclick = async () => {
    await api(`/api/appeals/${a.id}`, { method: "PUT", body: { body: $("#appeal-body").value } });
    approvedByPerson.delete(a.id);  // edits cancel approval
    renderAppeal({ ...a, body: $("#appeal-body").value, status: "draft" });
    $("#appeal-msg").textContent = "Saved. Please approve again.";
  };
  $("#approve").onclick = async () => {
    await api(`/api/appeals/${a.id}`, { method: "PUT", body: { body: $("#appeal-body").value } });
    await api(`/api/appeals/${a.id}/approve`, { method: "POST" });
    approvedByPerson.add(a.id);
    renderAppeal({ ...a, body: $("#appeal-body").value, status: "approved" });
  };
  $("#dl").onclick = () => {
    const url = URL.createObjectURL(new Blob([$("#appeal-body").value], { type: "text/plain" }));
    const l = document.createElement("a"); l.href = url; l.download = `appeal-${a.claim_id}.txt`; l.click(); URL.revokeObjectURL(url);
  };
  $("#send").onclick = async () => {
    try {
      const r = await api(`/api/appeals/${a.id}/submit`, { method: "POST" });
      renderAppeal({ ...a, body: $("#appeal-body").value, status: "sent" });
      $("#appeal-msg").textContent = r.note; toast("Appeal marked as sent (demo)"); loadHistory();
    } catch (e) { msg(e.message); }
  };
}

$("#reset").addEventListener("click", async () => {
  await api("/api/reset", { method: "POST" });
  approvedByPerson.clear();
  currentId = null;
  $("#detail-panel").innerHTML = '<p class="empty">Pick a statement to see what it means.</p>';
  loadList(); loadSummary(); loadHistory(); toast("Demo data reset");
});

// ---------- WebMCP: let a browser AI agent use the same actions ----------
// Feature detected: if the browser has no WebMCP, the page works normally.
function registerWebMCP() {
  const mc = document.modelContext;
  const status = $("#agent-status");
  if (!mc || typeof mc.registerTool !== "function") {
    status.textContent = "AI agent tools: not available in this browser (the page works normally).";
    return;
  }
  const text = (obj) => ({ content: [{ type: "text", text: JSON.stringify(obj, null, 2) }] });
  const idProp = { claim_id: { type: "string", description: "Statement id, for example CLM-1002" } };

  const tools = [
    {
      name: "get_claims",
      description: "List all sample statements with provider, date, amounts and any flags (duplicate, out_of_network, denied, not_a_bill).",
      inputSchema: { type: "object", properties: {} },
      annotations: { readOnlyHint: true },
      execute: async () => text(await api("/api/claims")),
    },
    {
      name: "load_sample_statement",
      description: "Read one of the bundled SAMPLE statement images and add it to the list. Choices: duplicate, out_of_network, denied, clear, blurry. Refuses blurry or inconsistent readings.",
      inputSchema: { type: "object", properties: { sample: { type: "string", enum: ["duplicate", "out_of_network", "denied", "clear", "blurry"] } }, required: ["sample"] },
      execute: async ({ sample }) => { const r = await useSample(sample); return text(r); },
    },
    {
      name: "get_claim_detail",
      description: "Get one statement: line items, what is owed and why, flags, and questions the person could ask. Also opens it on screen.",
      inputSchema: { type: "object", properties: idProp, required: ["claim_id"] },
      annotations: { readOnlyHint: true },
      execute: async ({ claim_id }) => { const d = await api(`/api/claims/${encodeURIComponent(claim_id)}`); showClaim(claim_id); return text(d); },
    },
    {
      name: "get_checked_explanation",
      description: "Get a plain-language AI explanation of one statement, together with a number check. The check compares every dollar amount in the explanation with the statement. If check.ok is false, do NOT repeat the explanation to the person. Tell them which number did not match.",
      inputSchema: { type: "object", properties: idProp, required: ["claim_id"] },
      annotations: { readOnlyHint: true },
      execute: async ({ claim_id }) => text(await api(`/api/claims/${encodeURIComponent(claim_id)}/ai-explain`)),
    },
    {
      name: "explain_charge",
      description: "Explain one service code in plain language, for example S-310.",
      inputSchema: { type: "object", properties: { code: { type: "string", description: "Service code such as S-310 or D-14" } }, required: ["code"] },
      annotations: { readOnlyHint: true },
      execute: async ({ code }) => text(await api(`/api/codes/${encodeURIComponent(code)}`)),
    },
    {
      name: "draft_appeal",
      description: "Create a draft appeal letter for a statement and show it on screen. This only drafts. It does not send anything. The person must read and approve it on the page.",
      inputSchema: { type: "object", properties: { ...idProp, note: { type: "string", description: "Optional extra note in the person's words" } }, required: ["claim_id"] },
      execute: async ({ claim_id, note }) => {
        await showClaim(claim_id);
        const a = await draftAppeal(claim_id, note);
        return text({ appeal_id: a.id, status: a.status, message: "Draft shown on screen. Ask the person to read, edit and approve it themselves.", body: a.body });
      },
    },
    {
      name: "submit_appeal",
      description: "Send an approved appeal. Fails unless the person has clicked Approve on the page. Do not try to work around this.",
      inputSchema: { type: "object", properties: { appeal_id: { type: "number" } }, required: ["appeal_id"] },
      annotations: { consequentialHint: true },
      execute: async ({ appeal_id }) => {
        if (!approvedByPerson.has(appeal_id)) {
          return text({ sent: false, reason: "The person has not approved this appeal on the page yet. Ask them to review it and click the approve button." });
        }
        return text({ sent: true, ...(await api(`/api/appeals/${appeal_id}/submit`, { method: "POST" })) });
      },
    },
  ];

  let ok = 0;
  for (const t of tools) {
    try { mc.registerTool(t); ok++; } catch (e) { console.warn("WebMCP: could not register", t.name, e); }
  }
  status.textContent = `AI agent tools: ${ok} of ${tools.length} registered with WebMCP.`;
}

loadList(); loadSummary(); loadHistory();
registerWebMCP();
