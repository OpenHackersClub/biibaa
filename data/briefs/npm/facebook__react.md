---
schema: biibaa-brief/1
title: facebook/react
slug: facebook__react
date: '2026-04-28'
run_at: '2026-04-28T17:12:00.099564+00:00'
project:
  purl: pkg:github/facebook/react
  name: facebook/react
  ecosystem: npm
  repo_url: https://github.com/facebook/react
  downloads_weekly: null
  archived: false
score:
  total: 38.8
  impact: 0.0
  effort: 95.0
  confidence: 100
maintainer_activity:
  label: last PR merged 1d ago
  last_pr_merged_at: '2026-04-27T16:48:37+00:00'
benchmarks:
  has: false
  signal: null
opportunities:
  count: 6
  kinds:
  - perf-replacement
  top_kind: perf-replacement
tags:
- npm
- perf
citations:
- type: e18e-replacement
  id: preferred.json#strip-ansi
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2591
- type: e18e-replacement
  id: preferred.json#chalk
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L93
- type: e18e-replacement
  id: preferred.json#string-width
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2585
- type: e18e-replacement
  id: preferred.json#emoji-regex
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L237
- type: e18e-replacement
  id: preferred.json#glob
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L393
- type: e18e-replacement
  id: preferred.json#readable-stream
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2497
---

# facebook/react — 2026-04-28 Improvement Brief

**Repo**: [github.com/facebook/react](https://github.com/facebook/react)

## Top opportunities

### 1. [perf-replacement] strip-ansi → <native>

- **Axis**: perf
- **Replace**: `strip-ansi` → `<native>`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L2591](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2591)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf: drop strip-ansi dep (use native API)`

### 2. [perf-replacement] chalk → picocolors, ansis

- **Axis**: perf
- **Replace**: `chalk` → `picocolors`, `ansis`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L93](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L93)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf(deps): replace chalk with picocolors`

### 3. [perf-replacement] string-width → fast-string-width

- **Axis**: perf
- **Replace**: `string-width` → `fast-string-width`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L2585](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2585)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf(deps): replace string-width with fast-string-width`

### 4. [perf-replacement] emoji-regex → emoji-regex-xs

- **Axis**: perf
- **Replace**: `emoji-regex` → `emoji-regex-xs`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L237](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L237)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf(deps): replace emoji-regex with emoji-regex-xs`

### 5. [perf-replacement] glob → tinyglobby, fdir

- **Axis**: perf
- **Replace**: `glob` → `tinyglobby`, `fdir`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L393](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L393)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf(deps): replace glob with tinyglobby`

### 6. [perf-replacement] readable-stream → <native>

- **Axis**: perf
- **Replace**: `readable-stream` → `<native>`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L2497](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2497)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf: drop readable-stream dep (use native API)`

