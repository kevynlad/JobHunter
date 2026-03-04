# 🎯 JobHunter

**AI-powered job hunting pipeline that finds, scores, and tracks the best job opportunities for you.**

JobHunter scrapes job boards, scores each posting against your career profile using RAG (vector similarity) + Gemini LLM (deep analysis), and sends the top matches straight to your Telegram. It remembers every job it's seen, so you never get the same posting twice.

---

## ⚡ How It Works

```
    Job Boards              RAG Scoring           Gemini LLM            You
  ┌──────────┐         ┌──────────────┐      ┌──────────────┐     ┌──────────┐
  │ LinkedIn │──scrape──│  Vector DB   │─rank─│  Deep Match  │─────│ Telegram │
  │  Indeed  │         │ (ChromaDB)   │      │  Analysis    │     │   Bot    │
  └──────────┘         └──────────────┘      └──────────────┘     └──────────┘
                              │                     │                   │
                        Your career docs      Score 0-100          Top matches
                        as embeddings         + fit analysis       + insights
```

### Pipeline Phases

| Phase | What happens | Tech |
|-------|-------------|------|
| **1. Scraping** | Searches LinkedIn + Indeed with 9 query combinations | `python-jobspy` |
| **2. Geo-filter** | Removes jobs outside São Paulo metro area | keyword matching |
| **3. Deduplication** | Merges duplicates across sources | SHA256 hash |
| **4. RAG Scoring** | Compares job descriptions against your career docs | `ChromaDB` + `sentence-transformers` |
| **5. LLM Classification** | Gemini analyzes fit, seniority, red flags, verdict | `Gemini 2.5 Flash` |
| **6. SQLite Tracking** | Stores results, skips already-notified jobs | `SQLite` |
| **7. Notification** | Sends new matches to Telegram with scores + insights | Telegram Bot API |
| **8. CSV Export** | Saves daily results for review | CSV |

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/kevynlad/JobHunter.git
cd JobHunter
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .
```

### 2. Configure

```bash
# Copy the example files
cp .env.example .env
cp career_summary.example.txt career_summary.txt
```

Edit `.env` with your API keys:

```env
GEMINI_API_KEYS=your_gemini_key_1,your_gemini_key_2
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
RAPIDAPI_KEY=your_rapidapi_key  # optional, for JSearch
```

Edit `career_summary.txt` with your career profile (the AI uses this to evaluate fit).

### 3. Ingest Your Career Documents

Place your resume, certificates, and career docs in `data/career/`, then:

```bash
python -m src.rag.ingest
```

This creates vector embeddings of your documents in ChromaDB for RAG scoring.

### 4. Run the Pipeline

```bash
python -m src.pipeline
```

Or via the CLI:

```bash
python -m src.cli run
```

---

## ⌨️ CLI Commands

```bash
python -m src.cli stats           # 📊 Summary of all tracked jobs
python -m src.cli new             # 🆕 Jobs you haven't acted on
python -m src.cli applied         # ✅ Jobs you've applied to
python -m src.cli search "query"  # 🔍 Search by title or company
python -m src.cli mark ID applied # ✏️ Mark a job as applied/skipped
python -m src.cli detail ID       # 🔎 Full details of a specific job
python -m src.cli all             # 📋 All tracked jobs
python -m src.cli run             # 🚀 Run the full pipeline
```

---

## 🏗️ Project Structure

```
JobHunter/
├── src/
│   ├── pipeline.py          # Main orchestrator — runs all phases
│   ├── cli.py               # Terminal interface with rich tables
│   ├── jobs/
│   │   ├── sources.py       # Job scraping (LinkedIn, Indeed via JobSpy)
│   │   ├── matcher.py       # Geo-filter + dedup + RAG scoring
│   │   ├── classifier.py    # Gemini LLM deep analysis
│   │   ├── database.py      # SQLite persistence + dedup tracking
│   │   ├── models.py        # Data models (JobPosting, ScoredJob)
│   │   └── config.py        # Search queries, career paths, keywords
│   ├── rag/
│   │   ├── ingest.py        # Converts career docs → ChromaDB vectors
│   │   └── retriever.py     # Queries ChromaDB for relevant career chunks
│   └── notify/
│       ├── telegram.py      # Telegram Bot API integration
│       └── scheduler.py     # Cron-like scheduler (2x daily)
├── data/
│   ├── career/              # Your career docs (gitignored)
│   ├── chroma_db/           # Vector DB (generated, gitignored)
│   └── jobs.db              # SQLite tracker (gitignored)
├── output/                  # Daily CSV exports (gitignored)
├── career_summary.txt       # Your AI profile (gitignored)
├── career_summary.example.txt  # Template for new users
├── .env                     # API keys (gitignored)
├── .env.example             # Template for new users
└── pyproject.toml           # Dependencies
```

---

## 🔧 Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Scraping** | `python-jobspy` | Aggregates LinkedIn + Indeed |
| **RAG** | `ChromaDB` + `sentence-transformers` (MiniLM) | Vector similarity scoring |
| **LLM** | `Gemini 2.5 Flash` (free tier) | Deep job-fit analysis |
| **Database** | `SQLite` | Job tracking + dedup |
| **Notification** | Telegram Bot API | Mobile alerts |
| **CLI** | `typer` + `rich` | Terminal interface |
| **Language** | Python 3.11+ | Everything |

---

## 🗺️ Roadmap

- [x] Multi-source job scraping (LinkedIn + Indeed)
- [x] RAG scoring with career document embeddings
- [x] Gemini LLM classification with detailed fit analysis
- [x] Telegram notifications with scores and insights
- [x] SQLite job tracking with deduplication
- [x] CLI for job management
- [ ] **GitHub Actions** — Automated 2x daily pipeline runs (no PC needed)
- [ ] **Telegram Inline Buttons** — Mark jobs as Applied/Skipped from your phone
- [ ] **AI Resume Generator** — Custom CVs tailored to each job description
- [ ] **Cloud Database** — Migrate SQLite to Turso for mobile-first access
- [ ] **Analytics Dashboard** — Track application rates, response rates, trends

---

## 📝 License

MIT — Use it, fork it, make it yours.
