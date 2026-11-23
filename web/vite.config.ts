import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

export default defineConfig(({ mode }) => ({
  plugins: [svelte()],
  // The demo is served from a sub-path on GitHub Pages; relative paths work anywhere.
  base: mode === 'demo' ? './' : '/',
  server: {
    fs: { allow: ['..'] }, // the demo reads invented data from ../demo
    // During development, send API calls to the local FlipDial server.
    proxy: { '/api': 'http://127.0.0.1:8080' },
  },
}))
