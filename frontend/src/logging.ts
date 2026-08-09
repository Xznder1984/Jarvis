// Frontend log capture: hooks console.* and forwards entries to the backend
// log broker over the existing WebSocket. Works standalone in the browser too
// (no Tauri dependency). Keeps a local ring so the GUI log panel shows
// frontend-originated entries even before the socket connects.

export interface LogEntry {
  level: "debug" | "info" | "warn" | "error";
  message: string;
  source: "frontend" | "shell" | "backend";
  ts: number;
}

type Send = (env: { type: string; payload: Record<string, unknown> }) => void;

const LOCAL_RING: LogEntry[] = [];
const MAX_RING = 500;

let sendFn: Send | null = null;
let installed = false;

function push(level: LogEntry["level"], message: string) {
  const entry: LogEntry = { level, message, source: "frontend", ts: Date.now() / 1000 };
  LOCAL_RING.push(entry);
  if (LOCAL_RING.length > MAX_RING) LOCAL_RING.shift();
  try {
    sendFn?.({ type: "log", payload: { level, message, source: "frontend" } });
  } catch {
    /* ignore */
  }
}

/** Install console.* forwarding. Call once, after the socket hook is alive. */
export function installFrontendLogging(send: Send): () => void {
  sendFn = send;
  if (installed) return () => {};
  installed = true;

  const orig = {
    log: console.log,
    info: console.info,
    warn: console.warn,
    error: console.error,
    debug: console.debug,
  };

  const fmt = (...args: unknown[]): string =>
    args.map((a) => (typeof a === "string" ? a : safeStringify(a))).join(" ");

  console.log = (...a) => { orig.log(...a); push("info", fmt(...a)); };
  console.info = (...a) => { orig.info(...a); push("info", fmt(...a)); };
  console.warn = (...a) => { orig.warn(...a); push("warn", fmt(...a)); };
  console.error = (...a) => { orig.error(...a); push("error", fmt(...a)); };
  console.debug = (...a) => { orig.debug(...a); push("debug", fmt(...a)); };

  window.addEventListener("error", (e) => push("error", `window error: ${e.message}`));
  window.addEventListener("unhandledrejection", (e) => push("error", `unhandled rejection: ${String(e.reason)}`));

  return () => {
    installed = false;
    console.log = orig.log;
    console.info = orig.info;
    console.warn = orig.warn;
    console.error = orig.error;
    console.debug = orig.debug;
    sendFn = null;
  };
}

export function getLocalLogs(limit = 200): LogEntry[] {
  return LOCAL_RING.slice(-limit);
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
