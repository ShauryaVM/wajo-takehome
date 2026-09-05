# Steward

Wajo take-home: a local email agent with four-way autonomy, a hard safety floor, and preference learning.

This is meant to be run on your machine. There is no hosted signup.

## Run

```bash
cp .env.example .env
docker compose up --build
```

Then open [http://localhost:3000](http://localhost:3000).

Login (after the login screen lands):

- email: `you@local`
- password: `steward`

The default inbox is seeded fixtures. You do not need Gmail or an LLM key to click around.

## Optional live inbox

In Settings you can connect Gmail, Outlook, or IMAP. That path needs OAuth client IDs (or an app password for IMAP) in `.env`. Same UI, real mail. Not required to grade the agent.

## Eval

From the repo root, with backend deps installed:

```bash
PYTHONPATH=backend python eval/run_eval.py
```

Prints accuracy, ask-rate, and safety violations. Writes `eval/results/` and `eval/transcripts/`. Design notes: [DESIGN.md](DESIGN.md).

No LLM key is required. If `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` is set, the classifier uses that instead of the heuristic. The safety guard stays the same.
