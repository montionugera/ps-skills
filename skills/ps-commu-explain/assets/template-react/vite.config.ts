import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// host is locked to loopback; serve.sh passes --port/--strictPort.
export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1' },
  preview: { host: '127.0.0.1' },
})
