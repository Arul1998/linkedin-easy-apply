# LinkedIn Easy Apply – Standalone Automation

A standalone Python + Selenium project that logs into LinkedIn, searches jobs with configurable keywords and location, and applies only to **Easy Apply** jobs. Applications are tracked to a CSV or JSON file, with configurable rate limiting to reduce detection risk.

## Features

- **Login** via environment variables or `.env` (no passwords in code)
- **Configurable job search**: keywords, location, remote filter
- **Easy Apply only**: detects Easy Apply jobs, fills saved answers where possible, submits; skips or flags multi-step/complex applications
- **Application tracking**: job title, company name, job URL, date applied (CSV or JSON)
- **Rate limiting**: configurable delays between actions and between applications
- **Single config**: `config.json` and/or env vars for keywords, location, delays, optional resume path

## Requirements

- Python 3.10+
- Chrome browser (for Selenium WebDriver)

## Setup

### 1. Clone and create virtualenv

```bash
cd linkedin-easy-apply
python -m venv venv
```

**Windows (PowerShell):**

```powershell
.\venv\Scripts\Activate.ps1
```

**Windows (cmd) / macOS / Linux:**

```bash
# Windows cmd
venv\Scripts\activate.bat
# macOS / Linux
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure credentials (required)

Create a `.env` file in the project root (never commit this file):

```bash
cp .env.example .env
```

Edit `.env` and set:

- `LINKEDIN_EMAIL` – your LinkedIn email
- `LINKEDIN_PASSWORD` – your LinkedIn password

### 4. Optional: config file

Copy the example config and edit as needed:

```bash
cp config.example.json config.json
```

You can override any of these with environment variables (see below).

## Configuration

### Environment variables

| Variable | Description |
|----------|-------------|
| `LINKEDIN_EMAIL` | LinkedIn login email (required) |
| `LINKEDIN_PASSWORD` | LinkedIn password (required) |
| `CONFIG_FILE` | Path to JSON config (default: `config.json`) |
| `LINKEDIN_KEYWORDS` | Job search keywords (e.g. `software engineer`) |
| `LINKEDIN_LOCATION` | Location (e.g. `United Kingdom`) |
| `LINKEDIN_REMOTE` | Remote filter (e.g. `Remote`; enables remote filter when set) |
| `LINKEDIN_JOB_TYPE` | Job type: `F` Full-time, `P` Part-time, `C` Contract, `T` Temporary, `I` Internship |
| `LINKEDIN_DATE_POSTED` | Date posted: `r86400` 24h, `r604800` week, `r2592000` month |
| `DELAY_ACTIONS_SEC` | Delay between actions in seconds |
| `DELAY_APPLICATIONS_SEC` | Delay after each application in seconds |
| `RESUME_PATH` | Optional path to resume/CV file for upload |
| `TRACKING_FILE` | Output file for applications (e.g. `applications.json` or `applications.csv`) |
| `TRACKING_FORMAT` | `json` or `csv` |

### Where to set role, start date, and filters

| What you want | Where to set it | File / section |
|---------------|-----------------|----------------|
| **Job role / title** | Search keywords | `config.json` → `search.keywords` (or env `LINKEDIN_KEYWORDS`) |
| **Job type** (Full-time, Part-time, Contract, etc.) | Search filter | `config.json` → `search.job_type` (or env `LINKEDIN_JOB_TYPE`) |
| **Date posted** (e.g. past week) | Search filter | `config.json` → `search.date_posted` (or env `LINKEDIN_DATE_POSTED`) |
| **Start date** (when you can start) | Answer in Easy Apply form | `config.json` → `saved_answers.start_date` |
| **Location, remote** | Search | `search.location`, `search.remote` |
| **Phone, city, cover letter, salary, sponsorship** | Answers in Easy Apply form | `saved_answers` in `config.json` |

- **Search filters** (role type, date posted): in **`config.json`** under **`search`**, or via env vars.  
  - `job_type`: `F` = Full-time, `P` = Part-time, `C` = Contract, `T` = Temporary, `I` = Internship. Leave empty for no filter.  
  - `date_posted`: `r86400` = past 24 hours, `r604800` = past week, `r2592000` = past month. Leave empty for no filter.  
- **Form answers** (start date, phone, city, etc.): in **`config.json`** under **`saved_answers`**. These are used when filling the Easy Apply modal.

### Config file (`config.json`)

Example (all optional if using env vars):

```json
{
  "search": {
    "keywords": "software engineer",
    "location": "United Kingdom",
    "remote": "Remote",
    "job_type": "F",
    "date_posted": "r604800"
  },
  "rate_limiting": {
    "delay_between_actions_sec": 2,
    "delay_between_applications_sec": 30
  },
  "resume_path": "/path/to/resume.pdf",
  "tracking": {
    "output_file": "applications.json",
    "format": "json"
  },
  "saved_answers": {
    "phone": "+44 ...",
    "city": "London",
    "cover_letter": "...",
    "salary": "",
    "sponsorship": "No",
    "start_date": "Immediately"
  }
}
```

Environment variables override config file values. Credentials **must** come from the environment (or `.env`), not from the config file.

## How to run and test

### Quick test (no applications submitted)

1. **Setup once**
   ```bash
   cd linkedin-easy-apply
   python -m venv venv
   .\venv\Scripts\Activate.ps1   # Windows PowerShell
   pip install -r requirements.txt
   ```
2. **Add credentials**
   - Copy `.env.example` to `.env` and set `LINKEDIN_EMAIL` and `LINKEDIN_PASSWORD`.
3. **Dry run** (login + search only; no Easy Apply clicks, no submissions):
   ```bash
   python main.py --dry-run
   ```
   You should see a Chrome window log in, open the job search, and then:  
   `Dry run: found N job cards, M with Easy Apply. Login and search OK. Run without --dry-run to apply.`

### Full run (apply to jobs)

1. Activate the virtualenv and ensure `.env` is set (see above).
2. Optional: copy `config.example.json` to `config.json` and set keywords, location, delays, `saved_answers`, and `resume_path`.
3. Run:
   ```bash
   python main.py
   ```

The script will:

1. Log into LinkedIn
2. Open job search with your keywords/location (Easy Apply filter applied)
3. Iterate over Easy Apply job cards: open each job, click Easy Apply, fill saved answers where possible, submit if it’s a single-step flow
4. Skip jobs already in the tracking file, multi-step applications, or when it can’t submit
5. Append each applied job to `applications.json` (or your configured CSV/JSON file)

## Output (tracking)

- **JSON** (default): array of `{ "job_title", "company_name", "job_url", "date_applied" }`.
- **CSV**: same fields as columns.

File path and format are set by `TRACKING_FILE` and `TRACKING_FORMAT` (or `config.json`).

## Rate limiting

- `delay_between_actions_sec`: pause between normal actions (clicks, page loads).
- `delay_between_applications_sec`: longer pause after each successful application.

Increase these if you want to lower the risk of detection (e.g. 3–5 s for actions, 45–60 s between applications).

## Security and compliance

- **Do not** put LinkedIn credentials in code or in `config.json`.
- Use `.env` for local secrets; `.env` is in `.gitignore`.
- Respect LinkedIn’s Terms of Service and use automation at your own risk. Prefer conservative delays and occasional use.

## Project structure

```
linkedin-easy-apply/
├── .env.example       # Example env (copy to .env)
├── .gitignore         # Includes .env
├── config.example.json
├── config.py          # Loads config from env + optional config.json
├── linkedin_automation.py  # Login, search, Easy Apply (Selenium)
├── main.py            # Entry point, rate limiting, tracking loop
├── tracker.py         # CSV/JSON application tracking
├── requirements.txt
└── README.md
```

## Troubleshooting

- **Login fails**: Check email/password in `.env`; ensure no 2FA or use an app password if required.
- **No jobs / wrong jobs**: Adjust `keywords` and `location` in config or env; search uses LinkedIn’s built-in Easy Apply filter.
- **Applications not submitted**: Many Easy Apply forms have multiple steps or custom questions; the script submits only when it finds a single-step Submit. Others are skipped.
- **LinkedIn blocks or CAPTCHA**: Increase delays and run less frequently.
