import { useEffect, useRef } from "react";
import type { Presence } from "../types";

interface OrbProps {
  presence: Presence;
  connected: boolean;
  intensity?: number;
}

type Rgb = [number, number, number];

const CYAN: Rgb = [0, 212, 255];
const CYAN_DIM: Rgb = [0, 120, 180];
const CYAN_BRIGHT: Rgb = [180, 240, 255];

const SPEED: Record<Presence, number> = {
  idle: 0.3,
  listening: 1.0,
  thinking: 1.8,
  speaking: 2.5,
};

const clamp01 = (n: number) => Math.max(0, Math.min(1, n));

interface Particle {
  angle: number;
  radius: number;
  speed: number;
  size: number;
  alpha: number;
}

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
    let size = canvas.clientWidth;

    const fitCanvas = () => {
      const dpr = window.devicePixelRatio || 1;
      size = canvas.clientWidth || size;
      canvas.width = Math.max(1, Math.round(size * dpr));
      canvas.height = Math.max(1, Math.round(size * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    fitCanvas();

    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(fitCanvas) : null;
    ro?.observe(canvas);

    const start = performance.now();

    // Particles orbiting on rings
    const particles: Particle[] = Array.from({ length: 40 }, () => ({
      angle: Math.random() * Math.PI * 2,
      radius: 0.6 + Math.random() * 0.5,
      speed: 0.2 + Math.random() * 0.6,
      size: 0.5 + Math.random() * 1.5,
      alpha: 0.3 + Math.random() * 0.5,
    }));

    const draw = (now: number) => {
      const t = (now - start) / 1000;
      ctx.clearRect(0, 0, size, size);
      const cx = size / 2;
      const cy = size / 2;
      const base = size * 0.22;
      const prs = presenceRef.current;
      const conn = connectedRef.current;
      const speed = SPEED[prs];
      const dim = (conn ? 1 : 0.4) * intensity;

      const [cr, cg, cb] = prs === "idle" ? CYAN_DIM : prs === "speaking" ? CYAN_BRIGHT : CYAN;

      ctx.globalCompositeOperation = "lighter";

      // Outer glow
      const outerGlow = ctx.createRadialGradient(cx, cy, base * 0.8, cx, cy, base * 2.2);
      outerGlow.addColorStop(0, `rgba(${cr},${cg},${cb},${0.08 * dim})`);
      outerGlow.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = outerGlow;
      ctx.beginPath();
      ctx.arc(cx, cy, base * 2.2, 0, Math.PI * 2);
      ctx.fill();

      // Concentric rings
      const rings = [
        { r: 0.5, w: 0.8, alpha: 0.15, speed: 0.1, rot: 0 },
        { r: 0.7, w: 1.0, alpha: 0.2, speed: -0.15, rot: 0.5 },
        { r: 0.9, w: 1.2, alpha: 0.25, speed: 0.08, rot: 1.0 },
        { r: 1.1, w: 1.0, alpha: 0.2, speed: -0.12, rot: 1.5 },
        { r: 1.3, w: 0.8, alpha: 0.15, speed: 0.06, rot: 2.0 },
        { r: 1.55, w: 0.6, alpha: 0.1, speed: -0.04, rot: 2.5 },
      ];

      for (const ring of rings) {
        const rr = base * ring.r;
        const a = ring.alpha * dim * (0.7 + 0.3 * Math.sin(t * speed + ring.rot));
        ctx.strokeStyle = `rgba(${cr},${cg},${cb},${clamp01(a)})`;
        ctx.lineWidth = ring.w;
        ctx.beginPath();
        ctx.arc(cx, cy, rr, 0, Math.PI * 2);
        ctx.stroke();
      }

      // Tick marks on outer ring
      const tickRing = base * 1.55;
      const tickCount = 60;
      for (let i = 0; i < tickCount; i++) {
        const ang = (i / tickCount) * Math.PI * 2 + t * speed * 0.05;
        const isMajor = i % 5 === 0;
        const len = isMajor ? base * 0.1 : base * 0.05;
        const innerR = tickRing;
        const outerR = tickRing + len;
        const alpha = (isMajor ? 0.35 : 0.12) * dim;
        ctx.strokeStyle = `rgba(${cr},${cg},${cb},${clamp01(alpha)})`;
        ctx.lineWidth = isMajor ? 1.2 : 0.6;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(ang) * innerR, cy + Math.sin(ang) * innerR);
        ctx.lineTo(cx + Math.cos(ang) * outerR, cy + Math.sin(ang) * outerR);
        ctx.stroke();
      }

      // Rotating arcs on inner rings
      const arcSets = [
        { r: 0.9, count: 3, span: 0.4, rotSpeed: speed * 0.3, width: 1.5 },
        { r: 1.1, count: 4, span: 0.3, rotSpeed: -speed * 0.2, width: 1.2 },
        { r: 1.3, count: 6, span: 0.2, rotSpeed: speed * 0.15, width: 0.8 },
      ];

      for (const set of arcSets) {
        const rr = base * set.r;
        for (let i = 0; i < set.count; i++) {
          const baseAng = (i / set.count) * Math.PI * 2 + t * set.rotSpeed;
          const a = 0.3 * dim * (0.6 + 0.4 * Math.sin(t * 0.5 + i));
          ctx.strokeStyle = `rgba(${cr},${cg},${cb},${clamp01(a)})`;
          ctx.lineWidth = set.width;
          ctx.beginPath();
          ctx.arc(cx, cy, rr, baseAng, baseAng + set.span);
          ctx.stroke();
        }
      }

      // Central core (arc reactor center)
      const coreR = base * 0.35;
      const pulse = 1 + 0.06 * Math.sin(t * speed * 1.5);

      // Core glow
      const coreGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR * 2.5 * pulse);
      coreGlow.addColorStop(0, `rgba(200,240,255,${0.4 * dim})`);
      coreGlow.addColorStop(0.3, `rgba(${cr},${cg},${cb},${0.25 * dim})`);
      coreGlow.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = coreGlow;
      ctx.beginPath();
      ctx.arc(cx, cy, coreR * 2.5 * pulse, 0, Math.PI * 2);
      ctx.fill();

      // Core solid
      const coreSolid = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR * pulse);
      coreSolid.addColorStop(0, `rgba(255,255,255,${0.9 * dim})`);
      coreSolid.addColorStop(0.5, `rgba(${cr},${cg},${cb},${0.7 * dim})`);
      coreSolid.addColorStop(1, `rgba(${cr},${cg},${cb},${0.15 * dim})`);
      ctx.fillStyle = coreSolid;
      ctx.beginPath();
      ctx.arc(cx, cy, coreR * pulse, 0, Math.PI * 2);
      ctx.fill();

      // Core ring
      ctx.strokeStyle = `rgba(255,255,255,${0.4 * dim})`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(cx, cy, coreR * pulse * 1.2, 0, Math.PI * 2);
      ctx.stroke();

      // Orbiting particles
      for (const p of particles) {
        p.angle += p.speed * speed * 0.02;
        const px = cx + Math.cos(p.angle) * base * p.radius;
        const py = cy + Math.sin(p.angle) * base * p.radius;
        const flicker = 0.5 + 0.5 * Math.sin(t * 3 + p.angle * 2);
        const a = p.alpha * dim * flicker;
        ctx.fillStyle = `rgba(${cr},${cg},${cb},${clamp01(a)})`;
        ctx.beginPath();
        ctx.arc(px, py, p.size, 0, Math.PI * 2);
        ctx.fill();
      }

      // Speaking: expanding rings
      if (prs === "speaking") {
        for (let i = 0; i < 2; i++) {
          const ph = (t * speed * 0.4 + i / 2) % 1;
          const rr = base * (0.8 + ph * 1.5);
          const a = (1 - ph) * 0.3 * dim;
          ctx.strokeStyle = `rgba(${cr},${cg},${cb},${clamp01(a)})`;
          ctx.lineWidth = (1 - ph) * 2 + 0.3;
          ctx.beginPath();
          ctx.arc(cx, cy, rr, 0, Math.PI * 2);
          ctx.stroke();
        }
      }

      // Listening: scanning line
      if (prs === "listening") {
        const scanAng = t * speed * 0.8;
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(scanAng);
        const grad = ctx.createLinearGradient(0, 0, base * 1.5, 0);
        grad.addColorStop(0, `rgba(${cr},${cg},${cb},${0.4 * dim})`);
        grad.addColorStop(1, "rgba(0,0,0,0)");
        ctx.strokeStyle = grad;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(base * 1.5, 0);
        ctx.stroke();
        ctx.restore();
      }

      // Thinking: pulsing inner ring
      if (prs === "thinking") {
        const thinkR = base * 0.5 * (1 + 0.15 * Math.sin(t * 4));
        ctx.strokeStyle = `rgba(${cr},${cg},${cb},${0.3 * dim})`;
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.arc(cx, cy, thinkR, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      ctx.globalCompositeOperation = "source-over";
      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      ro?.disconnect();
    };
  }, [intensity]);

  return (
    <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <canvas ref={canvasRef} style={{ width: "100%", height: "100%" }} />
    </div>
  );
}
