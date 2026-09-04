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

```bash
cd backend
pip install -r requirements.txt
cd ..
python -m eval.run_eval
```

Results land in `eval/results/`. Design notes are in `DESIGN.md` once that file exists.
