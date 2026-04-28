# biibaa site

Static site that renders the briefs from `../data/briefs/` for triage. Built with [Astro](https://astro.build) + Tailwind v4, deployed to Cloudflare Pages.

## Develop

```sh
cd site
npm install
npm run dev
```

Open http://localhost:4321. The dev server reads briefs straight from `../data/briefs/` and live-reloads when they change.

## Build

```sh
cd site
npm run build      # outputs static HTML/CSS/JS to site/dist/
npm run preview    # serve the built bundle locally
```

The output in `site/dist/` is fully static — no Node/Python runtime required to host it.

## Deploy (Cloudflare Pages)

CI handles deploys via `.github/workflows/deploy-site.yml` on every push to `main`. To wire it up the first time:

1. **Create a Pages project** at https://dash.cloudflare.com/?to=/:account/pages — pick "Direct upload", name it (e.g. `biibaa`), and skip the framework preset (we'll deploy from CI).
2. **Create an API token** at https://dash.cloudflare.com/profile/api-tokens with the `Cloudflare Pages — Edit` template scoped to your account.
3. Add two GitHub repo secrets:
   - `CLOUDFLARE_API_TOKEN` — the token from step 2.
   - `CLOUDFLARE_ACCOUNT_ID` — visible on the Cloudflare dashboard sidebar.
4. Push to `main`. The workflow builds `site/` and uploads `dist/` to the Pages project named `biibaa` (override via the `projectName` input to the action).

## Layout

- `src/content.config.ts` — content collection schema, mirrors `briefs/render.py:_build_frontmatter` (`biibaa-brief/1`).
- `src/pages/index.astro` — triage table. Multi-column sort + filters via Alpine.js islands.
- `src/pages/briefs/[...id].astro` — per-brief page, renders the brief markdown alongside score/project/maintainer cards.
- `src/layouts/Base.astro` — shared shell, fonts, header.
- `src/styles/global.css` — Tailwind v4 + theme tokens (matches the NiceGUI dev tool).
