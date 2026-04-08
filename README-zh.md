# BookGen

BookGen 是一个 Python 命令行工具，用于在 Ollama 兼容接口和 OpenAI 兼容接口之上执行长文（如书籍/报告）分章节生成流程。

它会按章节生成正文，并为每章生成“连续性摘要”用于下一章上下文，同时将所有结果持久化到文件。

作者：Lenik（<bookgen@bodz.net>）

许可证：AGPL-3.0-or-later，并附加 反-AI 使用声明（见 `LICENSE`）。

## 构建（Meson）

BookGen 使用 Meson。通过 Meson 安装的可执行文件，其 `--version` 来自 `project(version: ...)` 的自动替换。

```bash
meson setup build
meson compile -C build
meson install -C build
```

## 功能

- 分章节生成循环，每章上下文隔离
- 自动生成章节摘要（`chapter_XX_summary.txt`）用于衔接下一章
- 请求超时/连接失败自动重试
- 支持 `-e/--echo` 进行实时打字机式输出
- 未指定 `--model` 时自动发现模型
  - 优先使用 Ollama 当前运行模型（`/api/ps`）
  - 其次使用已安装模型（`/api/tags`）
- 支持章节范围和章节标题格式化

## 安装

依赖：

- Python 3.9+
- `requests`

安装依赖：

```bash
python3 -m pip install requests
```

## 使用

```bash
python3 bookgen.py [OPTIONS] FILES...
```

示例：

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

## CLI 选项

- `-S/--service URL` 服务地址
- `-t/--type TYPE` 服务类型：`ollama`（默认）或 `openai`
- `-m/--model MODEL` 指定模型（可选；未指定时自动发现）
- `-C/--context SIZE` 上下文大小
- `-o/--outdir PATH` 输出目录
- `-s/--summary-size NUM` 摘要目标字数（默认：`300`）
- `-n/--chapter NUM|N..M` 章节范围（`1..NUM` 或 `N..M`）
- `-c/--chapter-format SPEC` 章节标题格式，需包含 `%d` 占位符
- `-l/--lang LANG` 输出语言
- `-e/--echo` 生成时将章节实时输出到 stdout
- `-v/--verbose` 增加日志级别（可重复）
- `-q/--quiet` 降低日志级别（可重复）
- `--version`
- `-h/--help`

## 输出结构

```text
output/
  chapter_01.md
  chapter_01_summary.txt
  chapter_02.md
  chapter_02_summary.txt
  ...
  full_book.md
```

## 演示

使用内置 小红帽 示例内容：

```bash
make -C demo/redhat generate
```

## Shell 补全与 man 手册

通过 Meson 安装时，BookGen 会安装：

- man 手册：`bookgen(1)`
- Bash 补全：`/usr/share/bash-completion/completions/bookgen`
