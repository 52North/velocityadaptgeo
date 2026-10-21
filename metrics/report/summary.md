# Summary: How robust is the workflow agent to rewording?


We tested whether an LLM agent that builds geospatial workflows from a catalog of OGC processes still builds the right workflow when the same request is worded differently. This summary covers the first test case, a single request about walking distance to green spaces in Münster. Most of it is about the agent as built, which searches the catalog and sees the five closest matches. The last part of the results compares it with a version that sees every process at once, the way an MCP server lists its tools.

## At a glance

- **The agent usually gets it right.** For the original request it builds the correct workflow in **90%** of runs.
- **Rewording costs a little, even when the meaning is kept.** Paraphrases that keep the full meaning reach **81.5%**, about 8 points below the original. The gap is small but statistically significant.
- **One kind of rewording breaks it outright.** Turning "large enough for recreation" into "suitable / adequate / sufficient for recreation" silently drops the size requirement, and the agent then never filters by size (**0 of 7** correct).
- **The agent is not fully deterministic.** Identical requests give different workflows, more in the parameters (ring distances, minimum area) than in the structure.
- **Two capabilities are consistently missing:** no process can draw a map, and no process can compute *walking* distance around many parks. The agent says so honestly in its replies.
- **Showing the agent every process instead of searching makes it more robust.** It is right in **96%** of paraphrases (instead of 81%), rewording no longer costs anything measurable, and it stops adding the redundant extra step. It costs about 1.8 times as much, because the whole process list is sent with every request.
- **It is cheap:** about **1 cent per request**.

## The test

The original request (the *seed*):

> Identify all areas in Münster that are within a 300-meter walking distance of a public park or forest large enough for recreation. Output a visualization that highlights these well-served areas and displays the walking distances from the green spaces in incremental intervals up to the 300-meter limit.

**The correct workflow** is a chain of four steps:

``` text
city boundary → green areas (parks, forests) → minimum-area filter → distance rings (up to 300 m)
```

We score a workflow two ways, looking only at its structure (not at parameter values):

| Score | Counts as correct when… |
|----|----|
| **Lenient** | the four steps are present and connected in that order; extra steps are allowed |
| **Strict** | the workflow is exactly those four steps, nothing more |

Each rate comes with a **95% range**, the span its true value plausibly falls in given the sample size (Wilson interval).

The lenient score is the main measure. The strict score is low throughout (about 27%) because the agent often adds a redundant extra step, a plain 300 m buffer, next to the distance rings. This is harmless, and it happens equally with and without rewording.

**The paraphrases.** A local LLM rewrote the seed in six linguistic categories, from small word-form changes to restructured sentences, aiming for wording that differs a lot while the intent stays the same. Every candidate passed automated checks and a manual review. **162** paraphrases were kept.

**The baseline.** The agent varies even when given the identical request, so the seed was run **200 times**. This measures the agent's own run-to-run variation, which every paraphrase result has to be compared against.

## Results

### The original request

|         | Correct               | 95% range |
|---------|-----------------------|-----------|
| Lenient | 179 / 200 = **89.5%** | 84–93%    |
| Strict  | 54 / 200 = 27%        | 21–34%    |

- The rate was stable over the 200 runs, with no drift.
- The 21 failures: in 20 the size filter was left out or wired in the wrong place, and in 1 the distance rings were missing.
- **Parameters vary more than structure.** The minimum park size ranged from unset to 10,000 m² (most often 10,000 m²). The rings were usually 75 / 150 / 225 / 300 m, sometimes 50 m steps.

### The paraphrases

|  | Correct (lenient) | 95% range | Has the size filter | 95% range |
|----|----|----|----|----|
| Seed (200 runs) | **89.5%** | 84–93% | 93% | 89–96% |
| Paraphrases that keep the meaning (162) | **81.5%** | 75–87% | 93% | 88–96% |
| Paraphrases that drop the size requirement (9) | 0% | 0–30% | 0% | 0–30% |

The 162 paraphrases include the size filter exactly as often as the seed, so the requirement itself comes through. They fail more often on how the steps are put together:

| Failure                              | Seed (200) | Paraphrases (162) |
|--------------------------------------|------------|-------------------|
| size filter missing                  | 7%         | 6.8%              |
| size filter wired in the wrong place | 3%         | 6.8%              |
| distance rings missing               | 0.5%       | 3.1%              |
| city boundary missing                | 0%         | 1.9%              |

By category:

| Category | What changes | Correct (lenient) | 95% range |
|----|----|----|----|
| Syntactic | sentence structure | 100% (23) | 86–100% |
| Other | e.g. reordering, added purpose clauses | 95% (38) | 83–99% |
| Discourse | how the request is framed | 81% (31) | 64–91% |
| Lexico-syntactic | words and structure together | 82% (34) | 66–92% |
| Morphological | word forms | 60% (5) | 23–88% |
| Lexical | word choice | 55% (31) | 38–71% |

Each category compared with the seed's 89.5%:

| Category | Correct | Difference from seed | p-value | Significant (p \< 0.05) | Significant after correction (p \< 0.008) |
|----|----|----|----|----|----|
| Syntactic | 100% | +10.5 points | 0.14 | no | no |
| Other | 95% | +5.2 points | 0.55 | no | no |
| Discourse | 81% | −8.9 points | 0.22 | no | no |
| Lexico-syntactic | 82% | −7.1 points | 0.25 | no | no |
| Morphological | 60% | −29.5 points | 0.098 | no | no |
| Lexical | 55% | −34.7 points | \< 0.0001 | **yes** | **yes** |
| *All categories together* | *81.5%* | *−8.0 points* | *0.034* | *yes* | *n/a (a single test)* |

