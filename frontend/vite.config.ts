import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Some Linux desktops run close to `fs.inotify.max_user_instances`, and Vite then fails
// to start with ENOSPC on watch. Polling avoids inotify entirely at the cost of some
// CPU. The better fix is to raise the limit:
//   sudo sysctl -w fs.inotify.max_user_instances=512
const usePolling = process.env.VITE_USE_POLLING === '1'

const proxy = {
  // Keeps the browser same-origin, so signed asset URLs and the WebSocket work in
  // development without CORS gymnastics.
  '/v1': { target: 'http://127.0.0.1:8000', changeOrigin: true, ws: true },
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy,
    watch: usePolling ? { usePolling: true, interval: 300 } : undefined,
  },
  preview: { port: 4173, proxy },
  build: {
    rollupOptions: {
      output: {
        // Konva is large and stable; splitting it keeps app rebuilds small.
        manualChunks: { konva: ['konva', 'react-konva'] },
      },
    },
  },
})
