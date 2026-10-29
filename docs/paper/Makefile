# Build the paper with pdfLaTeX + BibTeX. Output: build/main.pdf, copied to main.pdf
# (main.pdf is committed so the current state can be read without a TeX installation)
LATEX   = pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build
BUILD   = build

.PHONY: all clean

all: main.pdf

main.pdf: $(BUILD)/main.pdf
	cp $(BUILD)/main.pdf main.pdf

$(BUILD)/main.pdf: main.tex paper-style.sty wichmann.bst references.bib chapters/*.tex tables/*
	mkdir -p $(BUILD)
	$(LATEX) main.tex
	cd $(BUILD) && BIBINPUTS=..: BSTINPUTS=..: bibtex main
	$(LATEX) main.tex
	$(LATEX) main.tex

clean:
	rm -rf $(BUILD)
