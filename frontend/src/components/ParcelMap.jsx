import { useEffect } from 'react'
import { GeoJSON, MapContainer, Marker, TileLayer, useMap, useMapEvents } from 'react-leaflet'

function ClickHandler({ onPick }) {
  useMapEvents({ click: (e) => onPick(e.latlng.lng, e.latlng.lat) })
  return null
}

function Recentre({ center }) {
  const map = useMap()
  useEffect(() => {
    if (center) map.setView(center, Math.max(map.getZoom(), 13))
  }, [center, map])
  return null
}

export default function ParcelMap({ center, geometry, pin, onPick, height = 380 }) {
  return (
    <div
      className="overflow-hidden rounded-lg border border-slate-300"
      // minHeight keeps the map usable on a phone without letting it dominate the
      // screen; the explicit height still governs from tablet upward.
      style={{ height, minHeight: 200 }}
    >
      <MapContainer center={center} zoom={12} scrollWheelZoom>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ClickHandler onPick={onPick} />
        <Recentre center={pin ? [pin[1], pin[0]] : null} />
        {/* Both overlays are non-interactive on purpose. Leaflet stops propagation on
            interactive vector layers and markers, so an outlined parcel swallowed every
            click that landed on it - once a field was highlighted, clicking it or its
            immediate neighbour did nothing at all and the picker looked broken. Neither
            overlay has a click behaviour of its own, so there is nothing to lose. */}
        {pin && <Marker position={[pin[1], pin[0]]} interactive={false} />}
        {geometry && (
          <GeoJSON
            // Keyed on the whole geometry: react-leaflet does not diff `data`, so the
            // layer is only redrawn when this key changes. Two adjacent parcels can
            // share a long leading coordinate prefix, and truncating the key to 80
            // characters was enough for the outline to stay on the previous field.
            key={JSON.stringify(geometry)}
            data={geometry}
            interactive={false}
            style={{ color: '#15803d', weight: 2, fillOpacity: 0.22 }}
          />
        )}
      </MapContainer>
    </div>
  )
}
