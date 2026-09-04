import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { ActivityLog } from "./components/ActivityLog";
import { LogPanel } from "./components/LogPanel";
import { Orb } from "./components/Orb";
import { Settings } from "./components/Settings";
import { StatusBar } from "./components/StatusBar";
import { TermsGate } from "./components/TermsGate";
import { Waveform } from "./components/Waveform";
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
  const [pttActive, setPttActive] = useState(false);
  const pttRef = useRef(false);

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
        playTtsAudio(audioB64, () => {
          setSpeaking(false);
          // Tell the backend playback finished so it can re-arm listening
          // without picking up its own TTS echo.
          send({ type: "tts_finished" });
        });
      }
    },
    onLog: (item) => setLogs((l) => [item, ...l].slice(0, 500)),
    onSettings: (s) => setSettings(s),
  });

  useEffect(() => {
    return installFrontendLogging((env) => send(env));
  }, [send]);

  const acceptTerms = () => {
    try {
      localStorage.setItem("jarvis.terms.accepted", "1");
    } catch { /* ignore */ }
    send({ type: "terms_accepted", payload: { accepted: true } });
    setAccepted(true);
  };

  const saveSettings = (settingsMap: SettingsMap) => {
    try {
      localStorage.setItem("jarvis.settings", JSON.stringify(settingsMap));
    } catch { /* ignore */ }
    sendSettings(settingsMap);
  };

  // PTT: spacebar hold-to-talk via Tauri commands
  const pttStart = useCallback(async () => {
    if (pttRef.current) return;
    pttRef.current = true;
    setPttActive(true);
    try {
      await invoke("push_to_talk_start");
    } catch (e) {
      console.error("PTT start failed:", e);
      pttRef.current = false;
      setPttActive(false);
    }
  }, []);

  const pttEnd = useCallback(async () => {
    if (!pttRef.current) return;
    pttRef.current = false;
    setPttActive(false);
    try {
      await invoke("push_to_talk_end");
    } catch (e) {
      console.error("PTT end failed:", e);
    }
  }, []);

  useEffect(() => {
    const isInputFocused = () => {
      const el = document.activeElement;
      return el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT");
    };

    const onDown = (e: KeyboardEvent) => {
      if (e.code === "Space" && !e.repeat && !isInputFocused() && !showSettings && !showLogs) {
        e.preventDefault();
        pttStart();
      }
    };
    const onUp = (e: KeyboardEvent) => {
      if (e.code === "Space" && !isInputFocused()) {
        e.preventDefault();
        pttEnd();
      }
    };

    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup", onUp);
    return () => {
      window.removeEventListener("keydown", onDown);
      window.removeEventListener("keyup", onUp);
    };
  }, [pttStart, pttEnd, showSettings, showLogs]);

  if (!accepted) {
    return <TermsGate onAccept={acceptTerms} />;
  }

  const livePresence: Presence = speaking ? "speaking" : presence;
  const isListening = livePresence === "listening" || livePresence === "thinking" || pttActive;

  return (
    <div className="app">
      <StatusBar connected={connected} presence={livePresence} provider={provider} credit={credit} mode={mode} />

      <main className="main">
        <div className="orb-wrap">
          <Orb presence={livePresence} connected={connected} />
          <div className="orb-label">
            {livePresence === "idle" && "STANDBY"}
            {livePresence === "listening" && "RECEIVING"}
            {livePresence === "thinking" && "PROCESSING"}
            {livePresence === "speaking" && "TRANSMITTING"}
          </div>
          {lastSay && <div className="say-bubble">{lastSay}</div>}
        </div>

        <Waveform active={isListening} />
      </main>

      <ActivityLog items={activities} />

      <div className="ptt-area">
        <button
          className={`ptt-btn ${pttActive ? "active" : ""} ${isListening && !pttActive ? "listening" : ""}`}
          onMouseDown={pttStart}
          onMouseUp={pttEnd}
          onMouseLeave={pttEnd}
          onTouchStart={pttStart}
          onTouchEnd={pttEnd}
          title="Hold to talk (or hold Space)"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" x2="12" y1="19" y2="22" />
          </svg>
        </button>
        <span className="ptt-label">{pttActive ? "TRANSMITTING" : "HOLD TO TALK"}</span>
      </div>

      {speaking && (
        <button className="stop-speech" title="Stop speaking" onClick={() => { stopTtsAudio(); setSpeaking(false); }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="6" width="12" height="12" rx="1" />
          </svg>
        </button>
      )}

      <div className="hud-controls">
        <button className="btn" onClick={() => setShowLogs(true)}>LOGS</button>
        <button className="btn" onClick={() => setShowSettings(true)}>CONFIG</button>
      </div>

      {showSettings && (
        <Settings initial={settings} onClose={() => setShowSettings(false)} onSave={saveSettings} />
      )}
      {showLogs && (
        <LogPanel items={logs} onClose={() => setShowLogs(false)} onClear={() => setLogs([])} />
      )}
    </div>
  );
}
