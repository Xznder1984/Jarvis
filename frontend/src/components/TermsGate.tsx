import { useState } from "react";

interface TermsGateProps {
  onAccept: () => void;
}

export function TermsGate({ onAccept }: TermsGateProps) {
  const [checked, setChecked] = useState(false);

  return (
    <div className="terms-gate">
      <h1>J.A.R.V.I.S.</h1>
      <p className="terms-body">
        Just A Rather Very Intelligent System — Personal Desktop Assistant
      </p>
      <ul>
        <li><strong>Microphone access:</strong> JARVIS listens for wake phrases and voice commands. Audio is processed locally via faster-whisper or sent to configured providers.</li>
        <li><strong>API usage:</strong> Conversation text may be sent to LLM providers you configure. Your keys are stored locally on this device only.</li>
        <li><strong>System actions:</strong> You can command JARVIS to open apps, manage files, set reminders, capture your screen, or control system power.</li>
        <li><strong>Privacy:</strong> JARVIS runs entirely on your machine. No data leaves your device except to providers you explicitly configure.</li>
      </ul>
      <label className="terms-check">
        <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
        I UNDERSTAND AND ACCEPT
      </label>
      <button className="btn btn-primary" disabled={!checked} onClick={onAccept}>
        INITIALIZE
      </button>
    </div>
  );
}
