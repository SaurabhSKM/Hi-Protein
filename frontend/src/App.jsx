import { useEffect, useState } from 'react'
import FarmerView from './pages/FarmerView.jsx'
import FoodView from './pages/FoodView.jsx'
import LandChangeView from './pages/LandChangeView.jsx'
import LandingView from './pages/LandingView.jsx'
import MethodView from './pages/MethodView.jsx'
import RegionView from './pages/RegionView.jsx'
import { Logo, LogoMark } from './components/Logo.jsx'
import { api } from './lib/api.js'
import { T as LABELS } from './lib/labels.js'

const TABS = ['farmer', 'food', 'region', 'land', 'method']

export default function App() {
  const [tab, setTab] = useState('farmer')
  const [lang, setLang] = useState('en')
  const [reference, setReference] = useState(null)
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)
  // The landing page sits in front of the tabs rather than being one of them, so
  // the tab strip and every existing view keep their previous behaviour exactly.
  const [showLanding, setShowLanding] = useState(true)

  useEffect(() => {
    api.reference().then(setReference).catch((e) => setError(e.message))
    api.health().then(setHealth).catch(() => {})
  }, [])

  const T = LABELS[lang]
  const titles = {
    farmer: T.farmerView, food: T.foodView, region: T.regionView,
    land: T.landView, method: T.methodView,
  }

  // Landing <-> tabs is the only navigation the app has, so both directions live
  // here and every control that moves between them calls one of these.
  const enter = (target) => {
    setTab(TABS.includes(target) ? target : 'region')
    setShowLanding(false)
    window.scrollTo(0, 0)
  }
  const backToOverview = () => {
    setShowLanding(true)
    window.scrollTo(0, 0)
  }

  if (showLanding) {
    return (
      <LandingView
        lang={lang}
        onToggleLang={() => setLang(lang === 'en' ? 'fr' : 'en')}
        onEnter={enter}
      />
    )
  }

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <header className="border-b border-slate-300 bg-white">
        {/* Five tabs do not fit a 375 px phone on one row. The title row stays
            compact, the tab strip becomes a horizontally scrollable rail below it on
            small screens, and the build-status block is hidden on phones where it is
            just noise. */}
        <div className="mx-auto max-w-[1600px] px-3 py-2 sm:px-4 sm:py-3">
          <div className="flex items-center gap-3">
            <button
              onClick={backToOverview}
              className="mr-auto min-w-0 text-left transition hover:opacity-80"
              aria-label={T.backToOverviewHint}
            >
              <Logo className="h-7 sm:h-8" />
              <div className="truncate text-[11px] text-slate-500 sm:text-xs">
                {T.appTitle}
              </div>
            </button>

            {/* The logo goes back too, but that is an invisible affordance - nobody
                finds it. This is the one people actually use. */}
            <button
              onClick={backToOverview}
              className="shrink-0 rounded border border-slate-300 px-2 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-100 hover:text-emerald-800"
              title={T.backToOverviewHint}
            >
              <span aria-hidden="true">&larr;</span> {T.backToOverview}
            </button>

            <button
              onClick={() => setLang(lang === 'en' ? 'fr' : 'en')}
              className="shrink-0 rounded border border-slate-300 px-2 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100"
              aria-label="Switch language"
            >
              {lang === 'en' ? 'FR' : 'EN'}
            </button>

            {health && (
              <div className="hidden shrink-0 text-[11px] leading-tight text-slate-500 lg:block">
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

          <nav
            className="-mx-3 mt-2 flex gap-1 overflow-x-auto px-3 pb-0.5 sm:mx-0 sm:mt-2.5 sm:px-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
            aria-label="Views"
          >
            {TABS.map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                aria-current={tab === t ? 'page' : undefined}
                className={`shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-[13px] font-medium transition sm:text-sm ${
                  tab === t
                    ? 'bg-emerald-700 text-white shadow-sm'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                {titles[t]}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-3 py-3 sm:px-4 sm:py-4">
        {error && (
          <div className="mb-3 rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">
            Backend unreachable: {error}
          </div>
        )}
        {tab === 'farmer' && reference && <FarmerView reference={reference} lang={lang} T={T} />}
        {tab === 'food' && <FoodView T={T} />}
        {tab === 'farmer' && !reference && !error && (
          <div className="text-sm text-slate-500">Loading reference data...</div>
        )}
        {tab === 'region' && <RegionView />}
        {tab === 'land' && <LandChangeView />}
        {tab === 'method' && <MethodView />}
      </main>

      <footer className="mx-auto flex max-w-[1600px] items-start gap-3 px-3 pb-6 text-[10px] leading-relaxed text-slate-500 sm:px-4 sm:text-[11px]">
        <LogoMark className="hidden h-6 w-6 shrink-0 opacity-70 sm:block" />
        <p>
          Data: Agreste SAA departmental yields 2010-2024, Meteo-France donnees climatologiques
          de base, IGN API Carto RPG v2, ADEME Agribalyse, PAC 2023-2027 unit amounts. Buyer
          prices and volumes are illustrative demo data and are not commercial offers. Figures
          are operational gross margins, not farm profit, and do not replace advice from a
          Chamber of Agriculture or a cooperative agronomist.
        </p>
      </footer>
    </div>
  )
}
