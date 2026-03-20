import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@shared': path.resolve(__dirname, '../shared'),
    },
  },
  server: {
    proxy: {
      // Kept as fallback — the app now connects directly to discovered IP
      '/robot': {
        target: process.env.ROBOT_URL || 'http://172.20.10.4:8888',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/robot/, ''),
      },
    },
  },
})
