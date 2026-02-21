---
name: generate-drugsheet
description: Generate a complete EPMA drug sheet for a named drug using all MCP servers and knowledge base files. Orchestrates multiple agents for dm+d codes, formulary status, clinical data, interactions, dose limits, and compiles into reviewable output.
user-invocable: true
allowed-tools: Bash, Read, Glob, Grep, Edit, Write, Task
argument-hint: <drug-name> [form]
---

# Generate Drug Sheet

You are generating a complete Non-infusion Drug Sheet (v3.6 template) for the drug: **$ARGUMENTS**

## Phase 0: Setup

1. Ask the user if they want to upload any supplementary documents (PDF printouts of BNF pages, specialist guidelines, trust protocols, etc.). Wait for their response before proceeding.
2. Parse the drug name and optional form from the arguments. If no form specified, gather data for all available forms.
3. Record today's date for reference citations.

## Phase 1: Data Gathering (run in parallel where possible)

Launch these agents concurrently:

### Agent 1: dm+d Lookup
Using `dmd-term-server` MCP:
- Call `map_drug_to_codes` with the drug name to get VTM, VMP, and AMP codes
- Call `get_controlled_drug_info` to check Controlled Drug status and schedule (1-5)
- Record all available strengths from VMP matches
- Check prescribing status — is brand prescribing mandatory?
- Cross-reference strengths against `Knowledge base/TFQavSummary.xlsx` (use the cleaned version at `Knowledge base/cleaned/tfqav_summary.xlsx` if available)

### Agent 2: Formulary Status
Using `birmingham-formulary` MCP:
- Call `get_local_formulary_status` for the drug
- Record: Green / Amber / Red status
- If Amber: determine if ESCA, RiCAD, or Pure Amber
- Capture any local prescribing notes
- This determines Table 3 (Amber Drug) and feeds into Other Information (Table 15)

### Agent 3: BNF Clinical Data
Using `bnf-pro` MCP:
- Call `analyze_drug` to get comprehensive BNF data
- Extract: indications_and_dose, contraindications, cautions, interactions, side_effects, pregnancy, breast_feeding, hepatic_impairment, renal_impairment, monitoring_requirements
- Call `get_interaction_detail` for the top interaction partners

### Agent 4: EMC SmPC Data
Using `emc-smpc` MCP:
- Call `get_smpc_details` for the drug
- Extract: Section 4.2 (posology), 4.3 (contraindications), 4.4 (warnings), 4.5 (interactions), 4.6 (pregnancy/fertility), 4.8 (side effects)
- Note any manufacturer-specific max doses that differ from BNF

## Phase 2: Mapping & Analysis (sequential, requires Phase 1 data)

### Agent 5: Brand/Redirect Check
- From dm+d prescribing status, determine if brand prescribing is required
- From BNF + EMC data, identify all known brand names
- If redirects are needed (e.g. brand→generic, or formulary redirect like Pantoprazole→Lansoprazole), document them for Table 5

### Agent 6: Drug Class Mapping
- Read `Knowledge base/drugsToClasses.xls` (or cleaned version)
- Using AI reasoning + BNF/EMC therapeutic classification, identify which drug classes this drug belongs to
- Map to PICS codes (DRUGCLS column) and class descriptions (classDesc column)
- Map to ALL possible classes that may be appropriate
- Output for Table 10: Drug Class name + PICS code

### Agent 7: Contraindications & Cautions → ICD-10
- Combine contraindications from BNF (Agent 3) and EMC Section 4.3 (Agent 4)
- Combine cautions from BNF and EMC Section 4.4
- For each contraindication/caution, map to ICD-10 code(s):
  - First check `Knowledge base/ICD10_usage.xlsx` for existing mappings
  - Use the ICD-10 Codes cloud MCP for any not found locally
- Format descriptions:
  - Contraindications: prefix with `contraindication:`
  - Cautions: prefix with `caution:`
- Assign warning levels: contraindications typically level 2-3, cautions typically level 0-1
- Always include pregnancy/lactation row with code `BNF_F10_55`
- Leave PICS Message code column blank (for manual entry)
- Output for Table 11

### Agent 8: Interactions Analysis
- Combine interaction data from BNF (Agent 3) and EMC Section 4.5 (Agent 4)
- For each interacting drug:
  - Search `Knowledge base/drugsToClasses.xls` to find if it belongs to an existing drug class with a PICS code
  - If a drug class covers the interaction, record the class code (prefix with C in the "Is this a drugclass?" column)
  - If a drug doesn't belong to any class, record the individual GENERIC code
- Coverage analysis:
  - If the MAJORITY of interacting drugs in a group fall into a drug class but NOT ALL, add flag: `[HUMAN REVIEW REQUIRED: Not all interacting drugs covered by class {class_name}]`
- Trend analysis:
  - Group interactions by pharmacological effect (e.g. hypokalaemia, QT prolongation, serotonin syndrome, bleeding risk)
  - If a significant cluster exists without a matching drug class, recommend: `[SUGGESTED NEW CLASS: "Drugs that can cause {effect}"]`
