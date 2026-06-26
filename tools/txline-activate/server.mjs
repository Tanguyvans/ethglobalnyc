import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || process.env.TXLINE_ACTIVATE_PORT || 8788);
const TXLINE_ORIGIN = (process.env.TXLINE_ORIGIN || "https://txline.txodds.com").replace(/\/$/, "");
const SOLANA_RPC_ORIGIN = process.env.SOLANA_RPC_ORIGIN || "https://solana-rpc.publicnode.com";

function sendJson(res, status, payload) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  res.end(JSON.stringify(payload, null, 2));
}

async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString("utf8").trim();
  return raw ? JSON.parse(raw) : {};
}

async function proxyTxline(path, options = {}) {
  const response = await fetch(`${TXLINE_ORIGIN}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const contentType = response.headers.get("content-type") || "";
  const text = await response.text();
  let body = text;
  if (contentType.includes("application/json") && text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!response.ok) {
    const message = typeof body === "string" ? body : JSON.stringify(body);
    throw new Error(`TXLine ${path} failed with ${response.status}: ${message}`);
  }
  return body;
}

async function proxySolanaRpc(req, res) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const body = Buffer.concat(chunks);
  const response = await fetch(SOLANA_RPC_ORIGIN, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  const text = await response.text();
  res.writeHead(response.status, {
    "Content-Type": response.headers.get("content-type") || "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  res.end(text);
}

async function handleRequest(req, res) {
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

  if (req.method === "GET" && (url.pathname === "/" || url.pathname === "/index.html")) {
    const html = await readFile(join(__dirname, "index.html"), "utf8");
    res.writeHead(200, {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
    });
    res.end(html);
    return;
  }

  if ((req.method === "GET" || req.method === "HEAD") && url.pathname === "/favicon.ico") {
    res.writeHead(204, { "Cache-Control": "no-store" });
    res.end();
    return;
  }

  if (req.method === "POST" && url.pathname === "/guest") {
    try {
      const payload = await proxyTxline("/auth/guest/start", { method: "POST" });
      sendJson(res, 200, payload);
    } catch (error) {
      sendJson(res, 502, { error: String(error.message || error) });
    }
    return;
  }

  if (req.method === "POST" && url.pathname === "/rpc") {
    try {
      await proxySolanaRpc(req, res);
    } catch (error) {
      sendJson(res, 502, { error: String(error.message || error) });
    }
    return;
  }

  if (req.method === "POST" && url.pathname === "/activate") {
    try {
      const body = await readJsonBody(req);
      const jwt = String(body.jwt || "").trim();
      const txSig = String(body.txSig || "").trim();
      const walletSignature = String(body.walletSignature || "").trim();
      const leagues = Array.isArray(body.leagues) ? body.leagues : [];
      if (!jwt || !txSig || !walletSignature) {
        sendJson(res, 400, { error: "Missing jwt, txSig, or walletSignature" });
        return;
      }
      const apiToken = await proxyTxline("/api/token/activate", {
        method: "POST",
        headers: { Authorization: `Bearer ${jwt}` },
        body: JSON.stringify({ txSig, walletSignature, leagues }),
      });
      sendJson(res, 200, {
        jwt,
        apiToken: typeof apiToken === "string" ? apiToken.trim() : apiToken?.token || apiToken,
      });
    } catch (error) {
      sendJson(res, 502, { error: String(error.message || error) });
    }
    return;
  }

  sendJson(res, 404, { error: "Not found" });
}

const server = createServer((req, res) => {
  handleRequest(req, res).catch((error) => {
    sendJson(res, 500, { error: String(error.message || error) });
  });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`TXLine activation helper: http://127.0.0.1:${PORT}`);
  console.log(`TXLine origin: ${TXLINE_ORIGIN}`);
  console.log(`Solana RPC origin: ${SOLANA_RPC_ORIGIN}`);
});
