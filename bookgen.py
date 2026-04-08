#!/usr/bin/env python3
"""
BookGen: chapter-by-chapter long-form generation wrapper.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests

VERSION = "@MESON_PROJECT_VERSION@"
if VERSION.startswith("@") and VERSION.endswith("@"):
    VERSION = "1.0.0-dev"

DEFAULT_OLLAMA_URL = "http://localhost:11434/api"
DEFAULT_OPENAI_URL = "http://localhost:11434/v1"
DEFAULT_SUMMARY_SIZE = 300
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_RETRIES = 3


@dataclass
class Config:
    service_url: str
    service_type: str
    model: str
    context_size: Optional[int]
    outdir: Path
    summary_size: int
    lang: str
    chapter_spec: Optional[str]
    chapter_format: Optional[str]
    fast: bool
    verbosity: int
    echo: bool


def log(cfg: Config, level: int, *args: object, **kwargs: object) -> None:
    # level 0: normal progress, 1: verbose, 2+: debug detail
    if cfg.verbosity >= level:
        print(*args, file=sys.stderr, **kwargs)


def load_dotenv(path: Path = Path(".env")) -> Dict[str, str]:
    env_map: Dict[str, str] = {}
    if not path.exists():
        return env_map
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        env_map[key] = value
    return env_map


def load_yaml(path: Path = Path("config.yaml")) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bookgen.py",
        description="Generate long-form content chapter-by-chapter with Ollama/OpenAI-style APIs.",
    )
    parser.add_argument("files", nargs="*", help="Input source files. First file determines default output dir.")
    parser.add_argument("-S", "--service", dest="service_url", help="Service URL.")
    parser.add_argument(
        "-t",
        "--type",
        dest="service_type",
        choices=["ollama", "openai"],
        default=None,
        help="Service type: ollama (default), openai.",
    )
    parser.add_argument("-m", "--model", dest="model", help="Model name.")
    parser.add_argument("-C", "--context", dest="context_size", type=int, help="Context size.")
    parser.add_argument("-o", "--outdir", dest="outdir", help="Output directory.")
    parser.add_argument(
        "-s",
        "--summary-size",
        dest="summary_size",
        type=int,
        default=None,
        help=f"Summary size in words, default {DEFAULT_SUMMARY_SIZE}.",
    )
    parser.add_argument(
        "-n",
        "--chapter",
        dest="chapter_spec",
        help="Chapter range: NUM (1..NUM) or N..M.",
    )
    parser.add_argument(
        "-c",
        "--chapter-format",
        dest="chapter_format",
        help='Chapter title format with %%d, e.g. "subsection 1.%%d", "第%%d章".',
    )
    parser.add_argument("-f", "--fast", action="store_true", help="Disable think/reasoning output mode.")
    parser.add_argument("-l", "--lang", dest="lang", help="Output language. Auto-detected by model and inputs if omitted.")
    parser.add_argument("-e", "--echo", action="store_true", help="Echo generated chapter content to stdout in real-time.")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (repeatable: -v, -vv).")
    parser.add_argument("-q", "--quiet", action="count", default=0, help="Decrease verbosity (repeatable: -q, -qq).")
    parser.add_argument("--version", action="store_true", help="Print version and exit.")
    return parser.parse_args(argv)


def derive_default_outdir(first_file: Path) -> Path:
    return first_file.parent / first_file.stem


def parse_chapters_from_toc(text: str) -> List[str]:
    chapters: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                chapters.append(title)
            continue
        if re.match(r"^\d+[\.\)]\s+.+", stripped):
            chapters.append(re.sub(r"^\d+[\.\)]\s+", "", stripped))
            continue
        if re.match(r"^(chapter|ch\.?)\s+\d+[:\-\s].+", stripped, flags=re.IGNORECASE):
            chapters.append(stripped)
            continue
    # Preserve order while deduplicating.
    seen = set()
    uniq = []
    for ch in chapters:
        norm = ch.lower().strip()
        if norm in seen:
            continue
        seen.add(norm)
        uniq.append(ch)
    return uniq


def parse_chapter_spec(spec: str) -> Tuple[int, int]:
    raw = spec.strip()
    if not raw:
        raise ValueError("Empty chapter range.")
    if ".." in raw:
        parts = raw.split("..", 1)
        if len(parts) != 2 or not parts[0].strip().isdigit() or not parts[1].strip().isdigit():
            raise ValueError(f"Invalid chapter range '{spec}'. Use NUM or N..M.")
        start = int(parts[0].strip())
        end = int(parts[1].strip())
    else:
        if not raw.isdigit():
            raise ValueError(f"Invalid chapter range '{spec}'. Use NUM or N..M.")
        start = 1
        end = int(raw)
    if start < 1 or end < 1 or end < start:
        raise ValueError(f"Invalid chapter range '{spec}'. Start/end must be >=1 and start<=end.")
    return start, end


def format_chapter_title(chapter_format: str, number: int) -> str:
    if "%d" not in chapter_format:
        raise ValueError("Chapter format must include %d placeholder, e.g. '第%d章'.")
    try:
        return chapter_format % number
    except Exception as exc:
        raise ValueError(f"Invalid chapter format '{chapter_format}': {exc}") from exc


def infer_toc_file(paths: List[Path]) -> Path:
    for p in paths:
        name = p.name.lower()
        if "toc" in name or "table-of-contents" in name or "contents" in name:
            return p
    return paths[-1]


def build_global_material(paths: Iterable[Path], toc_file: Path) -> str:
    parts: List[str] = []
    for p in paths:
        if p == toc_file:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        parts.append(f"## Source: {p.name}\n{text}\n")
    return "\n".join(parts).strip()


def resolve_chat_url(service_url: str, service_type: str) -> str:
    base = service_url.rstrip("/")
    if service_type == "ollama":
        if base.endswith("/api/chat") or base.endswith("/chat"):
            return base
        return base + "/chat"
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def resolve_generate_url(service_url: str) -> str:
    base = service_url.rstrip("/")
    if base.endswith("/api/generate"):
        return base
    if base.endswith("/api"):
        return base + "/generate"
    return base + "/api/generate"


def apply_think_option(payload: Dict[str, object], think_enabled: Optional[bool]) -> None:
    # Best-effort: models/services that do not support think controls will ignore these fields.
    if think_enabled is None:
        return
    # Different models/backends may use different keys.
    payload["think"] = think_enabled
    payload["thinking"] = think_enabled
    options = payload.get("options")
    if isinstance(options, dict):
        options["think"] = think_enabled
        options["thinking"] = think_enabled
    else:
        payload["options"] = {"think": think_enabled, "thinking": think_enabled}


def reset_service_context(cfg: Config) -> None:
    # /clear semantics: clear conversation state only, do not unload/touch model residency.
    # In this API workflow we already send standalone message histories per request,
    # so context reset is represented by request boundaries.
    _ = cfg
    return


def discover_default_model(service_url: str, service_type: str) -> Optional[str]:
    timeout_s = 5
    base = service_url.rstrip("/")
    try:
        if service_type == "ollama":
            # Prefer currently running model(s), equivalent to `ollama ps`.
            if base.endswith("/api/ps"):
                ps_url = base
            elif base.endswith("/api"):
                ps_url = base + "/ps"
            else:
                ps_url = base + "/api/ps"
            resp = requests.get(ps_url, timeout=timeout_s)
            if resp.ok:
                data = resp.json()
                models = data.get("models", [])
                if models:
                    first = models[0]
                    if isinstance(first, dict):
                        running_name = first.get("name") or first.get("model")
                        if running_name:
                            return running_name

            # Ollama native API: /api/tags
            if base.endswith("/api/tags"):
                tags_url = base
            elif base.endswith("/api"):
                tags_url = base + "/tags"
            else:
                tags_url = base + "/api/tags"
            resp = requests.get(tags_url, timeout=timeout_s)
            if resp.ok:
                data = resp.json()
                models = data.get("models", [])
                if models:
                    first = models[0]
                    if isinstance(first, dict):
                        return first.get("name") or first.get("model")
        # OpenAI-compatible API: /v1/models
        models_url = base if base.endswith("/v1/models") else base + "/models"
        resp = requests.get(models_url, timeout=timeout_s)
        if resp.ok:
            data = resp.json()
            models = data.get("data", [])
            if models:
                first = models[0]
                if isinstance(first, dict):
                    return first.get("id")
    except Exception:
        return None
    return None


def stream_ollama_chat(
    service_url: str,
    model: str,
    messages: List[Dict[str, str]],
    context_size: Optional[int],
    timeout_s: int,
    echo: bool,
    think_enabled: Optional[bool],
) -> str:
    url = resolve_chat_url(service_url, "ollama")
    payload: Dict[str, object] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if context_size is not None:
        payload["options"] = {"num_ctx": context_size}
    apply_think_option(payload, think_enabled)
    attempted_without_think = False
    while True:
        with requests.post(url, json=payload, stream=True, timeout=timeout_s) as resp:
            if resp.status_code == 405:
                raise RuntimeError(
                    f"405 Method Not Allowed at {url}. "
                    "Ollama /api/chat requires POST. Verify --type ollama and --service base URL."
                )
            if resp.status_code == 400 and think_enabled is not None and not attempted_without_think:
                # Some models reject explicit think controls. Retry once without them.
                payload.pop("think", None)
                if isinstance(payload.get("options"), dict):
                    payload["options"].pop("think", None)
                attempted_without_think = True
                continue
            if resp.status_code >= 400:
                detail = (resp.text or "").strip()
                if detail:
                    raise RuntimeError(f"Ollama request failed ({resp.status_code}) at {url}: {detail}")
            resp.raise_for_status()
            full = []
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                data = json.loads(line)
                token = data.get("message", {}).get("content", "")
                if token:
                    if echo:
                        print(token, end="", flush=True)
                    full.append(token)
            if echo:
                print("")
            return "".join(full).strip()


def stream_openai_chat(
    service_url: str,
    model: str,
    messages: List[Dict[str, str]],
    context_size: Optional[int],
    timeout_s: int,
    echo: bool,
    think_enabled: Optional[bool],
) -> str:
    url = resolve_chat_url(service_url, "openai")
    payload: Dict[str, object] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if context_size is not None:
        payload["max_tokens"] = context_size
    apply_think_option(payload, think_enabled)

    with requests.post(url, json=payload, stream=True, timeout=timeout_s) as resp:
        if resp.status_code == 405:
            raise RuntimeError(
                f"405 Method Not Allowed at {url}. "
                "OpenAI-style /chat/completions requires POST. Verify --type openai and --service base URL."
            )
        resp.raise_for_status()
        full = []
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith("data: "):
                raw = raw[6:]
            if raw.strip() == "[DONE]":
                break
            data = json.loads(raw)
            choices = data.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})
            token = delta.get("content", "")
            if token:
                if echo:
                    print(token, end="", flush=True)
                full.append(token)
        if echo:
            print("")
        return "".join(full).strip()


def chat_stream(
    cfg: Config,
    messages: List[Dict[str, str]],
    timeout_s: int = DEFAULT_TIMEOUT_SECONDS,
    echo: bool = False,
    think_enabled: Optional[bool] = None,
) -> str:
    if cfg.service_type == "ollama":
        return stream_ollama_chat(
            cfg.service_url, cfg.model, messages, cfg.context_size, timeout_s, echo, think_enabled
        )
    return stream_openai_chat(
        cfg.service_url, cfg.model, messages, cfg.context_size, timeout_s, echo, think_enabled
    )


def call_with_retries(
    cfg: Config,
    messages: List[Dict[str, str]],
    retries: int = DEFAULT_RETRIES,
    echo: bool = False,
    think_enabled: Optional[bool] = None,
) -> str:
    for attempt in range(1, retries + 1):
        try:
            return chat_stream(cfg, messages, echo=echo, think_enabled=think_enabled)
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt == retries:
                raise RuntimeError(f"Failed after {retries} attempts: {exc}") from exc
            log(cfg, 0, f"Request failed ({exc}). Retrying {attempt}/{retries}...")
            time.sleep(min(2 * attempt, 8))
    raise RuntimeError("Unexpected retry termination.")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def dump_input_bundle(path: Path, messages: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps({"messages": messages}, ensure_ascii=False, indent=2)
    path.write_text(serialized + "\n", encoding="utf-8")


def build_generation_prompt(
    chapter_idx: int,
    chapter_title: str,
    toc_text: str,
    global_material: str,
    prev_summary: str,
    lang: str,
    fast: bool,
) -> List[Dict[str, str]]:
    system = (
        "You are a professional long-form writer. Follow the provided context and TOC. "
        "Write clear, coherent, chapter-level content in markdown."
    )
    user = f"""
