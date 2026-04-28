---
schema: biibaa-brief/1
title: node-tesseract-ocr
slug: node-tesseract-ocr
date: '2026-04-28'
run_at: '2026-04-28T17:12:00.099564+00:00'
project:
  purl: pkg:npm/node-tesseract-ocr
  name: node-tesseract-ocr
  ecosystem: npm
  repo_url: https://github.com/zapolnoch/node-tesseract-ocr
  downloads_weekly: 50581
  archived: false
score:
  total: 29.2
  impact: 40.3
  effort: 20.0
  confidence: 0
maintainer_activity:
  label: last PR merged 1829d ago
  last_pr_merged_at: '2021-04-25T00:47:15+00:00'
opportunities:
  count: 1
  kinds:
  - vulnerability-fix
  top_kind: vulnerability-fix
tags:
- npm
- unpatched
- vuln
citations:
- type: advisory
  id: GHSA-8j44-735h-w4w2
  url: https://github.com/advisories/GHSA-8j44-735h-w4w2
---

# node-tesseract-ocr — 2026-04-28 Improvement Brief

**Repo**: [github.com/zapolnoch/node-tesseract-ocr](https://github.com/zapolnoch/node-tesseract-ocr)

## Top opportunities

### 1. [vulnerability-fix] GHSA-8j44-735h-w4w2

- **Severity**: critical · CVSS 9.8
- **Summary**: node-tesseract-ocr is vulnerable to OS Command Injection through unsanitized recognize() function parameter
- **Affected**: `<= 2.2.1`
- **Fix**: _no upstream patch — contribute one_ at [https://github.com/zapolnoch/node-tesseract-ocr](https://github.com/zapolnoch/node-tesseract-ocr)
- **Evidence**: [GHSA-8j44-735h-w4w2](https://github.com/advisories/GHSA-8j44-735h-w4w2)
- **Effort score**: 20 / 100 (high = easy)
- **Impact score**: 40 / 100
- **Suggested PR**: `fix: address GHSA-8j44-735h-w4w2 in node-tesseract-ocr`

