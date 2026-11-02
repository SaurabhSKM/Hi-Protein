/* Colour for the land-change view.
 *
 * The categorical order below was run through the palette validator rather than
 * chosen by eye, and it is the order the checks were run in, so it must not be
 * reshuffled: the adjacent-pair separation is what passed. Reported for the light
 * chart surface, which is the only surface this app has:
 *
 *   lightness band       PASS  all 5 inside L 0.43-0.77
 *   chroma floor         PASS  all 5 >= 0.1, none reads grey
 *   CVD separation       PASS  worst adjacent pair dE 21.0 (protan), 12.2 (tritan)
 *   normal-vision floor  PASS  worst adjacent pair dE 24.8
 *   contrast vs surface  PASS  all 5 >= 3:1
 *
 * Across ALL pairs rather than adjacent ones, orange and green fall to dE 6.9 under
 * deuteranopia. That is why every multi-series chart here carries a direct label at
 * the end of each line in addition to the legend: identity is never colour alone.
 * Crop colour follows the CROP, not its rank in the current sort, so filtering the
 * table never repaints a series.
 */
export const CROP_COLOUR = {
  green_lentil: '#16a34a',
  chickpea: '#0369a1',
  field_pea: '#ea580c',
  fava_bean: '#7c3aed',
  soybean: '#be123c',
}

export const CROP_LABEL = {
  green_lentil: 'Green lentil',
  chickpea: 'Chickpea',
  field_pea: 'Field pea',
  fava_bean: 'Fava bean',
  soybean: 'Soybean',
}

/* Which outlet the crop mostly goes to. This is the division the data turns on -
 * the two food pulses multiplied while the two feed pulses halved - so the charts
 * are faceted on it rather than showing five lines of two different stories. */
export const CROP_GROUP_LABEL = {
  food_pulse: 'Human-food pulses',
  feed_pulse: 'Animal-feed pulses',
  soy: 'Soy (crushed for meal and oil)',
}

/* Sequential ramp for a magnitude (a share). ColorBrewer Greens, single hue,
 * verified strictly light-to-dark by relative luminance:
 * 0.910 > 0.692 > 0.445 > 0.275 > 0.111. */
export const SEQ_GREENS = ['#edf8e9', '#bae4b3', '#74c476', '#31a354', '#006d2c']

/* Diverging ramp for a signed change. ColorBrewer PuOr: purple and orange poles,
 * NOT red and green, because a red-green diverging scale is the one scheme
 * deuteranopia cannot read. Verified to rise monotonically to the neutral midpoint
 * and fall monotonically away from it, with the midpoint the lightest step. */
export const DIV_PUOR = [
  '#b35806', '#f1a340', '#fee0b6', '#f7f7f7', '#d8daeb', '#998ec3', '#542788',
]

/* Ink. Values and labels wear text tokens, never a series colour. */
export const INK = {
  primary: '#0f172a',
  secondary: '#475569',
  muted: '#64748b',
  grid: '#e2e8f0',
}

/** Step index for a value on a ramp whose domain is [0, max]. */
export function seqStep(value, max, ramp = SEQ_GREENS) {
  if (value == null || !Number.isFinite(value) || max <= 0) return null
  const t = Math.min(Math.max(value / max, 0), 1)
  return ramp[Math.min(ramp.length - 1, Math.floor(t * ramp.length))]
}

/** Step for a signed value on a symmetric diverging ramp spanning [-bound, +bound]. */
export function divStep(value, bound, ramp = DIV_PUOR) {
  if (value == null || !Number.isFinite(value) || bound <= 0) return null
  const mid = (ramp.length - 1) / 2
  const t = Math.min(Math.max(value / bound, -1), 1)
  return ramp[Math.round(mid + t * mid)]
}

export const fmtHa = (v) =>
  v == null ? '-' : new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 }).format(v)

export const fmtPct = (v, d = 2) => (v == null ? '-' : `${v.toFixed(d)}%`)
