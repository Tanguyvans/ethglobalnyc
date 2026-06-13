import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// Standalone WebGPU prototype.
// Run from the PARENT (frontend) dir so it resolves the installed node_modules:
//   npx vite --config webgpu-proto/vite.config.ts
//
// `root` is pinned to this proto folder so index.html here is the entry,
// while the parent frontend/node_modules is used for three / react / r3f.
export default defineConfig({
  root: fileURLToPath(new URL('.', import.meta.url)),
  plugins: [react()],
  resolve: {
    // Ensure a single copy of three is used (the parent's r0.169).
    dedupe: ['three', '@react-three/fiber', 'react', 'react-dom'],
  },
  optimizeDeps: {
    // three/webgpu is a large prebuilt bundle; let esbuild prebundle it.
    include: ['three/webgpu', 'three/tsl'],
  },
  server: {
    port: 5180,
    host: true,
  },
})
