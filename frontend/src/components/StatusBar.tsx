import type { Presence } from "../types";

interface StatusBarProps {
  connected: boolean;
  presence: Presence;
  provider: string;
  credit: number | null;
  mode: "normal" | "coding";
}

const PRESENCE_LABEL: Record<Presence, string> = {
  idle: "Idle",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
};

export function StatusBar({ connected, presence, provider, credit, mode }: StatusBarProps) {
  return (
    <div className="status-bar">
      <span className={`dot ${connected ? "dot-on" : "dot-off"}`} title={connected ? "Backend connected" : "Backend offline"} />
      <span className="status-label">{PRESENCE_LABEL[presence]}</span>
      <span className="status-provider" title="Active provider">
        {provider ? provider.toUpperCase() : "NO PROVIDER"}
        {credit != null && <span className="credit"> ({Math.round(credit * 100)}%)</span>}
      </span>
      <span className={`mode mode-${mode}`}>{mode === "coding" ? "CODE" : "NORMAL"}</span>
    </div>
  );
}
