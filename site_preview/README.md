# PerimeterFlow — Site Preview (Stage 6 Staging)

Portable staging bundle for the interactive lab page and 4-sheet technical dossier,
built for later transfer into the Hugo site repository at `projects/perimeterflow`
(Cloudflare Pages). No version numbers, no fabricated results.

## Layout

```
site_preview/
  labs/perimeterflow/index.html      interactive dual-lens lab page
  labs/perimeterflow/dossier/        4-sheet Swiss-grid dossier (A4 landscape print)
  assets/css/                        main.css (OKLCH tokens, 1px grids, tabular numerals), dossier.css
  assets/js/app.js                   lens switcher, tabs, worker run, chart, status badge
  assets/worker/lab_worker.ts        worker source, imports web_worker/mfd_worker.ts (parity <= 1e-9)
  assets/worker/lab_worker.js        esbuild bundle (npm run build:worker)
  data/labs/perimeterflow/ensemble.json   artifact copy consumed by the status badge
  _headers                           Zero-Inline CSP for Cloudflare Pages
  tests/site.spec.ts                 Playwright: 0 CSP violations, 0 axe errors, PDF export
```

## Transfer into the Hugo site repo

1. Copy `labs/perimeterflow/` into the Hugo content tree (`content/labs/perimeterflow/`),
   preserving `dossier/` as a sibling page.
2. Copy `assets/` into the site's static or Hugo Pipes pipeline; the worker bundle
   (`lab_worker.js`) can be rebuilt from `lab_worker.ts` + repo-root `web_worker/mfd_worker.ts`
   with `esbuild --bundle --format=esm` and wired through `js.Build` with an SRI hash.
3. Copy `data/labs/perimeterflow/ensemble.json` to `data/labs/perimeterflow/ensemble.json`
   in the site repo so the `{{< result >}}` shortcode and the status badge read it.
4. Append the `_headers` directives to the site's existing `/_headers`.
5. Copy `tests/site.spec.ts` into the site repo's Playwright suite; adjust the PDF output
   path to `downloads/perimeterflow-technical-dossier.pdf` at the site root.

## Commands

```
npm install
npm run build:worker
npm run test:site
```

## Truthfulness

T1-T7 enforced: the page badge renders `Pending Execution (Pre-registered in
ANALYSIS_PLAN.md)` while `meta.status == "planned"`; the ablation table shows only
`planned` cells; the interactive lab is badged `Interactive Mechanics Dry-Run on
Reference Sample` and computes deterministic live values in a Web Worker — it is a
mechanics demonstration, not a research result.
