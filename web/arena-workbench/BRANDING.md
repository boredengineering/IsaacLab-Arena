# Cybernetic-Physics preview branding

The workbench preview is for **Cybernetic-Physics**. Keep the company identity distinct from the underlying Isaac Lab-Arena packages and research-environment names. Preview v3 applies this branding; v1/v2 remain unchanged historical artifacts.

## Observed sources

Inspected the rendered homepage, computed styles, font faces and header wordmark on 2026-09-14:

- Website: https://cyberneticphysics.com/
- Stylesheet: https://cyberneticphysics.com/_next/static/chunks/07uui9jhjx9cv.css
- Exact downloaded font URLs, hashes, retrieval time and wordmark provenance: `src/preview/brand/sources.json`.

The site's SVG wordmark spells Cybernetic Physics on two lines. The preview uses its original vector paths, with the requested company spelling in the accessible label and document title. `wordmark.json` contains only coordinates and a viewBox; React renders ordinary SVG paths, not raw HTML or remote markup.

## Website typography and palette

| Role | Observed choice |
| --- | --- |
| Display headings | Tomorrow, normal 400, uppercase |
| Body | IBM Plex Sans, normal 400 |
| Technical labels | Kode Mono, variable 400–700 |
| Page | `#000000` |
| Surface / strong surface | `#0d0d0d` / `#222222` |
| Text / muted | `#ffffff` / `#acacac` |
| Hairline | `#393939` |
| Green accent | `#4f8d7d` |
| Teal / darker teal | `#4e8d94` / `#30666b` |

Use these as a restrained technical interface: neutral surfaces, fine borders, square panels, compact monospace labels and Tomorrow headings. Do not copy the website's marketing text, animated wall, statistics or navigation into the research workflow.

## Workbench adaptations

- Light mode is a **workbench adaptation**, not an observed official website theme. White/near-white surfaces use dark neutral text and the site's darker teal `#30666b` for readable accents.
- Dense form text remains mixed case. Headings are scaled for a dashboard rather than a marketing hero. Status warning/error colors remain semantic UI colors, not claimed company brand tokens.
- Input boundaries use `#777777`; decorative panel borders remain subtler. Primary hover states retain a contrasting fill/text pair.
- Chromium measured primary-button hover text contrast at approximately 5.44:1 in dark mode and 6.48:1 in light mode. This is a focused check, not a complete accessibility certification.
- Global account/theme bar, collapsible left navigation and source-bound local workflow state are unchanged. Authentication and research execution remain disconnected.

## Offline font distribution

The three Latin WOFF2 subsets are vendored from the website, not fetched by the preview. Unsupported glyphs fall back to platform fonts. Vite embeds these files as data URLs; the preview CSP allows data fonts while keeping connections, workers and form submission disabled. Browser acceptance waits for `document.fonts.ready` and checks that each actual face loaded.

The font families use the SIL Open Font License 1.1. Original notices are retained in `src/preview/brand/*-OFL.txt`, sourced from the corresponding Google Fonts `ofl/tomorrow`, `ofl/ibmplexsans` and `ofl/kodemono` directories. `THIRD_PARTY_NOTICES.txt` is also embedded in the offline HTML and accessible through **Typography licenses** in the footer. Font licensing does not grant rights to the company wordmark.

Source fingerprinting includes the nested brand assets. Do not fetch assets or install packages during the isolated build, and do not overwrite older versioned HTML when changing branding.
