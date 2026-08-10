import { useEffect, useRef } from "react";
import type { Presence } from "../types";

interface OrbProps {
  presence: Presence;
  connected: boolean;
  intensity?: number;
}

type Rgb = [number, number, number];

const PALETTES: Record<Presence, Rgb> = {
  idle: [52, 140, 255],
  listening: [52, 211, 235],
  thinking: [245, 176, 65],
  speaking: [239, 90, 90],
};

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

const mix = (a: Rgb, b: Rgb, t: number): Rgb => [
  lerp(a[0], b[0], t),
  lerp(a[1], b[1], t),
  lerp(a[2], b[2], t),
];

const clamp01 = (n: number) => (n < 0 ? 0 : n > 1 ? 1 : n);

interface Dust {
  x: number;
  y: number;
  r: number;
  phase: number;
  speed: number;
}

/**
 * Canvas-rendered "living plasma" orb. A morphing energy core ringed by spiral
 * arms, tilted gyro rings, and orbiting sparks, over a field of ambient dust.
 * Presence drives speed + palette (crossfaded smoothly between states).
 */
export function Orb({ presence, connected, intensity = 1 }: OrbProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const presenceRef = useRef(presence);
  presenceRef.current = presence;
  const connectedRef = useRef(connected);
  connectedRef.current = connected;

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

    const start = performance.now();
    let color: Rgb = PALETTES[presenceRef.current];

    const dust: Dust[] = Array.from({ length: 46 }, () => ({
      x: Math.random(),
      y: Math.random(),
      r: 0.5 + Math.random() * 1.6,
      phase: Math.random() * Math.PI * 2,
      speed: 0.3 + Math.random() * 0.8,
    }));

    const draw = (now: number) => {
      const t = (now - start) / 1000;
      ctx.clearRect(0, 0, size, size);
      const cx = size / 2;
      const cy = size / 2;

      const prs = presenceRef.current;
      const conn = connectedRef.current;
      color = mix(color, PALETTES[prs], 0.05);
      const [cr, cg, cb] = color;
      const dim = (conn ? 1 : 0.55) * intensity;
      const speed =
        prs === "speaking" ? 3.2 : prs === "listening" ? 2.2 : prs === "thinking" ? 1.5 : 0.55;
      // base is sized so the largest element (2.05*base) fits inside the canvas
      // half-width — nothing gets clipped at the edges.
      const base = size * 0.24;

      // Ambient dust field (twinkling).
      ctx.globalCompositeOperation = "source-over";
      for (const d of dust) {
        const tw = 0.12 + 0.3 * (0.5 + 0.5 * Math.sin(d.phase + t * d.speed));
        ctx.globalAlpha = tw * dim;
        ctx.fillStyle = "#ffffff";
        ctx.beginPath();
        ctx.arc(d.x * size, d.y * size, d.r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;

      ctx.globalCompositeOperation = "lighter";

      // Breathing halo.
      const haloR = base * 1.9 * (1 + 0.06 * Math.sin(t * speed * 0.8));
      const halo = ctx.createRadialGradient(cx, cy, base * 0.4, cx, cy, haloR);
      halo.addColorStop(0, `rgba(${cr},${cg},${cb},${0.2 * dim})`);
      halo.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(cx, cy, haloR, 0, Math.PI * 2);
      ctx.fill();

      // Morphing plasma core (layered sines distort the radius).
      const blobR = base * (1 + 0.04 * Math.sin(t * speed * 0.7));
      ctx.beginPath();
      for (let a = 0; a <= Math.PI * 2 + 0.02; a += 0.06) {
        const wob =
          1 +
          0.15 * Math.sin(a * 5 + t * speed) * Math.sin(a * 3 - t * speed * 0.7) +
          0.07 * Math.sin(a * 8 + t * speed * 1.6);
        const rr = blobR * wob;
        const px = cx + Math.cos(a) * rr;
        const py = cy + Math.sin(a) * rr;
        if (a === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.closePath();
      const core = ctx.createRadialGradient(cx, cy, blobR * 0.08, cx, cy, blobR);
      core.addColorStop(0, `rgba(255,255,255,${0.95 * dim})`);
      core.addColorStop(0.4, `rgba(${cr},${cg},${cb},${0.85 * dim})`);
      core.addColorStop(0.75, `rgba(${cr},${cg},${cb},${0.22 * dim})`);
      core.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = core;
      ctx.fill();

      // Spiral arms of energy dots.
      const arms = 2;
      const armTurn = prs === "thinking" ? 2.6 : 2.1;
      const armMax = base * 1.6;
      for (let arm = 0; arm < arms; arm++) {
        const phase = arm * Math.PI + t * speed * 0.6;
        for (let i = 0; i < 96; i++) {
          const f = i / 96;
          const ang = f * armTurn * Math.PI + phase;
          const rad = base * 0.55 + f * (armMax - base * 0.55);
          const px = cx + Math.cos(ang) * rad;
          const py = cy + Math.sin(ang) * rad;
          const alpha = (1 - f) * (0.35 + 0.3 * Math.sin(t * 3 + f * 9 + arm)) * dim;
          const pr = (1 - f) * 2.4 + 0.6;
          ctx.fillStyle = `rgba(255,255,255,${clamp01(alpha)})`;
          ctx.beginPath();
          ctx.arc(px, py, pr, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      // Tilted gyro rings (3D foreshortened ellipses).
      const rings = [
        { tilt: 0.45, rot: t * speed * 0.5, size: 1.25 },
        { tilt: -0.8, rot: -t * speed * 0.36 + 1.3, size: 1.6 },
        { tilt: 1.15, rot: t * speed * 0.24 + 2.6, size: 1.95 },
      ];
      for (const ring of rings) {
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(ring.rot);
        ctx.scale(1, Math.max(0.15, Math.cos(ring.tilt)));
        ctx.strokeStyle = `rgba(${cr},${cg},${cb},${0.4 * dim})`;
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.arc(0, 0, base * ring.size, 0, Math.PI * 2);
        ctx.stroke();
        ctx.strokeStyle = `rgba(255,255,255,${0.5 * dim})`;
        ctx.beginPath();
        ctx.arc(0, 0, base * ring.size, -0.7, 0.85);
        ctx.stroke();
        ctx.restore();
      }

      // Orbiting sparks (two counter-rotating rings).
      for (let ring = 0; ring < 2; ring++) {
        const n = 14;
        const ringR = base * (ring === 0 ? 1.35 : 1.75);
        const spin = (ring === 0 ? 1 : -0.7) * speed * 0.5 + 0.5;
        for (let i = 0; i < n; i++) {
          const ang = (i / n) * Math.PI * 2 + t * spin + ring;
          const px = cx + Math.cos(ang) * ringR;
          const py = cy + Math.sin(ang) * ringR;
          const pr = (ring === 0 ? 3 : 2) * (1 + 0.4 * Math.sin(t * 3 + i));
          const alpha = (0.55 + 0.35 * Math.sin(t * 2 + i * 1.7)) * dim;
          ctx.fillStyle = `rgba(255,255,255,${clamp01(alpha)})`;
          ctx.beginPath();
          ctx.arc(px, py, pr, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      // Shockwave rings while speaking.
      if (prs === "speaking") {
        for (let i = 0; i < 3; i++) {
          const ph = (t * speed * 0.9 + i / 3) % 1;
          const rr = base * (0.75 + ph * 1.1);
          const a = (1 - ph) * 0.5 * dim;
          ctx.strokeStyle = `rgba(255,255,255,${clamp01(a)})`;
          ctx.lineWidth = (1 - ph) * 2 + 0.4;
          ctx.beginPath();
          ctx.arc(cx, cy, rr, 0, Math.PI * 2);
          ctx.stroke();
        }
      }

      ctx.globalCompositeOperation = "source-over";
      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [intensity]);

  return (
    <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <canvas ref={canvasRef} style={{ width: "100%", height: "100%" }} />
    </div>
  );
}
