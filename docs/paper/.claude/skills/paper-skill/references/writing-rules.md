# Writing rules

From `template/Hinweise_Tagungsband.pdf` (sections 1.1, 1.2, 2.1-2.12) and the examples in
`template/Mustertext_Tagungsband.docx`. Rules marked **DE** apply only to a German paper.

## Typography

| Rule | LaTeX |
|---|---|
| Always real umlauts and ß: Gräler, Münster, Straße - never ae/oe/ue/ss transliterations (team convention, also in English text and in `.bib`) | type them directly (UTF-8 source) |
| Typographic quotes; DE „…“, EN “…” | `\enquote{}` (`csquotes`) or `"`/`` ` `` babel shorthands; never straight `"` |
| Dash: en dash with spaces – as a dash | ` -- `; hyphen `-` only inside words |
| No manual hyphenation | never `\-` or `-` line breaks in chapters; fix bad breaks via `\hyphenation{}` in the `.sty` |
| Number + unit never split (3 %, 4 m, 50 kg) | non-breaking space `3~\%`, `4~m`; or thin `3\,\%` (pick one, be consistent) |
| Abbreviations with space: z. B., d. h., i. Allg. (**DE**); e.g., i.e. (EN) | `z.\,B.`, `d.\,h.`, `i.\,Allg.` |
| Thousands separator: DE `1.000`, EN `1,000` | write it out; no `siunitx` (not installed) |
| Percent values keep a (non-breaking) space in DE: `95,3~\%`; EN usual: `95.3\%` | choose per language, consistent |
| Only fonts/special characters that ship with MS Word/Windows | Times New Roman + its glyphs; no exotic symbols |
| New German spelling (**DE**) | - |
| Gender-fair language with colon: Autor:innen, Expert:innen; or neutral forms (das Team, die Studierenden) (**DE**) | write `Autor:innen` directly |
| No empty paragraphs/lines for spacing | no `\\`, `\vspace`, `\bigskip`, `\newline` in chapters |

## Structure

- Title: meaningful; multi-line titles break at a sensible point (`\\` in the title only).
- Authors: full first and last name (**sample**: first name normal case, last name normal case;
  guidelines 2.2 says "Nachname in Großschreibung" - the sample does not do this, follow the sample).
- Headings numbered by hand style: "1", "1.1", "1.1.1"; no level skipped; at least one
  subheading level used where sections are long. Unnumbered only: "Zusammenfassung"/"Abstract",
  "Literatur"/"References".
- Use real lists (`itemize`/`enumerate`), no fake bullets; no skipped list levels.
- Footnotes via `\footnote{}`; cross-references via `\label`/`\ref`, never hard-coded numbers.
- Links as real hyperlinks (`\url{}` / `\href{}`).

## Citations in the text (guidelines 2.10)

Author surnames only, author-year, **no comma between name and year**, page after a comma.

| Situation | Format | natbib (with matching style) |
|---|---|---|
| In the sentence | Name (2020) / Name (2020, 144) | `\citet{key}` / `\citet[144]{key}` |
| Two authors | Name1 & Name2 (2020) / (2020, 89 f.) | `\citet` |
| Three or more | Name et al. (2020) / (2020, 3) | `\citet` |
| End of sentence | (Name 2010) / (Name 2020, 144) | `\citep{key}` / `\citep[144]{key}` |
| End, two authors | (Name1 & Name2 2020) | `\citep` |
| End, et al. | (Name et al. 2020) | `\citep` |
| Several | (Name1 2020, Name2 2020, Name3 et al. 2020) - separated by **comma** | `\citep{a,b,c}` |
| Several with pages | (Name1 2020, 144; Name2 2020, 67; Name3 et al. 2020, 189) - separated by **semicolon** | write the parenthesis by hand with `\citealp[144]{a}; ...` |

natbib setup that yields this: `\setcitestyle{authoryear,round,citesep={,},aysep={},notesep={, }}`,
"&" instead of "and" and "et al." from three authors on come from `docs/paper/paper.bst`.
The Google Doc uses APA ("Vila et al., 2014") - every citation in LaTeX uses `\citep`/`\citet`.

## Bibliography (guidelines 2.11, sample "Literatur")

Heading "Literatur" (EN "References"), unnumbered, formatted like `Überschrift 1`. Entries
sorted alphabetically by first author, style `Literaturliste` (hanging 0.5 cm, after 3 pt).

| Type | Pattern (from the sample) |
|---|---|
| Book | `Lob, R. (1997): 20 Jahre Umweltbildung in Deutschland – eine Bilanz. Köln.` |
| Book, two places | `Engels-Wilhelmi, S. (1993): Title – Subtitle. Bonn/Bad Godesberg.` |
| Chapter in edited book | `Gebhard, U. (2005): Title. Subtitle. In: Unterbruner, U. & Forum Umweltbildung (Hrsg.): Book Title. Innsbruck/Wien/Bozen, 23-42.` |
| Journal / series | `Jelitto, M. (2000): Title. In: Deutsche Gesellschaft für Umwelterziehung, Nachrichten, 21, 16-20.` |
| Two authors | `Wolf, G. & Sauerborn, P. (2000): Title. ...` |
| Organisation as author | `Niedersächsisches Kultusministerium (2001): Title. Hannover.` / abbreviation first: `BMBWK – Bundesministerium für ... (2006): ...` |
| No year | `(o. J.)` (EN "(n.d.)") |
| Web source | `Schilcher, M. & Plabst, S. (2006): GIS Glossar. http://www.gis1.bv.tum.de (11.04.2006).` |

Web rules: no "URL:", "Web:", "available at", "last visited" before or after the address;
access date in parentheses, separated by one space, format `DD.MM.YYYY`.

