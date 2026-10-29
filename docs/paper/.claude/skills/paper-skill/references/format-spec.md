# Format specification

All values were read from `template/Mustertext_Tagungsband.docx` (`word/styles.xml`,
`word/document.xml`, `word/header*.xml`, `word/settings.xml`) and cross-checked against
`template/Hinweise_Tagungsband.pdf`. Word units: 1 cm = 567 twips, 1 pt = 20 twips,
font size `w:sz` is in half points. Where the guidelines text and the sample differ, both are
given; the sample is what the publisher's layout actually uses.

"before"/"after" = Word paragraph spacing ("Abstand vor/nach"). Word **adds** them:
gap between two paragraphs = after(previous) + before(next). Rebuild the gaps that way in LaTeX.

## Page and base text

| Property | Value | LaTeX |
|---|---|---|
| Paper | 17.0 × 24.0 cm (`pgSz` 9639 × 13608) | `geometry`: `paperwidth=17cm, paperheight=24cm` |
| Margins | top 2.3 cm, bottom 2.2 cm, left 2.0 cm, right 2.0 cm | `top=2.3cm, bottom=2.2cm, left=2cm, right=2cm` |
| Text width | 13.0 cm | follows from margins |
| Header | 1.2 cm from top edge (`header=680`), no footer | `headsep` so the header baseline sits ≈ 1.2 cm + 9 pt from the top; `footskip=0pt`, empty foot |
| Columns | one | - |
| Two-sided | different even/odd headers (`evenAndOddHeaders`), own first page (`titlePg`) | `\documentclass[twoside]`, fancyhdr `[LE,RO]` / `[RE,LO]` |
| Font | Times New Roman (docDefaults), body 10 pt | see "Open risks" in `SKILL.md` |
| Line spacing | single (Word single for TNR 10 pt ≈ 11.5 pt baseline) | `\fontsize{10}{11.5}\selectfont` |
| Alignment | justified (`Standard`: `jc=both`) | LaTeX default |
| Hyphenation | automatic, hyphenation zone 0.75 cm (`hyphenationZone=425`) | babel patterns; never `\-` by hand in text |
| Default tab stop | 1.25 cm | only relevant for emulated tabs |

## Paragraph styles

