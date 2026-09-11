import { createRoot } from 'react-dom/client';
import { QueryClient } from '@tanstack/react-query';
import { App } from './app';
import { ApiClient } from './api';
const cache = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    },
    mutations: { retry: false },
  },
});
createRoot(document.getElementById('root')!).render(<App api={new ApiClient()} cache={cache} />);
