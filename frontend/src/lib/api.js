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
  // No n_simulations: the regional view reads baked department profiles rather than
  // running 42 Monte Carlos per request.
  regional: () => call('/regional-overview'),
  strandedSurface: ({ department, region, status, limit = 20000 } = {}) => {
    const q = new URLSearchParams({ limit: String(limit) })
    if (department) q.set('department_code', department)
    if (region) q.set('region_code', region)
    if (status) q.set('status', status)
    return call(`/stranded-surface?${q}`)
  },
  optimiseSorters: (b) => call('/optimise-sorters', { method: 'POST', body: b }),
  breeders: (lon, lat, pulse, lotT = 50) =>
    call(
      `/breeders?lon=${lon}&lat=${lat}&pulse=${encodeURIComponent(pulse)}` +
        `&downgraded_lot_t=${lotT}`,
    ),
  dossier: (b) => call('/dossier', { method: 'POST', body: b }),
  modelReport: () => call('/model-report'),
  yieldTrend: () => call('/yield-trend'),
  // Land change. The department polygons are ~0.7 MB and never change, so they are a
  // separate call the page makes once rather than part of every crop switch.
  adoptionOverview: () => call('/adoption/overview'),
  adoptionDepartments: (crop) =>
    call(`/adoption/departments?crop=${encodeURIComponent(crop)}`),
  adoptionGeometry: () => call('/adoption/geometry'),
  adoptionAttribution: () => call('/adoption/attribution'),
  rpgChange: () => call('/adoption/rpg-change'),
  foodDemand: (n = 400, horizon = 'observed') =>
    call(`/food-demand?n_simulations=${n}&climate_horizon=${horizon}`),
  climateOutlook: (dept, crop, soil, n = 600) =>
    call(
      `/climate-outlook?department_code=${encodeURIComponent(dept)}` +
        `&crop=${encodeURIComponent(crop)}&soil_type=${encodeURIComponent(soil)}` +
        `&n_simulations=${n}`,
    ),
}

export const eur = (v, digits = 0) =>
  v == null ? '-' : new Intl.NumberFormat('fr-FR', { maximumFractionDigits: digits }).format(v)

export const pct = (v, digits = 0) => (v == null ? '-' : `${(v * 100).toFixed(digits)}%`)
