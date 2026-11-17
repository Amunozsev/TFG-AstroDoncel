import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'node:fs'

const appVersion = readFileSync(new URL('../VERSION', import.meta.url), 'utf8').trim()

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    global: 'globalThis',
    __APP_VERSION__: JSON.stringify(appVersion),
  },
  // One bundle on purpose; Plotly alone is about 1.2 MB.
  build: { chunkSizeWarningLimit: 1600 },
})
