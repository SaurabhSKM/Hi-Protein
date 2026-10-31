import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const API = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8099'

// Vite rejects requests whose Host header it does not recognise, which is a
// DNS-rebinding guard on the dev server. It fires whenever the dev server is reached
// through a proxy rather than on localhost, as in a cloud workspace that tunnels the
// port out under a generated hostname.
//
// A leading dot matches any subdomain, so these cover the usual tunnel providers
// without opening the server to an arbitrary Host. Set VITE_ALLOWED_HOSTS to a
// comma-separated list to add your own, or to `true` to disable the check entirely.
const DEFAULT_ALLOWED_HOSTS = [
  'localhost',
  '127.0.0.1',
  '.cloudfront.net',
  '.amazonaws.com',
  '.github.dev',
  '.gitpod.io',
  '.app.github.dev',
  '.ngrok-free.app',
  '.trycloudflare.com',
]

const envHosts = process.env.VITE_ALLOWED_HOSTS?.trim()
const allowedHosts =
  envHosts === 'true'
    ? true
    : envHosts
      ? envHosts.split(',').map((h) => h.trim()).filter(Boolean)
      : DEFAULT_ALLOWED_HOSTS

const proxy = {
  // /health sits outside the versioned prefix, so it needs its own rule.
  // Without it Vite's SPA fallback answers with index.html and a 200, and the
  // health chip silently fails to parse instead of reporting a real problem.
  '/api': { target: API, changeOrigin: true },
  '/health': { target: API, changeOrigin: true },
}

export default defineConfig({
  // Relative asset URLs, so the bundle works when it is served from a subpath
  // such as a workspace proxy's /ports/8099/ as well as from the domain root.
  // With the default '/' the browser asks for /assets/... above the prefix and
  // gets the proxy's 403 instead of the bundle, which renders as a blank page.
  base: './',
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Bind on all interfaces so a proxy or another machine can reach it. The API it
    // talks to stays bound to loopback.
    host: true,
    allowedHosts,
    proxy,
    hmr: {
      // Behind an HTTPS proxy the hot-reload socket has to be told to use wss on 443,
      // or the browser tries ws:// against the public host and the page sits there
      // reconnecting. Harmless to leave unset for plain local use.
      ...(process.env.VITE_HMR_HOST
        ? { host: process.env.VITE_HMR_HOST, protocol: 'wss', clientPort: 443 }
        : {}),
    },
  },
  // `vite preview` serves the production build and applies the same host check.
  preview: {
    port: 4173,
    host: true,
    allowedHosts,
    proxy,
  },
})