Global Materials:
{global_material}

Table of Contents:
{toc_text}

Previous Chapter Summary:
{prev_summary or "N/A (this is the first chapter)."}

Task:
Write Chapter {chapter_idx}: {chapter_title}.
Requirements:
- Output only the chapter in markdown.
- Keep continuity with prior summary.
- Do not write future chapters.
- Write in {lang}.
{"- Fast mode: do not output <think> tags or reasoning traces." if fast else "- If supported by the model, keep think/reasoning mode enabled for chapter generation."}
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_summary_prompt(chapter_markdown: str, summary_size: int, lang: str) -> List[Dict[str, str]]:
    system = "You create concise continuity summaries for future generation."
    user = f"""
/no_think

Summarize the following chapter for use as context in the next chapter.
Target length: about {summary_size} words.
Focus on key events, decisions, character/argument state, unresolved threads, and tone.
Write the summary in {lang}.
Do not output any <think> tags or hidden reasoning.

Chapter text:
{chapter_markdown}
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_summary_nothink(
    cfg: Config,
    summary_messages: List[Dict[str, str]],
) -> str:
    # Keep summary request simple: pass think-off payload once, then sanitize output.
    text = call_with_retries(cfg, summary_messages, echo=cfg.echo, think_enabled=False).strip()
    return strip_think_blocks(text).strip()


def resolve_config(args: argparse.Namespace, input_paths: List[Path]) -> Config:
    env_data = load_dotenv()
    yaml_data = load_yaml()

    service_type = args.service_type or str(
        env_data.get("BOOKGEN_SERVICE_TYPE") or yaml_data.get("service_type") or "ollama"
    ).lower()
    if service_type not in ("ollama", "openai"):
        raise ValueError(f"Unsupported service type: {service_type}")

    default_service = DEFAULT_OLLAMA_URL if service_type == "ollama" else DEFAULT_OPENAI_URL
    service_url = (
        args.service_url
        or env_data.get("BOOKGEN_SERVICE_URL")
        or str(yaml_data.get("service_url") or default_service)
    )

    configured_model = args.model or env_data.get("BOOKGEN_MODEL") or yaml_data.get("model")
    model = str(configured_model).strip() if configured_model else ""
    if not model:
        discovered = discover_default_model(service_url, service_type)
        if discovered:
            model = discovered
        else:
            model = "llama3.1"
    context_size = args.context_size or _as_int(env_data.get("BOOKGEN_CONTEXT")) or _as_int(yaml_data.get("context"))
    summary_size = args.summary_size or _as_int(env_data.get("BOOKGEN_SUMMARY_SIZE")) or _as_int(
        yaml_data.get("summary_size")
    )
    if summary_size is None:
        summary_size = DEFAULT_SUMMARY_SIZE
    lang = (
        args.lang
        or str(env_data.get("BOOKGEN_LANG") or yaml_data.get("lang") or "").strip()
        or infer_language(model, input_paths)
    )
    outdir = Path(args.outdir) if args.outdir else derive_default_outdir(input_paths[0])

    return Config(
        service_url=service_url,
        service_type=service_type,
        model=model,
        context_size=context_size,
        outdir=outdir,
        summary_size=summary_size,
        lang=lang,
        chapter_spec=args.chapter_spec,
        chapter_format=args.chapter_format,
        fast=bool(args.fast),
        verbosity=(args.verbose or 0) - (args.quiet or 0),
        echo=bool(args.echo),
    )


def _as_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value))
    except Exception:
        return None


def infer_language(model: str, input_paths: List[Path]) -> str:
    model_l = model.lower()
    if "zh" in model_l or "chinese" in model_l:
        return "Chinese"
    if "ja" in model_l or "japanese" in model_l:
        return "Japanese"
    if "ko" in model_l or "korean" in model_l:
        return "Korean"

    sample_chunks: List[str] = []
    for path in input_paths[:3]:
        try:
            sample_chunks.append(path.read_text(encoding="utf-8", errors="ignore")[:2000])
        except Exception:
            continue
    sample = "\n".join(sample_chunks)

    if re.search(r"[\u4e00-\u9fff]", sample):
        return "Chinese"
    if re.search(r"[\u3040-\u30ff]", sample):
        return "Japanese"
    if re.search(r"[\uac00-\ud7af]", sample):
        return "Korean"
    return "English"


def build_full_book(outdir: Path, chapter_files: List[Path]) -> Path:
    full_book_path = outdir / "full_book.md"
    parts = [strip_think_blocks(p.read_text(encoding="utf-8")) for p in chapter_files]
    full_book_path.write_text("\n\n".join(parts).strip() + "\n", encoding="utf-8")
    return full_book_path


def strip_think_blocks(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)


def validate_files(paths: List[Path]) -> None:
    missing = [str(p) for p in paths if not p.exists() or not p.is_file()]
    if missing:
        raise FileNotFoundError(f"Input file(s) not found: {', '.join(missing)}")


def run(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.version:
        print(VERSION)
        return 0
    if not args.files:
        raise RuntimeError("At least one input file is required. Use --help for usage.")

    input_paths = [Path(p) for p in args.files]
    validate_files(input_paths)
    cfg = resolve_config(args, input_paths)
    cfg.outdir.mkdir(parents=True, exist_ok=True)

    toc_path = infer_toc_file(input_paths)
    toc_text = toc_path.read_text(encoding="utf-8", errors="replace")
    chapters = parse_chapters_from_toc(toc_text)
    if not chapters:
        raise RuntimeError("No chapters detected in TOC. Use markdown headings, numbered lines, or Chapter-style lines.")

    if cfg.chapter_spec:
        start, end = parse_chapter_spec(cfg.chapter_spec)
        if cfg.chapter_format:
            fmt = cfg.chapter_format
            chapters = [format_chapter_title(fmt, i) for i in range(start, end + 1)]
        else:
            if end > len(chapters):
                raise RuntimeError(
                    f"Requested chapter range {start}..{end}, but TOC has only {len(chapters)} chapters."
                )
            chapters = chapters[start - 1 : end]
    elif cfg.chapter_format:
        fmt = cfg.chapter_format
        chapters = [format_chapter_title(fmt, i) for i in range(1, len(chapters) + 1)]

    global_material = build_global_material(input_paths, toc_path)

    log(cfg, 1, f"Using TOC: {toc_path}")
    log(cfg, 1, f"Output directory: {cfg.outdir}")
    log(cfg, 1, f"Detected chapters: {len(chapters)}")
    log(cfg, 1, f"Output language: {cfg.lang}")
    log(cfg, 1, f"Model: {cfg.model}")
    log(cfg, 2, f"Service type/url: {cfg.service_type} {cfg.service_url}")

    previous_summary = ""
    chapter_files: List[Path] = []

    for idx, title in enumerate(chapters, start=1):
        reset_service_context(cfg)
        log(cfg, 0, f"\n=== Generating chapter {idx}/{len(chapters)}: {title} ===")
        gen_messages = build_generation_prompt(idx, title, toc_text, global_material, previous_summary, cfg.lang, cfg.fast)
        if cfg.verbosity >= 1:
            dump_input_bundle(cfg.outdir / f"chapter_{idx:02d}.input", gen_messages)
        chapter_text = call_with_retries(
            cfg,
            gen_messages,
            echo=cfg.echo,
            think_enabled=(False if cfg.fast else True),
        )
        if cfg.fast:
            chapter_text = strip_think_blocks(chapter_text).strip()

        chapter_file = cfg.outdir / f"chapter_{idx:02d}.md"
        write_text(chapter_file, chapter_text)
        chapter_files.append(chapter_file)
        log(cfg, 1, f"Wrote {chapter_file}")

        log(cfg, 0, f"--- Summarizing chapter {idx} for continuity ---")
        chapter_text_for_summary = strip_think_blocks(chapter_text).strip()
        summary_messages = build_summary_prompt(chapter_text_for_summary, cfg.summary_size, cfg.lang)
        summary_text = generate_summary_nothink(cfg, summary_messages)
        summary_file = cfg.outdir / f"chapter_{idx:02d}_summary.txt"
        write_text(summary_file, summary_text)
        previous_summary = summary_text
        log(cfg, 1, f"Wrote {summary_file}")

        reset_service_context(cfg)
        log(cfg, 0, "--- Context reset complete ---")

    full_book = build_full_book(cfg.outdir, chapter_files)
    log(cfg, 0, f"\nDone. Full book: {full_book}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
