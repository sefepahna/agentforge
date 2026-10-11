import { healthBody, lookup } from "./lookup.js";
import index from "./generated/index.json" with { type: "json" };

const CORS = { "Access-Control-Allow-Origin": "*" };

function jsonResponse(body, status) {
  return new Response(body, {
    status: status,
    headers: { ...CORS, "content-type": "application/json; charset=utf-8" },
  });
}

async function readBody(request) {
  try {
    return await request.json();
  } catch {
    return {};
  }
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          ...CORS,
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "*",
        },
      });
    }
    if (request.method === "GET" && url.pathname === "/health") {
      return jsonResponse(healthBody(), 200);
    }
    const payload = request.method === "POST" ? await readBody(request) : {};
    const answer = lookup(index, request.method, url.pathname, payload);
    if (answer.delaySeconds > 0) {
      await new Promise((resolve) => setTimeout(resolve, answer.delaySeconds * 1000));
    }
    return jsonResponse(answer.body, answer.status);
  },
};
