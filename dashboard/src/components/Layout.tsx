import { Outlet } from 'react-router-dom';
import { NavRail } from './NavRail';
import { useTheme } from '../theme/ThemeContext';

export function Layout() {
  const { theme } = useTheme();
  return (
    <div className="cu" data-theme={theme}>
      <div className="pg">
        <NavRail />
        <div className="main">
          <div className="main-inner">
            <Outlet />
          </div>
        </div>
      </div>
    </div>
  );
}
