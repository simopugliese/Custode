import { DotRow } from './DotGrid';
import type { HabitRow as HabitRowType } from '../types/api';

export function HabitDotsRow({ habit }: { habit: HabitRowType }) {
  return (
    <div className="row">
      <span style={{ width: 130, fontSize: 14 }}>{habit.nome}</span>
      <DotRow values={habit.giorni} />
      <span
        className={habit.evidenziata ? 'cu-mono' : 'cu-muted cu-mono'}
        style={{
          marginLeft: 'auto',
          fontSize: 12,
          color: habit.evidenziata ? 'var(--color-accent-700)' : undefined,
          fontWeight: habit.evidenziata ? 600 : undefined,
        }}
      >
        {habit.progressoLabel}
      </span>
    </div>
  );
}
