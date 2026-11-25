# Multilingual Receipt & UPI Expense Analyzer

Upload a UPI payment screenshot or a photo of a bill. The app reads the vendor and amount, sorts the spending into categories, and shows a monthly budget view with alerts and practical suggestions.

## Chosen vertical

**Multilingual Receipt & UPI Expense Analyzer.** The persona is an everyday user in India who pays through UPI and keeps paper bills in English, Hindi, Marathi or another Indian language, and wants to know where the month's money went.

## Approach and logic

The app is a "smart, dynamic assistant" built from two parts that each do the job they are best at:

1. **AI reads the image** (Gemini). The model returns structured JSON: vendor, amount, date, language, a category hint and a confidence score. It is asked for the English spelling of the vendor when it can give one, which is what makes multilingual receipts work.
2. **Plain code makes the decisions.** Everything after reading is deterministic and unit tested:
   - **Categorizer** (`app/categorizer.py`): keyword rules in English and Devanagari. The longest matching keyword wins, so "Swiggy Instamart" is Groceries, not Food. Short keywords must match a whole word, so "Cola Corner" is not the cab company "Ola". The AI's category hint is used only if no rule matches.
   - **Budget engine** (`app/budget.py`): per-category totals, status (on track below 80% of budget, close to the limit from 80%, over budget above 100%), and a month-end projection for the month in progress.
   - **Alerts and suggestions use context**: if a category is over budget, the app names the vendor that drives it (when one vendor is 40% or more of that category) and points to a category with unused budget that could cover the gap.

The user stays in control. Every extracted row can be edited before it counts, a low-confidence reading is flagged, and correcting a category teaches the rest of the session (same vendor, same category).

## How it works

```
Browser                              FastAPI (Cloud Run)                 Gemini API
-------                              -------------------                 ----------
choose images  -- resize to 1600px -->  POST /api/extract
                                        check size + file signature
                                        send image + JSON schema   ---->  read receipt
                                        validate + clean the answer <----
                                        categorize with rules
edit rows  <---------------------------  expenses (JSON)
edit rows / budgets  ----------------->  POST /api/analyze  -> totals, status, alerts, tips
bars + alerts  <-----------------------
```

| Path | Purpose |
|---|---|
| `GET /api/config` | Which features are on, upload limits, category list |
| `POST /api/extract` | Up to 5 images, returns one result per image |
| `GET /api/categorize` | Rule-based category for a vendor typed by hand |
| `POST /api/analyze` | Budget analysis for a month |

Files: `app/` (backend), `static/` (UI, plain HTML/CSS/JS, no build step), `tests/`, `Dockerfile`.

## Quality notes

- **Security**: the API key lives only in an environment variable or Secret Manager. Uploads are checked by file signature (JPEG, PNG, WebP), size and count. Text read from images is treated as untrusted: it is cleaned on the server, rendered with `textContent` (never `innerHTML`), and exported to CSV with formula-injection protection. The model is told to ignore instructions inside images. Responses carry a strict Content-Security-Policy and other headers, API docs are switched off, errors never leak internals, and requests are rate limited. The container runs as a non-root user. Images and amounts are never written to disk or logged.
- **Efficiency**: images are shrunk in the browser before upload, rules run before any AI call, and nothing is stored.
- **Accessibility**: labelled fields, keyboard-friendly upload, visible focus, status messages announced to screen readers, bars that carry their values and status as text (not colour alone), responsive layout, reduced-motion support.
- **Testing**: `tests/` covers the categorizer, budget maths, extraction validation (with a fake AI transport, no network), upload and sanitising checks, and the API.

## Assumptions

- Amounts are in Indian rupees. Receipts in other currencies are read but treated as rupees.
- A UPI screenshot shows one payment, so one image gives one expense. A bill's grand total is used, not line items.
- Expenses without a date count toward the month being viewed.
- Dates like `05/11/2026` are read day first, as is usual in India.
- Budgets and expenses live only in the browser page. Reloading clears them. Use "Download CSV" to keep a copy.
- Images are sent to Google's Gemini API to be read. Use only receipts you are comfortable sending there.
- Readings can be wrong, especially for blurry or handwritten bills, so rows are shown for checking.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
export GEMINI_API_KEY="your-key"                         # Windows: set GEMINI_API_KEY=your-key
# optional: export GEMINI_MODEL="gemini-flash-latest"
uvicorn app.main:app --reload --port 8080
```

Open http://localhost:8080. Without a key the app still works for manual entry and sample data.

## Run the tests

```bash
python -m unittest discover -s tests -t . -v      # or: pytest
```

The API tests need `fastapi` and `httpx` (in `requirements-dev.txt`) and are skipped if they are missing.

## Deploy to Google Cloud Run

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com

# Store the key as a secret (never in the repo)
printf '%s' "YOUR_GEMINI_API_KEY" | gcloud secrets create gemini-api-key --data-file=-

# Let Cloud Run read it (replace PROJECT_NUMBER with your project number)
gcloud secrets add-iam-policy-binding gemini-api-key \
  --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# Build and deploy from source
gcloud run deploy receipt-analyzer --source . --region asia-south1 \
  --allow-unauthenticated --set-secrets GEMINI_API_KEY=gemini-api-key:latest \
  --max-instances 3 --memory 512Mi
```

If asked to create an Artifact Registry repository, answer `Y`. The command prints the service URL: that is your Cloud Run link.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | none | Required for reading images |
| `GEMINI_MODEL` | `gemini-flash-latest` | Model name. Change it if your key does not support this one |
| `MAX_UPLOAD_BYTES` | 5242880 | Largest image accepted |
| `MAX_FILES` | 5 | Images per request |
| `RATE_LIMIT_PER_MINUTE` | 20 | Extraction requests per client per minute |
