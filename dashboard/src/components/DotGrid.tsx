export function DotRow({ values }: { values: boolean[] }) {
  return (
    <div style={{ display: 'flex', gap: 5 }}>
      {values.map((on, i) => (
        <div key={i} className={on ? 'hb hb-on' : 'hb'} />
      ))}
    </div>
  );
}

export function DotGrid({ values, columns = 7, maxWidth = 230 }: { values: boolean[]; columns?: number; maxWidth?: number }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${columns},1fr)`, gap: 5, maxWidth }}>
      {values.map((on, i) => (
        <div key={i} className={on ? 'hb hb-on' : 'hb'} />
      ))}
    </div>
  );
}
