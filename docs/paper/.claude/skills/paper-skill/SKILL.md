---
name: paper-skill
description: Formatting, writing and citation rules for the contribution to the Wichmann conference volume "3. Forum GEO.KI" (Herbert Wichmann Verlag / VDE), rebuilt in LaTeX under docs/paper. Use whenever working on docs/paper - editing paper-style.sty, main.tex, chapters/, tables/, figures/ or references.bib, converting the extended abstract to LaTeX, checking the PDF against the publisher's template, or answering questions about the Tagungsband / Wichmann / GEO.KI format, citations or bibliography.
---

# Paper skill: Wichmann Tagungsband "3. Forum GEO.KI"

The paper (extended abstract "MCP vs. RAG: Evaluating Agentic Performance Across Paraphrased
Prompts for Geospatial Workflows", R. Flores & B. Gräler) goes into a Wichmann conference
volume. The publisher only ships Word material; we rebuild it in LaTeX.

Sources of truth (do not edit; `template/` is ignored by git - if the files are missing, ask
the user to copy them in):
- `docs/paper/template/Hinweise_Tagungsband.pdf` - guidelines for authors (German)
- `docs/paper/template/Mustertext_Tagungsband.docx` - sample text with all Word styles;
  every measurement in `references/format-spec.md` was read from its `word/styles.xml`
- `docs/paper/template/MCP vs RAG Comparison - Extended Abstract.{md,docx}` - our content

## References - read before acting

| File | Read when |
|------|-----------|
| `references/format-spec.md` | Changing anything visual: page, fonts, spacing, headings, captions, tables, lists, headers, first page |
| `references/writing-rules.md` | Writing or converting text: typography, citations, bibliography, figure/table sources, alt text, DE/EN labels |
| `references/checklist.md` | Before showing a build as "done" and before submission |

## Workflow

1. All formatting lives in `docs/paper/paper-style.sty`. `chapters/*.tex` contain text only -
   no spacing, font or layout commands. If something looks wrong, fix the `.sty`.
2. Tables: numbers in `tables/<name>.csv`, caption/label/source/column layout in
   `tables/tab-<name>.tex`. Figures: `figures/NN_<name>.<ext>` (figure number first).
3. Build with `make -C docs/paper` -> `docs/paper/build/main.pdf`.
4. Compare against the template: render it with
   `soffice --headless --convert-to pdf --outdir <scratch> docs/paper/template/Mustertext_Tagungsband.docx`
   and compare positions and sizes with `pdftotext -bbox` (font size ≈ word box height / 1.11).
5. Run `references/checklist.md`.
6. Show the diff and wait for approval before committing (English commit messages).

## Rules at a glance

- Page 17 × 24 cm, text block 13 cm wide; Times New Roman 10 pt, justified, hyphenation on.
- Headings numbered by hand ("1", "1.1", "1.1.1"), no trailing period, number + tab (0.9 cm).
- Captions **above** figures and tables: "**Abbildung 1:**" / "**Tabelle 1:**" + tab + text;
  a source line **below**: "Quelle: eigene Darstellung".
- Tables: full grid ½ pt, 13 cm wide, 9 pt, bold shaded header row, no merged cells.
- Citations author-year **without comma**: "Name (2020)", "(Name 2020, 144)",
  "(Name1 & Name2 2020)", "(Name et al. 2020)".
- Bibliography: "Name, V. & Name, V. (2020): Title. Place." - see `writing-rules.md`.
- Every figure needs alt text; formulas need an ASCII-math alt text.
- Running heads: even page "page | 3. Forum GEO.KI", odd page "R. Flores & B. Gräler: <short title> | page".

## Language

The guidelines and the sample are German; our text is English. The `.sty` must support both,
switched by the babel language (`ngerman` / `english`). Layout is identical; only labels change
(table in `writing-rules.md`, section "Labels"). German-only rules (spelling reform, gender
colon) apply only when the paper is German.

## Open risks - raise these, do not silently decide

1. **Submission format.** The guidelines describe Word plus a PDF printout only. Whether a
   LaTeX-made PDF is accepted must be confirmed with the publisher:
   Gerold Olbrich, Herbert Wichmann Verlag, gerold.olbrich@vde-verlag.de, +49 69 840006-1621.
2. **Accessible PDF.** The volume is produced as an accessible PDF (tags, alt text, heading
   structure). In LaTeX this realistically needs LuaLaTeX with `\DocumentMetadata{tagging=on}`.
   Only pdfLaTeX is usable right now; LuaLaTeX needs `sudo pacman -S texlive-luatex`.
3. **Font.** Only fonts that ship with MS Word/Windows are allowed -> Times New Roman.
   Not installed; installed is Liberation Serif (metrically identical, same line breaks, but a
   different font name in the PDF). Real TNR: `ttf-ms-fonts` (AUR) + LuaLaTeX/fontspec.
   pdfLaTeX Times (`texlive-fontsrecommended`) is only similar, not metric-identical.
4. **Bibliography style.** `biblatex`/`biber` are not installed. Options: a custom `.bst`
   for natbib, or a hand-written `thebibliography`. Decide when building the `.sty`.
5. **First-page box.** Its exact position in the printed volume is set by the publisher;
   the ISBN/DOI are placeholders ("7xx-x", "537xxxxxx") filled in by the publisher.
