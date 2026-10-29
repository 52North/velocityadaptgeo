# Build the paper with LuaLaTeX (pdfLaTeX as fallback) + BibTeX.
# Output: build/main.pdf, copied to main.pdf (committed, readable without a TeX installation).
# LuaLaTeX is needed for Times New Roman / Liberation Serif: pacman -S texlive-luatex
ENGINE := $(if $(shell kpsewhich luaotfload-main.lua),lualatex,pdflatex)
LATEX   = $(ENGINE) -interaction=nonstopmode -halt-on-error -output-directory=build
BUILD   = build

.PHONY: all clean

all: main.pdf

main.pdf: $(BUILD)/main.pdf
	cp $(BUILD)/main.pdf main.pdf

$(BUILD)/main.pdf: main.tex paper.cls paper-style.sty paper.bst references.bib chapters/*.tex tables/*
	mkdir -p $(BUILD)
	$(LATEX) main.tex
	cd $(BUILD) && BIBINPUTS=..: BSTINPUTS=..: bibtex main
	$(LATEX) main.tex
	$(LATEX) main.tex

clean:
	rm -rf $(BUILD)
