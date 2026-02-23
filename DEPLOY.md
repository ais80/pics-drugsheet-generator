# PICS Drug Sheet Generator — Deployment Guide

## Overview

This app runs on **Google Cloud Run** (serverless Docker). You deploy it entirely from a browser using **Google Cloud Shell** — no Python, Node.js, or Docker needed on your local PC.

## Prerequisites

- A Google Cloud project with billing enabled
- The `Drugsheets/` folder synced to Google Drive (or available as a zip)

---

## Option A: Deploy from Google Drive (any PC, just a browser)

### 1. Upload to Google Drive

Copy the entire `Drugsheets/` folder to your Google Drive. The key files needed are:

```
Drugsheets/
├── Dockerfile
├── .dockerignore
├── bnf-mcp/
│   ├── pyproject.toml
│   ├── generate.py
│   ├── api.py
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── style.css
└── Knowledge base/
    ├── drugsToClasses.xls
    ├── FormRoute.xlsx
    ├── ICD10_usage.xlsx
    ├── TFQavSummary.xlsx
    └── cleaned/
        ├── drugs_to_classes.xlsx
        ├── form_route.xlsx
        ├── icd10_usage.xlsx
        └── tfqav_summary.xlsx
```

### 2. Open Google Cloud Shell

Go to https://shell.cloud.google.com in your browser and open a terminal.

### 3. Copy files from Google Drive to Cloud Shell

```bash
# Mount Google Drive (follow the auth prompt)
cloudshell dl-auth

# Or: upload a zip file directly via Cloud Shell's "Upload" button (top-right)
# Then unzip:
# unzip Drugsheets.zip

# Alternatively, use gcloud storage if you've uploaded to a GCS bucket:
# gsutil -m cp -r gs://YOUR_BUCKET/Drugsheets .
```

**Easiest method:** Click the three-dot menu in Cloud Shell > "Upload" > select a zip of the Drugsheets folder.

### 4. Set your project

```bash
# Replace with your actual project ID
export PROJECT_ID="your-project-id"
gcloud config set project $PROJECT_ID

# Enable required APIs (first time only)
gcloud services enable cloudbuild.googleapis.com run.googleapis.com
```

### 5. Build and deploy

```bash
cd Drugsheets

# Build the container image
gcloud builds submit --tag gcr.io/$PROJECT_ID/pics-drugsheet-generator .

# Deploy to Cloud Run (London region)
gcloud run deploy pics-drugsheet-generator \
    --image gcr.io/$PROJECT_ID/pics-drugsheet-generator \
    --platform managed \
    --region europe-west2 \
    --allow-unauthenticated \
    --memory 1Gi \
    --cpu 1 \
    --timeout 300 \
    --max-instances 5 \
    --min-instances 0 \
    --port 8080
```

### 6. Get the URL

After deployment, Cloud Run prints the service URL:
```
Service URL: https://pics-drugsheet-generator-xxxx-nw.a.run.app
```

Share this URL with colleagues — they just need a browser.

---

## Option B: Deploy from a local machine with gcloud CLI

If you have `gcloud` CLI installed locally:

```bash
cd G:/Documents/PICS/Drugsheets

export PROJECT_ID="your-project-id"
gcloud config set project $PROJECT_ID

gcloud builds submit --tag gcr.io/$PROJECT_ID/pics-drugsheet-generator .

gcloud run deploy pics-drugsheet-generator \
    --image gcr.io/$PROJECT_ID/pics-drugsheet-generator \
    --platform managed --region europe-west2 \
    --allow-unauthenticated --memory 1Gi --cpu 1 \
    --timeout 300 --max-instances 5 --min-instances 0 --port 8080
```

---

## Local Development (optional, requires Python 3.12+)

```bash
cd Drugsheets/bnf-mcp

# Install dependencies
pip install -e ".[dev]"
# or with uv:
uv pip install -e ".[dev]"

# Run the web app
uvicorn api:app --reload --port 8080

# Open http://localhost:8080
```

---

## Updating the App

After making changes to any files:

```bash
cd Drugsheets

# Rebuild and redeploy (same commands as initial deploy)
gcloud builds submit --tag gcr.io/$PROJECT_ID/pics-drugsheet-generator .
gcloud run deploy pics-drugsheet-generator \
    --image gcr.io/$PROJECT_ID/pics-drugsheet-generator \
    --platform managed --region europe-west2
```

---

## Costs

- **Cloud Run**: Pay per request. Free tier covers ~2 million requests/month
- **Cloud Build**: 120 free build-minutes/day
- **Container Registry**: Minimal storage cost (~200MB image)
- **Estimated cost**: Near-zero for typical internal NHS use

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Build fails on `Knowledge base/` | Ensure the folder (with space in name) is present and .dockerignore doesn't exclude it |
| Generation times out (>300s) | Increase `--timeout` in deploy command |
| Out of memory | Increase `--memory` to `2Gi` |
| Can't access URL | Check `--allow-unauthenticated` was set, or configure IAM |
| Progress bar stuck | Check Cloud Run logs: `gcloud run logs read pics-drugsheet-generator` |
