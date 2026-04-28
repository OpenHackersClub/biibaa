---
schema: biibaa-brief/1
title: vercel/next.js
slug: vercel__next.js
date: '2026-04-28'
run_at: '2026-04-28T17:12:00.099564+00:00'
project:
  purl: pkg:github/vercel/next.js
  name: vercel/next.js
  ecosystem: npm
  repo_url: https://github.com/vercel/next.js
  downloads_weekly: null
  archived: false
score:
  total: 38.8
  impact: 0.0
  effort: 95.0
  confidence: 100
maintainer_activity:
  label: last PR merged 0d ago
  last_pr_merged_at: '2026-04-28T16:40:47+00:00'
benchmarks:
  has: true
  signal: script:bench:render-pipeline
opportunities:
  count: 6
  kinds:
  - dep-replacement
  - perf-replacement
  top_kind: perf-replacement
tags:
- bench
- bloat
- npm
- perf
citations:
- type: e18e-replacement
  id: preferred.json#strip-ansi
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2591
- type: dependency-location
  id: package.json
  url: https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/package.json
- type: dependency-location
  id: packages/next/package.json
  url: https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/packages/next/package.json
- type: dependency-location
  id: packages/next-codemod/package.json
  url: https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/packages/next-codemod/package.json
- type: e18e-replacement
  id: preferred.json#glob
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L393
- type: e18e-replacement
  id: native.json#escape-string-regexp
  url: https://github.com/e18e/module-replacements/blob/main/manifests/native.json#L2055
- type: e18e-replacement
  id: preferred.json#fs-extra
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L363
- type: dependency-location
  id: bench/rendering/package.json
  url: https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/bench/rendering/package.json
- type: e18e-replacement
  id: preferred.json#lodash
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L495
- type: e18e-replacement
  id: preferred.json#rimraf
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2521
- type: dependency-location
  id: bench/module-cost/package.json
  url: https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/bench/module-cost/package.json
- type: dependency-location
  id: bench/nested-deps/package.json
  url: https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/bench/nested-deps/package.json
- type: dependency-location
  id: bench/nested-deps-app-router/package.json
  url: https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/bench/nested-deps-app-router/package.json
- type: dependency-location
  id: bench/nested-deps-app-router-many-pages/package.json
  url: https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/bench/nested-deps-app-router-many-pages/package.json
- type: dependency-location
  id: bench/recursive-delete/package.json
  url: https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/bench/recursive-delete/package.json
---

# vercel/next.js — 2026-04-28 Improvement Brief

**Repo**: [github.com/vercel/next.js](https://github.com/vercel/next.js)

## Top opportunities

### 1. [perf-replacement] strip-ansi → <native>

- **Axis**: perf
- **Replace**: `strip-ansi` → `<native>`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L2591](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2591)
- **Found in**: [package.json](https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/package.json), [packages/next/package.json](https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/packages/next/package.json), [packages/next-codemod/package.json](https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/packages/next-codemod/package.json)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf: drop strip-ansi dep (use native API)`

### 2. [perf-replacement] glob → tinyglobby, fdir

- **Axis**: perf
- **Replace**: `glob` → `tinyglobby`, `fdir`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L393](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L393)
- **Found in**: [package.json](https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/package.json), [packages/next/package.json](https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/packages/next/package.json)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf(deps): replace glob with tinyglobby`

### 3. [dep-replacement] escape-string-regexp → <native>

- **Axis**: bloat
- **Replace**: `escape-string-regexp` → `<native>`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [native.json#L2055](https://github.com/e18e/module-replacements/blob/main/manifests/native.json#L2055)
- **Found in**: [package.json](https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/package.json)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `deps: drop escape-string-regexp dep (use native API)`

### 4. [perf-replacement] fs-extra → <native>

- **Axis**: perf
- **Replace**: `fs-extra` → `<native>`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L363](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L363)
- **Found in**: [package.json](https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/package.json), [bench/rendering/package.json](https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/bench/rendering/package.json)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf: drop fs-extra dep (use native API)`

### 5. [perf-replacement] lodash → es-toolkit

- **Axis**: perf
- **Replace**: `lodash` → `es-toolkit`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L495](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L495)
- **Found in**: [package.json](https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/package.json)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf(deps): replace lodash with es-toolkit`

### 6. [perf-replacement] rimraf → premove

- **Axis**: perf
- **Replace**: `rimraf` → `premove`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L2521](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2521)
- **Found in**: [bench/module-cost/package.json](https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/bench/module-cost/package.json), [bench/nested-deps/package.json](https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/bench/nested-deps/package.json), [bench/nested-deps-app-router/package.json](https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/bench/nested-deps-app-router/package.json), [bench/nested-deps-app-router-many-pages/package.json](https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/bench/nested-deps-app-router-many-pages/package.json), [bench/recursive-delete/package.json](https://github.com/vercel/next.js/blob/521ae9653e7c45ee1690323c86252b82d5740ffa/bench/recursive-delete/package.json)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf(deps): replace rimraf with premove`

