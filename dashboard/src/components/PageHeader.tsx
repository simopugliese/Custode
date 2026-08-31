import type { ReactNode } from 'react';
import { Moon } from 'lucide-react';
import { useTheme } from '../theme/ThemeContext';

interface PageHeaderProps {
  kicker: string;
  title: ReactNode;
}

export function PageHeader({ kicker, title }: PageHeaderProps) {
  const { themeLabel, toggleTheme } = useTheme();
  return (
    <header className="hd">
      <div className="row">
        <span className="cu-kicker">{kicker}</span>
        <button className="btn btn-ghost" style={{ marginLeft: 'auto' }} onClick={toggleTheme}>
          <Moon size={15} />
          <span>{themeLabel}</span>
        </button>
      </div>
      <h1>{title}</h1>
    </header>
  );
}
