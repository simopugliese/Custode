import { Checkbox } from './Checkbox';
import { Tag } from './Tag';
import type { ShoppingItem } from '../types/api';

interface ShoppingRowProps {
  item: ShoppingItem;
  onToggle: () => void;
  pending?: boolean;
  padding?: string;
}

export function ShoppingRow({ item, onToggle, pending, padding = '9px 0' }: ShoppingRowProps) {
  return (
    <div className="listrow" style={{ padding, opacity: item.preso ? 0.45 : 1 }}>
      <Checkbox checked={item.preso} onChange={onToggle} disabled={pending} />
      <span style={{ fontSize: 14, textDecoration: item.preso ? 'line-through' : 'none' }}>{item.nome}</span>
      {item.tag && (
        <span style={{ marginLeft: 'auto' }}>
          <Tag variant="neutral">{item.tag}</Tag>
        </span>
      )}
      {!item.tag && item.quantita && (
        <span className="cu-muted cu-mono" style={{ marginLeft: 'auto', fontSize: 11 }}>
          {item.quantita}
        </span>
      )}
    </div>
  );
}
