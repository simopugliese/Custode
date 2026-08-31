import type { ReactNode } from 'react';
import { Icon, type IconName } from '../lib/icons';

interface AvvisoRowProps {
  icon: IconName;
  children: ReactNode;
  actionLabel?: string;
  actionIcon?: IconName;
  onAction?: () => void;
  iconAccent?: boolean;
}

/** La riga d'avviso sotto l'header, presente su quasi ogni pagina del mock. */
export function AvvisoRow({ icon, children, actionLabel, actionIcon, onAction, iconAccent }: AvvisoRowProps) {
  return (
    <div className="row" style={{ padding: '13px 0', borderBottom: '1px solid var(--color-rule)', gap: 10 }}>
      <span style={{ display: 'flex', opacity: iconAccent ? 1 : 0.6, color: iconAccent ? 'var(--color-accent)' : undefined }}>
        <Icon name={icon} size={15} />
      </span>
      <span style={{ fontSize: 13 }}>{children}</span>
      {actionLabel && (
        <button className="btn btn-ghost" style={{ marginLeft: 'auto' }} onClick={onAction}>
          {actionLabel}
          {actionIcon && <Icon name={actionIcon} size={14} />}
        </button>
      )}
    </div>
  );
}
