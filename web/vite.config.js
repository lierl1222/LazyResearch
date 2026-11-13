import { defineConfig } from 'vite'

export default defineConfig({
  build: { assetsDir: 'static' },
  server: {
    proxy: {
      '/runs': 'http://127.0.0.1:8000',
      '/config': 'http://127.0.0.1:8000',
    },
  },
})
