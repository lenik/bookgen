# BookGen

BookGen is a Python CLI wrapper for long-form generation workflows on top of Ollama-compatible and OpenAI-compatible chat APIs.

It generates chapter-by-chapter, summarizes each chapter into a continuity bridge for the next step, and persists all outputs to files.

Author: Lenik (<bookgen@bodz.net>)

License: AGPL-3.0-or-later with an additional anti-AI usage statement (see `LICENSE`).

## Build (Meson)

BookGen uses Meson. The executable installed by Meson gets its `--version` value from `project(version: ...)` via Meson substitution.

```bash
meson setup build
meson compile -C build
meson install -C build
```

## Features

- Chapter generation loop with context isolation per chapter
- Automatic continuity summary (`chapter_XX_summary.txt`) between chapters
- Retry logic for timeout/connection failures
- Real-time chapter streaming with `-e/--echo`
- Model auto-discovery when `--model` is not specified
  - Ollama running model first (`/api/ps`)
  - then installed models (`/api/tags`)
- Flexible chapter selection and synthetic chapter title formatting

## Install

Requirements:

- Python 3.9+
- `requests`

Install dependency:

```bash
python3 -m pip install requests
```

## Usage

```bash
python3 bookgen.py [OPTIONS] FILES...
```

Example:

```bash
python3 bookgen.py source/story.txt source/story-toc.txt \
  -S "http://localhost:11434/api" \
  -t ollama \
  -o output \
  -n 1..3 \
  -c "第%d章" \
  -l Chinese \
  -e -v
```

## CLI options

- `-S/--service URL` service URL
- `-t/--type TYPE` service type: `ollama` (default) or `openai`
- `-m/--model MODEL` model name (optional; auto-discovered if omitted)
- `-C/--context SIZE` context size
- `-o/--outdir PATH` output directory
- `-s/--summary-size NUM` summary target size in words (default: `300`)
- `-n/--chapter NUM|N..M` chapter range (`1..NUM` or `N..M`)
- `-c/--chapter-format SPEC` chapter title format with `%d` placeholder
- `-l/--lang LANG` output language
- `-e/--echo` stream chapter output to stdout while generating
- `-v/--verbose` increase verbosity (repeatable)
- `-q/--quiet` decrease verbosity (repeatable)
- `--version`
- `-h/--help`

## Output structure

```text
output/
  chapter_01.md
  chapter_01_summary.txt
  chapter_02.md
  chapter_02_summary.txt
  ...
  full_book.md
```

## Demo

Use the bundled Red Hat demo content:

```bash
make -C demo/redhat generate
```

## Shell completion and man page

When installed with Meson, BookGen installs:

- man page: `bookgen(1)`
- bash completion: `/usr/share/bash-completion/completions/bookgen`
