# LaTeX → DOCX conversion: issues and solutions

`make docx` turns the LaTeX paper into `build/main.docx` in the styles of the publisher's Word
template (`template/Mustertext_Tagungsband.docx`). Pipeline:

1. `make` builds the PDF first; its `build/main.bbl` (bibliography formatted by `paper.bst`) is reused.
2. `pandoc docx/shim.tex main.tex` with the template as `--reference-doc`, `+native_numbering`,
   `--number-sections`, `--figure-caption-position=above` and the filter `docx/paper.lua`.
3. `docx/postprocess.py` rewrites the result in place (style names, captions, tables, header).

Tested with pandoc 3.14 and checked by rendering with LibreOffice, not in Word. The final check
in Word is still manual. Accessibility check (Word: Review → Check Accessibility) has not been run.

## Choice of tool

| Option | Result |
|---|---|
| pandoc + template as reference doc | **Used.** Takes page size 17 × 24 cm, margins, running heads and all paragraph styles from the template |
| tex4ht / make4ht → ODT/DOCX | Not used: its own styles instead of the template's, not installed |
| PDF → DOCX (Word / LibreOffice import) | Not used: text boxes, no document structure, useless for an accessible document |

Installing: the Arch package `pandoc-cli` failed with 404s because of an outdated package
database (needs a full `pacman -Syu`). The AUR package `pandoc-bin` (static binary) works.

## Issues

| # | Issue | Solution | Status |
|---|---|---|---|
| 1 | Our own commands from `paper-style.sty` (`\tabsource`, `\figsource`, `\figdatasource`, `\ownwork`, `\headcell`, `\rowcolor`, `\bibinname`, ...) are unknown to pandoc and get dropped | `docx/shim.tex` defines them in plain LaTeX for pandoc; source lines become environments that the filter recognises | solved |
| 2 | `\csvreader` (table rows from `tables/*.csv`) cannot run in pandoc: the table came out empty, CSV options leaked into the text and broke the following heading | `shim.tex` drops `\csvreader`; `paper.lua` reads `tables/tab-<name>.tex`, fills its row template with every CSV row and parses the rows with pandoc | solved (plain CSV only, no quoted fields) |
| 3 | Citations (`\citep`, `\citet`) rendered as empty text; pandoc cannot use `paper.bst` | The filter parses `build/main.bbl`: the `\bibitem[{Author(year)}]` labels give "(Vila et al. 2014)" / "Vila et al. (2014)" | solved; citations are plain text, not Word citation fields |
| 4 | Bibliography missing; pandoc misreads `thebibliography` | The filter turns each `\bibitem` of `build/main.bbl` into a paragraph in style `Literaturliste`, under an unnumbered heading "References" | solved; entries identical to the PDF |
| 5 | Images not found (`\graphicspath`, no file extension) | `--resource-path=.:figures --default-image-extension=png` | solved |
| 6 | Figure with image + source line: pandoc puts the blocks side by side in a layout table | The filter moves source lines out of the figure, below it | solved |
| 7 | Figure 3 (two images, `height=7cm` only): pandoc ignores a height-only size and stretches the image over several pages | The filter computes the width from the image's aspect ratio | solved |
| 8 | Figure 3 is laid out by pandoc as a table with its own style `FigureTable`, which is not defined | `postprocess.py` maps it to the template's `Normal Table` (no borders) | solved; images are centred in their cells (left-aligned in the PDF) |
| 9 | pandoc's own paragraph styles (`Body Text`, `First Paragraph`, `Compact`, `Image Caption`, `Table Caption`, `Captioned Figure`) instead of the template's | `postprocess.py` maps them to `Standard`, `Abbildungsüberschrift`, `Tabellenüberschrift`, `Grafik` | solved; pandoc's unused style definitions stay in `styles.xml` (invisible in the text, visible in Word's style list) |
| 10 | Title block: pandoc writes title/author/abstract in its own styles and drops `\address` | The filter builds the block from the metadata: `Beitragstitel`, `Autorenname`, `Autorenadresse_2`/`_1`, `ÜSZusammenfassung` + abstract | solved; the "Abstract" label is English only (`ngerman` not supported) |
| 11 | Document title/author in the file properties empty after #10 | `postprocess.py` sets them from `pdftitle`/`pdfauthor` in `main.tex` | solved |
| 12 | Odd running head shows the template's sample text | `postprocess.py` writes `\runningauthors: \runningtitle` from `main.tex` into the odd-page header | solved |
| 13 | Captions "Figure 1: text" without bold label and tab | `postprocess.py` sets "Figure 1:" bold + tab, as in the template; the number field becomes a complex field so it can be bold | solved |
| 14 | Captions and headings separated from their figure/text at page breaks (the template's styles have no "keep with next") | `keepNext` on caption and heading paragraphs | solved |
| 15 | Table: 10 pt, columns too narrow, words broken mid-word, no header shading | Cells in style `Tabellenüberschrift` with the sample table's direct formatting (9 pt, 3/1 pt spacing, 0.1 cm padding, header `#DDDDDD`), table style `Table Grid` | solved |
| 16 | Table column alignment lost (pandoc reads all columns as left) | The filter reads the `tabularx` column spec (`>{\centering}X`) | solved |
| 17 | Table column widths: LaTeX `l` + `X` columns | Equal widths over the full text width | partly: widths differ from the PDF |
| 18 | Cross references ("Figure 1") blue and underlined | The filter removes internal links (as `hidelinks` in the PDF) | solved; URLs stay links in the template's `Hyperlink` style |
| 19 | Alt text of images contained line breaks and indentation from the LaTeX source | The filter collapses whitespace | solved |
| 20 | Heading numbers referenced pandoc's undefined character style `Section Number` | Removed in `postprocess.py`; numbers are text + tab, as the guidelines require | solved |
| 21 | "X" at the end of captions in the first LibreOffice render | Disappeared with the caption rework (#13); probably a LibreOffice rendering of pandoc's bookmarks | solved |
| 22 | Bibliography lines with wide gaps: `Literaturliste` is justified and URLs cannot break | Kept: it is the template's style | open, check in Word |
| 23 | Numbered list indentation comes from pandoc's list definition, not from the template's list style | Not changed | open, check in Word |
| 24 | Language: pandoc writes `en-US` on every run (direct formatting) because the template's default is German | Accepted; needed for spell check/hyphenation | as intended |
| 25 | 16 pages in the DOCX vs. 15 in the PDF (different image sizes and page breaks) | Not changed | accepted |
