import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
// Bundled rather than pulled from a CDN: offline mode is a hard requirement here
// and an unstyled Leaflet map is the most visible possible way to fail it.
import 'leaflet/dist/leaflet.css'
// Must follow the stylesheet: bundling the CSS breaks Leaflet's runtime guess at
// where its default marker image lives, so the icon URLs are set explicitly.
import './lib/leafletIcons.js'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
