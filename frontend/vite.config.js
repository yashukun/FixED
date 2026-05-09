import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const ingestProxyTarget = env.VITE_INGEST_PROXY_TARGET || 'http://localhost:8001'
  const searchProxyTarget = env.VITE_SEARCH_PROXY_TARGET || 'http://localhost:8002'
  const qpaperProxyTarget = env.VITE_QPAPER_PROXY_TARGET || 'http://localhost:8003'
  const gatewayProxyTarget = env.VITE_GATEWAY_PROXY_TARGET || 'http://localhost:8000'

  return {
    plugins: [react()],
    esbuild: {
      jsx: 'automatic',
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: './src/test/setup.js',
    },
    server: {
      port: 3000,
      host: true,
      proxy: {
        '/api/ingest': {
          target: ingestProxyTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/ingest/, ''),
        },
        '/api/search': {
          target: searchProxyTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/search/, ''),
        },
        '/api/qpaper': {
          target: qpaperProxyTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/qpaper/, ''),
        },
        '/api/gateway': {
          target: gatewayProxyTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api\/gateway/, ''),
        },
      },
    },
  }
})
