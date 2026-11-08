const $ = (selector) => document.querySelector(selector);
const tokenKey = "wis-dashboard-token";
let dashboard = null;
let selectedId = null;

function authHeaders() {
  const token = sessionStorage.getItem(tokenKey);
  return token ? { authorization: `Bearer ${token}` } : {};
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...authHeaders(),
      ...(options.body ? { "content-type": "application/json" } : {}),
      ...options.headers,
    },
  });
  let result;
  try { result = await response.json(); } catch { result = null; }
  if (!response.ok) {
    const error = new Error(result?.error?.message || `Request failed (${response.status}).`);
    error.status = response.status;
    error.code = result?.error?.code;
    throw error;
  }
  return result;
}

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function badge(element, status, labels) {
  element.className = `badge ${status === "configured" || status === "qualified" ? "ok" : status === "local_only" ? "muted" : "warn"}`;
  element.textContent = labels[status] || status;
}

function formatTime(value) {
  return value ? new Intl.DateTimeFormat("ar", { dateStyle: "short", timeStyle: "short" }).format(new Date(value)) : "—";
}

function renderIntegrations(status) {
  const names = { messenger: "Messenger", gemini: "Gemini", whatsapp_link: "رابط WhatsApp" };
  const labels = { configured: "مُعدّ", not_configured: "غير مُعدّ", local_only: "محلي فقط", authenticated: "لوحة محمية" };
  $("#modeBadge").className = `badge ${status.mode === "authenticated" ? "ok" : "muted"}`;
  $("#modeBadge").textContent = labels[status.mode];
  const container = $("#integrationBadges");
  container.replaceChildren();
  for (const [key, value] of Object.entries(status)) {
    if (key === "mode") continue;
    const item = makeElement("span");
    badge(item, value, { configured: `${names[key]}: ${labels.configured}`, not_configured: `${names[key]}: ${labels.not_configured}` });
    container.append(item);
  }
}

function statusOf(conversation) {
  if (conversation.status === "needs_human") return ["warn", "مراجعة بشرية"];
  if (conversation.status === "transferred") return ["ok", "تحويل WhatsApp"];
  if (conversation.lead.qualified) return ["qualified", "مؤهل بالأدلة"];
  if (conversation.lead.status === "interested") return ["warn", "اهتمام مبدئي"];
  return ["muted", "غير مؤهل بعد"];
}

function renderList() {
  const list = $("#conversationList");
  list.replaceChildren();
  const conversations = dashboard.conversations;
  $("#conversationCount").textContent = conversations.length ? `${conversations.length} محادثة` : "لا توجد محادثات بعد";
  for (const conversation of conversations) {
    const button = makeElement("button", `conversation-item${selectedId === conversation.id ? " selected" : ""}`);
    button.type = "button";
    button.addEventListener("click", () => { selectedId = conversation.id; renderList(); renderDetail(); });
    const top = makeElement("div", "conversation-item-top");
    top.append(makeElement("strong", "", conversation.customerId || "عميل"));
    top.append(makeElement("time", "", formatTime(conversation.updatedAt)));
    const last = conversation.messages.at(-1);
    const status = makeElement("div", "lead-status");
    const [tone, label] = statusOf(conversation);
    status.append(makeElement("span", `badge ${tone}`, label));
    if (conversation.whatsappConsent === "granted") status.append(makeElement("span", "badge ok", "وافق على WhatsApp"));
    button.append(top, makeElement("div", "conversation-preview", last?.body || "لا توجد رسائل"), status);
    list.append(button);
  }
}

