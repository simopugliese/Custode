interface BarProps {
  quota: number; // 0-1
  width?: number | string;
  color?: string;
}

/** Barretta di avanzamento sottile, usata per quote di categoria/tema/reparto. */
export function Bar({ quota, width = 88, color = 'var(--color-accent)' }: BarProps) {
  const pct = Math.max(0, Math.min(1, quota)) * 100;
  return (
    <div style={{ width, height: 6, background: 'color-mix(in srgb,var(--color-text) 10%,transparent)', flex: 'none' }}>
      <div style={{ width: `${pct}%`, height: 6, background: color }} />
    </div>
  );
}