| Word style | Font | Before | After | Indent | Other | LaTeX target |
|---|---|---|---|---|---|---|
| `Standard` | 10 pt | 0 | 6 pt | none, no first-line indent | justified | `\parindent=0pt`, `\parskip=6pt` (no stretch) |
| `Beitragstitel` | 16 pt bold | 0 | 12 pt | - | left, sensible manual line break | custom `\maketitle` |
| `Autorenname` | 10 pt | 0 | 4 pt | - | "Vorname Nachname", several joined by "und" / "and" | custom `\maketitle` |
| `Autorenadresse_2` | 9 pt | 0 | 0 | - | first address line(s), with superscript number | custom `\maketitle` |
| `Autorenadresse_1` | 9 pt | 0 | 15 pt | - | last (or only) address line; "Institute, City · e-mail" | custom `\maketitle` |
| `ÜSZusammenfassung` | 13 pt bold (from Ü1) | 15 pt | 10 pt | none | heading "Zusammenfassung"/"Abstract", unnumbered | `\section*`-like, own spacing |
| `Überschrift 1` | 13 pt bold | 18 pt | 12 pt | hanging 0.9 cm | number + tab at 0.9 cm, left-aligned | `titlesec`: `\titleformat{\section}[hang]` with number in `\makebox[0.9cm][l]` |
| `Überschrift 2` | 11 pt bold | 6 pt | 6 pt | hanging 0.9 cm | as above | `\subsection` |
| `Überschrift 3` | 10 pt bold | 6 pt | 6 pt | hanging 0.9 cm | not forced left (inherits justify) | `\subsubsection` |
| Two headings in a row | - | second: 0 pt | - | - | e.g. Ü1 directly followed by Ü2 | detect in `.sty` or `\vspace{-6pt}` in a dedicated macro, never in chapters |
| `Tabellenüberschrift` | 10 pt | 12 pt | 6 pt | hanging 1.7 cm | "**Tabelle 1:**" + tab at 1.7 cm; **above** the table | `caption` with custom `labelformat`/`labelsep`, `\captionsetup[table]{position=top}` |
| Table caption at top of a page | - | 0 pt | - | - | - | let LaTeX drop space at page top (`\vspace` not `\vspace*`) |
| `Abbildungsüberschrift` | 10 pt | 12 pt | 6 pt | hanging 2.3 cm | "**Abbildung 1:**" + tab at 2.3 cm; **above** the figure | as table caption, own indent |
| `Grafik` | - | 0 | 0 | none | left-aligned | `\includegraphics` without `\centering` |
| `Abbildungsquelle` | 10 pt | 6 pt | 18 pt | hanging 1.0 cm | "Quelle:" + tab at 1.0 cm | `\figsource{...}` macro |
| `Tabellenquelle` | 10 pt | 6 pt | 18 pt | hanging 1.0 cm | as above | `\tabsource{...}` macro |
| Source line followed by a heading | - | - | 6 pt | - | - | macro option or rely on heading "before" |
| `Absatz nach Tab.` | 10 pt | 18 pt | 6 pt | - | paragraph after a table (only base for `Tabellenquelle`) | covered by source "after" |
| `Literaturliste` | 10 pt | 0 | 3 pt | hanging 0.5 cm | justified | natbib `\bibhang=0.5cm`, `\bibsep=3pt`; entry layout from `wichmann.bst` |
| `Fußnotentext` | 9 pt | 0 | 6 pt | hanging 0.35 cm | mark + tab at 0.35 cm | `\renewcommand\@makefntext` |
| `Fußnotenzeichen` | superscript | - | - | - | - | default |
| `Kopfzeile` | 9 pt | - | 0 | - | - | fancyhdr with `\fontsize{9}{10.35}` |
| `Hyperlink` | blue `#0000FF`, underlined | - | - | - | links must be live (accessibility) | `hyperref` with `urlcolor`; whether the publisher wants coloured links in print is unclear - ask |

## Lists ("Aufzählungen", guidelines 2.7, sample `numId` 16/17)

| Property | Value | LaTeX (`enumitem`) |
|---|---|---|
| Bullet | round bullet "•" (Symbol font) | `label=\textbullet` |
| Indent | bullet at 0, text at 0.63 cm (`left=357 hanging=357`) | `leftmargin=0.63cm, labelsep=*, labelindent=0pt` |
| Alignment | justified | default |
| Paragraph before list | after 3 pt | `topsep` so the gap is 3 pt (`\parskip` counts too) |
| Inside list | before/after 0 pt | `itemsep=0pt, parsep=0pt` |
| Last item | after 6 pt | gap after list = 6 pt |
| Numbered | "1.", "2.", same indents; tab at 0.63 cm | `enumerate` with the same keys, `label=\arabic*.` |

## Tables (guidelines 2.6, sample table 1)

| Property | Value | LaTeX |
|---|---|---|
| Width | full text width 13 cm, centred (= flush) | `tabularx{\textwidth}` |
| Grid | every line, outer frame and inner lines ½ pt (`sz=4`) | `\setlength\arrayrulewidth{0.5pt}`, `|` columns and `\hline` everywhere; **no booktabs** |
| Cell padding | left/right 0.1 cm (`tblCellMar 57`) | `\setlength\tabcolsep{0.1cm}` |
| Font | 9 pt | `\fontsize{9}{10.35}\selectfont` inside the table |
| Header row | bold, shading: sample `#DDDDDD` (guidelines say "10 %") | `\rowcolor[HTML]{DDDDDD}` (`xcolor` with `table`) |
| Header cells | before/after 3 pt | strut or `\rule{0pt}{...}` / `cellspace` |
| Data cells | before/after 1 pt | `\renewcommand\arraystretch` tuned, or `cellspace` |
| Alignment | text left; numbers centred or right | `X` left, `>{\centering\arraybackslash}X` or `r` |
| Forbidden | merged cells, empty rows/columns, layout tables, complex tables (split them) | no `\multicolumn`/`\multirow` |
| Multi-page | header row repeats | `xltabular`/`longtable` with `\endhead` |
| Order | caption above -> table -> "Quelle: ..." below | `tab-*.tex` wrapper |

