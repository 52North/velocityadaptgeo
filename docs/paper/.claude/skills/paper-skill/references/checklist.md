# Checklist before "done" / submission

Run from `docs/paper/` after `make`. Report every failed point; do not tick what was not checked.

## Build

- [ ] `make` ends with exit code 0
- [ ] `grep -E "^!|Warning" build/main.log` shows no undefined references/citations and no
      overfull boxes > 1 pt
- [ ] `pdfinfo build/main.pdf`: page size 481.9 × 680.3 pt (17 × 24 cm)
- [ ] `pdffonts build/main.pdf`: all fonts embedded (`emb yes`), only Times New Roman (or the
      agreed substitute) plus Symbol
- [ ] Page count within the limit given by the editors (extended abstract)

## Layout (compare with the rendered `Mustertext_Tagungsband.docx`)

- [ ] Text block 13 cm wide, margins top 2.3 / bottom 2.2 / sides 2.0 cm
- [ ] Body 10 pt, justified, hyphenated, 6 pt after each paragraph, no first-line indent
- [ ] Title 16 pt bold; authors 10 pt; addresses 9 pt with superscript numbers; e-mail only
      for the lead author
- [ ] Headings 13/11/10 pt bold, number + 0.9 cm tab, no level skipped; two headings in a row:
      no space before the second
- [ ] First page: only the page number at the top right
- [ ] Even pages: page number left, "3. Forum GEO.KI" right; odd pages:
      "R. Flores & B. Gräler: <short title>" left, page number right; 9 pt
- [ ] Captions above, "**Abbildung/Tabelle n:**" bold + tab, text regular; source line below
- [ ] Tables: 13 cm, full ½ pt grid, 9 pt, bold shaded header, no merged cells, no empty
      rows/columns, header repeated across pages
- [ ] Figures left-aligned, ≥ 300 dpi at 13 cm, lines ≥ 0.25 pt
- [ ] Lists: bullet, 0.63 cm hanging, 3 pt before / 0 inside / 6 pt after
- [ ] Display formulas: 1 cm indent, numbered "(n)" at the right margin, referenced in the text
- [ ] Bibliography: hanging 0.5 cm, 3 pt after, alphabetical, pattern from `writing-rules.md`

## Text

- [ ] All citations author-year without comma; every citation has a bibliography entry and
      vice versa
- [ ] Every figure and table referenced in the text, word written out
- [ ] Typographic quotes and dashes; non-breaking spaces for number + unit and abbreviations
- [ ] Labels in the paper's language (table "Labels" in `writing-rules.md`)
- [ ] **DE only:** new spelling, gender-fair language

## Accessibility

- [ ] Text selectable/searchable in the PDF (`pdftotext build/main.pdf -` gives the full text)
- [ ] PDF metadata: title and authors set (`pdfinfo` Title/Author), document language set
- [ ] Every figure has alt text; complex figures are described in the text
- [ ] Contrast ≥ 3:1 (graphics) / 4.5:1 (text in figures); no colour-only information
- [ ] Links are live hyperlinks
- [ ] Formulas have ASCII-math alt text
- [ ] If tagging is required: built with LuaLaTeX + `\DocumentMetadata{tagging=on}`, checked
      with a PDF/UA validator (e.g. veraPDF)

## Deliverables

- [ ] PDF of the paper
- [ ] Original figures as separate files, named with the figure number first
      (`01_workflow.png`), rasters TIFF/PNG/JPEG, vectors PDF/EMF
- [ ] Reprint permissions for external figures
- [ ] Submission format confirmed with the publisher (see open risk 1 in `SKILL.md`)
- [ ] If needed: `.docx` built from the template's styles and passed Word's accessibility
      check (see "Word deliverable" in `SKILL.md`)
