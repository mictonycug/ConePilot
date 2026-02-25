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
      '/robot': {
        target: 'http://172.20.10.3:8888',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/robot/, ''),
      },
    },
  },
})
