# Drugsheets Project

## Purpose

Automated generation of EPMA (Electronic Prescribing and Medicines Administration) drug sheets for PICS. Given a drug name (+/- form), the system uses MCP servers and AI to look up clinical data, map codes, and populate a standardised drug sheet template (Non-infusion Drugsheet v3.6).

## Project Structure

```
Drugsheets/
├── CLAUDE.md                          # This file
├── Drug sheet creator prompt.docx     # Master workflow specification
├── Templates/
│   └── Non-infusion Drugsheet v3.6.docx
├── Knowledge base/                    # Source Excel files (DO NOT MODIFY originals)
│   ├── drugsToClasses.xls             # Drug-to-class mappings (PICS codes, class descriptions)
│   ├── FormRoute.xlsx                 # Form/route matrix
│   ├── ICD10_usage.xlsx               # ICD-10 code mappings for contraindications/cautions
│   ├── TFQavSummary.xlsx              # Trade/form/quantity/availability summary
│   ├── cleaned/                       # Output from /tidy-kb skill
│   └── organized/                     # Categorised cleaned files
├── bnf-mcp/                           # Python engine, web apps, and MCP servers
│   ├── generate.py                    # Core engine — BNF/EMC data gathering, analysis, compilation
│   ├── app.py                         # Streamlit web app (deployed to Streamlit Cloud)
│   ├── api.py                         # FastAPI web app (SSE streaming, file downloads)
│   ├── server.py                      # BNF-Pro MCP (analyze_drug, get_interaction_detail)
│   ├── emc_server.py                  # EMC SmPC MCP (get_smpc_details)
│   ├── dmd_server.py                  # dm+d Term Server MCP (map_drug_to_codes, get_controlled_drug_info)
│   ├── formulary_server.py            # Birmingham Formulary MCP (get_local_formulary_status)
│   ├── tidy_kb.py                     # Knowledge base cleaning script
│   ├── static/                        # Frontend assets for FastAPI app
│   ├── requirements.txt               # Streamlit Cloud dependencies
│   └── pyproject.toml                 # Python deps (fastmcp, beautifulsoup4, pandas, etc.)
├── cache/                             # Cached generated drug sheets (auto-created)
├── output/                            # Generated output files (auto-created)
├── prompts/
│   ├── claude_code_prompt.md          # Master prompt for Claude Code
│   └── gemini_cli_prompt.md           # Equivalent prompt for Gemini CLI (Linux Mint)
└── .claude/
    └── skills/
        ├── tidy-kb/                   # /tidy-kb slash command
        └── generate-drugsheet/        # /generate-drugsheet slash command
```

## MCP Servers

All custom servers use FastMCP (Python) and run via `uv run`. Playwright uses npx.

| Server | File | Tools | Purpose |
|---|---|---|---|
| `bnf-pro` | `server.py` | `analyze_drug`, `get_interaction_detail` | BNF drug data, interactions |
| `emc-smpc` | `emc_server.py` | `get_smpc_details` | EMC SmPC sections (4.2–4.8) |
| `dmd-term-server` | `dmd_server.py` | `map_drug_to_codes`, `get_controlled_drug_info` | VTM/VMP/AMP codes, brand prescribing status, controlled drug schedule |
| `birmingham-formulary` | `formulary_server.py` | `get_local_formulary_status` | Local formulary status (Green/Amber/Red) |
| `playwright` | (npm) | Browser automation | Web scraping fallback |

Cloud MCP servers also available: **PubMed**, **ICD-10 Codes**, **Clinical Trials**.

## BNF Data Architecture

The core engine (`generate.py`) fetches BNF drug data via the **Gatsby JSON API** (`page-data.json` endpoints) rather than HTML scraping. This is more reliable from cloud environments where HTML pages may return 403.

### Key endpoints
- Drug list: `https://bnf.nice.org.uk/page-data/drugs/page-data.json` → `allDrugs.letters[].links[]` (~1,771 drugs)
- Drug data: `https://bnf.nice.org.uk/page-data/drugs/{slug}/page-data.json`
- Interactions: `https://bnf.nice.org.uk/page-data/interactions/{slug}/page-data.json`

