# newgrad-job-notifier

Polls [SimplifyJobs/New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions)
(`dev` branch) on a schedule, pushes an [ntfy.sh](https://ntfy.sh) notification
for each newly added posting, and maintains a small `latest_jobs.json` for a
Scriptable iOS home-screen widget to read.

## How it works

- `check_jobs.py` fetches `.github/scripts/listings.json` from the repo (a
  structured JSON feed Simplify's own bot maintains). If that's ever
  unavailable, it falls back to best-effort parsing of the README's markdown
  table.
- It diffs the current active listings against `snapshot.json` (ids of
  postings already seen) to find new ones.
- New postings trigger a POST to `https://ntfy.sh/<topic>` with the company
  as the notification title and the role as the body; tapping the
  notification opens the application link.
- The top 10 postings are written to `latest_jobs.json` (company + role
  only), ranked by a priority tier before recency: big tech / well-known SV
  companies (see `BIG_TECH_COMPANIES` in `check_jobs.py`) and postings
  located in CA or NYC (see `PRIORITY_LOCATION_TOKENS`) get bumped above
  everything else. Edit those two lists in `check_jobs.py` to change what
  counts as "priority".
- `.github/workflows/check-jobs.yml` runs this on a cron schedule and commits
  the updated `snapshot.json` / `latest_jobs.json` back to the repo.
- `scriptable/NewGradJobsWidget.js` is an iOS Scriptable widget that reads
  `latest_jobs.json` via its raw GitHub URL and displays the most recent
  postings on your home screen.

## Local testing

```
NTFY_TOPIC=your-topic-name python3 check_jobs.py
```

Set `DRY_RUN=1` to run the full pipeline (fetch, diff, write files) without
actually POSTing to ntfy — useful for testing without spamming your phone.

The very first run only seeds `snapshot.json`; it does not send
notifications for the entire existing backlog.
