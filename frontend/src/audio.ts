// TTS playback: decode base64 WAV and play it. Tracks speaking state so the UI
// can reflect it. Falls back gracefully if the backend sent no audio.

export interface AudioPlayback {
  play: (base64Wav: string, onEnd?: () => void) => void;
  stop: () => void;
}

let current: HTMLAudioElement | null = null;

export function playTtsAudio(base64Wav: string, onEnd?: () => void): void {
  stopTtsAudio();
  if (!base64Wav) {
    onEnd?.();
    return;
  }
  try {
    const audio = new Audio(`data:audio/wav;base64,${base64Wav}`);
    current = audio;
    audio.onended = () => {
      if (current === audio) current = null;
      onEnd?.();
    };
    audio.onerror = () => {
      if (current === audio) current = null;
      onEnd?.();
    };
    void audio.play().catch(() => onEnd?.());
  } catch {
    onEnd?.();
  }
}

export function stopTtsAudio(): void {
  if (current) {
    try {
      current.pause();
    } catch {
      /* ignore */
    }
    current = null;
  }
}
