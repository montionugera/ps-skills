import fs from 'node:fs'
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const localFonts = path.resolve(__dirname, 'vendor/fonts.css')
const localTheme = path.resolve(__dirname, 'theme.css')
const alias: Record<string, string> = {}
if (fs.existsSync(localFonts)) {
  alias['../../vendor/fonts.css'] = localFonts
}
if (fs.existsSync(localTheme)) {
  alias['../../template-infographic/theme.css'] = localTheme
}

// host is locked to loopback; serve.sh passes --port/--strictPort.
export default defineConfig({
  plugins: [react()],
  resolve: { alias },
  server: { host: '127.0.0.1' },
  preview: { host: '127.0.0.1' },
})
