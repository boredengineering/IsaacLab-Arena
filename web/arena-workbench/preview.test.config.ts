import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  envDir: '/tmp/arena-preview-empty-env',
  cacheDir: '/tmp/arena-preview-vite-cache',
  test: {
    environment: 'jsdom',
    include: ['src/preview/**/*.test.{ts,tsx}'],
    setupFiles: ['./src/test-setup.ts', './src/preview/test-isolation.ts'],
    restoreMocks: true,
  },
});
