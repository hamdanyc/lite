# Qualitative Analysis Toolkit

Python tools for analyzing qualitative interview text and historical qualitative articles against XML codebooks. The scripts use language models to suggest semantic phrases or source-grounded evidence, then verify phrase occurrences in the source text.

## Features

- **Text analysis** - process `.txt` interviews using a hierarchical qualitative codebook.
- **HTML analysis** - analyze historical news articles against qualitative-analysis codes.
- **Multiple providers** - use Groq, OpenRouter, or a local llama.cpp server for granular text analysis.
- **Traceable results** - write Markdown summaries and CSV rows linked to article IDs and codebook hierarchy.
- **Local inference** - run the granular workflow without sending article text to a hosted model.


# Workflows

## 1. Granular Interview Analysis

`analyze_granular.py` reads `.txt` files from `data/` by default, extracts codes from `code-book-genai.qdc`, generates semantic phrases, and records verified phrase occurrences.

| Provider | Model | Credentials / service |
|----------|-------|-----------------------|
| `groq` (default) | `qwen/qwen3.8-27b` | `GROQ_API_KEY` |
| `openrouter` | `google/gemma-3-27b-it` | `OPENROUTER_API_KEY` |
| `local` | `gemma-4-E2B-it-Q4_0.gguf` | Local llama.cpp server at `http://127.0.0.1:8080/v1` |

```bash
# Process all .txt files using Groq (default)
python analyze_granular.py

# Select OpenRouter and limit processing to 10 articles
python analyze_granular.py --provider openrouter --max-articles 10

# Use a local llama.cpp server
python analyze_granular.py --provider local
```

The local provider expects the GGUF file at `/mnt/abi-ai/gguf-model/gemma-4-E2B-it-Q4_0.gguf`. Start the server in a separate terminal:

```bash
python -m llama_cpp.server \
  --model /mnt/abi-ai/gguf-model/gemma-4-E2B-it-Q4_0.gguf \
  --host 127.0.0.1 --port 8080 \
  --model_alias gemma-4-E2B-it-Q4_0.gguf
```

Install the optional server package with `pip install 'llama-cpp-python[server]'` if it is not already available.

## 2. HTML qualitative Analysis

`analyze_conflict.py` scans HTML files with Groq. It reads `code-book.qdc` by default and searches for articles in `Articles/` (with fallback locations).

```bash
python analyze_conflict.py --max-articles 25
```

The `run_analysis.sh` wrapper runs this HTML workflow, not `analyze_granular.py`. It accepts an optional article limit:

```bash
./run_analysis.sh       # all matching HTML articles
./run_analysis.sh 10    # at most 10 articles
```

The default Markdown report is `conflict_analysis_results.md` in the current directory.

## 3. Local HTML/Text Analysis

`analyze_conflict_local.py` connects to a separately running llama.cpp server and reads `.txt` articles from `data/` by default. Its defaults are the local GGUF at `/mnt/abi-ai/gguf-model/gemma-4-E2B-it-Q4_0.gguf`, server URL `http://127.0.0.1:8080/v1`, model alias `local-model`, and output `analysis_local.md`.

```bash
python analyze_conflict_local.py --max-articles 25
```

Use `--model-path`, `--base-url`, `--model-name`, `--codebook`, `--articles`, or `--output` to override those defaults. This workflow is separate from the `--provider local` option in `analyze_granular.py`.


# Input-Output

## Input Formats

| Format | Description |
|--------|-------------|
| `.qdc` | XML codebooks containing nested `<Code>` elements and optional descriptions. |
| `.txt` | Interview text files; granular analysis reads from `data/` by default. |
| `.html` | Historical articles; `analyze_conflict.py` reads from `Articles/` by default. |
| `.env` | Optional local environment file for hosted-provider API keys. |

## Output Formats

### Granular Text Analysis

By default, `analyze_granular.py` writes:

