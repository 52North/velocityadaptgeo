# Paper

LaTeX rebuild of the formatting template in `template/` (guidelines PDF + Word template).

## Build

```sh
make        # -> build/main.pdf, copied to main.pdf (pdfLaTeX + BibTeX)
make clean
```

Requires `pdflatex` and `bibtex` (TeX Live). `latexmk`, `biber` and `biblatex` are not
needed.

## Layout

| Path              | Content                                                       |
|-------------------|---------------------------------------------------------------|
| `main.tex`        | Document frame: title, order of chapters, bibliography        |
| `paper-style.sty` | **All** formatting (fonts, margins, headings, captions, ...)  |
| `references.bib`  | Bibliography (BibTeX)                                         |
| `wichmann.bst`    | BibTeX style in the publisher's format (author-year, natbib)  |
| `chapters/`       | Text only, one file per section                               |
| `tables/`         | Data as `*.csv` plus one thin `tab-*.tex` wrapper per table   |
| `figures/`        | Images, referenced without the folder prefix                  |
| `template/`       | Delivered guidelines, Word template and our abstract exports; local only, ignored by git |

## Conventions

- No formatting commands in `chapters/`; if something needs to look different,
  change `paper-style.sty`.
- A table is a CSV (the numbers) and a `tab-<name>.tex` (caption, label, column
  layout). Include it with `\input{tables/tab-<name>}`.
- Labels: `sec:`, `tab:`, `fig:` prefixes.
