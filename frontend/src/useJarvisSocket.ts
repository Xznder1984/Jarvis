import { useEffect, useRef, useState } from "react";
import type { Envelope, Handlers, Presence } from "./types";

// When served over a tunnel/domain the backend and the page share an origin,
// so the WS endpoint is ws(s)://<same-host>/ws. In Tauri/vite dev the backend
// is a separate localhost process on the configured port.
function resolveWsUrl(): string {
  const proto = window.location.protocol;
  const host = window.location.host;
  const isTauri = proto === "tauri:" || proto === "tauri-fp";
  const isDev = (proto === "http:" || proto === "https:") && host.startsWith("localhost:1420");
  if (isTauri || isDev) {
    return `ws://127.0.0.1:8765/ws`;
  }
  return `${proto === "https:" ? "wss" : "ws"}://${host}/ws`;
}

const WS_URL = resolveWsUrl();

export function useJarvisSocket(handlers: Handlers) {
  const [connected, setConnected] = useState(false);
  const [presence, setPresence] = useState<Presence>("idle");
  const wsRef = useRef<WebSocket | null>(null);
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    let closed = false;
    let reconnect: number | undefined;

    const connect = () => {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onopen = () => {
        if (!closed) setConnected(true);
      };
      ws.onclose = () => {
        if (closed) return;
        setConnected(false);
        setPresence("idle");
        reconnect = window.setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (evt) => {
        let env: Envelope;
        try {
          env = JSON.parse(evt.data);
        } catch {
          return;
        }
        const h = handlersRef.current;
        const p = env.payload ?? {};
        switch (env.type) {
          case "state_update":
            setPresence(p.state as Presence);
            h.onState(p.state as Presence);
            break;
          case "activity":
            h.onActivity(p as { level: "info" | "warn" | "error"; message: string; ts: number });
            break;
          case "provider_update":
            h.onProvider(
              p.provider as string,
              p.state as string,
              (p.credit_estimate as number | null) ?? null
            );
            break;
          case "transcript":
            h.onTranscript(p.text as string);
            break;
          case "mode_update":
            h.onMode(p.mode as "normal" | "coding");
            break;
          case "say":
            h.onSay(p.text as string, (p.provider as string) ?? "", (p.audio as string) ?? undefined);
            break;
          case "log":
            h.onLog({
              level: p.level as "debug" | "info" | "warn" | "error",
              message: (p.message as string) ?? "",
              source: (p.source as "frontend" | "shell" | "backend") ?? "backend",
              ts: (p.ts as number) ?? Date.now() / 1000,
            });
            break;
          case "settings":
            h.onSettings((p.settings as Record<string, unknown>) ?? {});
            break;
        }
      };
    };

    connect();
    return () => {
      closed = true;
      if (reconnect) window.clearTimeout(reconnect);
      wsRef.current?.close();
    };
  }, []);

  const send = (env: { type: string; payload?: Record<string, unknown> }) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(env));
    }
  };

  const sendSettings = (settings: Record<string, unknown>) => {
    send({ type: "settings_update", payload: { settings } });
  };

  return { connected, presence, send, sendSettings };
}
