import { useMemo } from 'react'
import { GeoJSON, MapContainer, TileLayer } from 'react-leaflet'
import {
  DIV_PUOR, INK, SEQ_GREENS, divStep, fmtHa, seqStep,
} from '../lib/landPalette.js'

/* Department choropleth: where the land actually moved.
 *
 * The one decision that makes this map honest is the colour DOMAIN. Rescaling the
 * ramp to each year's own maximum would hold the picture roughly constant as the
 * slider moves, because the ramp would grow with the data - the map would show the
 * geography of each year and hide the growth entirely. So the share domain is fixed
 * across every year in the series, computed once from the whole panel. Dragging the
 * slider then shows colour spreading, which is the finding.
 *
 * The change view is a signed quantity, so it gets a diverging ramp with a neutral
 * midpoint and a symmetric domain - the same number of hectares gained and lost read
 * as the same depth of colour in opposite directions.
 */

function Legend({ mode, max, bound, unit }) {
  const ramp = mode === 'change' ? DIV_PUOR : SEQ_GREENS
  const labels =
    mode === 'change'
      ? [`-${bound.toFixed(1)}`, '0', `+${bound.toFixed(1)}`]
      : ['0', (max / 2).toFixed(mode === 'share' ? 2 : 0), max.toFixed(mode === 'share' ? 2 : 0)]
  return (
    <div className="flex items-center gap-2">
      <div className="flex">
        {ramp.map((c) => (
          <div key={c} style={{ background: c }} className="h-3 w-5 border border-white" />
        ))}
      </div>
      <div className="flex w-full justify-between text-[10px] text-slate-500">
        {labels.map((l, i) => <span key={i}>{l}</span>)}
      </div>
      <span className="whitespace-nowrap text-[10px] text-slate-500">{unit}</span>
    </div>
  )
}

export default function AdoptionMap({ geometry, deptData, year, mode }) {
  const { features, max, bound, byCode } = useMemo(() => {
    if (!geometry || !deptData) return { features: null, max: 0, bound: 0, byCode: {} }
    const byCode = Object.fromEntries(deptData.departments.map((d) => [d.dept_code, d]))

    // Fixed domains, computed over every year and department in the panel.
    let max = 0
    let bound = 0
    for (const d of deptData.departments) {
      for (const v of Object.values(d.share_pct_by_year)) {
        if (v != null && v > max) max = v
      }
      const [first, last] = deptData.compare_years
      const a = d.share_pct_by_year[String(first)]
      const b = d.share_pct_by_year[String(last)]
      if (a != null && b != null) bound = Math.max(bound, Math.abs(b - a))
    }

    const features = {
      type: 'FeatureCollection',
      features: Object.entries(geometry)
        .filter(([code]) => byCode[code])
        .map(([code, info]) => ({
          type: 'Feature',
          id: code,
          properties: { code, name: info.name },
          geometry: info.geometry,
        })),
    }
    return { features, max, bound, byCode }
  }, [geometry, deptData])

  if (!features) return <div className="text-sm text-slate-500">Loading map...</div>

  const [first, last] = deptData.compare_years

  const valueFor = (code) => {
    const d = byCode[code]
    if (!d) return null
    if (mode === 'change') {
      const a = d.share_pct_by_year[String(first)]
      const b = d.share_pct_by_year[String(last)]
      return a == null || b == null ? null : b - a
    }
    return d.share_pct_by_year[String(year)] ?? null
  }

  const style = (feature) => {
    const v = valueFor(feature.properties.code)
    const fill =
      v == null
        ? '#f1f5f9'
        : mode === 'change'
          ? divStep(v, bound) ?? '#f1f5f9'
          : seqStep(v, max) ?? '#f1f5f9'
    return {
      fillColor: fill,
      // A 1px surface-coloured stroke keeps neighbouring departments separated
      // without the border reading as data.
      color: '#ffffff',
      weight: 1,
      fillOpacity: 0.9,
    }
  }

  const onEach = (feature, layer) => {
    const code = feature.properties.code
    const d = byCode[code]
    if (!d) return
    const a = d.area_ha_by_year[String(first)]
    const b = d.area_ha_by_year[String(last)]
    const sel = d.area_ha_by_year[String(year)]
    const shareSel = d.share_pct_by_year[String(year)]
    layer.bindTooltip(
      `<div style="font-size:12px">
         <b>${d.dept_name} (${code})</b><br/>
         ${year}: ${fmtHa(sel)} ha${shareSel != null ? ` &middot; ${shareSel.toFixed(2)}% of mapped area` : ''}<br/>
         ${first}: ${fmtHa(a)} ha &rarr; ${last}: ${fmtHa(b)} ha<br/>
         ${d.peak_year ? `peak ${d.peak_year}: ${fmtHa(d.peak_area_ha)} ha<br/>` : ''}
         ${d.arrived_during_series ? '<i>arrived during the series (0 ha in ' + first + ')</i>' : ''}
       </div>`,
      { sticky: true },
    )
  }

  return (
    <div>
      <div className="h-[460px] overflow-hidden rounded border border-slate-300">
        <MapContainer
          center={[46.7, 2.4]}
          zoom={5}
          scrollWheelZoom={false}
          style={{ height: '100%', width: '100%', background: '#f8fafc' }}
        >
          <TileLayer
            url="https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png"
            attribution="&copy; OpenStreetMap, &copy; CARTO"
          />
          {/* Remounting on every control change is what re-runs `style`. 94 polygons
              is cheap enough that this is simpler and more reliable than imperatively
              calling setStyle on each layer. */}
          <GeoJSON
            key={`${deptData.crop}-${mode}-${year}`}
            data={features}
            style={style}
            onEachFeature={onEach}
          />
        </MapContainer>
      </div>
      <div className="mt-2">
        <Legend
          mode={mode}
          max={max}
          bound={bound}
          unit={
            mode === 'change'
              ? `change in share, percentage points, ${first} to ${last}`
              : `share of mapped COP area, %, fixed scale across all years`
          }
        />
        <div className="mt-1 text-[11px] text-slate-500">
          Grey means the department publishes no area for this crop. Hover a department
          for its hectares.
        </div>
      </div>
    </div>
  )
}
