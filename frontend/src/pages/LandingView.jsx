/* The landing page. Deliberately self-contained and fully static: it is the first
   thing a ministry, co-op or farmer sees, and it must render even when the backend
   is unreachable. Every figure below is pinned from a generated artefact rather
   than fetched, with the artefact named in the provenance line beneath it. */

import { Logo, LogoMark, LogoStacked, LogoWatermark } from '../components/Logo.jsx'

const NATIONAL = {
  // adits/external/idle_land_by_dept.csv + _meta.json, RPG 2024, generated 2026-10-31.
  idleHa: 368202,
  idleHaLo: 328240,
  idleHaHi: 409213,
  idleParcels: 1042036,
  meanParcelHa: 0.39,
  arableHa: 10556377,
  pulseHa: 310695,
  pulseSharePct: 2.94,
  targetPct: 8,
  gapHa: 533815,
  idleCoversGapPct: 69,
  departments: 95,
}

// econ_fallow_conversion.csv, dept 45, simulate-rotation fallow -> winter pea,
// 2,000 Monte Carlo paths, year 2 of 3.
const EXAMPLE = {
  dept: 'Loiret',
  deptCode: '45',
  parcelHa: 45,
  pulse: 'winter pea',
  pulseFr: "pois d'hiver",
  marginPerHa: 1040,
  probGain: 99.6,
  displacingBarley: -180,
  idleHa: 11920,
  coversGapPct: 75,
}

const TOP_DEPTS = [
  { code: '17', name: 'Charente-Maritime', idleHa: 16628, pctArable: 6.3, coversGap: 230 },
  { code: '32', name: 'Gers', idleHa: 14842, pctArable: 5.3, coversGap: 363 },
  { code: '16', name: 'Charente', idleHa: 14047, pctArable: 8.2, coversGap: 327 },
  { code: '86', name: 'Vienne', idleHa: 12523, pctArable: 4.1, coversGap: 93 },
  { code: '45', name: 'Loiret', idleHa: 11920, pctArable: 4.5, coversGap: 75 },
  { code: '40', name: 'Landes', idleHa: 11764, pctArable: 9.2, coversGap: 127 },
]

