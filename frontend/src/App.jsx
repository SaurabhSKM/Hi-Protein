import { useEffect, useState } from 'react'
import FarmerView from './pages/FarmerView.jsx'
import MethodView from './pages/MethodView.jsx'
import RegionView from './pages/RegionView.jsx'
import { api } from './lib/api.js'
import { T as LABELS } from './lib/labels.js'

const TABS = ['farmer', 'region', 'method']

export default function App() {
  const [tab, setTab] = useState('farmer')
  const [lang, setLang] = useState('en')
  const [reference, setReference] = useState(null)
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.reference().then(setReference).catch((e) => setError(e.message))
    api.health().then(setHealth).catch(() => {})
  }, [])

  const T = LABELS[lang]
  const titles = { farmer: T.farmerView, region: T.regionView, method: T.methodView }

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <header className="border-b border-slate-300 bg-white">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-3 px-4 py-3">
          <div className="mr-auto">
            <div className="text-lg font-bold tracking-tight text-emerald-800">Hi-Protein</div>
            <div className="text-xs text-slate-500">{T.appTitle}</div>
          </div>

          <nav className="flex rounded-lg border border-slate-300 p-0.5">
            {TABS.map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`rounded px-3 py-1.5 text-sm font-medium ${
                  tab === t ? 'bg-emerald-700 text-white' : 'text-slate-600 hover:bg-slate-100'
                }`}
              >
                {titles[t]}
              </button>
            ))}
          </nav>

          <button
            onClick={() => setLang(lang === 'en' ? 'fr' : 'en')}
            className="rounded border border-slate-300 px-2 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100"
          >
            {lang === 'en' ? 'FR' : 'EN'}
          </button>

          {health && (
            <div className="text-[11px] text-slate-500">
              <div>
                model{' '}
                <span className={health.model_trained ? 'text-emerald-700' : 'text-amber-700'}>
                  {health.model_version}
                </span>
              </div>
              <div>
                {health.weather_departments} departments
                {health.offline_mode ? ' - offline mode' : ''}
              </div>
            </div>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-4 py-4">
        {error && (
          <div className="mb-3 rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">
            Backend unreachable: {error}
          </div>
        )}
        {tab === 'farmer' && reference && <FarmerView reference={reference} lang={lang} T={T} />}
        {tab === 'farmer' && !reference && !error && (
          <div className="text-sm text-slate-500">Loading reference data...</div>
        )}
        {tab === 'region' && <RegionView />}
        {tab === 'method' && <MethodView />}
      </main>

      <footer className="mx-auto max-w-[1600px] px-4 pb-6 text-[11px] leading-relaxed text-slate-500">
        Data: Agreste SAA departmental yields 2010-2024, Meteo-France donnees climatologiques de
        base, IGN API Carto RPG v2, ADEME Agribalyse, PAC 2023-2027 unit amounts. Buyer prices and
        volumes are illustrative demo data and are not commercial offers. Figures are operational
        gross margins, not farm profit, and do not replace advice from a Chamber of Agriculture or
        a cooperative agronomist.
      </footer>
    </div>
  )
}
