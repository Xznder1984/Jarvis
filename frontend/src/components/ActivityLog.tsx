import type { ActivityItem } from "../types";

interface ActivityLogProps {
  items: ActivityItem[];
}

function fmt(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function ActivityLog({ items }: ActivityLogProps) {
  return (
    <div className="activity-log">
      <h3>Activity</h3>
      <ul>
        {items.map((item, i) => (
          <li key={i} className={`log-${item.level}`}>
            <span className="log-time">{fmt(item.ts)}</span>
            <span className="log-msg">{item.message}</span>
          </li>
        ))}
        {items.length === 0 && (
          <li className="log-info">
            <span className="log-msg" style={{ opacity: 0.3 }}>No activity yet.</span>
          </li>
        )}
      </ul>
    </div>
  );
}
