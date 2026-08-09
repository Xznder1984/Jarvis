import { useEffect, useState } from "react";
import { ActivityLog } from "./components/ActivityLog";
import { LogPanel } from "./components/LogPanel";
import { Orb } from "./components/Orb";
import { Settings } from "./components/Settings";
import { StatusBar } from "./components/StatusBar";
import { TermsGate } from "./components/TermsGate";
import { playTtsAudio, stopTtsAudio } from "./audio";
import { getLocalLogs, installFrontendLogging } from "./logging";
import type { ActivityItem, LogItem, Presence, SettingsMap } from "./types";
import { useJarvisSocket } from "./useJarvisSocket";

export default function App() {
  const [accepted, setAccepted] = useState<boolean>(() => {
    try {
      return localStorage.getItem("jarvis.terms.accepted") === "1";
    } catch {
      return false;
    }
  });
  const [showSettings, setShowSettings] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [logs, setLogs] = useState<LogItem[]>(getLocalLogs());
  const [provider, setProvider] = useState("");
  const [credit, setCredit] = useState<number | null>(null);
  const [mode, setMode] = useState<"normal" | "coding">("normal");
  const [lastSay, setLastSay] = useState("");
  const [settings, setSettings] = useState<SettingsMap>({});
  const [speaking, setSpeaking] = useState(false);

  const { connected, presence, send, sendSettings } = useJarvisSocket({
    onState: (s) => {
      if (s !== "speaking") setSpeaking(false);
    },
    onActivity: (item) => setActivities((a) => [item, ...a].slice(0, 100)),
    onProvider: (p, _s, c) => {
      setProvider(p);
      setCredit(c);
    },
    onTranscript: () => {},
    onMode: (m) => setMode(m),
    onSay: (text, _provider, audioB64) => {
      setLastSay(text);
      if (audioB64) {
        setSpeaking(true);
        playTtsAudio(audioB64, () => setSpeaking(false));
      }
    },
    onLog: (item) => setLogs((l) => [item, ...l].slice(0, 500)),
    onSettings: (s) => setSettings(s),
  });

  // Forward console.* errors to the backend log broker.
  useEffect(() => {
    return installFrontendLogging((env) => send(env));
  }, [send]);

  const acceptTerms = () => {
    try {
      localStorage.setItem("jarvis.terms.accepted", "1");
    } catch {
      /* ignore */
    }
    send({ type: "terms_accepted", payload: { accepted: true } });
    setAccepted(true);
  };

  const saveSettings = (settingsMap: SettingsMap) => {
    try {
      localStorage.setItem("jarvis.settings", JSON.stringify(settingsMap));
    } catch {
      /* ignore */
    }
    sendSettings(settingsMap);
  };

  if (!accepted) {
    return <TermsGate onAccept={acceptTerms} />;
  }

  const livePresence: Presence = speaking ? "speaking" : presence;

  return (
    <div className="app">
      <StatusBar connected={connected} presence={livePresence} provider={provider} credit={credit} mode={mode} />
      <main className="main">
        <div className="orb-wrap">
          <Orb presence={livePresence} connected={connected} />
          <div className="orb-label">
            {livePresence === "idle" && "Listening for claps…"}
            {livePresence === "listening" && "I'm listening."}
            {livePresence === "thinking" && "Thinking…"}
            {livePresence === "speaking" && "Speaking…"}
          </div>
          {lastSay && <div className="say-bubble">{lastSay}</div>}
        </div>
        <ActivityLog items={activities} />
      </main>
      <footer className="footer">
        <button className="btn" onClick={() => setShowLogs(true)}>Logs</button>
        <button className="btn" onClick={() => setShowSettings(true)}>Settings</button>
      </footer>
      {showSettings && (
        <Settings
          initial={settings}
          onClose={() => setShowSettings(false)}
          onSave={saveSettings}
        />
      )}
      {showLogs && (
        <LogPanel
          items={logs}
          onClose={() => setShowLogs(false)}
          onClear={() => setLogs([])}
        />
      )}
      <button className="stop-speech" title="Stop speaking" onClick={() => { stopTtsAudio(); setSpeaking(false); }}>
        {speaking ? "■" : ""}
      </button>
    </div>
  );
}
