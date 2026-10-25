# prompt-regression-lab

A tiny, dependency-free prompt regression checker. It turns "does this prompt still behave?" into explicit, repeatable contracts.

## Why this exists

Prompts regress. A model upgrade, a wording tweak, or a new system message can silently remove a required fact, re-introduce a banned phrase, or blow up the output length.

Reading every output by hand does not scale. This tool keeps the checks small and explicit:

- must contain these phrases;
- must not contain these phrases;
- must stay under this character limit;
- must not be empty.

Phrase checks are case-insensitive. They are contracts, not a semantic judge.

## Quick start

Requires Python 3.8+, no third-party packages.

```bash
python prompt_regression.py \
  --cases cases.example.jsonl \
  --outputs outputs.example.jsonl \
  --report report.md
```

Expected:

```text
3/3 passed
wrote report.md
```

## Two ways to supply model output

### 1. Offline outputs (recommended for CI)

Run your model elsewhere, save one JSON object per line:

```json
{"id": "greeting", "output": "Hello! How can I help?"}
```

Then point `--outputs` at that file. This keeps the checker deterministic and makes regressions easy to diff.

### 2. Command adapter

```bash
python prompt_regression.py \
  --cases cases.example.jsonl \
  --command "python my_model.py" \
  --timeout 30
```

The command is split with `shlex.split`, run without a shell, receives the prompt on stdin, and must write the answer to stdout. A non-zero exit or timeout becomes a data error (exit code `2`).

## Case format

```json
{
  "id": "refund",
  "prompt": "State the refund window in one sentence.",
  "must_contain": ["14 days"],
  "must_not_contain": ["30 days"],
  "max_chars": 80
}
```

- `id`: unique, non-empty;
- `prompt`: non-empty;
- `must_contain`, `must_not_contain`: arrays of non-empty strings;
- `max_chars`: optional positive integer.

## Output and exit codes

- `0`: every case passed;
- `1`: at least one contract failed;
- `2`: malformed input, missing output, or command failure.

`report.md` contains a case table plus the full output of each failure.

## Tests

```bash
python -m unittest -v
```

Covered: passing output, missing phrase, forbidden phrase, length limit, empty output, missing output, duplicate IDs, malformed JSON line numbers, and report content.

## Design choices

- **No LLM-as-judge.** The checks are deterministic and cheap. Semantic quality is a different problem.
- **Case-insensitive phrases.** `As an AI` and `as an ai` should be caught by the same contract.
- **No shell.** `--command` uses an argv list, not `shell=True`.
- **Outputs as data.** The same checker works for any model/provider.

## Limitations

- Substring checks cannot understand meaning, negation, or paraphrase.
- It does not measure helpfulness, factuality, or safety in general.
- Character count is not token count.
- The command adapter assumes a stdin/stdout convention.

## Files

```text
prompt-regression-lab/
├── prompt_regression.py
├── test_prompt_regression.py
├── cases.example.jsonl
├── outputs.example.jsonl
├── README.md
├── .gitignore
└── .github/workflows/tests.yml
```
