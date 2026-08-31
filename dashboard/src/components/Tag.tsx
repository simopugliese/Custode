import type { ReactNode } from 'react';

type TagVariant = 'accent' | 'outline' | 'neutral';

interface TagProps {
  variant?: TagVariant;
  mono?: boolean;
  children: ReactNode;
  style?: React.CSSProperties;
}

const VARIANT_CLASS: Record<TagVariant, string> = {
  accent: 'tag-accent',
  outline: 'tag-outline',
  neutral: 'tag-neutral',
};

export function Tag({ variant = 'neutral', mono, children, style }: TagProps) {
  const cls = ['tag', VARIANT_CLASS[variant], mono ? 'cu-mono' : ''].filter(Boolean).join(' ');
  return (
    <span className={cls} style={style}>
      {children}
    </span>
  );
}
