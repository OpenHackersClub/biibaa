---
schema: biibaa-brief/1
title: microsoft/vscode
slug: microsoft__vscode
date: '2026-04-28'
run_at: '2026-04-28T17:12:00.099564+00:00'
project:
  purl: pkg:github/microsoft/vscode
  name: microsoft/vscode
  ecosystem: npm
  repo_url: https://github.com/microsoft/vscode
  downloads_weekly: null
  archived: false
score:
  total: 38.8
  impact: 0.0
  effort: 95.0
  confidence: 100
maintainer_activity:
  label: last PR merged 0d ago
  last_pr_merged_at: '2026-04-28T15:52:37+00:00'
benchmarks:
  has: false
  signal: null
opportunities:
  count: 3
  kinds:
  - perf-replacement
  top_kind: perf-replacement
tags:
- npm
- perf
citations:
- type: e18e-replacement
  id: preferred.json#glob
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L393
- type: dependency-location
  id: package.json#L204
  url: https://github.com/microsoft/vscode/blob/81e19a693faea10313612a2f5e31f4e61b0f7f98/package.json#L204
- type: e18e-replacement
  id: preferred.json#rimraf
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2521
- type: dependency-location
  id: package.json#L239
  url: https://github.com/microsoft/vscode/blob/81e19a693faea10313612a2f5e31f4e61b0f7f98/package.json#L239
- type: e18e-replacement
  id: preferred.json#minimist
  url: https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2325
- type: dependency-location
  id: package.json#L135
  url: https://github.com/microsoft/vscode/blob/81e19a693faea10313612a2f5e31f4e61b0f7f98/package.json#L135
---

# microsoft/vscode — 2026-04-28 Improvement Brief

**Repo**: [github.com/microsoft/vscode](https://github.com/microsoft/vscode)

## Top opportunities

### 1. [perf-replacement] glob → tinyglobby, fdir

- **Axis**: perf
- **Replace**: `glob` → `tinyglobby`, `fdir`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L393](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L393)
- **Found in**: [package.json#L204](https://github.com/microsoft/vscode/blob/81e19a693faea10313612a2f5e31f4e61b0f7f98/package.json#L204)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf(deps): replace glob with tinyglobby`

### 2. [perf-replacement] rimraf → premove

- **Axis**: perf
- **Replace**: `rimraf` → `premove`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L2521](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2521)
- **Found in**: [package.json#L239](https://github.com/microsoft/vscode/blob/81e19a693faea10313612a2f5e31f4e61b0f7f98/package.json#L239)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf(deps): replace rimraf with premove`

### 3. [perf-replacement] minimist → mri

- **Axis**: perf
- **Replace**: `minimist` → `mri`
- **Effort band**: drop-in
- **Evidence**: e18e [module-replacements](https://github.com/e18e/module-replacements) · manifest [preferred.json#L2325](https://github.com/e18e/module-replacements/blob/main/manifests/preferred.json#L2325)
- **Found in**: [package.json#L135](https://github.com/microsoft/vscode/blob/81e19a693faea10313612a2f5e31f4e61b0f7f98/package.json#L135)
- **Effort score**: 95 / 100 (high = easy)
- **Impact score**: 0 / 100
- **Suggested PR**: `perf(deps): replace minimist with mri`

