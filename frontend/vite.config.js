import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react({
      babel: {
        plugins: [['babel-plugin-react-compiler']],
      },
    }),
  ],
  server: {
    proxy: {
      '/score': 'http://localhost:8000',
      '/ingest': 'http://localhost:8000',
      '/directions': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})