LATEX := lualatex
LATEX_FLAGS := -interaction=nonstopmode -halt-on-error
TEX_SOURCES := $(filter-out settings.tex,$(wildcard *.tex))
PDFS := $(TEX_SOURCES:.tex=.pdf)

.PHONY: all clean

all: $(PDFS)

%.pdf: %.tex settings.tex
	$(LATEX) $(LATEX_FLAGS) $<
	$(LATEX) $(LATEX_FLAGS) $<

clean:
	rm -f *.aux *.log *.out *.toc *.lof *.lot *.fls *.fdb_latexmk *.synctex.gz *.xdv