- Warning level assignment:
  - Level 3 (disallow): "must not be used together", "contraindicated combination"
  - Level 2 (password): "severe interaction", "enhanced effect — monitor closely"
  - Level 1 (tick box): "moderate interaction", "be aware"
  - Level 0 (info): "minor interaction", "theoretical risk"
- Leave PICS Message code column blank
- Output for Table 12

### Agent 9: Unconditional Messages
- From BNF + EMC data, identify messages that should ALWAYS be displayed (no trigger/condition):
  - Administration instructions (e.g. "swallow whole with plenty of water")
  - Storage/handling warnings
  - Withdrawal warnings (e.g. "do not withdraw suddenly")
  - Form-specific messages
- For each message:
  - Target: Prescriber (P) or Nurse (N)
  - Form: specific form or ALL
  - Warning level: typically 0-1
- Leave PICS Message code column blank
- Output for Table 13

### Agent 10: Result Warnings
- From BNF renal_impairment and hepatic_impairment data, and EMC Section 4.4:
  - Extract threshold-based warnings (eGFR, creatinine clearance, ALT, AST, platelets, etc.)
  - Format using PICS syntax: `{{{If [Result][Comparator][Value with units], [Message], [Doctor/Nurse], Level [0-3], Validity [N] days}}}`
- Also extract age-based dose modifications
- Note any Blueteq requirements if found
- If drug is Amber, include the appropriate ESCA/RiCAD/Pure Amber message template
- Output for Table 15

## Phase 3: Dosing & Forms (requires Phase 1 data)

### Agent 11: Forms & Routes
- Read `Knowledge base/FormRoute.xlsx` (or cleaned version) to get the valid form-route combinations
- From BNF + EMC, identify all available forms and routes for this drug
- Include enteral routes: nasogastric, gastrostomy, jejunostomy, nasojejunal where applicable
- For each form-route combination:
  - Licensed: Y/N
  - UHB Formulary status: R/A/G/NF
- Identify the default form and route (most common prescribing combination)
- Output for Tables 16, 17

### Agent 12: Adult Dose Limits
- From BNF indications_and_dose and EMC Section 4.2:
  - For each form, extract:
    - Default dose (with units)
    - Default frequency
    - Duration of prescription (default + max)
    - Single dose warning limit → assign warning level (highest = level 3 hard stop, sensible threshold = level 2 password)
    - Total daily dose warning limit → assign warning level
  - If drug is given less frequently than daily (e.g. methotrexate weekly), set the appropriate periodic limit
- Determine PRN eligibility and settings if applicable
- Output for Tables 18-19 (PRN) and 20 (Adult dose limits)

### Agent 13: Paediatric Dose Limits
- From BNF + EMC, determine if paediatric doses differ from adult
- If same as adult: Table 21 = Yes
- If different: derive age brackets directly from BNF/EMC age ranges for this drug
  - **CRITICAL: Ensure age brackets are continuous with NO gaps**
  - E.g. if BNF says "1 month–1 year" and "1–5 years" and "6–11 years" and "12–17 years", use exactly those brackets
  - Lower bound is inclusive (>=), upper bound is exclusive (<)
  - For each bracket and form:
    - Default dose, frequency, duration
    - Single dose limit + warning level
    - Daily dose limit + warning level
- Output for Tables 21-22

## Phase 4: Compilation

### Agent 14: Reference Compiler
- Collect all URLs accessed during data gathering
- Record today's date as the access date
- Format for Table 23: Source description | URL | Date accessed

### Agent 15: Final Compilation
Assemble ALL agent outputs into two formats:

#### Format 1: Human-Reviewable Drug Sheet
Create a markdown document that mirrors the Non-infusion Drugsheet v3.6 template layout:
- All tables populated with gathered data
- Manual fields marked `[TO BE COMPLETED]`
- Human review flags clearly highlighted in bold: `**[HUMAN REVIEW REQUIRED]**`
- Suggested new drug classes highlighted: `**[SUGGESTED NEW CLASS]**`
- Save to: `output/{drug_name}_drugsheet_review.md`

#### Format 2: Programmer/EPMA Format
Create a structured JSON file with all data keyed for direct entry into PICS:
- Each table as a named section
- Warning levels as integers
- Codes (ICD-10, dm+d, PICS class) as separate fields
- Flags for manual completion
- Save to: `output/{drug_name}_drugsheet_epma.json`

## Important Rules

- **NEVER modify original Knowledge base files**
- **All clinical data must be referenced** with source URL and access date
- **Age brackets must be continuous** — no gaps between paediatric dose ranges
- **Warning levels**: 0=information, 1=tick box, 2=password, 3=disallow
- **Prefix contraindications** with `contraindication:` and cautions with `caution:`
- **Flag incomplete class mappings** with `[HUMAN REVIEW REQUIRED]`
- **Leave PICS message code columns blank** for manual entry by PICS team
- **Leave prescriber privilege and directorate fields as** `[TO BE COMPLETED]`
- If EMC and BNF data conflict, present BOTH with a note for human review
