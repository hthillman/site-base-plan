// Basesheet result card for ChatGPT and Claude (loaded by the MCP resource shell in mcp.py).
// Speaks the MCP Apps bridge (JSON-RPC over postMessage) and, inside ChatGPT, the window.openai globals.
(function () {
  "use strict";
  const SITE = window.BASESHEET_SITE || "https://basesheet.site";
  const root = document.getElementById("card");
  const openai = window.openai;
  let lastKey = "";

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---- MCP Apps bridge
  let nextId = 0;
  const pending = {};
  function request(method, params) {
    const id = ++nextId;
    window.parent.postMessage({ jsonrpc: "2.0", id, method, params }, "*");
    return new Promise((resolve) => { pending[id] = resolve; setTimeout(() => resolve(null), 5000); });
  }
  function notify(method, params) { window.parent.postMessage({ jsonrpc: "2.0", method, params }, "*"); }

  window.addEventListener("message", (e) => {
    if (e.source !== window.parent) return;
    const m = e.data;
    if (!m || m.jsonrpc !== "2.0") return;
    if (m.id != null && !m.method) { const r = pending[m.id]; if (r) { delete pending[m.id]; r(m.result || null); } return; }
    if (m.method === "ui/notifications/tool-result") render((m.params || {}).structuredContent, m.params);
    else if (m.method === "ui/notifications/host-context-changed") applyTheme(m.params);
    if (m.id != null && m.method) window.parent.postMessage({ jsonrpc: "2.0", id: m.id, result: {} }, "*"); // e.g. ui/resource-teardown
  });

  function openLink(url) {
    if (openai && openai.openExternal) { openai.openExternal({ href: url }); return; }
    request("ui/open-link", { url }).then((r) => { if (r === null) window.open(url, "_blank", "noopener"); });
  }

  function applyTheme(ctx) {
    const t = ctx && (ctx.theme || (ctx.hostContext || {}).theme);
    if (t === "dark" || t === "light") document.documentElement.dataset.theme = t;
  }

  function reportSize() {
    if (openai) return; // ChatGPT sizes the frame itself
    notify("ui/notifications/size-changed", { height: Math.ceil(document.documentElement.getBoundingClientRect().height) });
  }

  // ---- rendering
  function quotaLine(q) {
    if (!q) return "";
    if (q.pro) return '<p class="quota">Basesheet Pro · unlimited plans</p>';
    if (q.allowance == null) return "";
    const tail = q.left === 0 ? ' · <a href="' + esc(SITE + "/pricing") + '" data-link>Plans and pricing</a>' : "";
    return '<p class="quota">' + esc(q.left) + " of " + esc(q.allowance) + " free plans left this month" + tail + "</p>";
  }

  function render(d) {
    if (!d || !d.title) return;
    const key = d.result_page || d.title;
    if (key === lastKey) return;
    lastKey = key;
    const files = d.files || {};
    const facts = (d.facts || []).slice(0, 8).map((f) =>
      '<div class="fact"><span class="k">' + esc(f.label) + '</span><span class="v">' + esc(f.value) + "</span>" +
      (f.sub ? '<span class="s">' + esc(f.sub) + "</span>" : "") + "</div>").join("");
    const look = (d.needs_a_look || []).slice(0, 4).map((t) => "<li>" + esc(t) + "</li>").join("");
    root.className = "";
    root.innerHTML =
      '<header><span class="brand">Basesheet</span><h1>' + esc(d.title) + "</h1></header>" +
      (files.preview ? '<a class="map" href="' + esc(d.result_page) + '" data-link><img alt="Preview map of the site" src="' + esc(files.preview) + '"></a>' : "") +
      '<div class="actions">' +
        (files.zip ? '<a class="btn primary" href="' + esc(files.zip) + '" data-link>Download files</a>' : "") +
        (files.pdf ? '<a class="btn" href="' + esc(files.pdf) + '" data-link>Open PDF</a>' : "") +
        '<a class="btn" href="' + esc(d.result_page) + '" data-link>Result page</a>' +
      "</div>" +
      '<p class="formats">DXF for CAD, SketchUp terrain, Civil 3D LandXML, GIS layers and a PDF. Links last 2 days.</p>' +
      (facts ? '<div class="facts">' + facts + "</div>" : "") +
      (look ? '<h2>Needs a look</h2><ul class="look">' + look + "</ul>" : "") +
      quotaLine(d.quota) +
      '<p class="disclaimer"><b>Not a survey. Not for permit submission.</b> Parcel lines are assessor tax lines, not boundaries. ' +
      'Check with a licensed surveyor and the jurisdiction before relying on anything here.</p>';
    root.querySelectorAll("[data-link]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openLink(a.getAttribute("href")); }));
    const img = root.querySelector("img");
    if (img) img.addEventListener("load", reportSize);
    reportSize();
  }

  // ---- start
  if (openai) {
    applyTheme({ theme: openai.theme });
    render(openai.toolOutput);
    window.addEventListener("openai:set_globals", () => { applyTheme({ theme: openai.theme }); render(openai.toolOutput); });
  } else {
    request("ui/initialize", { appInfo: { name: "basesheet-plan-card", version: "1" }, appCapabilities: {}, protocolVersion: "2026-01-26" })
      .then((r) => { if (r) applyTheme(r.hostContext); notify("ui/notifications/initialized", {}); reportSize(); });
  }
  if (window.ResizeObserver) new ResizeObserver(reportSize).observe(document.body);
})();