### BNF JSON section patterns
Most sections use a `{"content": "<p>HTML...</p>"}` pattern, but some differ:
- `monitoringRequirements` uses `monitoringOfPatientParameters`, `patientMonitoringProgrammes`, `therapeuticDrugMonitoring`
- `indicationsAndDose` uses `indicationAndDoseGroups` with `doseStatement` on each patient group
- Combination drugs have a `constituentDrugs` field that lists the individual component drugs

### Resilient fetching
`_resilient_get()` tries direct fetch first, then falls back to CORS proxy services (allorigins, corsproxy.io, codetabs) if blocked.

## Template Field Mapping (Non-infusion Drugsheet v3.6)

Each table in the template is mapped to a data source and automation status.

### Admin & Governance (Manual)
| Table | Section | Source | Automated? |
|---|---|---|---|
| 0 | TRAC date, Ivanti ticket | Manual | No — PICS team |
| 6 | GENERIC/TRADE codes | Manual | No — PICS programmers |
| 7 | Prescriber privilege restriction | Manual | No — mark "TO BE COMPLETED" |
| 8 | Directorate availability | Manual | No — mark "TO BE COMPLETED" |
| 24 | Sign-off (entered by, reviewed by, date) | Manual | No |

### Drug Identity & Classification (Automated)
| Table | Section | Source | Automated? |
|---|---|---|---|
| 1 | Controlled drug? + schedule | dm+d MCP (`get_controlled_drug_info`) | Yes |
| 2 | Blueteq drug? | Manual (no MCP available) | No — flag if info found in BNF/EMC |
| 3 | Amber drug (ESCA/RiCAD/Pure Amber)? | Birmingham Formulary MCP | Yes |
| 4 | Modification of current drug | Manual | No |
| 5 | Redirects (brand→generic) | BNF + EMC (brand name check) | Yes |
| 9 | Strengths, divisibility, dm+d codes (VTM/VMP/AMP) | dm+d MCP + TFQavSummary.xlsx | Yes |
| 10 | Drug classes + PICS codes | AI + drugsToClasses.xls | Yes |

### Clinical Safety (Automated)
| Table | Section | Source | Automated? |
|---|---|---|---|
| 11 | Contraindications + ICD-10 codes + warning levels | BNF + EMC + ICD-10 tiered lookup (see below) | Yes |
| 12 | Interactions + drug class codes + warning levels | BNF + EMC (section 4.5) + drugsToClasses.xls | Yes |
| 13 | Unconditional messages (P/N, form, level) | BNF + EMC + AI | Yes |
| 15 | Other info + Result warnings (eGFR, ALT syntax) | BNF + EMC + AI | Yes |

### Forms, Routes & Dosing (Automated)
| Table | Section | Source | Automated? |
|---|---|---|---|
| 16 | Allowable forms & routes + licensed + formulary | BNF + EMC + FormRoute.xlsx + Formulary MCP | Yes |
| 17 | Defaults (route, form) | BNF + AI | Yes |
| 18–19 | PRN settings | BNF + EMC | Yes |
| 20 | Adult dose limits (single + daily, warning levels) | BNF + EMC | Yes |
| 21 | Same settings for <18? | BNF | Yes |
| 22 | Paediatric dose limits (age brackets from BNF/EMC) | BNF + EMC | Yes |

### References (Automated)
| Table | Section | Source | Automated? |
|---|---|---|---|
| 23 | Reference sources + URLs + date accessed | All MCP sources | Yes |

## PICS Message Codes

- Leave PICS message code fields **blank** for manual entry by the PICS team
- Exception: `BNF_F10_55` for pregnancy/lactation is pre-populated in the template as a standard row

## Warning Levels

| Level | Type | Behaviour |
|---|---|---|
| 0 | Information | Displayed to prescriber, no action required |
| 1 | Tick box | Prescriber must acknowledge to proceed |
| 2 | Password | Prescriber password required to override |
| 3 | Disallow | Prescription blocked entirely |

