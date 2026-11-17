# Build the paper with LuaLaTeX (pdfLaTeX as fallback) + BibTeX.
# Output: build/main.pdf, copied to main.pdf (committed, readable without a TeX installation).
# LuaLaTeX is needed for Times New Roman / Liberation Serif: pacman -S texlive-luatex
ENGINE := $(if $(shell kpsewhich luaotfload-main.lua),lualatex,pdflatex)
LATEX   = $(ENGINE) -interaction=nonstopmode -halt-on-error -output-directory=build
BUILD   = build

.PHONY: all docx clean

all: main.pdf

# Word version for the publisher: build/main.docx in the styles of the Word template.
# Needs pandoc and the local template/ files; uses build/main.bbl from the PDF build.
REFDOC = template/Mustertext_Tagungsband.docx

docx: $(BUILD)/main.docx

$(BUILD)/main.docx: $(BUILD)/main.pdf $(REFDOC) docx/shim.tex docx/paper.lua docx/postprocess.py figures/*
	pandoc docx/shim.tex main.tex -f latex -t docx+native_numbering \
	  --reference-doc=$(REFDOC) --number-sections --figure-caption-position=above \
	  --resource-path=.:figures --default-image-extension=png -M lang=en-US \
	  --lua-filter=docx/paper.lua -o $@
	python3 docx/postprocess.py $@ main.tex

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
