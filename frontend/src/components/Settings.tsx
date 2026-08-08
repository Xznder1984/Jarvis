import { useState } from "react";

interface SettingsProps {
  onClose: () => void;
  onSave: (settings: Record<string, string>) => void;
}

const PROVIDERS = [
  { key: "GROQ_API_KEY", label: "Groq", env: "GROQ_API_KEY" },
  { key: "NVIDIA_API_KEY", label: "NVIDIA NIM", env: "NVIDIA_API_KEY" },
  { key: "CEREBRAS_API_KEY", label: "Cerebras", env: "CEREBRAS_API_KEY" },
  { key: "OPENCODE_ZEN_API_KEY", label: "OpenCode Zen", env: "OPENCODE_ZEN_API_KEY" },
  { key: "OLLAMA_CLOUD_API_KEY", label: "Ollama Cloud", env: "OLLAMA_CLOUD_API_KEY" },
  { key: "FISH_AUDIO_API_KEY", label: "Fish Audio (TTS)", env: "FISH_AUDIO_API_KEY" },
];

const TEXT_FIELDS = [
  { key: "WAKE_PHRASE", label: "Wake phrase", placeholder: "jarvis" },
  { key: "WAKE_RESPONSE", label: "Wake response", placeholder: "Ready at any moment, {honorific}." },
  { key: "HONORIFIC", label: "Honorific", placeholder: "sir" },
  { key: "FISH_AUDIO_REFERENCE_ID", label: "Fish Audio voice reference ID", placeholder: "" },
  { key: "LOCAL_TTS_VOICE", label: "Local TTS voice", placeholder: "Samantha" },
];

const NUM_FIELDS = [
  { key: "CLAP_COUNT", label: "Clap count to wake", default: "2" },
  { key: "CLAP_WINDOW_MS", label: "Clap detection window (ms)", default: "1200" },
  { key: "IDLE_TIMEOUT_MS", label: "Idle timeout (ms, 0 = off)", default: "0" },
];

export function Settings({ onClose, onSave }: SettingsProps) {
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [fields, setFields] = useState<Record<string, string>>({});
  const [priority, setPriority] = useState<string[]>([
    "groq",
    "nvidia",
    "cerebras",
    "opencode_zen",
    "ollama_cloud",
  ]);
  const [sleepAction, setSleepAction] = useState<"off" | "sleep" | "shutdown">("off");

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
    const settings: Record<string, string> = {
      ...apiKeys,
      ...fields,
      PROVIDER_PRIORITY: JSON.stringify(priority),
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
              <span>{p.label}</span>
              <input
                type="password"
                placeholder="••••••••"
                value={apiKeys[p.env] ?? ""}
                onChange={(e) => setKey(p.env, e.target.value)}
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