The p-value is the chance of seeing a gap at least this large if the category really performed like the seed (Fisher's exact test). Comparing six categories at once makes a chance hit more likely, so the last column uses a stricter threshold (0.05 / 6 ≈ 0.008, Bonferroni correction). The wide ranges show how small some of the categories are (as few as 5 paraphrases).

**Lexical paraphrases are clearly worse than the seed**, even after the correction. Morphological ones also look lower, but with only 5 paraphrases that could be chance. The other four categories are in line with the seed.

### The wording that breaks it

"Large enough for recreation" asks for a **size** threshold. "Adequate / suitable / sufficient for recreation" reads as a **quality**, so the agent never looks for an area filter:

| Wording | Paraphrases | Size filter present | Correct |
|----|----|----|----|
| keeps "large enough" (or similar) | 162 | 93% \[88–96%\] | 81.5% \[75–87%\] |
| "adequate / suitable / sufficient for recreation" | 7 | 0% \[0–35%\] | 0% \[0–35%\] |

This is the clearest case in the study of a paraphrase changing the workflow. Strictly speaking, these 7, plus 2 others that dropped the size wording entirely, are **not true paraphrases** because they lost part of the meaning. The automated checks and the first manual review both let them through. They are now rejected, based on their wording alone, and the checks will be extended to catch them.

### How sure can we be?

- The gap between the paraphrases and the seed is **−8 points**. Given the sample sizes, the true gap plausibly lies between **−15 and −1 points**, so rewording most likely does cost something.
- We can't claim the paraphrases perform *as well as* the seed. An equivalence test with a ±10-point margin fails, because a gap of more than 10 points is still within the range.
- With only the first 50 seed runs, the seed looked lower (84%) and the gap looked like noise. The 150 further runs settled the seed at about 90%, and the earlier "no detectable difference" no longer holds.
- One caveat: most seed runs ran a day after the paraphrases. The setup was the same, but a small day-to-day shift can't be fully ruled out. Re-running the paraphrases would settle it.

## Showing every process instead of searching

The agent as tested finds processes by searching the catalog: each search returns the five closest matches, and the agent only sees those. The alternative is to show it every process the server offers, the way an MCP server lists its tools. Here that is 25 processes, sent with every request. Everything else stayed the same: the same agent, model, paraphrases and scoring. We ran the seed 200 times and all 162 paraphrases with this version.

|  | Every process | Catalog search |
|----|----|----|
| Original request, lenient | **95%** \[91–97%\] | 90% \[84–93%\] |
| Original request, strict | **94%** \[89–96%\] | 27% \[21–34%\] |
| Paraphrases, lenient | **96%** \[91–98%\] | 81% \[75–87%\] |
| Paraphrases, strict | **91%** \[85–94%\] | 27% \[21–34%\] |
| Cost per request | 2.2 cent | 1.2 cent |
| Share of the input that is process descriptions | 78% | 41% |

- **Paraphrases are handled clearly better** (+14 points lenient, p \< 0.0001). On the original request the difference is small (+6 points, p = 0.060) and could still be chance.
- **Rewording no longer costs anything measurable:** paraphrases 96% against 95% for the original request. The lexical paraphrases, the weak spot of the catalog search, reach 94%.
- **The workflows are much more consistent.** The redundant 300 m buffer never appears, which is why the strict score jumps. The only real failure left is the missing size filter (17 of 362 workflows). The steps are never connected wrongly.
- **Walking distance is still straight-line.** Even with the travel-time isochrone in view on every request, the agent never uses it.
- **The price is context.** Each request sends about 2.2 times as much text to the model, mostly process descriptions. It is still a little faster, since the agent needs fewer rounds of searching.

Two things limit this result. The catalog has only 25 processes. With hundreds, the list would grow with every addition, and whether the agent stays this accurate is untested. Neither version used prompt caching, which would make a fixed list of processes much cheaper.

## Gaps in the process catalog

**Visualization.** No process in the catalog renders a map, so almost every workflow reports exactly this one missing capability. This is expected, and the agent handles it correctly.

**Walking distance.** The request asks for *walking* distance, but every workflow uses straight-line distance rings. The agent's replies state this openly, for example:

> Distances are straight-line buffers in a local UTM projection, not walking distances along the street network. Real walking routes would be longer, so some areas counted as served may be farther than 300 m on foot.

There are two reasons:

1.  **The agent doesn't look for it.** It translates "within 300 m in intervals" directly into distance rings, which match that wording exactly, and the word "walking" gets absorbed along the way. In 150 seed runs where the agent's search steps were recorded, it searched for a buffer-style process every time and never for distance along a street network.
2.  **When it does look, it correctly rejects what it finds.** The catalog has a travel-time isochrone process, but it works from a single starting point, takes times in minutes, and is built around public transit timetables. It cannot produce 300 m walking zones around many parks.

Whether this is a problem depends on the catalog's intent. If the isochrone is meant as a near miss, the agent behaves correctly. If network-based walking distance is meant to be achievable, the catalog needs a process that fits: many starting areas, distances in metres, walking only.

## Next steps

- **Find where the extra wiring errors come from.** The paraphrases keep the size filter as often as the seed but connect the steps wrongly more often. Re-running the paraphrases with the agent's reasoning recorded (about \$2) should show at which step this goes wrong.
- **Stricter paraphrase checks** that reject wordings which drop the size requirement.
- **Targeted rewording tests** that change one phrase at a time, e.g. "Pinpoint" as the opening verb, "0.3 km" instead of "300 m", or "pedestrian". These showed weak signals that the current data can't confirm.
- **Showing every process at a larger scale:** a bigger catalog, and the same version with prompt caching, to see whether the accuracy holds and what it costs then.
- **Run the workflows.** Remove duplicate workflows and execute each distinct one, so results can also be scored on their actual output, not only on their structure.
