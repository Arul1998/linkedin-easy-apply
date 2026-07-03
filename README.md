# LinkedIn Easy Apply Bot

A small robot on your computer that helps you apply to jobs on LinkedIn — automatically.

You tell it what job you want. It opens Chrome, logs into LinkedIn, finds **Easy Apply** jobs, fills in your details, uploads your CV, and clicks submit. It also keeps a list of jobs it already applied to so it does not apply twice.

**Cost:** Free. No monthly fee. You only need your computer, Chrome, internet, and a LinkedIn account.

---

## What it does (in plain English)

1. Reads your settings (`config.json` + `.env`)
2. Opens Chrome and logs into LinkedIn
3. Searches for jobs (e.g. "frontend developer" in "United Kingdom")
4. For each Easy Apply job:
   - Opens the job
   - Fills your name, email, phone, city, etc.
   - Uploads your CV (PDF) and photo (PNG/JPG) if the form asks
   - Answers simple questions (some from your CV automatically)
   - Clicks Submit — or skips if the form is too hard
5. Saves every successful application to `applications.json`

It waits between clicks so it does not go too fast (that helps avoid LinkedIn blocking you).

---

## What you need

- **Python 3.10+**
- **Google Chrome**
- **LinkedIn account** (email + password)
- Your **CV** (PDF) and optional **photo** (PNG/JPG)

---

## Setup (one time)

Open PowerShell in the project folder:

```powershell
cd linkedin-easy-apply

python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Step 1 — Add your LinkedIn login

```powershell
copy .env.example .env
```

Edit `.env`:

```
LINKEDIN_EMAIL=your-email@example.com
LINKEDIN_PASSWORD=your-password
```

> Never share `.env` or put your password in `config.json`.

### Step 2 — Add your job settings

```powershell
copy config.example.json config.json
```

Edit `config.json`. The important parts:

| Setting | What it means | Example |
|---------|---------------|---------|
| `search.keywords` | Job title to search | `"frontend developer"` |
| `search.location` | Where to search | `"United Kingdom"` |
| `search.work_type` | `2` = Remote | `"2"` |
| `max_applications` | How many jobs per run | `5` |
| `resume_path` | Full path to your CV PDF | `"C:/path/to/cv.pdf"` |
| `photo_path` | Full path to your photo | `"C:/path/to/photo.png"` |
| `saved_answers` | Your name, email, phone, city, etc. | see example file |

---

## How to run

Always activate the virtualenv first:

```powershell
.\venv\Scripts\Activate.ps1
```

### Safe test (no applications sent)

```powershell
python main.py --dry-run
```

Chrome opens, logs in, searches jobs — but does **not** apply. Use this first.

### Check your setup (no browser)

```powershell
python main.py --validate-only
```

### Real run (applies to jobs)

```powershell
python main.py --confirm
```

Asks "Proceed?" before sending applications.

```powershell
python main.py
```

Applies without asking.

### Useful extra flags

| Flag | What it does |
|------|--------------|
| `--dry-run` | Test login + search only |
| `--confirm` | Ask before applying |
| `--max-applications 3` | Only apply to 3 jobs this run |
| `--pause-on-challenge` | Wait for you to solve CAPTCHA / 2FA |
| `--fresh-login` | Ignore saved session, log in again |
| `--debug` | Show detailed logs |

Example:

```powershell
python main.py --confirm --pause-on-challenge --max-applications 5
```

---

## Your two config files

### `.env` — secrets only

- LinkedIn email
- LinkedIn password

### `config.json` — everything else

- **search** — what jobs to look for
- **saved_answers** — name, email, phone, city, cover letter, start date
- **resume_path** — your CV file
- **photo_path** — your photo (for forms that ask for a picture)
- **custom_answers** — extra Q&A for tricky form questions

Example `custom_answers`:

```json
"custom_answers": {
  "years of experience with react": "4",
  "are you authorized to work in the uk": "Yes"
}
```

If the bot cannot answer a question, it logs something like:

`Unanswered form question (add to custom_answers): "..."`

Copy that question into `custom_answers` with your answer.

---

## Smart answers from your CV

If you set `resume_path`, the bot reads your PDF and tries to answer questions like:

- "How many years of experience with Angular?"
- "Are you authorized to work in the UK?"

**Priority:** `custom_answers` → CV profile → `saved_answers`

---

## Where results are saved

After each run, check `applications.json` (or `applications.csv` if you configured that):

```json
{
  "job_title": "Frontend Developer",
  "company_name": "Some Company",
  "job_url": "https://...",
  "date_applied": "2026-07-03 12:00:00",
  "status": "applied"
}
```

---

## Important things to know

- **Free to use** — no API keys, no subscription for this tool
- **LinkedIn may not like bots** — use reasonable delays (30+ seconds between applications)
- **Not every job works** — complex forms with many steps or weird questions get skipped
- **CAPTCHA / 2FA** — run with `--pause-on-challenge` and complete it in the browser
- **Session saved** — after first login, cookies are stored in `.linkedin_session/` so you log in less often

---

## If something goes wrong

| Problem | Fix |
|---------|-----|
| Login fails | Check `.env` email/password. Try `--fresh-login` |
| CAPTCHA appears | Run with `--pause-on-challenge` |
| No jobs found | Change `keywords` or `location` in `config.json` |
| Form not filled | Update `saved_answers` with your real details |
| Weird question skipped | Add it to `custom_answers` in `config.json` |
| `ModuleNotFoundError: selenium` | Activate venv and run `pip install -r requirements.txt` |

---

## Project files (quick map)

```
main.py                 ← start here (run this)
config.json             ← your job search + personal details
.env                    ← your LinkedIn login (secret)
linkedin_automation.py  ← browser robot (login, apply, fill forms)
resume_profile.py       ← reads your CV to answer questions
tracker.py              ← saves applied jobs list
applications.json       ← output: jobs you applied to
```

---

## Run tests (optional)

```powershell
pip install -r requirements-dev.txt
pytest
```

---

## One-line summary

> **Free bot that applies to LinkedIn Easy Apply jobs for you, using your CV and saved answers, and keeps track of what it already did.**
