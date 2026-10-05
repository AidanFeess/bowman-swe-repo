# Game Night Deal Tracker — Project Skeleton

A minimal web service for CSC 4033 that calculates a sale price from a price and a discount percent.

**Live service:** https://deal-tracker-skeleton.onrender.com/
**Endpoint docs:** https://deal-tracker-skeleton.onrender.com/docs
**Repository:** https://github.com/AidanFeess/bowman-swe-repo/tree/main/Project%20Skeleton

> Hosted on Render's free tier. The first load may take up to a minute while the service wakes up.

---

## Websites and Tools Used

| Tool | What it's for | Link |
|---|---|---|
| GitHub | Stores the code | https://github.com |
| GitHub Actions | Runs the tests automatically on every push | https://docs.github.com/actions |
| Render | Hosts the live web service | https://render.com |
| Python | Programming language | https://www.python.org |
| Flask | Turns Python functions into web endpoints | https://flask.palletsprojects.com |
| Gunicorn | Runs the Flask app on a real server | https://gunicorn.org |
| pytest | Runs the automated tests | https://docs.pytest.org |

---

## Endpoints

| Endpoint | Expects | Returns |
|---|---|---|
| `GET /` | nothing | 200 with the service name and `"running"` |
| `GET /discount` | `price`: a number 0 or more<br>`percent`: a number from 0 to 100 | 200 with `price`, `percent`, and `sale_price`, or 400 with an error message |
| `GET /docs` | nothing | A page listing every endpoint |

**Examples:**
- `/discount?price=60&percent=25` returns `200` and `{"price": 60.0, "percent": 25.0, "sale_price": 45.0}`
- `/discount?price=60&percent=150` returns `400` and `{"error": "..."}`

---

## Files

All service files are in the `Project Skeleton` folder. The test workflow is at the repository root, because GitHub Actions only reads workflows from there.

| File | Purpose |
|---|---|
| `Project Skeleton/app.py` | The Flask web service |
| `Project Skeleton/test_app.py` | Four automated tests |
| `Project Skeleton/requirements.txt` | Packages to install (Flask, Gunicorn) |
| `.github/workflows/tests.yml` | Tells GitHub Actions to run the tests on every push |

---

## How to Start the Service on Render

1. Go to https://render.com and click **Get Started**. Sign up with **GitHub**.
2. In the dashboard, click **+ New > Web Service**.
3. Connect GitHub and select the `bowman-swe-repo` repository.
4. Fill in the settings:

   | Field | Value |
   |---|---|
   | Name | `deal-tracker-skeleton` |
   | Language | Python 3 |
   | Branch | `main` |
   | Region | Ohio (US East) |
   | Root Directory | `Project Skeleton` |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `gunicorn app:app` |
   | Instance Type | Free |

5. Click **Deploy Web Service**.
6. Wait for the log to say **"Your service is live"** (about 2 to 3 minutes).
7. Open the URL shown at the top of the page.

Render redeploys automatically every time code is pushed to `main`.

---

## Automated Tests

Tests run on every push using GitHub Actions. To see results:

1. Open the **Actions** tab of this repository.
2. Click a run, then the **test** job, then **Run pytest -v**.

Each commit in the history shows a green check (passed) or a red X (failed).

| Test | Sends | Passes when |
|---|---|---|
| Home is running | `/` | status is 200 and status is `"running"` |
| Valid discount works | `/discount?price=60&percent=25` | status is 200 and `sale_price` is 45.0 |
| Invalid percent is refused | `/discount?price=60&percent=150` | status is 400 |
| Missing price is refused | `/discount?percent=25` | status is 400 |
