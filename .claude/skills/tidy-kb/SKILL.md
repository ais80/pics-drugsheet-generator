---
name: tidy-kb
description: Clean and organize Excel files in the Knowledge base folder. Removes (dm+d) tags, trims whitespace, fixes headers, drops empty rows/columns, and organizes files into categorized subfolders.
user-invocable: true
allowed-tools: Bash, Read, Glob
argument-hint: [--dry-run]
---

# Tidy Knowledge Base

Run the knowledge base tidying script to clean and organize the Excel files in `Knowledge base/`.

## What it does

1. **Cleans data** in each Excel file:
   - `drugsToClasses.xls` — strips whitespace, removes `(dm+d)` from drug descriptions, drops empty rows
   - `FormRoute.xlsx` — drops fully empty columns and rows
   - `ICD10_usage.xlsx` — promotes the real header row (CI description, ICD10 code, etc.), drops empty rows
   - `TFQavSummary.xlsx` — strips whitespace, removes `(dm+d)` references, drops empty rows

2. **Renames** files to consistent `snake_case.xlsx` format

3. **Organizes** into categorized subfolders:
   - `organized/drug_classifications/` — drugs_to_classes.xlsx
   - `organized/formulary/` — form_route.xlsx, tfqav_summary.xlsx
   - `organized/clinical_codes/` — icd10_usage.xlsx

## How to run

```bash
cd G:/Documents/PICS/Drugsheets/bnf-mcp && source .venv/Scripts/activate && python tidy_kb.py
```

Original files are **never modified**. Cleaned outputs go to `Knowledge base/cleaned/` and organized copies to `Knowledge base/organized/`.

If the user passes `--dry-run` as an argument, just list what would be done without executing the script. Otherwise, run it.
