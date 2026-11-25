import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 默认把 /api 代理到本地后端；需要连别的端口时用 VITE_API_PROXY 覆盖，不改代码
const apiProxyTarget = process.env.VITE_API_PROXY || 'http://localhost:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5199,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        // 把体积大的依赖拆开，首屏只需要 vue + markdown
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('echarts') || id.includes('zrender')) return 'charts'
          if (id.includes('marked') || id.includes('highlight.js') || id.includes('dompurify')) {
            return 'markdown'
          }
          if (
            id.includes('/vue/') ||
            id.includes('vue-router') ||
            id.includes('pinia') ||
            id.includes('@vue/')
          ) {
            return 'vue-vendor'
          }
          return 'vendor'
        },
      },
    },
  },
})
