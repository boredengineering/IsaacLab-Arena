import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';
export default defineConfig({
  base: './',
  plugins: [react()],
  envDir: '/tmp/arena-preview-empty-env',
  cacheDir: '/tmp/arena-preview-vite-cache',
  publicDir: false,
  build: {
    assetsInlineLimit: 100000,
    outDir: '/tmp/arena-ui-preview-dist',
    emptyOutDir: true,
    rolldownOptions: { input: resolve(import.meta.dirname, 'preview.html') },
  },
});
