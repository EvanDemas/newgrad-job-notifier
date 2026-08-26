// New Grad Jobs Widget
// Scriptable widget that shows the most recent postings from
// SimplifyJobs/New-Grad-Positions, tracked by EvanDemas/newgrad-job-notifier.
//
// Setup: change JOBS_URL below if you rename the repo/branch.

const JOBS_URL =
  "https://raw.githubusercontent.com/EvanDemas/newgrad-job-notifier/main/latest_jobs.json";
const REPO_URL = "https://github.com/SimplifyJobs/New-Grad-Positions";

const family = config.widgetFamily || "medium";
const jobCount = family === "small" ? 3 : 5;

async function fetchJobs() {
  const req = new Request(JOBS_URL);
  req.timeoutInterval = 15;
  const data = await req.loadJSON();
  if (!data || !Array.isArray(data.jobs)) {
    throw new Error("Unexpected response shape");
  }
  return data;
}

function buildErrorWidget(message) {
  const w = new ListWidget();
  w.backgroundColor = new Color("#111111");
  const title = w.addText("New Grad Jobs");
  title.font = Font.boldSystemFont(13);
  title.textColor = Color.white();
  w.addSpacer(6);
  const body = w.addText(message);
  body.font = Font.systemFont(12);
  body.textColor = new Color("#ff6b6b");
  body.minimumScaleFactor = 0.7;
  w.url = REPO_URL;
  return w;
}

function formatUpdatedLabel(isoString) {
  if (!isoString) return "";
  try {
    const d = new Date(isoString);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch (e) {
    return "";
  }
}

async function buildWidget() {
  let data;
  try {
    data = await fetchJobs();
  } catch (e) {
    return buildErrorWidget("Couldn't load jobs");
  }

  const jobs = data.jobs.slice(0, jobCount);
  const w = new ListWidget();
  w.backgroundColor = new Color("#111111");
  w.url = REPO_URL;

  const header = w.addText("New Grad Jobs");
  header.font = Font.boldSystemFont(13);
  header.textColor = Color.white();

  const updatedLabel = formatUpdatedLabel(data.updated_utc);
  if (updatedLabel) {
    const sub = w.addText(`Updated ${updatedLabel}`);
    sub.font = Font.systemFont(9);
    sub.textColor = new Color("#888888");
  }

  w.addSpacer(8);

  if (jobs.length === 0) {
    const empty = w.addText("No postings found");
    empty.font = Font.systemFont(12);
    empty.textColor = new Color("#aaaaaa");
    return w;
  }

  jobs.forEach((job, i) => {
    const row = w.addStack();
    row.layoutVertically();

    const companyText = row.addText(job.company || "Unknown company");
    companyText.font = Font.semiboldSystemFont(12);
    companyText.textColor = Color.white();
    companyText.lineLimit = 1;
    companyText.minimumScaleFactor = 0.8;

    const roleText = row.addText(job.role || "");
    roleText.font = Font.systemFont(11);
    roleText.textColor = new Color("#bbbbbb");
    roleText.lineLimit = 1;
    roleText.minimumScaleFactor = 0.7;

    if (i < jobs.length - 1) {
      w.addSpacer(6);
    }
  });

  return w;
}

const widget = await buildWidget();

if (config.runsInWidget) {
  Script.setWidget(widget);
} else {
  // Preview in-app when run manually
  if (family === "small") {
    await widget.presentSmall();
  } else {
    await widget.presentMedium();
  }
}

Script.complete();