const COPY = {
  en: {
    eyebrow: 'French plant protein — idle land, measured',
    h1a: 'France needs 534,000 hectares of pulses.',
    h1b: '368,000 are already sitting idle.',
    lede:
      'Roughly half the plant protein in French animal feed is imported, mostly Brazilian soybean meal. The 2030 national target asks for 8% of arable land in food-grade grain pulses. Today it is 2.9%. We measured where the missing hectares already exist — and they are the cheapest land in France to convert.',
    ctaStats: 'Explore Statistics',
    ctaFarmer: 'Check your parcel',
    ctaMethod: 'Model & method',
    // Destinations named the way the tab strip names them, so arriving somewhere
    // does not feel like arriving somewhere else.
    openStats: 'Open the statistics',
    openLand: 'See how the land changed',
    ctaAdvisor: 'Open the Farm & Advisor workspace',
    ctaAdvisorSub:
      'Pick a parcel, choose a pulse and a rotation, and read the margin, the grading risk and the contract side by side.',
    heroNote:
      'Parcel counts are a census of the 2024 subsidy register. Hectares are sampled and scaled, with a 95% interval.',

    statsTitle: 'The gap, and what is already lying in it',
    sIdle: 'Idle farmland',
    sIdleSub: '95 departments, RPG 2024',
    sGap: 'Gap to the 2030 target',
    sGapSub: 'at 8% of arable land in pulses',
    sCovers: 'Of the gap idle land could cover',
    sCoversSub: 'without displacing a single crop',
    sShare: 'Pulse share of arable land today',
    sShareSub: 'against the 8% target',

    problemTitle: 'Why the target is missing, and it is not for lack of land',
    p1h: 'The land is not the constraint',
    p1b:
      'Every department we measured holds idle declared farmland. Nationally it is 368,202 hectares across 1,042,036 parcels — enough to cover 69% of the entire national gap to the 8% target, before anyone gives up a hectare of wheat.',
    p2h: 'Converting anything else costs money',
    p2b:
      'Putting pulses on land that currently grows barley costs about €180 per hectare in displaced margin. Putting them on declared fallow displaces nothing, and our simulation returns a gain above €900 per hectare over three years in every department we ran. Idle land is the only tranche that pays before any premium.',
    p3h: 'And the rules quietly penalise it',
    p3b:
      'Fallow counts toward the non-productive area farmers are required to hold under BCAE 8. Converting it means finding that area elsewhere on the farm. The cheapest conversion in France carries an administrative cost nobody has priced — which is exactly the friction we exist to absorb.',

    nuanceTag: 'What the obvious reading gets wrong',
    nuanceH:
      '10.9% of declared parcels are idle — but they average 0.39 hectares against roughly 2.9 for farmland generally.',
    nuanceB:
      'Idle land is mostly field margins, headlands and set-aside corners: many parcels, few hectares. So the share of parcels overstates the share of land by roughly seven times, and a pitch built on parcel counts falls apart under the first serious question. Our 368,202 hectares is 3.5% of France’s arable cereal, oilseed and pulse area. Every figure on this page is derived from hectares, never from parcel counts — which is why our number is smaller than the obvious one, and why it holds.',

    exampleTitle: 'What it looks like on one farm',
    exampleIntro:
      'A 45-hectare block of declared fallow in Loiret, converted to winter pea in year two of a three-year rotation. Figures are operational gross margin from 2,000 Monte Carlo paths.',
    exBefore: 'Today, lying fallow',
    exBeforeVal: 'No crop margin',
    exBeforeSub: 'Basic CAP support only; nothing grown, nothing sold',
    exAfter: 'Converted to winter pea',
    exAfterSub: 'per hectare over three years, 99.6% probability of gain',
    exAlt: 'The same switch on barley land',
    exAltSub: 'per hectare — displacing a paying crop costs money',
    exTotal: 'On the full 45 hectares',
    exTotalSub: 'operational gross margin over three years, not farm profit',

    offerTitle: 'What a farmer gets by working with us',
    o1h: 'The agronomy, decided',
    o1b:
      'Which pulse suits your soil, your rainfall and your rotation history — including the disease return intervals that make a pea-after-pea decision expensive six years later.',
    o2h: 'A buyer before you drill',
    o2b:
      'Contracted offtake through our processor and co-op partnerships, so the crop is sold before it is sown rather than hunted for at harvest.',
    o3h: 'Logistics and storage',
    o3b:
      'Collection, haulage, drying and storage arranged through partners, sized to your tonnage rather than to a 500-hectare grower.',
    o4h: 'The grading risk, carried',
    o4b:
      'Food specification is where pulse margin is won or lost. We price that risk and carry it, so a lot that misses food grade is our exposure before it is yours.',

    topTitle: 'Where the idle hectares are',
    topIntro:
      'The six departments holding the most idle declared farmland. In several of them, idle land alone exceeds the entire gap to the 8% target.',
    thDept: 'Department',
    thIdle: 'Idle hectares',
    thPct: 'Share of arable',
    thCovers: 'Covers of its gap',
    topMore: 'All 95 departments, mapped and rankable',

    finalH: 'See the whole picture',
    finalB:
      'The statistics page carries every department, the yield model behind the margins, and the provenance of each figure — including where our own numbers are estimates rather than measurements.',

    footer:
      'Sources: IGN RPG 2024 via Geoplateforme, Agreste SAA departmental series (2022–2024 mean), Météo-France climatological records, ADEME Agribalyse, CAP 2023–2027 unit amounts. Idle hectares are a sampled estimate with a 95% interval, not an exact census; parcel counts are exact. Buyer prices and volumes in the simulation are illustrative demo data and are not commercial offers. All figures are operational gross margins, not farm profit, and do not replace advice from a Chamber of Agriculture or a cooperative agronomist.',
  },
  fr: {
    eyebrow: 'Protéines végétales françaises — la terre inutilisée, mesurée',
    h1a: 'La France a besoin de 534 000 hectares de légumineuses.',
    h1b: '368 000 sont déjà inutilisés.',
    lede:
      "Environ la moitié des protéines végétales de l'alimentation animale française est importée, surtout du tourteau de soja brésilien. L'objectif national 2030 demande 8 % des terres arables en légumineuses à graines alimentaires. Aujourd'hui, c'est 2,9 %. Nous avons mesuré où se trouvent déjà les hectares manquants — et ce sont les terres les moins chères de France à convertir.",
    ctaStats: 'Explorer les statistiques',
    ctaFarmer: 'Évaluer votre parcelle',
    ctaMethod: 'Modèle et méthode',
    openStats: 'Ouvrir les statistiques',
    openLand: "Voir l'évolution des surfaces",
    ctaAdvisor: "Ouvrir l'espace agriculteur et conseiller",
    ctaAdvisorSub:
      "Choisissez une parcelle, une légumineuse et une rotation, et lisez côte à côte la marge, le risque de calibrage et le contrat.",
    heroNote:
      'Le nombre de parcelles est un recensement du registre PAC 2024. Les hectares sont estimés par échantillonnage, avec un intervalle à 95 %.',

    statsTitle: "L'écart, et ce qui s'y trouve déjà",
    sIdle: 'Terres agricoles inutilisées',
    sIdleSub: '95 départements, RPG 2024',
    sGap: "Écart à l'objectif 2030",
    sGapSub: '8 % des terres arables en légumineuses',
    sCovers: "De l'écart couvert par les terres inutilisées",
    sCoversSub: 'sans déplacer une seule culture',
    sShare: 'Part actuelle des légumineuses',
    sShareSub: "contre un objectif de 8 %",

    problemTitle: "Pourquoi l'objectif est manqué, et ce n'est pas faute de terres",
    p1h: "La terre n'est pas la contrainte",
    p1b:
      "Chaque département mesuré détient des terres agricoles déclarées mais non cultivées. À l'échelle nationale : 368 202 hectares sur 1 042 036 parcelles — de quoi couvrir 69 % de l'écart national à l'objectif de 8 %, avant que quiconque renonce à un hectare de blé.",
    p2h: 'Convertir autre chose coûte de l’argent',
    p2b:
      "Implanter des légumineuses sur une terre en orge coûte environ 180 € par hectare de marge déplacée. Les implanter sur une jachère déclarée ne déplace rien, et notre simulation retourne un gain supérieur à 900 € par hectare sur trois ans dans tous les départements testés. La jachère est la seule tranche rentable avant toute prime.",
    p3h: 'Et la réglementation la pénalise discrètement',
    p3b:
      "La jachère compte dans la surface non productive exigée au titre de la BCAE 8. La convertir oblige à retrouver cette surface ailleurs sur l'exploitation. La conversion la moins chère de France porte un coût administratif que personne n'a chiffré — c'est précisément le frottement que nous existons pour absorber.",

    nuanceTag: 'Ce que la lecture évidente fait dire de faux',
    nuanceH:
      '10,9 % des parcelles déclarées sont inutilisées — mais elles font 0,39 hectare en moyenne, contre environ 2,9 pour les terres agricoles en général.',
    nuanceB:
      "La terre inutilisée, ce sont surtout des bordures, des tournières et des coins gelés : beaucoup de parcelles, peu d'hectares. La part des parcelles surestime donc la part de la surface d'environ sept fois, et un argumentaire bâti sur le nombre de parcelles s'effondre à la première question sérieuse. Nos 368 202 hectares représentent 3,5 % de la surface française en céréales, oléagineux et protéagineux. Tous les chiffres de cette page sont dérivés des hectares, jamais du nombre de parcelles — c'est pourquoi notre chiffre est plus petit que le chiffre évident, et pourquoi il tient.",

    exampleTitle: 'Ce que cela donne sur une exploitation',
    exampleIntro:
      "Un îlot de 45 hectares de jachère déclarée dans le Loiret, converti en pois d'hiver en année deux d'une rotation de trois ans. Chiffres en marge brute opérationnelle, sur 2 000 trajectoires Monte-Carlo.",
    exBefore: "Aujourd'hui, en jachère",
    exBeforeVal: 'Aucune marge de culture',
    exBeforeSub: 'Soutien PAC de base seulement ; rien de cultivé, rien de vendu',
    exAfter: "Converti en pois d'hiver",
    exAfterSub: 'par hectare sur trois ans, 99,6 % de probabilité de gain',
    exAlt: 'Le même choix sur une terre en orge',
    exAltSub: 'par hectare — déplacer une culture rémunératrice coûte',
    exTotal: 'Sur les 45 hectares',
    exTotalSub: "marge brute opérationnelle sur trois ans, pas le bénéfice de l'exploitation",

    offerTitle: 'Ce que l’agriculteur obtient en travaillant avec nous',
    o1h: "L'agronomie, tranchée",
    o1b:
      "Quelle légumineuse convient à votre sol, votre pluviométrie et votre historique de rotation — y compris les délais de retour sanitaires qui rendent un pois après pois coûteux six ans plus tard.",
    o2h: 'Un acheteur avant le semis',
    o2b:
      "Débouché contractualisé via nos partenariats avec transformateurs et coopératives : la récolte est vendue avant d'être semée, pas cherchée à la moisson.",
    o3h: 'Logistique et stockage',
    o3b:
      "Collecte, transport, séchage et stockage organisés avec nos partenaires, dimensionnés à votre tonnage et non à celui d'un exploitant de 500 hectares.",
    o4h: 'Le risque de calibrage, porté',
    o4b:
      "La spécification alimentaire décide de la marge en légumineuses. Nous chiffrons ce risque et nous le portons : un lot qui manque le grade alimentaire est notre exposition avant d'être la vôtre.",

    topTitle: 'Où sont les hectares inutilisés',
    topIntro:
      "Les six départements détenant le plus de terres agricoles déclarées non cultivées. Dans plusieurs d'entre eux, la jachère seule dépasse tout l'écart à l'objectif de 8 %.",
    thDept: 'Département',
    thIdle: 'Hectares inutilisés',
    thPct: 'Part des terres arables',
    thCovers: 'Couvre de son écart',
    topMore: 'Les 95 départements, cartographiés et classables',

    finalH: "Voir l'ensemble",
    finalB:
      "La page statistiques présente tous les départements, le modèle de rendement derrière les marges, et la provenance de chaque chiffre — y compris là où nos propres nombres sont des estimations et non des mesures.",

    footer:
      "Sources : IGN RPG 2024 via la Géoplateforme, séries départementales Agreste SAA (moyenne 2022-2024), données climatologiques Météo-France, ADEME Agribalyse, montants unitaires PAC 2023-2027. Les hectares inutilisés sont une estimation par échantillonnage avec intervalle à 95 %, pas un recensement exact ; le nombre de parcelles est exact. Les prix et volumes acheteurs de la simulation sont des données de démonstration et ne constituent pas une offre commerciale. Tous les chiffres sont des marges brutes opérationnelles, pas le bénéfice de l'exploitation, et ne remplacent pas l'avis d'une Chambre d'agriculture ou d'un agronome de coopérative.",
  },
}

