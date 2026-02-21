---
name: gemini-verify
description: Use Gemini CLI as a verification tool for cross-checking drug data, web searching for latest guidelines, and confirming clinical accuracy. Delegates specific queries to Gemini for a second opinion.
user-invocable: true
allowed-tools: Bash, Read, Write
argument-hint: <query or "verify" followed by data to check>
---

# Gemini Verification Agent

Use Gemini CLI to cross-check, verify, or search for information that complements the main workflow. Gemini has built-in Google Search which makes it excellent for finding the latest guidelines and confirming clinical data.

## When to Use

- **Cross-checking**: Verify drug data gathered by MCP servers against a second source
- **Web searching**: Find latest NICE guidelines, trust protocols, or clinical evidence
- **Confirming results**: Double-check ICD-10 mappings, drug interactions, or dose limits
- **Codebase review**: Ask Gemini to review generated output for consistency

## How to Run

The user's query/task is: **$ARGUMENTS**

### Step 1: Determine the query type

Parse the arguments to determine what Gemini should do:
- If starts with "verify": extract the data to verify and construct a verification prompt
- If starts with "search": construct a web search query
- If starts with "review": pass code/data for review
- Otherwise: treat as a general query

### Step 2: Execute via Gemini CLI

Run the query through Gemini CLI. The system should have Gemini CLI installed (`gemini` command).

```bash
# Check if Gemini CLI is available
which gemini || echo "Gemini CLI not found. Install with: npm install -g @anthropic-ai/gemini-cli"

# Run a query
echo "{constructed_prompt}" | gemini
```

If Gemini CLI is not installed, fall back to using web search tools available in Claude Code (WebSearch, WebFetch) to perform the verification manually.

### Step 3: Parse and report

- Compare Gemini's response with existing data
- Flag any discrepancies
- Report findings with confidence level

## Example Uses

```
/gemini-verify search latest NICE guidelines for methotrexate prescribing 2024
/gemini-verify verify amoxicillin max adult dose 3g daily
/gemini-verify review output/amoxicillin_drugsheet_review.md for clinical accuracy
/gemini-verify ICD-10 code for hepatic impairment
```

## Fallback

If Gemini CLI is not available, use these Claude Code tools instead:
- `WebSearch` — for Google searches
- `WebFetch` — for fetching and analysing web pages
- `PubMed` cloud MCP — for clinical literature
- `ICD-10 Codes` cloud MCP — for code lookups
