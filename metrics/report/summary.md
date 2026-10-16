# Summary: How robust is the workflow agent to rewording?

We tested whether an LLM agent that builds geospatial workflows from a catalog of OGC processes still builds the right workflow when the same request is worded differently. This summary covers the first test case, a single request about walking distance to green spaces in Münster.

## At a glance

- **The agent usually gets it right.** For the original request it builds the correct workflow in **84%** of runs.
- **Rewording that keeps the meaning makes no detectable difference.** Paraphrases that keep the full meaning reach **81.5%**, statistically indistinguishable from the original.
- **One kind of rewording does change the result.** Turning "large enough for recreation" into "suitable / adequate / sufficient for recreation" silently drops the size requirement, and the agent then never filters by size (**0 of 7** correct).
- **The agent is not fully deterministic.** Identical requests give different workflows, more in the parameters (ring distances, minimum area) than in the structure.
- **Two capabilities are consistently missing:** no process can draw a map, and no process can compute *walking* distance around many parks. The agent says so honestly in its replies.
- **It is cheap:** about **1 cent per request**.

## The test

The original request (the *seed*):

> Identify all areas in Münster that are within a 300-meter walking distance of a public park or forest large enough for recreation. Output a visualization that highlights these well-served areas and displays the walking distances from the green spaces in incremental intervals up to the 300-meter limit.

**The correct workflow** is a chain of four steps:

```
city boundary → green areas (parks, forests) → minimum-area filter → distance rings (up to 300 m)
```

We score a workflow two ways, looking only at its structure (not at parameter values):

| Score | Counts as correct when… |
|---|---|
| **Lenient** | the four steps are present and connected in that order; extra steps are allowed |
| **Strict** | the workflow is exactly those four steps, nothing more |

Each rate comes with a **95% range**, the span its true value plausibly falls in given the sample size (Wilson interval).

The lenient score is the main measure. The strict score is low throughout (about 26%) because the agent often adds a redundant extra step, a plain 300 m buffer, next to the distance rings. This is harmless, and it happens equally with and without rewording.

**The paraphrases.** A local LLM rewrote the seed in six linguistic categories, from small word-form changes to restructured sentences, aiming for wording that differs a lot while the intent stays the same. Every candidate passed automated checks and a manual review. **162** paraphrases were kept.

**The baseline.** The agent varies even when given the identical request, so the seed was run **50 times**. This measures the agent's own run-to-run variation, which every paraphrase result has to be compared against.

## Results

### The original request

| | Correct | 95% range |
|---|---|---|
| Lenient | 42 / 50 = **84%** | 71–92% |
| Strict | 13 / 50 = 26% | 16–40% |

- The rate was stable over the 50 runs, with no drift.
- The 8 failures: in 6 the size filter was left out or wired in the wrong place, and in 2 the agent wrongly decided that the distance-ring process did not fit.
- **Parameters vary more than structure.** The minimum park size ranged from unset to 10,000 m² (most often 10,000 m²). The rings were usually 75 / 150 / 225 / 300 m, sometimes 50 m steps.

### The paraphrases

| | Correct (lenient) | 95% range | Has the size filter | 95% range |
|---|---|---|---|---|
| Seed (50 runs) | **84%** | 71–92% | 92% | 81–97% |
| Paraphrases that keep the meaning (162) | **81.5%** | 75–87% | 93% | 88–96% |
| Paraphrases that drop the size requirement (9) | 0% | 0–30% | 0% | 0–30% |

The 162 paraphrases perform like the seed, and they include the size filter just as often.

By category:

| Category | What changes | Correct (lenient) | 95% range |
|---|---|---|---|
| Syntactic | sentence structure | 100% (14) | 78–100% |
| Other | e.g. reordering, added purpose clauses | 96% (27) | 82–99% |
| Discourse | how the request is framed | 87% (45) | 74–94% |
| Lexico-syntactic | words and structure together | 80% (35) | 64–90% |
| Morphological | word forms | 67% (12) | 39–86% |
| Lexical | word choice | 59% (29) | 41–74% |

Lexical paraphrases are somewhat lower, but the difference is not statistically significant once the number of categories compared is taken into account. The wide ranges show how small some of the categories are (12 to 14 paraphrases).

### The wording that breaks it

"Large enough for recreation" asks for a **size** threshold. "Adequate / suitable / sufficient for recreation" reads as a **quality**, so the agent never looks for an area filter:

| Wording | Paraphrases | Size filter present | Correct |
|---|---|---|---|
| keeps "large enough" (or similar) | 162 | 93% [88–96%] | 81.5% [75–87%] |
| "adequate / suitable / sufficient for recreation" | 7 | 0% [0–35%] | 0% [0–35%] |

This is the clearest case in the study of a paraphrase changing the workflow. Strictly speaking, these 7, plus 2 others that dropped the size wording entirely, are **not true paraphrases** because they lost part of the meaning. The automated checks and the first manual review both let them through. They are now rejected, based on their wording alone, and the checks will be extended to catch them.

### How sure can we be?

"No detectable difference" is not the same as "no difference."

- The gap between the paraphrases and the seed is **−2.5 points**. Given the sample sizes, the true gap could plausibly lie anywhere from **−14 to +9 points**.
- Most of that uncertainty comes from having only 50 seed runs. About 150–200 more seed runs (a few dollars) would allow a proper test of whether the paraphrases perform *as well as* the seed, within ±10 points.

## Gaps in the process catalog

**Visualization.** No process in the catalog renders a map, so almost every workflow reports exactly this one missing capability. This is expected, and the agent handles it correctly.

**Walking distance.** The request asks for *walking* distance, but every workflow uses straight-line distance rings. The agent's replies state this openly, for example:

> Distances are straight-line buffers in a local UTM projection, not walking distances along the street network. Real walking routes would be longer, so some areas counted as served may be farther than 300 m on foot.

There are two reasons:

1. **The agent rarely looks for it.** It translates "within 300 m in intervals" directly into distance rings, which match that wording exactly, and the word "walking" gets absorbed along the way.
2. **When it does look, it correctly rejects what it finds.** The catalog has a travel-time isochrone process, but it works from a single starting point, takes times in minutes, and is built around public transit timetables. It cannot produce 300 m walking zones around many parks.

Whether this is a problem depends on the catalog's intent. If the isochrone is meant as a near miss, the agent behaves correctly. If network-based walking distance is meant to be achievable, the catalog needs a process that fits: many starting areas, distances in metres, walking only.

## Next steps

- **More seed runs** to narrow the uncertainty and test "as good as the seed" properly.
- **Stricter paraphrase checks** that reject wordings which drop the size requirement.
- **Targeted rewording tests** that change one phrase at a time, e.g. "Pinpoint" as the opening verb, "0.3 km" instead of "300 m", or "pedestrian". These showed weak signals that the current data can't confirm.
- **Run the workflows.** Remove duplicate workflows and execute each distinct one, so results can also be scored on their actual output, not only on their structure.
