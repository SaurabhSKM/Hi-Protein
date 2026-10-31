// The API is served by the same process as this bundle, so resolve its URL against
// the directory the page itself was loaded from rather than the domain root. A
// root-absolute '/api/v1' breaks whenever the app is reached through a proxy that
// mounts it under a prefix, as a workspace tunnel's /ports/8099/ does.
const ROOT = new URL('.', document.baseURI).href
const BASE = import.meta.env.VITE_API_BASE ?? new URL('api/v1', ROOT).href

async function call(path, { method = 'GET', body } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'content-type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const j = await res.json()
      if (j.detail) detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* non-JSON error body */ }
    throw new Error(detail)
  }
  return res.json()
}

export const api = {
  // /health sits outside the versioned prefix, so it resolves against ROOT directly.
  health: () => fetch(new URL('health', ROOT).href).then((r) => r.json()),
  reference: () => call('/reference'),
  simulate: (b) => call('/simulate-rotation', { method: 'POST', body: b }),
  rank: (b) => call('/rank-candidates', { method: 'POST', body: b }),
  parcel: (lon, lat) => call('/parcel', { method: 'POST', body: { lon, lat } }),
  regional: (n = 600) => call(`/regional-overview?n_simulations=${n}`),
  dossier: (b) => call('/dossier', { method: 'POST', body: b }),
  modelReport: () => call('/model-report'),
  yieldTrend: () => call('/yield-trend'),
}

export const eur = (v, digits = 0) =>
  v == null ? '-' : new Intl.NumberFormat('fr-FR', { maximumFractionDigits: digits }).format(v)

export const pct = (v, digits = 0) => (v == null ? '-' : `${(v * 100).toFixed(digits)}%`)
