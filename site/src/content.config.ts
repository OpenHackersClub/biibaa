import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

// Mirror of the biibaa-brief/1 frontmatter shape (see briefs/render.py).
// Loose where the upstream is loose (downloads_weekly may be null, benchmarks
// may be omitted) but precise on the fields the index page sorts/filters on.
const briefs = defineCollection({
  loader: glob({
    pattern: "**/*.md",
    // data/briefs lives in the repo root; site/ is a sibling, hence ../../.
    base: "../data/briefs",
  }),
  schema: z.object({
    schema: z.literal("biibaa-brief/1"),
    title: z.string(),
    slug: z.string(),
    date: z.string(),
    run_at: z.string(),
    project: z.object({
      purl: z.string(),
      name: z.string(),
      ecosystem: z.string(),
      repo_url: z.string().nullable(),
      downloads_weekly: z.number().nullable(),
      archived: z.boolean(),
    }),
    score: z.object({
      total: z.number(),
      impact: z.number(),
      effort: z.number(),
      confidence: z.number(),
    }),
    maintainer_activity: z
      .object({
        label: z.string(),
        last_pr_merged_at: z.string().nullable(),
      })
      .optional(),
    benchmarks: z
      .object({
        has: z.boolean(),
        signal: z.string().nullable(),
      })
      .optional(),
    opportunities: z.object({
      count: z.number(),
      kinds: z.array(z.string()),
      top_kind: z.string().nullable(),
    }),
    tags: z.array(z.string()).default([]),
    citations: z
      .array(
        z.object({
          type: z.string(),
          id: z.string(),
          url: z.string(),
        }),
      )
      .default([]),
  }),
});

export const collections = { briefs };
