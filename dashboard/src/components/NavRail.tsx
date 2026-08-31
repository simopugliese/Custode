import { NavLink } from 'react-router-dom';
import { Icon, type IconName } from '../lib/icons';

interface NavItem {
  to: string;
  icon: IconName;
  label: string;
  end?: boolean;
}

const PRIMARY: NavItem[] = [
  { to: '/', icon: 'house', label: 'Home', end: true },
  { to: '/diario', icon: 'book-open', label: 'Diario' },
  { to: '/lezioni', icon: 'graduation-cap', label: 'Lezioni e corsi' },
];

const SECONDARY: NavItem[] = [
  { to: '/task', icon: 'list-todo', label: 'Task' },
  { to: '/lista-spesa', icon: 'shopping-cart', label: 'Lista spesa' },
  { to: '/spese', icon: 'wallet', label: 'Spese' },
  { to: '/abitudini', icon: 'repeat', label: 'Abitudini' },
  { to: '/regole', icon: 'zap', label: 'Regole di contesto' },
];

function railClass({ isActive }: { isActive: boolean }) {
  return `rail-item${isActive ? ' active' : ''}`;
}

function RailLink({ item }: { item: NavItem }) {
  return (
    <NavLink to={item.to} end={item.end} className={railClass}>
      <Icon name={item.icon} size={19} />
      <span>{item.label}</span>
    </NavLink>
  );
}

export function NavRail() {
  return (
    <nav className="rail">
      <div style={{ width: 20, height: 20, background: 'var(--color-accent)', marginBottom: 20 }} />
      {PRIMARY.map((item) => (
        <RailLink key={item.to} item={item} />
      ))}
      <div style={{ width: 22, height: 1, background: 'var(--color-divider)', margin: '12px 0' }} />
      {SECONDARY.map((item) => (
        <RailLink key={item.to} item={item} />
      ))}
      <div style={{ marginTop: 'auto' }}>
        <NavLink to="/impostazioni" className={railClass}>
          <Icon name="settings" size={18} />
          <span>Impostazioni</span>
        </NavLink>
      </div>
    </nav>
  );
}
