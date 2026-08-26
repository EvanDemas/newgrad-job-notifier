#!/usr/bin/env python3
"""
Checks SimplifyJobs/New-Grad-Positions for newly added job postings,
sends an ntfy.sh push notification for each new one, and writes out
a small "latest jobs" file for a home-screen widget to read.

Primary data source: .github/scripts/listings.json on the `dev` branch,
which is a structured JSON array Simplify's own bot maintains. This is
far more reliable than scraping the README table, so it's tried first.
If that ever disappears, we fall back to parsing the README's markdown
table.
"""

import hashlib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

REPO = "SimplifyJobs/New-Grad-Positions"
BRANCH = "dev"
LISTINGS_JSON_URL = (
    f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/.github/scripts/listings.json"
)
README_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/README.md"

SNAPSHOT_PATH = os.environ.get("SNAPSHOT_PATH", "snapshot.json")
LATEST_JOBS_PATH = os.environ.get("LATEST_JOBS_PATH", "latest_jobs.json")
LATEST_JOBS_COUNT = 10
# How long to remember an id after a listing goes inactive/disappears, so the
# snapshot doesn't grow forever. Currently-active listings are ALWAYS kept
# regardless of this cutoff or how many there are -- this only prunes ids for
# listings that are no longer active AND old enough to be irrelevant.
STALE_ID_RETENTION_DAYS = 120

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_URL_BASE = "https://ntfy.sh"
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

# Companies whose postings get bumped to the top of latest_jobs.json (the
# widget's list). Matched as whole words, case-insensitive, against
# company_name. Edit freely -- this is just a curated "big tech" list.
BIG_TECH_COMPANIES = [
    # FAANG / MAMAA
    "meta", "facebook", "apple", "amazon", "netflix", "google", "alphabet",
    "microsoft",
    # other large / notable SV & big tech
    "nvidia", "openai", "anthropic", "tesla", "spacex", "uber", "airbnb",
    "stripe", "palantir", "salesforce", "adobe", "linkedin", "snap",
    "pinterest", "databricks", "bytedance", "tiktok", "oracle", "ibm",
    "intel", "amd", "qualcomm", "cisco", "vmware", "reddit", "doordash",
    "instacart", "robinhood", "coinbase", "block", "square", "zoom",
    "dropbox", "atlassian", "servicenow", "workday", "splunk", "mongodb",
    "snowflake", "twilio", "asana", "figma", "notion", "discord", "roblox",
    "epic games", "unity", "waymo", "cruise", "rivian", "lucid",
    "deepmind", "xai", "x corp", "twitter",
]
BIG_TECH_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(name) for name in BIG_TECH_COMPANIES) + r")\b",
    re.IGNORECASE,
)

# Location tokens (matched exactly, after splitting on commas) that count as
# "CA or NYC" for widget ranking purposes.
PRIORITY_LOCATION_TOKENS = {
    "ca", "california", "sf", "san francisco", "bay area", "silicon valley",
    "los angeles", "san jose", "mountain view", "menlo park", "palo alto",
    "sunnyvale", "santa clara", "cupertino", "redwood city",
    "ny", "new york", "nyc", "manhattan", "brooklyn",
}


def is_big_tech(company):
    return bool(BIG_TECH_PATTERN.search(company or ""))


def is_priority_location(location):
    if not location:
        return False
    for part in re.split(r"[,/]", location):
        if part.strip().lower() in PRIORITY_LOCATION_TOKENS:
            return True
    return False


def widget_priority(job):
    """Higher = shown first in latest_jobs.json. Big tech companies and
    CA/NYC locations get bumped up; recency is still the tiebreaker within
    each tier."""
    tier = (2 if is_big_tech(job["company"]) else 0) + (
        1 if is_priority_location(job.get("location", "")) else 0
    )
    return (tier, job["date_posted"])

REQUEST_TIMEOUT = 30
USER_AGENT = "newgrad-job-notifier/1.0 (+https://github.com/EvanDemas/newgrad-job-notifier)"


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return resp.read()


def fetch_listings_from_json():
    """Try the structured listings.json source. Returns a list of normalized
    job dicts, or None if the source isn't available / doesn't parse."""
    try:
        raw = http_get(LISTINGS_JSON_URL)
        data = json.loads(raw)
    except Exception as e:
        print(f"listings.json unavailable or unparsable: {e}", file=sys.stderr)
        return None

    if not isinstance(data, list):
        print("listings.json did not contain a list; ignoring", file=sys.stderr)
        return None

    jobs = []
    for entry in data:
        if not entry.get("active", True) or not entry.get("is_visible", True):
            continue
        job_id = entry.get("id")
        company = entry.get("company_name")
        title = entry.get("title")
        url = entry.get("url")
        if not (job_id and company and title and url):
            continue
        locations = entry.get("locations") or []
        jobs.append(
            {
                "id": str(job_id),
                "company": company,
                "role": title,
                "url": url,
                "location": ", ".join(locations) if locations else "",
                "date_posted": entry.get("date_posted") or entry.get("date_updated") or 0,
            }
        )

    if not jobs:
        return None

    jobs.sort(key=lambda j: j["date_posted"], reverse=True)
    return jobs


TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
HTML_IMG_RE = re.compile(r"<img[^>]*>")
HTML_TAG_RE = re.compile(r"<[^>]+>")


def clean_cell(cell):
    cell = HTML_IMG_RE.sub("", cell)
    cell = HTML_TAG_RE.sub("", cell)
    return cell.strip().strip("*_").strip()


def extract_first_link(cell):
    match = MARKDOWN_LINK_RE.search(cell)
    if match:
        return match.group(2).strip()
    return None


