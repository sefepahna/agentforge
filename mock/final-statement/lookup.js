// Generic fixture lookup. Customer rows come from the generated index, not from this file.

const TEMPLATE_PREFIXES = ["{{", "%7B%7B"];

export function lookup(index, method, path, payload) {
  const operation = (index.paths || {})[path];
  if (!operation || String(method || "").toUpperCase() !== operation.method) {
    return { status: 404, body: JSON.stringify({ error: "not_found", path: path }), delaySeconds: 0 };
  }
  const data = payload && payload.data && typeof payload.data === "object" ? payload.data : {};
  if (templated(data, operation.by) && index.template_probe) {
    const sample = firstSuccess((index.records || {})[operation.name] || {});
    if (sample) return { status: sample.status, body: sample.body, delaySeconds: 0 };
  }
  const missing = missingField(operation.by, data);
  if (missing) return invalid(index);
  const key = recordKey(operation.by, data);
  const found = ((index.records || {})[operation.name] || {})[key];
  if (!found) {
    const fallback = (index.fallback || {})[operation.name] || invalid(index);
    return { status: fallback.status, body: fallback.body, delaySeconds: 0 };
  }
  return { status: found.status, body: found.body, delaySeconds: Number(found.delaySeconds || 0) };
}

function identity(value) {
  if (value === null || value === undefined || typeof value === "boolean") return "";
  if (typeof value === "number") return String(Math.trunc(value));
  return String(value).trim();
}

function recordKey(mode, data) {
  if (mode === "cardWeek") return identity(data.cardNumber) + "|" + identity(data.newStatementWeek);
  if (mode === "cardNumber") return identity(data.cardNumber);
  return identity(data.customerNo);
}

function missingField(mode, data) {
  if (mode === "cardWeek") {
    if (!identity(data.cardNumber)) return "cardNumber";
    if (!identity(data.newStatementWeek)) return "newStatementWeek";
    return "";
  }
  if (mode === "cardNumber") return identity(data.cardNumber) ? "" : "cardNumber";
  return identity(data.customerNo) ? "" : "customerNo";
}

function templated(data, mode) {
  const fields = mode === "cardWeek" ? ["cardNumber", "newStatementWeek"] : mode === "cardNumber" ? ["cardNumber"] : ["customerNo"];
  return fields.some((field) => typeof data[field] === "string" && TEMPLATE_PREFIXES.some((prefix) => data[field].startsWith(prefix)));
}

function firstSuccess(bucket) {
  for (const entry of Object.values(bucket)) {
    if (Number(entry.status) === 200) return entry;
  }
  return null;
}

function invalid(index) {
  const fallback = (index.fallback || {}).INVALID_ARGUMENTS_ERROR;
  if (!fallback) {
    return { status: 400, body: JSON.stringify({ result: { code: "INVALID_ARGUMENTS_ERROR" } }), delaySeconds: 0 };
  }
  return { status: fallback.status, body: fallback.body, delaySeconds: 0 };
}

export function healthBody() {
  return JSON.stringify({ durum: "ok" });
}