const nf = (lang) => new Intl.NumberFormat(lang === 'fr' ? 'fr-FR' : 'en-GB')

function Figure({ value, label, sub, tone = 'light', onClick, title }) {
  const tones = {
    light: 'border-white/15 bg-white/[0.06] text-white',
    solid: 'border-emerald-200 bg-white text-slate-900',
  }
  // Every headline figure on this page comes from the statistics view, so each tile
  // doubles as a way into it rather than being a dead end.
  const Tag = onClick ? 'button' : 'div'
  const interactive = onClick
    ? 'text-left transition hover:border-white/40 hover:bg-white/[0.12] focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300'
    : ''
  return (
    <Tag
      onClick={onClick}
      title={onClick ? title : undefined}
      className={`rounded-xl border p-4 backdrop-blur-sm ${tones[tone]} ${interactive}`}
    >
      <div className="text-2xl font-semibold tabular-nums sm:text-3xl">{value}</div>
      <div className="mt-1 text-[13px] font-medium leading-snug">{label}</div>
      {sub && <div className="mt-1 text-[11px] leading-snug opacity-70">{sub}</div>}
      {onClick && (
        <div className="mt-2 text-[11px] font-semibold text-emerald-200">
          {title} <span aria-hidden="true">&rarr;</span>
        </div>
      )}
    </Tag>
  )
}

