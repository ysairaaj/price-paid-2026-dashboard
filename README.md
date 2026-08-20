# Price Paid 2026 Dashboard

Full-stack dashboard for [HM Land Registry Price Paid Data](https://www.gov.uk/government/statistical-data-sets/price-paid-data-downloads) (2026 YTD).

```text
pp-2026.csv
    → ETL (Python / Polars)
    → PostgreSQL (transactions table)
    → Metabase (SQL questions + charts)   ← "backend"
    → React (Vite) embeds chart iframes   ← "frontend"
```

| Layer | Role | Default URL |
|---|---|---|
| PostgreSQL | Stores sale transactions | `localhost:5433` / db `price_paid` |
| Metabase | Queries DB, draws charts (backend BI server) | http://localhost:3000 |
| React + Vite | Dashboard UI that embeds Metabase charts | http://localhost:5173 |

---

## Prerequisites

Install these once (user-space; no sudo required on this project’s setup):

1. **uv** (Python tooling) — https://docs.astral.sh/uv/
2. **micromamba** env `ppd` with PostgreSQL 16 + OpenJDK 21
3. **nvm** + Node.js LTS
4. Project Python venv + deps
5. Metabase jar (already under `metabase/` if downloaded)

### What is micromamba? (PostgreSQL + Java)

**micromamba** is a lightweight package manager (like a small conda). We used it because this Mac had no Homebrew/admin rights.

It installs tools into your home directory — **not** into `/Applications` or system folders:

| What | Where it lives on this machine |
|---|---|
| micromamba binary | `~/.local/bin/micromamba` |
| micromamba root | `~/micromamba/` |
| Env name | `ppd` → `~/micromamba/envs/ppd/` |
| PostgreSQL (`psql`, `pg_ctl`, `initdb`) | `~/micromamba/envs/ppd/bin/` |
| Java (for Metabase) | `~/micromamba/envs/ppd/lib/jvm/bin/java` |
| Postgres **data files** for this project | `Analysis/db/pgdata/` (created by `./db/start_postgres.sh`) |

So “PostgreSQL + Java (micromamba)” means: both programs are installed inside `~/micromamba/envs/ppd/`, and the start scripts on PATH find them from there.

### 1. Python venv

From the project root (`Analysis/`):

```bash
# if .venv does not exist yet
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

### 2. Install PostgreSQL + Java via micromamba

```bash
# install micromamba if needed, then:
export MAMBA_ROOT_PREFIX="$HOME/micromamba"
eval "$(~/.local/bin/micromamba shell hook -s zsh)"   # or bash

micromamba create -y -n ppd -c conda-forge postgresql=16 openjdk=21
```

### 3. Node.js (nvm)

```bash
# install nvm if needed, then:
export NVM_DIR="$HOME/.nvm"
. "$NVM_DIR/nvm.sh"
nvm install --lts
```

### 4. Metabase jar (first time only)

```bash
mkdir -p metabase
curl -L -o metabase/metabase.jar https://downloads.metabase.com/latest/metabase.jar
```

### 5. Data file

Place the yearly CSV in the project root as `pp-2026.csv`.

---

## First-time setup (once)

Run these in order from the project root.

### A. Start Postgres and load the CSV into the DB

The script that **reads `pp-2026.csv` and fills Postgres** is:

```text
etl/load_to_postgres.py
```

It reuses `load_data()` from `analyze_price_paid.py`, then COPY-loads rows into the `transactions` table.

```bash
./db/start_postgres.sh
.venv/bin/python etl/load_to_postgres.py pp-2026.csv
```

Re-run that same ETL command whenever you replace/update `pp-2026.csv`.

### B. Start Metabase (backend)

```bash
./metabase/start_metabase.sh
```

If the start script exits after the health check and Metabase dies, run Java in a dedicated terminal and leave it open:

```bash
cd metabase
export MB_DB_FILE="$PWD/metabase.db"
export MB_JETTY_PORT=3000
~/micromamba/envs/ppd/lib/jvm/bin/java -Xmx2g -jar metabase.jar
```

Wait until http://localhost:3000/api/health returns OK.

### C. Configure Metabase charts (once)

With Metabase running:

```bash
.venv/bin/python metabase/setup_metabase.py
```

This will:

- create the Metabase admin user (first run)
- connect Metabase to Postgres
- create the chart Questions
- enable public sharing
- write embed URLs into `frontend/src/config/metabaseCharts.ts`

**Metabase admin login** (from `metabase/setup_metabase.py`):

- Email: `admin@pricepaid.local`
- Password: `PricePaidAdmin1!`

### D. Install frontend deps (once)

```bash
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh"
cd frontend
npm install
```

---

## How to run (every day)

You need **3 processes**: Postgres, Metabase (backend), React (frontend).

### Terminal 1 — Postgres

```bash
cd /path/to/Analysis
./db/start_postgres.sh
```

### Terminal 2 — Backend (Metabase)

```bash
cd /path/to/Analysis
./metabase/start_metabase.sh

# or keep Java running in the foreground:
cd metabase
export MB_DB_FILE="$PWD/metabase.db" MB_JETTY_PORT=3000
~/micromamba/envs/ppd/lib/jvm/bin/java -Xmx2g -jar metabase.jar
```

### Terminal 3 — Frontend (React)

```bash
cd /path/to/Analysis
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh"
cd frontend
npm run dev
```

### Open the apps

| App | URL |
|---|---|
| **Frontend dashboard** | http://localhost:5173 |
| **Metabase (backend UI)** | http://localhost:3000 |

---

## Stopping

```bash
./db/stop_postgres.sh
./metabase/stop_metabase.sh
# Frontend: Ctrl+C in the npm run dev terminal
```

---

## When to re-run what

| Action | When |
|---|---|
| `etl/load_to_postgres.py` | CSV updated / you want to reload DB |
| `metabase/setup_metabase.py` | First setup, or you changed chart SQL and want to recreate Questions + URLs |
| `analyze_price_paid.py` | Optional offline Polars analysis + PNG charts (not used by the live dashboard) |

The live dashboard path is: **CSV → Postgres → Metabase SQL → React iframes**.  
`analyze_price_paid.py` is a separate CLI tool.

---

## Project layout

```text
Analysis/
├── pp-2026.csv                 # source data
├── analyze_price_paid.py       # optional Polars CLI analysis
├── requirements.txt
├── db/
│   ├── start_postgres.sh
│   ├── stop_postgres.sh
│   └── schema.sql
├── etl/
│   └── load_to_postgres.py     # CSV → Postgres
├── metabase/                   # backend (BI server)
│   ├── metabase.jar
│   ├── start_metabase.sh
│   ├── stop_metabase.sh
│   └── setup_metabase.py       # one-time chart setup
└── frontend/                   # React dashboard
    └── src/
        ├── config/metabaseCharts.ts
        └── pages/Dashboard.tsx
```

---

## Notes

- Public Metabase embed URLs have **no login**. Fine for local demo; do not expose to the internet as-is.
- Metabase must be running for the React iframes to show charts.
- Postgres runs on port **5433** (not the default 5432) to avoid clashing with other installs.

---

## Attribution

Contains HM Land Registry data © Crown copyright and database right.  
This information is licensed under the Open Government Licence v3.0.
