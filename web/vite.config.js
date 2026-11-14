import { defineConfig } from 'vite'

export default defineConfig({
  build: { assetsDir: 'static' },
  server: {
    proxy: {
      '/research': 'http://127.0.0.1:8010',
      '/runs': 'http://127.0.0.1:8000',
      '/config': 'http://127.0.0.1:8000',
    },
  },
})
