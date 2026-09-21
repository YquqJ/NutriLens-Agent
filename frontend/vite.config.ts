import { defineConfig } from 'vite'
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { resolveBackendPort } from './vite-backend-port'

function getBackendPort() {
  const frontendDir = fileURLToPath(new URL('.', import.meta.url))
  const runtimeFile = path.resolve(frontendDir, '../backend/.runtime-port')
  const runtimePort = existsSync(runtimeFile) ? readFileSync(runtimeFile, 'utf8') : undefined
  return resolveBackendPort(process.env.BACKEND_PORT, runtimePort)
}

const backendPort = getBackendPort()

// 开发期把 /api 代理到后端实际端口，前后端同源，规避 CORS 与 cookie 问题。
// SSE 流式端点 /api/conversations/*/chat 走 http-proxy 原生透传，打字机效果不缓存。
export default defineConfig({
  plugins: [
    vue(),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: 'src/components.d.ts',
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: `http://localhost:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
})
