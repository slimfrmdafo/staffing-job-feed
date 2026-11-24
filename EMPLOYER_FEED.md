# Employer job feed

The employer feed publishes beside the staffing feed in this repository's `feed` branch. The board needs only the fixed public CSV URL; it needs no GitHub login or new access to its own code.

- CSV: https://raw.githubusercontent.com/slimfrmdafo/staffing-job-feed/feed/employer_jobs.csv
- Live status: https://raw.githubusercontent.com/slimfrmdafo/staffing-job-feed/feed/employer_status.txt
- Cloud collections: https://github.com/slimfrmdafo/staffing-job-feed/actions/workflows/employer-collect.yml
- Hourly timer: https://github.com/slimfrmdafo/staffing-job-feed/actions/workflows/employer-clock.yml

## Scope and source rules

The eight priority employers are attempted first on every cloud run, followed by every other employer in `employer_collectors.REGISTRY`. City of Charlotte is added alongside the requested Aviation Department/airport source. Airport rows require aviation/airport content in the full posting; the separate city source covers other matching city roles. The airport's own careers page identifies more than 700 Aviation Department employees: https://www.cltairport.com/careers/ .

First-party search pages/services enumerate native IDs and all result pages. Each included row is read from the employer's full posting page or the full posting resource used by that page. Search teasers are never substituted for descriptions. Workday uses ordinary Chromium rendering, including from the cloud. No CAPTCHA solving or challenge bypass is implemented.

The exact twenty-column contract is FEED_SPEC.md. `firm` is the employer's stable name. Optional values remain empty unless explicitly posted. Pay amounts are kept as posted; hourly/yearly units are assigned only when stated. Names are never guessed from email addresses. Nonclinical operations, execution, risk/controls, compliance, governance, change, process, PMO and related project/program roles are included around Charlotte and for US remote work. Store, branch teller, clinical, warehouse, trades, software engineering and construction jobs are excluded. Known-pay ranges entirely below $60,000/year are excluded; unknown pay remains available for the board's final filtering.

A complete successful newer pull replaces only its own employer. Failed searches or unreadable full details preserve the previous whole employer snapshot. Workday's ID-only entries without a title or public link are recorded separately. If such an entry was previously published in this feed, that employer's pull fails and preserves its prior rows. A known Lowe's posting missing from the portal search is reread in full before it can disappear, protecting against indexing lag between its two career platforms.

`employer_state.json`, `employer_jobs.csv` and `employer_status.txt` are independent of the staffing state and filenames. Both publishers advance the shared branch without force, rebase after conflicts, and retain the other feed's files. The CSV, status and state for a publication are committed together.

## Hourly execution

The cloud timer uses the same verified relay pattern as staffing. Each tick queues its successor behind the `employer-hourly-clock` environment's automatic 60-minute server-side wait, then dispatches collection. There are no reviewers or manual approvals. A waiting timer does not allocate a runner. The extra hourly cron is a watchdog; the server-side timer supplies normal recurrence.

The native macOS service `com.employer.jobfeed` starts at login and runs at hourly intervals. It reads shared cloud status and collects only employers whose latest cloud attempt failed. It uses the isolated runtime in `~/Library/Application Support/StaffingFeed`, a separate lock and separate employer logs. It runs independently of Codex. The Mac must be awake, online and logged in; cloud execution continues without it.

## Check, pause and resume

Open the status URL for current per-employer counts, errors, last successful snapshots and run receipts. A cloud receipt with `trigger=cloud_clock` and `timer_run_id` was dispatched automatically. A Mac receipt with `trigger=mac_launchd` came from the background service. Setup validations are separately identifiable.

Pause cloud collection by disabling **both** employer workflows and canceling waiting/queued employer clock runs:

```sh
gh workflow disable employer-clock.yml --repo slimfrmdafo/staffing-job-feed
gh workflow disable employer-collect.yml --repo slimfrmdafo/staffing-job-feed
# Cancel active/waiting employer timer runs from their Actions pages.
```

Resume the cloud relay once:

```sh
gh workflow enable employer-collect.yml --repo slimfrmdafo/staffing-job-feed
gh workflow enable employer-clock.yml --repo slimfrmdafo/staffing-job-feed
gh workflow run employer-clock.yml --repo slimfrmdafo/staffing-job-feed -f start_now=true
```

Pause the Mac collector:

```sh
launchctl disable gui/501/com.employer.jobfeed
launchctl bootout gui/501/com.employer.jobfeed
```

Resume it:

```sh
launchctl enable gui/501/com.employer.jobfeed
launchctl bootstrap gui/501 "$HOME/Library/LaunchAgents/com.employer.jobfeed.plist"
```

Check the Mac with `launchctl print gui/501/com.employer.jobfeed`. Its logs are `~/Library/Application Support/StaffingFeed/work/employer-mac-agent.log` and `employer-mac-agent-error.log`. Staffing has its own service and cloud workflows; these controls affect only the employer feed. Pausing preserves the published files.
