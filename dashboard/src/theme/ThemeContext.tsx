import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type Theme = 'giorno' | 'notte';

const STORAGE_KEY = 'custode-theme';

interface ThemeContextValue {
  theme: Theme;
  themeLabel: string;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'giorno';
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === 'notte' ? 'notte' : 'giorno';
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(readInitialTheme);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const value = useMemo<ThemeContextValue>(
    () => ({
      theme,
      themeLabel: theme === 'giorno' ? 'Notte' : 'Giorno',
      toggleTheme: () => setTheme((t) => (t === 'giorno' ? 'notte' : 'giorno')),
    }),
    [theme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside ThemeProvider');
  return ctx;
}