Our results table in the abstract has merged header cells ("Lenient accuracy" over three
columns) and an empty corner cell - both are forbidden. Split it into one header row with full
column names (e.g. "Lenient seed", "Lenient paraphrases", ...) or two tables.

## Figures (guidelines 2.5)

| Property | Value |
|---|---|
| Placement | left-aligned, inside the text |
| Raster resolution | ≥ 300 dpi at 13 cm width (≈ 1535 px wide); scanned vector art ≥ 1,200 dpi |
| Line width | ≥ 0.25 pt / 0.15 mm; screens/tints ≥ 5 % |
| Labels in figures | still readable after scaling to 13 cm |
| Screenshots | max screen resolution, save lossless (TIFF uncompressed / PNG) |
| Deliver separately | rasters as TIFF/PNG/JPEG, vectors as PDF/EMF/WMF (or original PPT/XLS), file name starts with the figure number |
| Order | caption above -> graphic -> "Quelle: ..." below |

## Formulas (guidelines 2.9)

| Property | Value | LaTeX |
|---|---|---|
| Inline | small formulas not referenced elsewhere | `$...$` |
| Display | indent left 1 cm, after 6 pt | `\[`/`equation` with `fleqn`, `\mathindent=1cm`, `\belowdisplayskip=6pt` |
| Numbering | "(1)" right-aligned at 13 cm, consecutive, referenced in the text | default `equation` numbering on the right |
| Alt text | ASCII-math, e.g. `x = (-b +- sqrt(b^2 - 4ac)) / (2a)` | `\DocumentMetadata` tagging + `alt` key, or a comment in the source until tagging works |

## Running heads (guidelines 2.8, `header1-3.xml`)

| Page | Left | Right | LaTeX |
|---|---|---|---|
| First page | - | page number | `\thispagestyle{firstpage}` |
| Even (left page) | page number | "3. Forum GEO.KI" (volume title, do not change) | `\fancyhead[LE]{\thepage}`, `\fancyhead[RE]{3. Forum GEO.KI}` |
| Odd (right page) | "R. Flores & B. Gräler: <short title>" | page number | `\fancyhead[LO]{...}`, `\fancyhead[RO]{\thepage}` |

- Size 9 pt, regular, no rule (`\headrulewidth=0pt`).
- Authors in the odd head: abbreviated first name + surname; two authors joined by "&";
  three or more: "R. Flores et al.". Long titles: sensible short form.
- The publisher sets real page numbers; our numbering starting at 1 is fine.

## First page

1. Title (`Beitragstitel`), starting at the top margin (2.3 cm).
2. Author line (`Autorenname`): "Randy Flores¹,² und Benedikt Gräler¹" (EN: "and"); superscripts
   on the surnames, starting with 1.
3. Address lines: `Autorenadresse_2` for all but the last, `Autorenadresse_1` for the last;
   each starts with a superscript number; e-mail only for the lead author, separated by " · ".
4. Optional "Zusammenfassung"/"Abstract" (`ÜSZusammenfassung`) + `Standard` paragraph(s).
5. Section 1 starts.
6. Publisher box at the **bottom of page 1** (in Word a floating table anchored there;
   LibreOffice's render wrongly moves it to page 2): 8 pt, one rule above (top border only),
   full text width, no cell padding. Text from the sample:
   "Klingner, S., Wagenseil, H., Merita, P., Pauly, P. & Schymik, C. (Hrsg.) (2027): 3. Forum
   GEO.KI. Modelle, Methoden, Mehrwert – KI-gestützte Geodatenanalyse von der Infrastruktur bis
   zur Anwendung. © Wichmann Verlag, VDE VERLAG GMBH · Berlin · Offenbach.
   ISBN 978-3-87907-7xx-x, doi:10.14627/537xxxxxx."
   LaTeX: a box placed absolutely just above the bottom margin of page 1 (e.g.
   `\AddToHookNext{shipout/foreground}` with `\put`), containing `\rule{\textwidth}{0.5pt}` and
   the 8 pt text; reserve its height on page 1 so body text does not run into it.