## Result Warning Syntax

Result warnings follow PICS format:
```
{{{Result, threshold (with units), message, target (Doctor/Nurse), warning level, validity of result}}}
```
Examples:
- `{{{If eGFR<25ml/min, Discontinue treatment, Doctor, Level 3, Validity 7 days}}}`
- `{{{If Eosinophil counts ≤300 cells/μL, Treatment not recommended, Doctor, Level 2, Validity 7 days}}}`
- `{{{If Age >65 years, Reduce dose to 0.625mg in elderly patients, Level 2, Validity 28 days}}}`

## Drug Sheet Workflow

For a given drug, the system runs these agents in order:

### Phase 0: Setup
- Ask user if they want to upload supplementary documents (PDF printouts, specialist resources)

### Phase 1: Data Gathering (parallel where possible)
1. **dm+d Agent** — controlled drug status/schedule, available strengths, VTM/VMP/AMP codes, brand prescribing requirement
2. **Formulary Agent** — Birmingham Formulary Green/Amber/Red status, ESCA/RiCAD/Pure Amber classification, local notes
3. **Clinical Agent** — BNF + EMC data: indications, dose, contraindications, cautions, interactions, side effects, pregnancy, hepatic/renal impairment, monitoring

### Phase 2: Mapping & Analysis (sequential, depends on Phase 1)
4. **Brand/Redirect Agent** — identify if brand prescribing required, set up redirects
5. **Drug Class Agent** — map drug to classes in drugsToClasses.xls, identify PICS codes. Flag incomplete mappings for human review
6. **Contraindication/Caution Agent** — map to ICD-10 codes (tiered lookup, see ICD-10 Mapping section), prefix descriptions, assign warning levels
7. **Interaction Agent** — cross-reference against drug classes, identify coverage gaps, suggest new classes for trends, assign warning levels (0–3)
8. **Message Agent** — identify unconditional prescriber/nurse messages, form-specific messages
9. **Result Warning Agent** — extract renal/hepatic/age thresholds, format as PICS result warning syntax

### Phase 3: Dosing & Forms (sequential, depends on Phase 1)
10. **Forms/Routes Agent** — map against FormRoute.xlsx, identify enteral routes (NG/PEG), check licensing, set defaults
11. **Dose Limits Agent** — adult single/daily limits with warning levels, PRN settings
12. **Paediatric Agent** — derive age brackets from BNF/EMC, ensure continuous with no gaps, set limits per bracket

### Phase 4: Compilation
13. **Compilation Agent** — assemble all data into two output formats:
    - **Human-reviewable**: resembles the template, easy for clinical pharmacist to verify
    - **Programmer/EPMA format**: structured data for keying into PICS
14. **Reference Agent** — compile all source URLs with access dates

## ICD-10 Mapping Architecture

Contraindications and cautions are mapped to ICD-10 codes using a 5-tier approach. Tiers 0-3 run automatically in `generate.py`; tier 4 runs when Claude orchestrates via `/generate-drugsheet`.

| Tier | Source | Confidence | Details |
|---|---|---|---|
| 0 | `_COMMON_ICD10_MAP` (curated) | High | 200+ entries: ~55 broad clinical terms hardcoded + 150+ loaded from `Reverse drugsheets/contraindication_icd10_lookup.json` |
| 1 | `ICD10_usage.xlsx` (PICS KB) | High | Existing PICS mappings from knowledge base |
| 2 | NLM ICD-10-CM API | Medium | Free API, no auth: `clinicaltables.nlm.nih.gov`. Can return wrong codes for broad terms |
| 3 | `[NEEDS ICD-10 MAPPING]` | None | Fallback — returns original text + cleaned text for Claude to pick up |
| 4 | **Claude reasoning** (skill only) | High | When `/generate-drugsheet` runs, Claude interprets unmapped conditions, refines search terms, validates codes, and saves new mappings |

