# Steward

Wajo take-home: a local email agent with four-way autonomy, a hard safety floor, and preference learning.

This is meant to be run on your machine. There is no hosted signup.

## Run

```bash
cp .env.example .env
docker compose up --build
```

Then open [http://localhost:3000](http://localhost:3000).

Login:

- email: `you@local`
- password: `steward`

The default inbox is seeded fixtures. You do not need Gmail or an LLM key to click around.

## Connect your Gmail

Steward is local. It is not a public SaaS, so Google will not verify an OAuth app for it. Use an App Password over IMAP. That path does not need Google Cloud or app verification.

### 1. Enable IMAP in Gmail

1. Open Gmail in a browser.
2. Gear -> See all settings -> Forwarding and POP/IMAP.
3. Select Enable IMAP. Save changes.

### 2. Create a Google App Password

Google rejects your normal Gmail password for IMAP.

1. Open [Google Account security](https://myaccount.google.com/security).
2. Turn on 2-Step Verification if it is off. App passwords do not appear without it.
3. Open [App passwords](https://myaccount.google.com/apppasswords). If that page is hidden, search "App passwords" in the Google Account search box.
4. Create one. Name it Steward. Google shows 16 characters, sometimes grouped with spaces. Either form is fine.
5. Copy it once. Google will not show it again.

Workspace / Advanced Protection accounts sometimes hide App passwords. Use a personal Gmail with 2FA, or the OAuth test-user path below.

### 3. Paste it in Steward Settings

1. Sign in to Steward (`you@local` / `steward`).
2. Settings -> Gmail (App Password).
3. Email: your Gmail address.
4. App password: paste the 16-character value.
5. Leave hosts as `imap.gmail.com` / `smtp.gmail.com` (ports 993 / 587).
6. Test connection, then Save and sync.

Steward encrypts the password (Fernet) and stores it in Postgres. The worker polls about every 45 seconds. First connect pulls the latest ~100 messages and runs them through the existing safety floor. Send/reply still ask first. Delete, forward, money, and injection still escalate.

Do not put the app password in `.env` or commit it.

## Gmail API OAuth (optional)

Only needed if App passwords are blocked. This is an unverified local client. Only Google accounts listed as test users can connect.

1. [Google Cloud Console](https://console.cloud.google.com/) -> create a project (or pick one).
2. Enable the Gmail API.
3. APIs & Services -> OAuth consent screen. User type: External. Publishing status: Testing. Add your Gmail as a test user.
4. Credentials -> Create credentials -> OAuth client ID -> Web application.
   - Authorized JavaScript origins: `http://localhost:3000` and `http://localhost:8000`
   - Authorized redirect URI: `http://localhost:8000/accounts/gmail/callback`
5. Put `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`. Restart `docker compose up`.
6. Settings -> Connect Gmail with Google.

`OAUTHLIB_INSECURE_TRANSPORT=1` is set in docker compose so the HTTP localhost callback works. Tokens are encrypted in the database. Reconnecting the same address updates them instead of duplicating the mailbox.

If Google shows "this app isn't verified", that is expected. Continue only on an account you added as a test user.

## Eval

From the repo root, with backend deps installed:

```bash
PYTHONPATH=backend python eval/run_eval.py
```

Prints accuracy, ask-rate, and safety violations. Writes `eval/results/` and `eval/transcripts/`. Design notes: [DESIGN.md](DESIGN.md).

No LLM key is required. If `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` is set, structured LLM classify is the primary decision and the heuristic is the fallback. The safety guard still runs after. Regex is the hard floor; an LLM second pass may only raise money or injection.
