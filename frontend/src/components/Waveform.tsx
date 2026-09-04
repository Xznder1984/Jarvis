import { useEffect, useRef } from "react";

interface WaveformProps {
  active: boolean;
  color?: string;
}

export function Waveform({ active, color = "0, 212, 255" }: WaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const activeRef = useRef(active);
  activeRef.current = active;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    const start = performance.now();

    const fitCanvas = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      canvas.width = Math.max(1, Math.round(w * dpr));
      canvas.height = Math.max(1, Math.round(h * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    fitCanvas();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(fitCanvas) : null;
    ro?.observe(canvas);

    const bars = 64;
    const barValues = new Float32Array(bars);

    const draw = (now: number) => {
      const t = (now - start) / 1000;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      ctx.clearRect(0, 0, w, h);

      const isActive = activeRef.current;
      const barWidth = w / bars;
      const gap = 2;

      for (let i = 0; i < bars; i++) {
        // Generate organic-looking waveform
        const norm = i / bars;
        let target: number;
        if (isActive) {
          // Active: dynamic waveform with multiple frequency layers
          const wave1 = Math.sin(norm * 6 + t * 3) * 0.3;
          const wave2 = Math.sin(norm * 12 - t * 2.5) * 0.2;
          const wave3 = Math.sin(norm * 3 + t * 1.5) * 0.15;
          const envelope = Math.sin(norm * Math.PI); // taper edges
          target = (0.15 + wave1 + wave2 + wave3) * envelope;
          // Add random peaks
          if (Math.random() < 0.08) target += Math.random() * 0.2;
        } else {
          // Idle: subtle breathing line
          target = 0.04 + 0.03 * Math.sin(norm * 4 + t * 0.5);
        }

        // Smooth interpolation
        barValues[i] += (target - barValues[i]) * 0.15;

        const barH = Math.max(2, barValues[i] * h * 0.9);
        const x = i * barWidth + gap / 2;
        const y = (h - barH) / 2;

        const alpha = isActive ? 0.6 + 0.4 * barValues[i] : 0.25;
        ctx.fillStyle = `rgba(${color},${alpha})`;
        ctx.fillRect(x, y, barWidth - gap, barH);
      }

      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      ro?.disconnect();
    };
  }, [color]);

  return (
    <div className={`waveform-wrap ${active ? "active" : ""}`}>
      <canvas ref={canvasRef} className="waveform-canvas" />
    </div>
  );
}
