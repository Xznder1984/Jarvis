import { useState } from "react";
import { ActivityLog } from "./components/ActivityLog";
import { Orb } from "./components/Orb";
import { Settings } from "./components/Settings";
import { StatusBar } from "./components/StatusBar";
import { TermsGate } from "./components/TermsGate";
import type { ActivityItem } from "./types";
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
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [provider, setProvider] = useState("");
  const [credit, setCredit] = useState<number | null>(null);
  const [mode, setMode] = useState<"normal" | "coding">("normal");
  const [lastSay, setLastSay] = useState("");

  const { connected, presence, send } = useJarvisSocket({
    onState: () => {},
    onActivity: (item) => setActivities((a) => [item, ...a].slice(0, 100)),
    onProvider: (p, _s, c) => {
      setProvider(p);
      setCredit(c);
    },
    onTranscript: () => {},
    onMode: (m) => setMode(m),
    onSay: (text) => setLastSay(text),
  });

  const acceptTerms = () => {
    try {
      localStorage.setItem("jarvis.terms.accepted", "1");
    } catch {
      /* ignore */
    }
    send({ type: "terms_accepted", payload: { accepted: true } });
    setAccepted(true);
  };

  const saveSettings = (settings: Record<string, string>) => {
    try {
      localStorage.setItem("jarvis.settings", JSON.stringify(settings));
    } catch {
      /* ignore */
    }
  };

  if (!accepted) {
    return <TermsGate onAccept={acceptTerms} />;
  }

  return (
    <div className="app">
      <StatusBar connected={connected} presence={presence} provider={provider} credit={credit} mode={mode} />
      <main className="main">
        <div className="orb-wrap">
          <Orb presence={presence} connected={connected} />
          <div className="orb-label">
            {presence === "idle" && "Listening for claps…"}
            {presence === "listening" && "I'm listening."}
            {presence === "thinking" && "Thinking…"}
            {presence === "speaking" && "Speaking…"}
          </div>
          {lastSay && <div className="say-bubble">{lastSay}</div>}
        </div>
        <ActivityLog items={activities} />
      </main>
      <footer className="footer">
        <button className="btn" onClick={() => setShowSettings(true)}>Settings</button>
      </footer>
      {showSettings && <Settings onClose={() => setShowSettings(false)} onSave={saveSettings} />}
    </div>
  );
}
