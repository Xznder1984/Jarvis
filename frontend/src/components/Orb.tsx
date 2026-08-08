import { useEffect, useRef } from "react";
import type { Presence } from "../types";

interface OrbProps {
  presence: Presence;
  connected: boolean;
  intensity?: number;
}

const COLORS: Record<Presence, { core: string; glow: string }> = {
  idle: { core: "#1f6feb", glow: "rgba(31,111,235,0.25)" },
  listening: { core: "#2dd4bf", glow: "rgba(45,212,191,0.35)" },
  thinking: { core: "#f59e0b", glow: "rgba(245,158,11,0.4)" },
  speaking: { core: "#ef4444", glow: "rgba(239,68,68,0.45)" },
};

/**
 * Canvas-rendered reactive orb. Pulse speed/amplitude follow the presence state.
 * Original design — an energy core ringed by orbiting particles.
 */
export function Orb({ presence, connected, intensity = 1 }: OrbProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    const dpr = window.devicePixelRatio || 1;
    const size = canvas.clientWidth;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);

    const colors = COLORS[presence];
    const start = performance.now();

    const draw = (now: number) => {
      const t = (now - start) / 1000;
      ctx.clearRect(0, 0, size, size);

      const cx = size / 2;
      const cy = size / 2;
      const baseR = size * 0.28;
      const pulseSpeed =
        presence === "listening" ? 2.4 : presence === "thinking" ? 1.2 : presence === "speaking" ? 3.2 : 0.4;
      const r = baseR * (1 + 0.08 * Math.sin(pulseSpeed * t)) * (connected ? 1 : 0.85);

      // Outer glow
      const glow = ctx.createRadialGradient(cx, cy, r * 0.4, cx, cy, r * 2.4);
      glow.addColorStop(0, colors.glow);
      glow.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(cx, cy, r * 2.4, 0, Math.PI * 2);
      ctx.fill();

      // Core
      const core = ctx.createRadialGradient(cx, cy, r * 0.1, cx, cy, r);
      core.addColorStop(0, "#ffffff");
      core.addColorStop(0.35, colors.core);
      core.addColorStop(1, "rgba(0,0,0,0.2)");
      ctx.fillStyle = core;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fill();

      // Orbiting particles (2 rings)
      for (let ring = 0; ring < 2; ring++) {
        const particles = 12;
        const ringR = r * (ring === 0 ? 1.7 : 2.2);
        const speed = (ring === 0 ? 0.9 : -0.6) * pulseSpeed * 0.4 + 0.6;
        for (let i = 0; i < particles; i++) {
          const angle = (i / particles) * Math.PI * 2 + t * speed + ring;
          const px = cx + Math.cos(angle) * ringR;
          const py = cy + Math.sin(angle) * ringR;
          const pr = (ring === 0 ? 3.5 : 2.2) * (1 + 0.5 * Math.sin(t * 3 + i));
          ctx.fillStyle = `rgba(255,255,255,${0.5 + 0.3 * Math.sin(t * 2 + i)})`;
          ctx.beginPath();
          ctx.arc(px, py, pr, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [presence, connected, intensity]);

  return (
    <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <canvas ref={canvasRef} style={{ width: "100%", height: "100%" }} />
    </div>
  );
}
