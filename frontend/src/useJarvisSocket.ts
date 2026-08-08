import { useEffect, useRef, useState } from "react";
import type { Envelope, Handlers, Presence } from "./types";

const WS_URL = `ws://${window.location.hostname || "127.0.0.1"}:8765/ws`;

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
            h.onSay(p.text as string, p.provider as string);
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

  const send = (env: Partial<Envelope>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(env));
    }
  };

  return { connected, presence, send };
}
