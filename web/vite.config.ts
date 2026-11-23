import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [svelte()],
  server: {
    // During development, send API calls to the local FlipDial server.
    proxy: { '/api': 'http://127.0.0.1:8080' },
  },
})
