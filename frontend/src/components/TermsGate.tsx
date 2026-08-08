import { useState } from "react";

interface TermsGateProps {
  onAccept: () => void;
}

export function TermsGate({ onAccept }: TermsGateProps) {
  const [checked, setChecked] = useState(false);

  return (
    <div className="terms-gate">
      <h1>JARVIS — Terms &amp; Conditions</h1>
      <p className="terms-body">
        JARVIS is a local, personal desktop assistant. By continuing you agree to the following:
      </p>
      <ul>
        <li><strong>Microphone access:</strong> JARVIS listens continuously for claps and wake phrases. Audio is processed locally (STT via faster-whisper) or sent to configured third-party providers for speech understanding.</li>
        <li><strong>API usage:</strong> Conversation text may be sent to the LLM providers you configure (Groq, NVIDIA, Cerebras, etc.). Your keys are stored locally and never transmitted to JARVIS itself.</li>
        <li><strong>System actions:</strong> You can command JARVIS to open apps, capture your screen, or put the machine to sleep/shut down. You are responsible for these actions.</li>
        <li><strong>Privacy:</strong> JARVIS is provided as-is without warranty. Never share secrets or sensitive data in conversations if you do not trust your providers.</li>
      </ul>
      <label className="terms-check">
        <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
        I have read and accept the terms
      </label>
      <button className="btn btn-primary" disabled={!checked} onClick={onAccept}>
        Continue
      </button>
    </div>
  );
}
