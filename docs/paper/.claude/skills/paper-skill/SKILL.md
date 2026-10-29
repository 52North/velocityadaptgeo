---
name: paper-skill
description: Formatting, writing and citation rules for our conference paper (Tagungsband), with the layout of the delivered Word template rebuilt in LaTeX under docs/paper. Use whenever working on docs/paper - editing paper-style.sty, main.tex, chapters/, tables/, figures/ or references.bib, converting the extended abstract to LaTeX, checking the PDF against the publisher's template, or answering questions about the Tagungsband / Wichmann / GEO.KI format, citations or bibliography.
---

# Paper skill: Tagungsband layout in LaTeX

The paper (extended abstract "MCP vs. RAG: Evaluating Agentic Performance Across Paraphrased
Prompts for Geospatial Workflows", R. Flores & B. Gräler) goes into a conference
volume (Tagungsband). The publisher only ships Word material; we rebuild it in LaTeX.

Sources of truth (do not edit; `template/` is ignored by git - if the files are missing, ask
the user to copy them in):
- `docs/paper/template/Hinweise_Tagungsband.pdf` - guidelines for authors (German)
- `docs/paper/template/Mustertext_Tagungsband.docx` - sample text with all Word styles;
  every measurement in `references/format-spec.md` was read from its `word/styles.xml`
- `docs/paper/template/MCP vs RAG Comparison - Extended Abstract.{md,docx}` - our content

## Principle

Apply every rule of the template to our text, including the additions the rules require:
table/figure mentioned in the text, a source line under every table/figure, the place in each
bibliography entry, both running heads (short title on odd pages, the given volume title
"3. Forum GEO.KI" on even pages). Change our wording only where a rule demands it. Never copy
the sample's own content (its text, its citation box, its author data).

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

## Commands provided by `paper-style.sty`

| Command | Use |
|---|---|
| `\documentclass[ngerman]{paper}` | German labels/hyphenation; default English. `paper.cls` sets the font and loads `paper-style.sty` |
| `\author{A\textsuperscript{1,2} and B\textsuperscript{1}}` | author line |
| `\address{\textsuperscript{1}Institute, City · e-mail}` | one call per address line |
| `\runningauthors{R. Flores \& B. Gräler}`, `\runningtitle{Short title}` | odd running head |
| `\headcell{Text}` | bold table header cell with the 3 pt padding |
| `\tabsource{\ownwork}`, `\figsource{...}` | source line below a table / figure |
| `\begin{abstract}` | "Abstract"/"Zusammenfassung" block (`ÜSZusammenfassung`) |

The header rules, captions, lists, footnotes and the
bibliography layout are automatic.

Spacing was verified against the LibreOffice render of the sample with
`pdftotext -bbox` (body pitch 11.5 pt, paragraph 17.5 pt, table row 12.8 pt, cell line 10.3 pt,
caption to table 20 pt; deviations mostly ≤ 1 pt, up to 2 pt below floats). Good enough - the
templates are first guidance; final verification is the Word check at the end. Do not chase
single points.

## Rules at a glance

- Page 17 × 24 cm, text block 13 cm wide; Times New Roman 10 pt, justified, hyphenation on.
- Headings numbered by hand ("1", "1.1", "1.1.1"), no trailing period, number + tab (0.9 cm).
- Captions **above** figures and tables: "**Abbildung 1:**" / "**Tabelle 1:**" + tab + text;
  a source line **below**: "Quelle: eigene Darstellung".
- Tables: full grid ½ pt, 13 cm wide, 9 pt, bold shaded header row, no merged cells.
- Citations author-year **without comma**: "Name (2020)", "(Name 2020, 144)",
  "(Name1 & Name2 2020)", "(Name et al. 2020)".
- Bibliography: "Name, V. & Name, V. (2020): Title. Place." - produced by
  `docs/paper/paper.bst`; `.bib` conventions in `writing-rules.md`.
- Always real umlauts (Gräler, Münster), never ae/oe/ue.
- Every figure needs alt text; formulas need an ASCII-math alt text.
- Running heads: even page "page | 3. Forum GEO.KI", odd page "R. Flores & B. Gräler: <short title> | page".

## Language

The guidelines and the sample are German; our text is English. The `.sty` must support both,
switched by the babel language (`ngerman` / `english`). Layout is identical; only labels change
(table in `writing-rules.md`, section "Labels"). German-only rules (spelling reform, gender
colon) apply only when the paper is German.

## Word deliverable (last step, only after the LaTeX version is final)

LaTeX stays the source. At the very end, a `.docx` is built in parallel so the publisher's
Word-based accessibility workflow can be served:

1. Start from a copy of `template/Mustertext_Tagungsband.docx` and fill in our content using
   its own paragraph styles (`Beitragstitel`, `Überschrift 1`, `Tabellenüberschrift`, ...) -
   never direct formatting. Use the Word/docx skill for this.
2. Check it in Word for the web (Microsoft 365 account available; driven via the Chrome
   extension): "Überprüfen -> Barrierefreiheit überprüfen". Record the result (screenshot).
3. Only a `.docx` can be checked this way - opening our LaTeX PDF in Word converts it and says
   nothing about our document.

## Open risks - raise these, do not silently decide

1. **Submission format.** What the guidelines say:
   - 1.1: "Das Manuskript wird als PDF gedruckt. Deshalb ist es vorteilhaft, den Druckertreiber
     Adobe PDF oder einen anderen kompatiblen PDF-Druckertreiber zu verwenden."
   - Footnote 1: page format 17 × 24 cm, not A4 - "beim Ausdrucken zu berücksichtigen".
   - 1.3: "Ein barrierefreies Word-Dokument ist Grundvoraussetzung für die Umwandlung in ein
     barrierefreies PDF-Dokument."

   So printing is done from a PDF (fine for LaTeX), but the publisher apparently converts the
   **Word file** into the accessible PDF. Whether a LaTeX-made PDF alone is accepted must be
   confirmed with the contact named in the guidelines (section 3). Fallback: the Word deliverable below.
2. **Accessible PDF.** The volume is produced as an accessible PDF (tags, alt text, heading
   structure). In LaTeX this realistically needs LuaLaTeX with `\DocumentMetadata{tagging=on}`.
   LuaLaTeX is installed; tagging is not switched on yet.
3. **Font.** Build needs `texlive-luatex` and `texlive-langgerman` (both installed); the Makefile
   picks LuaLaTeX automatically, pdfLaTeX is only a fallback with Computer Modern.
   Only fonts that ship with MS Word/Windows are allowed -> Times New Roman.
   Not installed; installed is Liberation Serif (metrically identical, same line breaks, but a
   different font name in the PDF). Real TNR: `ttf-ms-fonts` (AUR) + LuaLaTeX/fontspec.
   pdfLaTeX Times (`texlive-fontsrecommended`) is only similar, not metric-identical.
