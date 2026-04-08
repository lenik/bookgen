PYTHON ?= python3
BOOKGEN ?= ../../bookgen.py
#MODEL ?= llama3.1
SERVICE ?= http://localhost:11434/api
OUTDIR ?= output
CHAPTERS ?= 3
BOOK_LANG ?= Chinese
FORMAT ?= 第%d章
.PHONY: help generate clean

all: generate

help:
	@echo "Targets:"
	@echo "  make generate   # 运行 BookGen 生成章节"
	@echo "  make clean      # 清理输出目录"
	@echo ""
	@echo "Variables (override with make VAR=value):"
	@echo "  MODEL=$(MODEL)"
	@echo "  SERVICE=$(SERVICE)"
	@echo "  OUTDIR=$(OUTDIR)"
	@echo "  CHAPTERS=$(CHAPTERS)"
	@echo "  BOOK_LANG=$(BOOK_LANG)"
	@echo "  FORMAT=$(FORMAT)"

generate:
	$(PYTHON) $(BOOKGEN) -e bookinfo.txt \
		-S "$(SERVICE)" \
		-t ollama \
		-o "$(OUTDIR)" \
		-n "$(CHAPTERS)" \
		-c "$(FORMAT)" \
		-l "$(BOOK_LANG)" \
		-v

clean:
	rm -rf "$(OUTDIR)"
