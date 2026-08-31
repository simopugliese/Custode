import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from './theme/ThemeContext';
import { Layout } from './components/Layout';
import Home from './pages/Home';
import Diario from './pages/Diario';
import Lezioni from './pages/Lezioni';
import Task from './pages/Task';
import ListaSpesa from './pages/ListaSpesa';
import Spese from './pages/Spese';
import Abitudini from './pages/Abitudini';
import Regole from './pages/Regole';
import Impostazioni from './pages/Impostazioni';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Home />} />
              <Route path="diario" element={<Diario />} />
              <Route path="lezioni" element={<Lezioni />} />
              <Route path="task" element={<Task />} />
              <Route path="lista-spesa" element={<ListaSpesa />} />
              <Route path="spese" element={<Spese />} />
              <Route path="abitudini" element={<Abitudini />} />
              <Route path="regole" element={<Regole />} />
              <Route path="impostazioni" element={<Impostazioni />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
