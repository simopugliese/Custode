import type { ReactNode } from 'react';
import { Checkbox } from './Checkbox';
import { Tag } from './Tag';
import type { TaskItem } from '../types/api';

interface TaskRowProps {
  task: TaskItem;
  onToggle: () => void;
  pending?: boolean;
  padding?: string;
  onPostpone?: () => void;
  postponePending?: boolean;
}

/** Riga di task riusata in Home, Task, Lezioni (piani di ripasso — sono task, §8.11) e Abitudini. */
export function TaskRow({ task, onToggle, pending, padding = '13px 0', onPostpone, postponePending }: TaskRowProps) {
  const trailing: ReactNode[] = [];
  if (task.tag) trailing.push(<Tag key="tag" variant="outline">{task.tag}</Tag>);
  if (task.scadenzaLabel)
    trailing.push(
      <span key="sc" className="cu-mono" style={{ fontSize: 12, fontWeight: 600 }}>
        {task.scadenzaLabel}
      </span>,
    );
  if (task.meta)
    trailing.push(
      <span key="meta" className="cu-muted" style={{ fontSize: 12 }}>
        {task.meta}
      </span>,
    );

  return (
    <div className="listrow" style={{ padding, opacity: task.fatto ? 0.45 : 1 }}>
      <Checkbox checked={task.fatto} onChange={onToggle} disabled={pending} />
      <span style={{ fontSize: 15, textDecoration: task.fatto ? 'line-through' : 'none' }}>{task.titolo}</span>
      {trailing.map((node, i) => (
        <span key={i} style={{ marginLeft: i === 0 ? 'auto' : 12, display: 'inline-flex', alignItems: 'center' }}>
          {node}
        </span>
      ))}
      {onPostpone && !task.fatto && (
        <div className="rowact row" style={{ gap: 2, marginLeft: trailing.length === 0 ? 'auto' : 12 }}>
          <button className="btn btn-ghost" onClick={onPostpone} disabled={postponePending}>
            Rinvia
          </button>
        </div>
      )}
    </div>
  );
}
