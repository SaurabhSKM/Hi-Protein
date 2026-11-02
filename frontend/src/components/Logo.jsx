/* The brand logo, in the shapes the pages actually need.

   Assets live in frontend/public/ and are generated from the deck artwork by
   scripts/make_logo_assets.py - see that file for why there are separate light and
   dark cuts rather than one image with its background keyed out.

   Paths go through BASE_URL because Vite is configured with `base: './'`, so the
   bundle has to work when it is served from a workspace proxy's subpath as well as
   from the domain root. */

const asset = (file) => `${import.meta.env.BASE_URL}${file}`

const NAME = 'Hi! Protein'

/** Mark beside the wordmark. The default, and the only cut that stays legible in a
    page header: the stacked artwork at 36 px leaves the wordmark about 8 px tall. */
export function Logo({ onDark = false, className = 'h-9' }) {
  return (
    <img
      src={asset(onDark ? 'logo-horizontal-ondark.png' : 'logo-horizontal.png')}
      alt={NAME}
      className={`w-auto ${className}`}
      /* Intrinsic size, so nothing reflows once the image lands. */
      width={683}
      height={160}
    />
  )
}

/** Mark above the wordmark. For the places with room to let it breathe. */
export function LogoStacked({ onDark = false, className = 'h-24' }) {
  return (
    <img
      src={asset(onDark ? 'logo-lockup-ondark.png' : 'logo-lockup.png')}
      alt={NAME}
      className={`w-auto ${className}`}
      width={878}
      height={528}
    />
  )
}

/** Just the symbol, square. Use where a lockup would be too wide to read. */
export function LogoMark({ onDark = false, className = 'h-7 w-7', alt = '' }) {
  return (
    <img
      src={asset(onDark ? 'logo-mark-ondark.png' : 'logo-mark.png')}
      alt={alt}
      aria-hidden={alt ? undefined : 'true'}
      className={className}
      width={256}
      height={256}
    />
  )
}

/** Oversized flat silhouette for background texture. Decorative only. */
export function LogoWatermark({ className = '' }) {
  return (
    <img
      src={asset('logo-mark-white.png')}
      alt=""
      aria-hidden="true"
      className={`pointer-events-none select-none ${className}`}
      width={512}
      height={512}
    />
  )
}