| File | Contents |
|------|----------|
| `output/qualitative_analysis_results.md` | Factor, generated semantic phrases, and total verified count. |
| `output/qualitative_analysis_granular.csv` | One row per verified phrase occurrence, with article ID and code hierarchy. |
| `output/codebook.csv` | Code IDs, code names, hierarchy, and descriptions. |
| `output/fileid.csv` | Mapping from generated article IDs to source filenames. |

### HTML Analysis

`analyze_conflict.py` writes a Markdown table with `factor`, `semantic_phrases`, and `count` fields. Its default output is `conflict_analysis_results.md`.


# Configuration

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Skip this copy if you already have a .env file.
if [ ! -f .env ]; then cp .env.example .env; fi
```

Set the relevant key in `.env` or the shell environment before using a hosted provider:

```dotenv
GROQ_API_KEY=your_groq_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
```

The local provider does not require an API key, but it does require the llama.cpp server and GGUF model described above.

## Granular Analysis Options

| Option | Description | Default |
|--------|-------------|---------|
| `--provider` | `groq`, `openrouter`, or `local` | `groq` |
| `--max-articles` / `--max-files` | Maximum number of `.txt` files to process | All files |
| `--codebook` | XML codebook path | `code-book-genai.qdc` |
| `--articles-dir` | Directory containing `.txt` files | `data` |
| `--output` | Markdown report path | `output/qualitative_analysis_results.md` |
| `--csv-output` | Granular occurrence CSV path | `output/qualitative_analysis_granular.csv` |

See each script's `--help` output for its complete set of options.


# Project Structure

```text
.
|-- analyze_granular.py          # Text analysis with provider selection
|-- analyze_conflict.py          # Groq-based HTML qualitative analysis
|-- analyze_conflict_local.py    # Local llama.cpp workflow
|-- analyze_conflict_old.py      # Shared/legacy analysis implementation
|-- run_analysis.sh              # Wrapper for analyze_conflict.py
|-- code-book-genai.qdc          # Interview analysis codebook
|-- code-book.qdc                # qualitative analysis codebook
|-- data/                        # Interview text files
|-- Articles/                    # HTML news articles
|-- output/                      # Generated granular reports and CSVs
|-- tests/                       # Unit tests
|-- requirements.txt             # Python dependencies
`-- .env.example                 # API-key template
```


# Responsible Use Guidelines

1. **Review model output** - model-suggested phrases and classifications are aids for analysis, not validated findings.
2. **Verify against sources** - inspect source passages and codebook definitions before drawing conclusions from counts.
3. **Protect sensitive data** - hosted providers receive submitted text; use the local workflow when data must remain on the machine.
4. **Keep credentials private** - store API keys in `.env` or environment variables and do not commit secrets.
5. **Report limitations** - document the model, codebook, article set, and any manual corrections used in research outputs.


# Troubleshooting

| Issue | Solution |
|-------|----------|
| Missing Python package | Activate `.venv` and run `pip install -r requirements.txt`. |
| Missing `GROQ_API_KEY` or `OPENROUTER_API_KEY` | Set the key for the selected provider in `.env` or the shell environment. |
| Local provider cannot connect | Start `llama_cpp.server` on `127.0.0.1:8080` with the expected model alias. |
| No articles are processed | Check the selected input directory and ensure it contains `.txt` or `.html` files as appropriate. |
| Full pytest collection reports duplicate module names | Run the relevant test file directly, for example `python -m pytest tests/test_analyze_granular.py`. |


# Development

Run the granular test module with:

```bash
python -m pytest tests/test_analyze_granular.py
```

The repository currently has a root-level and a `tests/` copy of `test_analyze_conflict.py`; running all tests together may cause pytest's duplicate-module collection error.

The OpenRouter provider test currently expects an older model ID; the script is configured for `google/gemma-3-27b-it`.


# License and Acknowledgments

No `LICENSE` file is currently present in this repository. The project uses Groq and OpenAI-compatible Python clients, `python-dotenv`, Beautiful Soup, and pytest; local inference uses the optional `llama-cpp-python` server package.