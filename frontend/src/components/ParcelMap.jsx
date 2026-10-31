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
    <div className="overflow-hidden rounded-lg border border-slate-300" style={{ height }}>
      <MapContainer center={center} zoom={12} scrollWheelZoom>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ClickHandler onPick={onPick} />
        <Recentre center={pin ? [pin[1], pin[0]] : null} />
        {pin && <Marker position={[pin[1], pin[0]]} />}
        {geometry && (
          <GeoJSON
            key={JSON.stringify(geometry).slice(0, 80)}
            data={geometry}
            style={{ color: '#15803d', weight: 2, fillOpacity: 0.22 }}
          />
        )}
      </MapContainer>
    </div>
  )
}