function renderDetail() {
  const detail = $("#conversationDetail");
  const conversation = dashboard.conversations.find((item) => item.id === selectedId);
  if (!conversation) {
    detail.className = "empty-state";
    detail.replaceChildren(
      makeElement("span", "empty-icon", "↙"),
      makeElement("h2", "", "اختر محادثة"),
      makeElement("p", "", "ستظهر الرسائل والأدلة وسبب التحويل هنا."),
    );
    return;
  }
  detail.className = "";
  detail.replaceChildren();
  const header = makeElement("div", "detail-header");
  const title = makeElement("div", "detail-title");
  const copy = document.createElement("div");
  copy.append(makeElement("h2", "", conversation.customerId || "عميل"),
    makeElement("p", "", `${conversation.channel} · ${conversation.intent || "بانتظار التصنيف"}`));
  const [tone, label] = statusOf(conversation);
  title.append(copy, makeElement("span", `badge ${tone}`, label));
  const actions = makeElement("div", "detail-actions");
  if (conversation.status !== "needs_human") {
    const handoff = makeElement("button", "button button-quiet", "تصعيد بشري");
    handoff.type = "button";
    handoff.addEventListener("click", () => handoffConversation(conversation));
    actions.append(handoff);
  }
  const consent = makeElement("button", "button button-secondary",
    conversation.whatsappConsent === "granted" ? "تم تسجيل الموافقة" :
      conversation.whatsappConsent === "declined" ? "رفض العميل WhatsApp" :
      conversation.whatsappConsent === "pending" ? "بانتظار موافقة العميل" : "اطلب موافقة WhatsApp");
  consent.type = "button";
  consent.disabled = conversation.whatsappConsent !== "not_asked" || !conversation.lead.qualified || conversation.channel !== "messenger";
  consent.title = conversation.channel !== "messenger" ? "التحويل متاح لمحادثات Messenger فقط" :
    !conversation.lead.qualified ? "يتطلب اهتماماً مباشراً وتوقيتاً واحتياجاً تجارياً مثبتاً" : "";
  consent.addEventListener("click", () => requestConsent(conversation));
  actions.append(consent);
  header.append(title, actions);

  const messages = makeElement("div", "messages");
  for (const message of conversation.messages) {
    const bubble = makeElement("article", `message ${message.direction}`);
    const body = makeElement("p", "", message.body);
    if (message.delivery_status !== "sent" && message.direction === "outbound") {
      body.append(document.createTextNode(` (${message.delivery_status === "draft" ? "مسودة محلية" : "لم يُرسل"})`));
    }
    bubble.append(body, makeElement("time", "", formatTime(message.created_at)));
    messages.append(bubble);
  }
  const evidenceBox = makeElement("section", "evidence-box");
  evidenceBox.append(makeElement("h3", "", `تأهيل العميل · ${conversation.lead.score}/100`));
  const evidenceList = makeElement("div", "evidence-list");
  for (const [key, labelText] of [
    ["direct_interest", "اهتمام مباشر"], ["timeframe", "توقيت معلن"], ["business_need", "احتياج تجاري"],
  ]) {
    const row = makeElement("div", "evidence-row");
    row.append(makeElement("strong", "", labelText));
    const quote = conversation.lead.evidence[key];
    row.append(quote ? makeElement("q", "", quote) : makeElement("span", "", "لا يوجد دليل بعد"));
    evidenceList.append(row);
  }
  evidenceBox.append(evidenceList);
  if (conversation.handoffReason) evidenceBox.append(makeElement("p", "reason-note", `سبب التحويل: ${conversation.handoffReason}`));
  evidenceBox.append(makeElement("p", "processing-note", `حالة المعالجة: ${conversation.processingStatus} · موافقة WhatsApp: ${conversation.whatsappConsent}`));
  detail.append(header, messages, evidenceBox);
}

function render() {
  $("#metricConversations").textContent = dashboard.metrics.conversations;
  $("#metricQualified").textContent = dashboard.metrics.qualifiedLeads;
  $("#metricHuman").textContent = dashboard.metrics.needsHuman;
  $("#metricConsents").textContent = dashboard.metrics.whatsappConsents;
  renderIntegrations(dashboard.integrations);
  renderList();
  renderDetail();
  $("#catalogJson").value = JSON.stringify(dashboard.catalog, null, 2);
}

async function loadDashboard() {
  $("#appError").textContent = "";
  try {
    dashboard = await request("/api/dashboard");
    $("#loginPanel").hidden = true;
    $("#dashboardPanel").hidden = false;
    render();
  } catch (error) {
    if (error.status === 401) {
      $("#loginPanel").hidden = false;
      $("#dashboardPanel").hidden = true;
      $("#loginError").textContent = sessionStorage.getItem(tokenKey) ? "تعذر الدخول؛ تحقق من الرمز." : "";
      return;
    }
    $("#appError").textContent = error.message;
  }
}

async function handoffConversation(conversation) {
  const reason = window.prompt("اكتب سبب التصعيد البشري المدعوم من المحادثة:");
  if (!reason) return;
  try {
    await request(`/api/conversations/${conversation.id}/handoff`, { method: "POST", body: JSON.stringify({ reason }) });
    await loadDashboard();
  } catch (error) { $("#appError").textContent = error.message; }
}

async function requestConsent(conversation) {
  if (!window.confirm("سيُرسل طلب موافقة واضحاً للعميل عبر Messenger. لا يتم إرسال رابط WhatsApp قبل موافقته الصريحة.")) return;
  try {
    await request(`/api/conversations/${conversation.id}/whatsapp-consent`, { method: "POST", body: "{}" });
    await loadDashboard();
  } catch (error) { $("#appError").textContent = error.message; }
}

$("#loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const token = $("#adminToken").value;
  try {
    await request("/api/auth", { method: "POST", body: JSON.stringify({ token }) });
    sessionStorage.setItem(tokenKey, token);
    $("#adminToken").value = "";
    await loadDashboard();
  } catch (error) { $("#loginError").textContent = error.message; }
});

$("#refreshButton").addEventListener("click", loadDashboard);
$("#clearSelection").addEventListener("click", () => { selectedId = null; renderList(); renderDetail(); });
$("#demoForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#appError").textContent = "";
  try {
    const result = await request("/api/demo/messages", {
      method: "POST",
      body: JSON.stringify({ customerId: $("#demoCustomerId").value, text: $("#demoText").value }),
    });
    $("#demoText").value = "";
    selectedId = result.conversationId || null;
    await loadDashboard();
  } catch (error) { $("#appError").textContent = error.message; }
});

$("#saveCatalog").addEventListener("click", async () => {
  $("#catalogStatus").textContent = "";
  try {
    const entries = JSON.parse($("#catalogJson").value);
    const result = await request("/api/catalog", { method: "PUT", body: JSON.stringify({ entries }) });
    $("#catalogStatus").textContent = `تم حفظ ${result.count} معلومة معتمدة.`;
    await loadDashboard();
  } catch (error) { $("#catalogStatus").textContent = error.message; }
});

loadDashboard();
