import { useState } from "react";
import type { SettingsMap } from "../types";

interface SettingsProps {
  initial: SettingsMap;
  onClose: () => void;
  onSave: (settings: SettingsMap) => void;
}

const PROVIDERS = [
  { key: "GROQ_API_KEY", label: "Groq" },
  { key: "NVIDIA_API_KEY", label: "NVIDIA NIM" },
  { key: "CEREBRAS_API_KEY", label: "Cerebras" },
  { key: "OPENCODE_ZEN_API_KEY", label: "OpenCode Zen" },
  { key: "OLLAMA_CLOUD_API_KEY", label: "Ollama Cloud" },
  { key: "FISH_AUDIO_API_KEY", label: "Fish Audio (TTS)" },
];

const TEXT_FIELDS: FieldDef[] = [
  { key: "WAKE_PHRASE", label: "Wake phrase", placeholder: "jarvis" },
  { key: "WAKE_RESPONSE", label: "Wake response", placeholder: "Ready at any moment, {honorific}." },
  { key: "HONORIFIC", label: "Honorific", placeholder: "sir" },
  { key: "FISH_AUDIO_REFERENCE_ID", label: "Fish Audio voice reference ID", placeholder: "" },
  { key: "LOCAL_TTS_VOICE", label: "Local TTS voice", placeholder: "Daniel" },
];

const NUM_FIELDS: FieldDef[] = [
  { key: "CLAP_COUNT", label: "Clap count to wake", default: "2" },
  { key: "CLAP_WINDOW_MS", label: "Clap detection window (ms)", default: "1200" },
  { key: "IDLE_TIMEOUT_MS", label: "Idle timeout (ms, 0 = off)", default: "0" },
];

interface FieldDef {
  key: string;
  label: string;
  placeholder?: string;
  default?: string;
}

const DEFAULT_PRIORITY = ["groq", "nvidia", "cerebras", "opencode_zen", "ollama_cloud"];

function asString(v: unknown, def: string): string {
  if (v === undefined || v === null) return def;
  return String(v);
}

export function Settings({ initial, onClose, onSave }: SettingsProps) {
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [fields, setFields] = useState<Record<string, string>>(() => {
    const out: Record<string, string> = {};
    for (const f of [...TEXT_FIELDS, ...NUM_FIELDS]) {
      out[f.key] = asString(initial[f.key], f.placeholder ?? f.default ?? "");
    }
    return out;
  });
  const [priority, setPriority] = useState<string[]>(() => {
    const raw = initial.PROVIDER_PRIORITY;
    if (Array.isArray(raw)) return (raw as string[]).filter((p) => p);
    if (typeof raw === "string") {
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) return parsed as string[];
      } catch {
        /* ignore */
      }
    }
    return DEFAULT_PRIORITY;
  });
  const [sleepAction, setSleepAction] = useState<"off" | "sleep" | "shutdown">(
    (initial.IDLE_ACTION as "off" | "sleep" | "shutdown") ?? "off"
  );

  const setField = (key: string, value: string) => setFields((f) => ({ ...f, [key]: value }));
  const setKey = (key: string, value: string) => setApiKeys((f) => ({ ...f, [key]: value }));

  const move = (index: number, dir: -1 | 1) => {
    const target = index + dir;
    if (target < 0 || target >= priority.length) return;
    const next = [...priority];
    [next[index], next[target]] = [next[target], next[index]];
    setPriority(next);
  };

  const handleSave = () => {
    const settings: SettingsMap = {
      ...apiKeys,
      ...fields,
      PROVIDER_PRIORITY: priority,
      IDLE_ACTION: sleepAction,
    };
    onSave(settings);
    onClose();
  };

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-panel" onClick={(e) => e.stopPropagation()}>
        <h2>Settings</h2>

        <section>
          <h3>API Keys</h3>
          {PROVIDERS.map((p) => (
            <label key={p.key} className="field">
              <span>
                {p.label}
                {initial[p.key] === true && <em className="key-set"> · saved</em>}
              </span>
              <input
                type="password"
                placeholder={initial[p.key] === true ? "•••••••• (saved)" : "Enter key"}
                value={apiKeys[p.key] ?? ""}
                onChange={(e) => setKey(p.key, e.target.value)}
              />
            </label>
          ))}
        </section>

        <section>
          <h3>Voice &amp; Behavior</h3>
          {TEXT_FIELDS.map((f) => (
            <label key={f.key} className="field">
              <span>{f.label}</span>
              <input
                type="text"
                placeholder={f.placeholder}
                value={fields[f.key] ?? ""}
                onChange={(e) => setField(f.key, e.target.value)}
              />
            </label>
          ))}
          {NUM_FIELDS.map((f) => (
            <label key={f.key} className="field">
              <span>{f.label}</span>
              <input
                type="number"
                defaultValue={f.default}
                value={fields[f.key] ?? f.default}
                onChange={(e) => setField(f.key, e.target.value)}
              />
            </label>
          ))}
        </section>

        <section>
          <h3>Provider Priority</h3>
          <ul className="priority">
            {priority.map((name, i) => (
              <li key={name}>
                <span className="prio-name">{name}</span>
                <button onClick={() => move(i, -1)} disabled={i === 0}>↑</button>
                <button onClick={() => move(i, 1)} disabled={i === priority.length - 1}>↓</button>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h3>Power Saving (opt-in, off by default)</h3>
          <label className="field">
            <span>When idle for the timeout</span>
            <select value={sleepAction} onChange={(e) => setSleepAction(e.target.value as "off" | "sleep" | "shutdown")}>
              <option value="off">Do nothing</option>
              <option value="sleep">Sleep</option>
              <option value="shutdown">Shut down</option>
            </select>
          </label>
        </section>

        <div className="settings-actions">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSave}>Save</button>
        </div>
      </div>
    </div>
  );
}