### Self-expanding map
- `save_icd10_mapping(condition, icd10_code, description)` in `generate.py` writes new entries to the JSON lookup file
- The JSON file is loaded at startup and merged with the hardcoded map (hardcoded entries take priority)
- Each drugsheet generated adds new mappings, reducing `[NEEDS ICD-10 MAPPING]` over time
- To expand further: process more reverse drugsheet PDFs from the `Reverse drugsheets/` folder

## EMC SmPC Parsing

EMC uses `<details>/<summary>` accordion HTML structure (not `<h2>/<h3>`). The parser in `_fetch_single_smpc()` searches for `<details>` tags whose `<summary>` contains the section number (e.g. "4.3"). Falls back to legacy h2/h3 for older pages.

Key sections extracted: 4.2 (posology), 4.3 (contraindications), 4.4 (special warnings/cautions), 4.5 (interactions), 4.6 (pregnancy), 4.8 (side effects).

## Interactions

BNF interactions are fetched from the interactions endpoint. EMC section 4.5 is parsed for additional interaction drugs using `_extract_emc_interaction_drugs()`. EMC-only interactions are merged with BNF results, deduplicated by drug name, each tagged with a `source` field ("BNF" or "EMC SmPC 4.5").

## Key Rules

- **NEVER modify original Knowledge base files** — always output to `cleaned/` or `organized/`
- **All clinical data must be referenced** with source URL and access date
- **Age brackets must be continuous** with no gaps in dose limit tables
- **Warning levels**: 0=information, 1=tick box, 2=password, 3=disallow
- **Contraindication prefix**: `contraindication:` — **Caution prefix**: `caution:`
- **Human review flags**: When drug class mapping is incomplete (majority but not all drugs match), flag `[HUMAN REVIEW REQUIRED]`
- **Manual fields**: Prescriber privilege, directorate availability, PICS message codes, Blueteq status — mark as `[TO BE COMPLETED]`
- **Interaction trends**: When multiple interacting drugs share a pharmacological effect (e.g. hypokalaemia), suggest a new drug class

## Development

```bash
# Run FastAPI app locally (primary local method)
cd bnf-mcp && uvicorn api:app --host 127.0.0.1 --port 8000

# Or use the desktop shortcuts:
#   ~/Desktop/Drug Sheet Generator.desktop   — starts FastAPI on port 8000, opens browser
#   ~/Desktop/Stop Drug Sheet Generator.desktop — kills server
# Scripts: bnf-mcp/start.sh, bnf-mcp/stop.sh

# Run Streamlit app locally
streamlit run app.py

# Run an MCP server locally for testing
uv run server.py

# Clean knowledge base files
python tidy_kb.py

# List MCP servers
claude mcp list
```

### Streamlit Cloud deployment
- App URL: `picsdrugsheetgenerator.streamlit.app`
- Auto-deploys on push to `main` branch
- Dependencies: `bnf-mcp/requirements.txt`

## Skills

- `/tidy-kb` — Clean and organize Knowledge base Excel files
- `/generate-drugsheet` — Run the full drugsheet generation workflow for a named drug

## Output Formats

The final drug sheet is produced in two formats:
1. **Human-reviewable** — Resembles the Non-infusion Drugsheet v3.6 template, easy to verify clinically
2. **Programmer/coder format** — Structured JSON/tabular data for keying into EPMA by hand

Two prompt variants are maintained:
1. **Claude Code** (`prompts/claude_code_prompt.md`) — uses MCP servers directly
2. **Gemini CLI** (`prompts/gemini_cli_prompt.md`) — adapted for Linux Mint with equivalent API calls

## Web App (Deferred)

The final product will be published as a web app with:
- **Interactive generator** — users enter a drug name and generate a new drug sheet live
- **Published library** — browse/search completed and reviewed drug sheets

Hosting options (to be decided post-testing):
- **Firebase Hosting + Cloud Functions** — simplest for static + serverless
- **Google Cloud Run** — better for the Python MCP backends
- **GitHub Pages + API backend** — free static hosting with separate API

Implementation is deferred until after thorough clinical testing and governance sign-off.
