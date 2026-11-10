# Third-party files

These are copied in so the kiosk needs no CDN.

| File | Project | Version | License |
|---|---|---|---|
| `maplibre-gl.mjs`, `maplibre-gl-worker.mjs`, `maplibre-gl.css` | [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js) | 6.17.0 | BSD-3-Clause, `LICENSE-maplibre-gl.txt` |
| `pmtiles.js` | [PMTiles](https://github.com/protomaps/PMTiles) | 4.5.0 | BSD-3-Clause, `LICENSE-pmtiles.txt` |
| `../fonts/Noto Sans */*.pbf` | [Protomaps basemap fonts](https://github.com/protomaps/basemaps-assets) (Noto Sans) | 11/2026 | OFL-1.1, `../fonts/LICENSE-noto-sans.txt` |
| `../fonts/ui/inter-latin-wght-normal.woff2` | [Inter](https://github.com/rsms/inter) via Fontsource | 5.3.0 | OFL-1.1, `../fonts/ui/LICENSE-inter.txt` |

To update MapLibre or PMTiles, copy the same files from the new npm package's `dist/` folder.
