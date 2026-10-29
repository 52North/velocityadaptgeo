# Build the paper with pdfLaTeX + BibTeX. Output: build/main.pdf
LATEX   = pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build
BUILD   = build

.PHONY: all clean

all: $(BUILD)/main.pdf

$(BUILD)/main.pdf: main.tex paper-style.sty references.bib chapters/*.tex tables/*
	mkdir -p $(BUILD)
	$(LATEX) main.tex
	cd $(BUILD) && BIBINPUTS=..: bibtex main
	$(LATEX) main.tex
	$(LATEX) main.tex

clean:
	rm -rf $(BUILD)