Details:
- Author: `Surname, Initial.`; several authors joined by `,` and the last by ` & `.
- Year in parentheses, followed by a colon: `(2020):`.
- Editors marked `(Hrsg.)` (EN `(Eds.)`).
- Page ranges with a hyphen `23-42` (sample), no "pp.".
- Conference proceedings follow the "Chapter in edited book" pattern
  (`In: Editors (Hrsg.): Proceedings title. Place, pages.`).
- DOI: give as `https://doi.org/...` like a web source but without access date (the guidelines
  are silent on DOIs; keep it short and consistent).

### Implementation: `paper.bst` + `references.bib`

`docs/paper/paper.bst` produces exactly these patterns from BibTeX entries (`@article`,
`@inproceedings`/`@incollection`, `@book`, `@misc`/`@online`). Conventions for `references.bib`:

- First names as initials, as the bibliography shows them: `author = {Vila, M. and Martí, M. A.}`.
- Names and titles in UTF-8 (`Martí`, `Gräler`). Exception: an initial that is itself a
  non-ASCII letter must be TeX-escaped (`{\"O}.`), BibTeX's initials function cuts UTF-8 bytes.
- Titles in double braces `{{...}}` so the original capitalisation survives.
- Page ranges as `205--218`; the style prints them with a hyphen.
- Place in `address`; if there is none, `publisher` is printed in its place.
- DOI in `doi` (printed as `https://doi.org/...`); web sources in `url` + `urldate = {11.04.2006}`.
- Language words come from macros in `paper-style.sty`: `\bibinname`, `\bibedsname`,
  `\bibnodatename`.

Our three references converted (EN paper):

```
Kovatchev, V., Martí, M. A. & Salamó, M. (2018): ETPC – A Paraphrase Identification Corpus
  Annotated with Extended Paraphrase Typology and Negation. In: Proceedings of the Eleventh
  International Conference on Language Resources and Evaluation (LREC 2018). Miyazaki.
Vila, M., Martí, M. A. & Rodríguez, H. (2014): Is This a Paraphrase? What Kind? Paraphrase
  Boundaries and Typology. In: Open Journal of Modern Linguistics, 4 (1), 205-218.
  https://doi.org/10.4236/ojml.2014.41016
Wahle, J. P., Ruas, T., Xu, Y. & Gipp, B. (2024): Paraphrase Types Elicit Prompt Engineering
  Capabilities. In: Al-Onaizan, Y., Bansal, M. & Chen, Y.-N. (Eds.): Proceedings of the 2024
  Conference on Empirical Methods in Natural Language Processing. Association for
  Computational Linguistics, 11004-11033. https://doi.org/10.18653/v1/2024.emnlp-main.617
```


## Figures and tables in the text

- Always write the word out: "Abbildung 1", "Tabelle 1" (EN "Figure 1", "Table 1"); never
  "Abb."/"Tab."/"Fig.". LaTeX: `Abbildung~\ref{fig:x}` or a `\figref` macro from the `.sty`.
- Numbering consecutive through the paper (figures and tables separately).
- Caption above, source line below - every figure and every table gets a source line.
- Source lines (`Abbildungsquelle`/`Tabellenquelle`):
  - own work: "Quelle: eigene Darstellung"
  - book/journal, with page: "Quelle: Bill 2023, 306"
  - web: "Quelle: https://statistikinteraktiv.augsburg.de/Interaktiv/; Stadt Augsburg"
    (address first, then the site operator)
  - maps with external data: "Datenquelle: http://www.openstreetmap.org/#map=19/48.22853/16.36850;
    © OpenStreetMap-Mitwirkende, http://www.openstreetmap.org/copyright"
- External figures need a reprint permission **before** submission; the credit line given with
  the permission goes into the source line.

## Accessibility (guidelines 1.3)

- All text searchable; no scanned text images.
- Every informative figure has alt text that can replace it; complex figures (diagrams,
  process charts) additionally get a full description in the nearby text.
  LaTeX: `\includegraphics[alt={...}]{...}` (works with tagging in LuaLaTeX); keep the alt text in
  the source even while tagging is not active.
- Colour contrast ≥ 3:1 in graphics, ≥ 4.5:1 for text in figures; never encode information by
  colour alone.
- Tables only for data, simple, with a header row, no merged cells, no empty rows/columns.
- Formulas get an ASCII-math alt text (examples from the guidelines):
  `a/b`, `a * b` or `a xx b`, `a <= b`, `a >= b`, `a != b`, `x^2`, `x_i`, `sqrt(x)`,
  `root(n)(x)`, Greek written out (`alpha`, `Delta`), `sum_(i=1)^n i`, `int_a^b f(x) dx`,
  `lim_(x -> oo)`, `oo`, matrix `[[a, b], [c, d]]`.

## Labels (DE / EN)

| Purpose | German (sample) | English |
|---|---|---|
| Figure caption | **Abbildung 1:** | **Figure 1:** |
| Table caption | **Tabelle 1:** | **Table 1:** |
| Source line | Quelle: | Source: |
| Own work | eigene Darstellung | own illustration |
| Data source (maps) | Datenquelle: | Data source: |
| Abstract heading | Zusammenfassung | Abstract |
| Bibliography heading | Literatur | References |
| Editors | (Hrsg.) | (Eds.) |
| No year | (o. J.) | (n.d.) |
| Authors joined | und | and |
| Odd running head (authors) | R. Flores & B. Gräler | R. Flores & B. Gräler |
| Even running head | 3. Forum GEO.KI | 3. Forum GEO.KI (volume title, unchanged) |
