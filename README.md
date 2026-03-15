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
| `LINKEDIN_KEYWORDS` | Job search keywords / role (e.g. `software engineer`) |
| `LINKEDIN_LOCATION` | Location (e.g. `United Kingdom`) |
| `LINKEDIN_WORK_TYPE` | Work type: `1` On-site, `2` Remote, `3` Hybrid (or `Remote`/`Hybrid`/`On-site`) |
| `LINKEDIN_JOB_TYPE` | Job type: `F` Full-time, `P` Part-time, `C` Contract, `T` Temporary, `V` Volunteer, `I` Internship, `O` Other |
| `LINKEDIN_DATE_POSTED` | Date posted: `r86400` 24h, `r604800` week, `r2592000` month |
| `LINKEDIN_EXPERIENCE_LEVEL` | Experience: `1`–`6` (comma-separated), see below |
| `LINKEDIN_FEW_APPLICANTS` | Fewer than 10 applicants: `true`/`false` |
| `LINKEDIN_GEO_ID` | LinkedIn location ID (optional; overrides `location` if set) |
| `DELAY_ACTIONS_SEC` | Delay between actions in seconds |
| `DELAY_APPLICATIONS_SEC` | Delay after each application in seconds |
| `RESUME_PATH` | Optional path to resume/CV file for upload |
| `TRACKING_FILE` | Output file for applications (e.g. `applications.json` or `applications.csv`) |
| `TRACKING_FORMAT` | `json` or `csv` |

### Where to set role, start date, and filters

| What you want | Where to set it | Config key (in `search` or env) |
|---------------|-----------------|----------------------------------|
| **Role / job title** | Search keywords | `keywords` / `LINKEDIN_KEYWORDS` |
| **Location** | Search | `location` / `LINKEDIN_LOCATION` |
| **Work type** (On-site / Remote / Hybrid) | Search | `work_type` / `LINKEDIN_WORK_TYPE` (`1`/`2`/`3` or "On-site"/"Remote"/"Hybrid") |
| **Job type** (Full-time, Part-time, Contract, etc.) | Search | `job_type` / `LINKEDIN_JOB_TYPE` (`F`, `P`, `C`, `T`, `V`, `I`, `O`) |
| **Date posted** | Search | `date_posted` / `LINKEDIN_DATE_POSTED` (`r86400`, `r604800`, `r2592000`) |
| **Experience level** | Search | `experience_level` / `LINKEDIN_EXPERIENCE_LEVEL` (`1`–`6`, comma-separated) |
| **Few applicants** (&lt;10) | Search | `few_applicants` / `LINKEDIN_FEW_APPLICANTS` (`true`/`false`) |
| **Location by ID** | Search | `geo_id` / `LINKEDIN_GEO_ID` (optional) |
| **Start date** (when you can start) | Easy Apply form answer | `saved_answers.start_date` |
| **Phone, city, cover letter, salary, sponsorship** | Easy Apply form answers | `saved_answers` in `config.json` |

**Search filters reference** (all under `config.json` → `search`, or env):

| Key | Values | Description |
|-----|--------|-------------|
| `keywords` | Any string | Role / job title search |
| `location` | e.g. "United Kingdom" | Geographic location |
| `work_type` | `1` or "On-site", `2` or "Remote", `3` or "Hybrid" | Work arrangement |
| `job_type` | `F` Full-time, `P` Part-time, `C` Contract, `T` Temporary, `V` Volunteer, `I` Internship, `O` Other | Job type |
| `date_posted` | `r86400` (24h), `r604800` (week), `r2592000` (month) | When job was posted |
| `experience_level` | `1` Intern, `2` Associate, `3` Junior, `4` Mid-Senior, `5` Director, `6` Executive (use `"3,4"` for multiple) | Experience level |
| `few_applicants` | `true` / `false` | Only jobs with fewer than 10 applicants |
| `geo_id` | LinkedIn geo ID | Optional; overrides `location` if set |

**Not available as URL filters** (LinkedIn does not expose these in the search URL): salary range, industry, job function, benefits, sponsorship. You can add keywords like "visa sponsorship" in `keywords`, or apply those filters once manually in LinkedIn’s job search UI and then run the script.

**Form answers** (start date, phone, city, cover letter, salary, sponsorship, etc.) go in **`saved_answers`** and are used when filling the Easy Apply modal.

### Config file (`config.json`)

Example (all optional if using env vars):

```json
{
  "search": {
    "keywords": "software engineer",
    "location": "United Kingdom",
    "work_type": "2",
    "job_type": "F",
    "date_posted": "r604800",
    "experience_level": "3,4",
    "few_applicants": false,
    "geo_id": ""
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
