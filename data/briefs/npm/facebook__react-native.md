---
schema: biibaa-brief/1
title: facebook/react-native
slug: facebook__react-native
date: '2026-04-28'
run_at: '2026-04-28T17:12:00.099564+00:00'
project:
  purl: pkg:github/facebook/react-native
  name: facebook/react-native
  ecosystem: npm
  repo_url: https://github.com/facebook/react-native
  downloads_weekly: null
  archived: false
score:
  total: 38.8
  impact: 0.0
  effort: 95.0
  confidence: 100
maintainer_activity:
  label: last PR merged 1d ago
  last_pr_merged_at: '2026-04-27T09:50:07+00:00'
benchmarks:
  has: true
  signal: devDep:tinybench
opportunities:
  count: 2
  kinds:
  - perf-replacement
  top_kind: perf-replacement
tags:
- bench
- npm
- perf
citations:
- type: e18e-replacement
  id: preferred.json#mkdirp
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2331
- type: e18e-replacement
  id: preferred.json#cosmiconfig
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L153
---

# facebook/react-native — 2026-04-28 Improvement Brief

**Repo**: [github.com/facebook/react-native](https://github.com/facebook/react-native)

## Top opportunities

### 1. [perf-replacement] mkdirp → <native>

- **Axis**: perf
- **Replace**: `mkdirp` → `<native>`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L2331](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2331)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf: drop mkdirp dep (use native API)`

### 2. [perf-replacement] cosmiconfig → lilconfig

- **Axis**: perf
- **Replace**: `cosmiconfig` → `lilconfig`
- **Effort band**: minor-migration
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L153](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L153)
- **Effort score**: 70 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf(deps): replace cosmiconfig with lilconfig`

