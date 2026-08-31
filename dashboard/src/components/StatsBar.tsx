import type { ReactNode } from 'react';

export interface StatItem {
  label: string;
  value: ReactNode;
  accent?: boolean;
}

export function StatsBar({ items }: { items: StatItem[] }) {
  return (
    <div className="stats">
      {items.map((it) => (
        <div key={it.label}>
          <span className="cu-kicker">{it.label}</span>
          <div className="num" style={it.accent ? { color: 'var(--color-accent)' } : undefined}>
            {it.value}
          </div>
        </div>
      ))}
    </div>
  );
}
