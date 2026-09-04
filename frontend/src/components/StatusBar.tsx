import type { Presence } from "../types";

interface StatusBarProps {
  connected: boolean;
  presence: Presence;
  provider: string;
  credit: number | null;
  mode: "normal" | "coding";
}

const PRESENCE_LABEL: Record<Presence, string> = {
  idle: "STANDBY",
  listening: "LISTENING",
  thinking: "PROCESSING",
  speaking: "TRANSMITTING",
};

export function StatusBar({ connected, presence, provider, credit, mode }: StatusBarProps) {
  return (
    <div className="status-bar">
      <span className={`dot ${connected ? "dot-on" : "dot-off"}`} title={connected ? "ONLINE" : "OFFLINE"} />
      <span className="status-label">{PRESENCE_LABEL[presence]}</span>
      <span className="status-provider" title="PROVIDER">
        {provider ? provider.toUpperCase() : "---"}
      </span>
      {credit != null && <span className="credit">{Math.round(credit * 100)}%</span>}
      <span className={`mode mode-${mode}`}>{mode === "coding" ? "CODE" : "NORM"}</span>
    </div>
  );
}