function Section({ children, className = '' }) {
  return (
    <section className={`mx-auto max-w-[1100px] px-5 ${className}`}>{children}</section>
  )
}

export default function LandingView({ onEnter, lang, onToggleLang }) {
  const C = COPY[lang] ?? COPY.en
  const fmt = nf(lang)

  return (
    <div className="min-h-screen bg-white text-slate-900">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1100px] items-center gap-3 px-5 py-3">
          <div className="mr-auto min-w-0">
            <Logo className="h-8 sm:h-9" />
          </div>
          <button
            onClick={onToggleLang}
            className="shrink-0 rounded border border-slate-300 px-2 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-100"
            aria-label="Switch language"
          >
            {lang === 'en' ? 'FR' : 'EN'}
          </button>
          <button
            onClick={() => onEnter('region')}
            className="shrink-0 rounded-lg bg-emerald-700 px-3 py-2 text-[13px] font-semibold text-white shadow-sm transition hover:bg-emerald-800"
          >
            {C.ctaStats}
          </button>
        </div>
      </header>

      {/* Hero */}
      <div className="relative overflow-hidden bg-gradient-to-br from-emerald-950 via-emerald-900 to-slate-900 text-white">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage:
              'radial-gradient(circle at 1px 1px, white 1px, transparent 0)',
            backgroundSize: '22px 22px',
          }}
          aria-hidden="true"
        />
        {/* The mark as hero texture. Low enough not to compete with the headline,
            and clipped by the band's overflow-hidden on narrow screens. */}
        <LogoWatermark className="absolute -right-16 -top-10 h-[320px] w-[320px] opacity-[0.06] sm:-right-10 sm:h-[420px] sm:w-[420px]" />
        <Section className="relative py-14 sm:py-20">
          <div className="inline-flex items-center gap-2 rounded-full border border-emerald-400/30 bg-emerald-400/10 py-1 pl-2 pr-3 text-[11px] font-semibold uppercase tracking-wide text-emerald-200">
            <LogoMark onDark className="h-4 w-4" />
            {C.eyebrow}
          </div>

          <h1 className="mt-5 max-w-3xl text-3xl font-bold leading-[1.15] tracking-tight sm:text-5xl">
            <span className="block text-white/70">{C.h1a}</span>
            <span className="mt-1 block">{C.h1b}</span>
          </h1>

          <p className="mt-5 max-w-2xl text-[15px] leading-relaxed text-emerald-50/80 sm:text-base">
            {C.lede}
          </p>

          <div className="mt-8 flex flex-wrap gap-3">
            <button
              onClick={() => onEnter('region')}
              className="rounded-lg bg-white px-5 py-3 text-sm font-semibold text-emerald-900 shadow-lg shadow-emerald-950/30 transition hover:bg-emerald-50"
            >
              {C.ctaStats}
            </button>
            <button
              onClick={() => onEnter('farmer')}
              className="rounded-lg border border-white/25 bg-white/5 px-5 py-3 text-sm font-semibold text-white transition hover:bg-white/10"
            >
              {C.ctaFarmer}
            </button>
            <button
              onClick={() => onEnter('method')}
              className="rounded-lg border border-transparent px-5 py-3 text-sm font-semibold text-emerald-200 transition hover:text-white"
            >
              {C.ctaMethod}
            </button>
          </div>

          <div className="mt-10 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Figure
              value={`${fmt.format(NATIONAL.idleHa)} ha`}
              label={C.sIdle}
              sub={C.sIdleSub}
              onClick={() => onEnter('region')}
              title={C.openStats}
            />
            <Figure
              value={`${fmt.format(NATIONAL.gapHa)} ha`}
              label={C.sGap}
              sub={C.sGapSub}
              onClick={() => onEnter('region')}
              title={C.openStats}
            />
            <Figure
              value={`${NATIONAL.idleCoversGapPct}%`}
              label={C.sCovers}
              sub={C.sCoversSub}
              onClick={() => onEnter('land')}
              title={C.openLand}
            />
            <Figure
              value={lang === 'fr' ? '2,94 %' : '2.94%'}
              label={C.sShare}
              sub={C.sShareSub}
              onClick={() => onEnter('region')}
              title={C.openStats}
            />
          </div>

          <p className="mt-5 max-w-2xl text-[11px] leading-relaxed text-emerald-200/60">
            {C.heroNote}
          </p>
        </Section>
      </div>

      {/* The problem */}
      <Section className="py-14 sm:py-16">
        <h2 className="max-w-2xl text-2xl font-bold tracking-tight sm:text-3xl">
          {C.problemTitle}
        </h2>
        <div className="mt-8 grid gap-5 md:grid-cols-3">
          {[
            [C.p1h, C.p1b],
            [C.p2h, C.p2b],
            [C.p3h, C.p3b],
          ].map(([h, b], i) => (
            <div key={i} className="rounded-xl border border-slate-200 bg-slate-50 p-5">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-700 text-[13px] font-bold text-white">
                {i + 1}
              </div>
              <h3 className="mt-3 text-base font-semibold leading-snug">{h}</h3>
              <p className="mt-2 text-[13px] leading-relaxed text-slate-600">{b}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* The parcel/hectare correction - our distinguishing rigour, so it gets its own band */}
      <div className="border-y border-amber-200 bg-amber-50">
        <Section className="py-12">
          <div className="inline-block rounded-full border border-amber-300 bg-white px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-amber-800">
            {C.nuanceTag}
          </div>
          <h2 className="mt-4 max-w-3xl text-xl font-bold leading-snug tracking-tight text-amber-950 sm:text-2xl">
            {C.nuanceH}
          </h2>
          <p className="mt-3 max-w-3xl text-[13px] leading-relaxed text-amber-900/80 sm:text-sm">
            {C.nuanceB}
          </p>
        </Section>
      </div>

      {/* Worked example */}
      <Section className="py-14 sm:py-16">
        <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">{C.exampleTitle}</h2>
        <p className="mt-3 max-w-2xl text-[13px] leading-relaxed text-slate-600 sm:text-sm">
          {C.exampleIntro}
        </p>

        <div className="mt-8 grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-5">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              {C.exBefore}
            </div>
            <div className="mt-2 text-2xl font-semibold text-slate-400">{C.exBeforeVal}</div>
            <p className="mt-2 text-xs leading-relaxed text-slate-500">{C.exBeforeSub}</p>
          </div>

          <div className="rounded-xl border-2 border-emerald-600 bg-emerald-50 p-5 shadow-sm">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700">
              {C.exAfter}
            </div>
            <div className="mt-2 text-3xl font-bold tabular-nums text-emerald-800">
              +{fmt.format(EXAMPLE.marginPerHa)} €
            </div>
            <p className="mt-2 text-xs leading-relaxed text-emerald-800/80">{C.exAfterSub}</p>
          </div>

          <div className="rounded-xl border border-rose-200 bg-rose-50 p-5">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-rose-700">
              {C.exAlt}
            </div>
            <div className="mt-2 text-3xl font-bold tabular-nums text-rose-800">
              {fmt.format(EXAMPLE.displacingBarley)} €
            </div>
            <p className="mt-2 text-xs leading-relaxed text-rose-800/80">{C.exAltSub}</p>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-baseline gap-x-4 gap-y-1 rounded-xl border border-emerald-200 bg-white p-5">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            {C.exTotal}
          </span>
          <span className="text-2xl font-bold tabular-nums text-emerald-800">
            +{fmt.format(EXAMPLE.marginPerHa * EXAMPLE.parcelHa)} €
          </span>
          <span className="text-xs text-slate-500">{C.exTotalSub}</span>
        </div>
      </Section>

      {/* What we provide */}
      <div className="border-y border-slate-200 bg-slate-50">
        <Section className="py-14 sm:py-16">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">{C.offerTitle}</h2>
          <div className="mt-8 grid gap-4 sm:grid-cols-2">
            {[
              [C.o1h, C.o1b],
              [C.o2h, C.o2b],
              [C.o3h, C.o3b],
              [C.o4h, C.o4b],
            ].map(([h, b], i) => (
              <div key={i} className="rounded-xl border border-slate-200 bg-white p-5">
                <div className="flex items-start gap-2.5">
                  <LogoMark className="mt-0.5 h-5 w-5 shrink-0" />
                  <h3 className="text-base font-semibold text-emerald-900">{h}</h3>
                </div>
                <p className="mt-2 text-[13px] leading-relaxed text-slate-600">{b}</p>
              </div>
            ))}
          </div>

          {/* The four cards above describe the workspace; this is the door into it. */}
          <div className="mt-7 flex flex-col gap-4 rounded-xl border border-emerald-200 bg-white p-5 sm:flex-row sm:items-center">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <LogoMark className="h-5 w-5 shrink-0" />
                <div className="text-sm font-semibold text-emerald-900">{C.ctaAdvisor}</div>
              </div>
              <p className="mt-1.5 text-[13px] leading-relaxed text-slate-600">
                {C.ctaAdvisorSub}
              </p>
            </div>
            <button
              onClick={() => onEnter('farmer')}
              className="shrink-0 rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-800 sm:ml-auto"
            >
              {C.ctaFarmer} <span aria-hidden="true">&rarr;</span>
            </button>
          </div>
        </Section>
      </div>

      {/* Top departments */}
      <Section className="py-14 sm:py-16">
        <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">{C.topTitle}</h2>
        <p className="mt-3 max-w-2xl text-[13px] leading-relaxed text-slate-600 sm:text-sm">
          {C.topIntro}
        </p>

        <div className="mt-6 overflow-hidden rounded-xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2.5 text-left font-semibold">{C.thDept}</th>
                <th className="px-4 py-2.5 text-right font-semibold">{C.thIdle}</th>
                <th className="hidden px-4 py-2.5 text-right font-semibold sm:table-cell">
                  {C.thPct}
                </th>
                <th className="px-4 py-2.5 text-right font-semibold">{C.thCovers}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {TOP_DEPTS.map((d) => (
                <tr key={d.code} className="transition hover:bg-emerald-50/40">
                  <td className="px-4 py-2.5">
                    <span className="mr-2 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-slate-600">
                      {d.code}
                    </span>
                    {d.name}
                  </td>
                  <td className="px-4 py-2.5 text-right font-medium tabular-nums">
                    {fmt.format(d.idleHa)}
                  </td>
                  <td className="hidden px-4 py-2.5 text-right tabular-nums text-slate-600 sm:table-cell">
                    {fmt.format(d.pctArable)} %
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[12px] font-semibold tabular-nums ${
                        d.coversGap >= 100
                          ? 'bg-emerald-100 text-emerald-800'
                          : 'bg-slate-100 text-slate-700'
                      }`}
                    >
                      {fmt.format(d.coversGap)} %
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <button
          onClick={() => onEnter('region')}
          className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-emerald-800 transition hover:text-emerald-950"
        >
          {C.topMore}
          <span aria-hidden="true">→</span>
        </button>
      </Section>

      {/* Final CTA */}
      <div className="bg-emerald-950 text-white">
        <Section className="py-14 text-center sm:py-16">
          <LogoStacked onDark className="mx-auto mb-7 h-20 sm:h-24" />
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">{C.finalH}</h2>
          <p className="mx-auto mt-3 max-w-xl text-[13px] leading-relaxed text-emerald-100/70 sm:text-sm">
            {C.finalB}
          </p>
          <div className="mt-7 flex flex-wrap justify-center gap-3">
            <button
              onClick={() => onEnter('region')}
              className="rounded-lg bg-white px-5 py-3 text-sm font-semibold text-emerald-900 shadow-lg transition hover:bg-emerald-50"
            >
              {C.ctaStats}
            </button>
            <button
              onClick={() => onEnter('farmer')}
              className="rounded-lg border border-white/25 px-5 py-3 text-sm font-semibold text-white transition hover:bg-white/10"
            >
              {C.ctaAdvisor}
            </button>
          </div>
        </Section>
      </div>

      <footer className="mx-auto max-w-[1100px] px-5 py-8">
        <Logo className="h-7" />
        <p className="mt-3 text-[10px] leading-relaxed text-slate-500 sm:text-[11px]">
          {C.footer}
        </p>
      </footer>
    </div>
  )
}
