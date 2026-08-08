export type Presence = "idle" | "listening" | "thinking" | "speaking";

export interface ActivityItem {
  level: "info" | "warn" | "error";
  message: string;
  ts: number;
}

export interface ProviderStatus {
  provider: string;
  state: string;
  credit_estimate: number | null;
}

export interface Envelope {
  type: string;
  id: string;
  ts: number;
  payload: Record<string, unknown>;
}

export type Handlers = {
  onState: (state: Presence) => void;
  onActivity: (item: ActivityItem) => void;
  onProvider: (provider: string, state: string, credit: number | null) => void;
  onTranscript: (text: string) => void;
  onMode: (mode: "normal" | "coding") => void;
  onSay: (text: string, provider: string) => void;
};