def fetch_listings_from_readme():
    """Best-effort fallback: parse the README's markdown job table.
    Only used if listings.json is unavailable."""
    try:
        raw = http_get(README_URL).decode("utf-8", errors="replace")
    except Exception as e:
        print(f"Failed to fetch README fallback: {e}", file=sys.stderr)
        return []

    lines = raw.splitlines()
    jobs = []
    last_company = None
    in_table = False

    for line in lines:
        m = TABLE_ROW_RE.match(line)
        if not m:
            in_table = False
            continue

        cells = [c for c in m.group(1).split("|")]
        if len(cells) < 4:
            continue

        # Header/separator rows
        joined = "".join(cells).strip()
        if not joined or set(joined.replace(" ", "")) <= {"-", ":"}:
            continue
        if not in_table:
            # First non-separator row after a non-table line is treated as
            # a header if it doesn't look like data (no links, no locations)
            if "application" in joined.lower() and "company" in joined.lower():
                in_table = True
                continue
            in_table = True

        company_raw = clean_cell(cells[0])
        role_raw = clean_cell(cells[1])
        location_raw = clean_cell(cells[2]) if len(cells) > 2 else ""
        application_cell = cells[3] if len(cells) > 3 else ""

        company = company_raw if company_raw and company_raw != "↳" else last_company
        if not company:
            continue
        last_company = company

        role = role_raw
        url = extract_first_link(application_cell)
        if not role or not url:
            continue

        synthetic_id = hashlib.sha1(f"{company}|{role}|{url}".encode()).hexdigest()
        jobs.append(
            {
                "id": synthetic_id,
                "company": company,
                "role": role,
                "url": url,
                "location": location_raw,
                # README rows are already in "most recent first" order;
                # fabricate a descending rank so downstream sort is stable.
                "date_posted": -len(jobs),
            }
        )

    return jobs


def fetch_current_listings():
    jobs = fetch_listings_from_json()
    if jobs:
        print(f"Loaded {len(jobs)} active listings from listings.json")
        return jobs

    print("Falling back to README table parsing", file=sys.stderr)
    jobs = fetch_listings_from_readme()
    print(f"Parsed {len(jobs)} listings from README fallback")
    return jobs


def load_snapshot():
    if not os.path.exists(SNAPSHOT_PATH):
        return {}
    try:
        with open(SNAPSHOT_PATH, "r") as f:
            data = json.load(f)
        return data.get("seen_ids", {})
    except Exception as e:
        print(f"Could not read snapshot ({e}); starting fresh", file=sys.stderr)
        return {}


def prune_seen_ids(seen_ids, current_jobs):
    """Drop old ids for listings that are no longer active, so the snapshot
    doesn't grow forever. Never drops an id for a listing that's currently
    active, no matter how many there are or how old its date_posted is."""
    current_ids = {j["id"] for j in current_jobs}
    cutoff = datetime.now(timezone.utc).timestamp() - STALE_ID_RETENTION_DAYS * 86400
    return {
        job_id: ts
        for job_id, ts in seen_ids.items()
        if job_id in current_ids or ts >= cutoff
    }


def save_snapshot(seen_ids, current_jobs):
    trimmed = prune_seen_ids(seen_ids, current_jobs)
    with open(SNAPSHOT_PATH, "w") as f:
        json.dump(
            {
                "seen_ids": trimmed,
                "last_run_utc": datetime.now(timezone.utc).isoformat(),
            },
            f,
            indent=2,
        )
        f.write("\n")


def save_latest_jobs(jobs):
    ranked = sorted(jobs, key=widget_priority, reverse=True)
    latest = ranked[:LATEST_JOBS_COUNT]
    out = []
    for j in latest:
        out.append(
            {
                "company": j["company"],
                "role": j["role"],
            }
        )
    with open(LATEST_JOBS_PATH, "w") as f:
        json.dump(
            {
                "updated_utc": datetime.now(timezone.utc).isoformat(),
                "jobs": out,
            },
            f,
            indent=2,
        )
        f.write("\n")


def send_ntfy_notification(job):
    if DRY_RUN:
        print(f"[DRY RUN] Would notify: {job['company']} - {job['role']}")
        return
    if not NTFY_TOPIC:
        print("NTFY_TOPIC not set; skipping notification", file=sys.stderr)
        return

    title = f"New grad job: {job['company']}"
    body = job["role"]

    url = f"{NTFY_URL_BASE}/{NTFY_TOPIC}"
    req = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Title": title,
            "Click": job["url"],
            "Tags": "briefcase",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            resp.read()
        print(f"Notified: {job['company']} - {job['role']}")
    except Exception as e:
        print(f"Failed to send notification for {job['company']}: {e}", file=sys.stderr)


def main():
    jobs = fetch_current_listings()
    if not jobs:
        print("No listings fetched from any source; aborting without changes.", file=sys.stderr)
        sys.exit(1)

    seen_ids = load_snapshot()
    is_first_run = len(seen_ids) == 0

    new_jobs = [j for j in jobs if j["id"] not in seen_ids]

    if is_first_run:
        # Don't blast a notification for every historical listing on the very
        # first run — just establish the baseline.
        print(f"First run: seeding snapshot with {len(jobs)} listings, no notifications sent.")
    else:
        # Notify oldest-new-first so the newest ends up as the most recent
        # notification on the phone.
        for job in sorted(new_jobs, key=lambda j: j["date_posted"]):
            send_ntfy_notification(job)
        print(f"{len(new_jobs)} new listing(s) found.")

    for job in jobs:
        seen_ids[job["id"]] = job["date_posted"]

    save_snapshot(seen_ids, jobs)
    save_latest_jobs(jobs)


if __name__ == "__main__":
    main()
