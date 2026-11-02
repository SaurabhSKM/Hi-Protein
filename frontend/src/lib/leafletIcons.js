import L from 'leaflet'
import iconRetinaUrl from 'leaflet/dist/images/marker-icon-2x.png'
import iconUrl from 'leaflet/dist/images/marker-icon.png'
import shadowUrl from 'leaflet/dist/images/marker-shadow.png'

/* Make Leaflet's default marker visible under a bundler.
 *
 * Leaflet builds the URL for its default marker at runtime by finding where
 * `leaflet.css` was loaded from and appending `images/marker-icon.png`. That works
 * when the stylesheet comes from a CDN, because the images sit next to it on the same
 * server. It silently breaks the moment the CSS is bundled: Vite emits one hashed
 * stylesheet, there is no `images/` directory beside it, the request 404s, and the
 * marker renders as nothing at all. No console error that names the cause, no missing
 * element - just an invisible pin.
 *
 * This regressed exactly that way when the CDN stylesheet was dropped in favour of a
 * bundled one (which was the right call - the CDN broke offline mode, and offline mode
 * exists because the demo runs on conference wifi). The fix is to import the three
 * assets so the bundler emits them with hashed URLs it can resolve, and hand those
 * URLs to Leaflet explicitly.
 *
 * Imported once from main.jsx rather than per component, so a future default Marker
 * anywhere in the app is already correct. Custom `divIcon` markers - the squares and
 * numbered circles on the regional map - were never affected, because their content is
 * inline HTML rather than an image file, which is why the bug only showed on tab 1.
 */
L.Icon.Default.mergeOptions({ iconRetinaUrl, iconUrl, shadowUrl })

// `_getIconUrl` is the method that does the path sniffing described above. Leaving it
// in place means Leaflet can still prefer its own broken guess over the options set
// here, so it is removed outright. This is the documented workaround for bundlers.
delete L.Icon.Default.prototype._getIconUrl

export default L
