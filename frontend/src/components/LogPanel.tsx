import { useState } from "react";
import type { LogItem, LogLevel } from "../types";

interface LogPanelProps {
  items: LogItem[];
  onClose: () => void;
  onClear: () => void;
}

const LEVEL_FILTERS: (LogLevel | "all")[] = ["all", "info", "warn", "error"];

function fmt(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString();
}

export function LogPanel({ items, onClose, onClear }: LogPanelProps) {
  const [filter, setFilter] = useState<LogLevel | "all">("all");

  const visible = filter === "all" ? items : items.filter((i) => i.level === filter);

  return (
    <div className="log-overlay" onClick={onClose}>
      <div className="log-panel" onClick={(e) => e.stopPropagation()}>
        <div className="log-panel-head">
          <h2>Logs</h2>
          <div className="log-filters">
            {LEVEL_FILTERS.map((f) => (
              <button
                key={f}
                className={`btn btn-sm ${filter === f ? "btn-primary" : ""}`}
                onClick={() => setFilter(f)}
              >
                {f}
              </button>
            ))}
            <button className="btn btn-sm" onClick={onClear}>Clear</button>
          </div>
        </div>
        <div className="log-panel-body">
          {visible.length === 0 && <div className="log-empty">No log entries.</div>}
          {visible.map((item, i) => (
            <div key={i} className={`log-row log-${item.level}`}>
              <span className="log-time">{fmt(item.ts)}</span>
              <span className={`log-src log-src-${item.source}`}>{item.source}</span>
              <span className="log-msg">{item.message}</span>
            </div>
          ))}
        </div>
        <div className="log-panel-foot">
          <span className="log-count">
            {items.length} entries
            {filter !== "all" && ` · filtered to ${filter}`}
          </span>
          <button className="btn btn-sm" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
