# Staffing job feed

This repository collects staffing firms' own public job searches and full listing details, then publishes a single UTF-8 CSV for the existing board. The feed contract is [FEED_SPEC.md](FEED_SPEC.md).

- [Raw feed](https://raw.githubusercontent.com/slimfrmdafo/staffing-job-feed/feed/staffing_jobs.csv)
- [Live per-firm status](https://raw.githubusercontent.com/slimfrmdafo/staffing-job-feed/feed/staffing_status.txt)
- [Cloud runs](https://github.com/slimfrmdafo/staffing-job-feed/actions/workflows/collect.yml)
- [Published files and history](https://github.com/slimfrmdafo/staffing-job-feed/tree/feed)

These addresses stay fixed. `main` holds the implementation. The `feed` branch holds the CSV, status and shared per-firm state. Both runners publish there; there is no file transfer, import or manual start in the hourly process.

## Schedule and runners

The cloud runs every hour at minute 07 UTC, using GitHub Actions. GitHub may start scheduled jobs late; the status file records actual start, completion and publication times.

The native macOS LaunchAgent **com.staffing.jobfeed** runs every hour at minute 56 and starts automatically at login. Its runtime is installed in `~/Library/Application Support/StaffingFeed`, with a separate Python environment, browser and source checkout. The script updates its code with a fast-forward pull, reads shared status, and selects only firms whose latest cloud attempt failed. The Mac must be awake, online and logged in. The collector does not require Codex to be open. The Codex automation **Hourly Mac staffing fallback** checks service health hourly at minute 06; only this additional health check needs Codex to be running. Cloud collection continues independently.

The cloud retries every firm each hour, including firms previously assigned to Mac fallback. When a cloud pull recovers, the next Mac run automatically stops collecting that firm. Successful zero-match searches are not considered failures.

The Mac setup uses the existing GitHub login in the macOS keychain; no token is committed to this repository. The cloud uses its repository-scoped `GITHUB_TOKEN`.

## Check it

Open the live status link above. It shows the last publication time, current rows and contract count per firm, the runner that supplied each snapshot, the latest attempt from each runner, and failures with their causes. Contract counts include contract-to-hire listings.

For cloud execution evidence, open Cloud runs and inspect runs whose event is **schedule**. Manually dispatched validation runs are separate. For Mac execution evidence, inspect recent status entries with `route=mac` and `trigger=mac_launchd`. The local service log is `~/Library/Application Support/StaffingFeed/work/mac-agent.log`.

The source CSV has exactly the twenty columns required by FEED_SPEC.md. A row's optional fields stay empty when the source does not supply a usable explicit value. Rows with unknown pay are retained for the board to evaluate; a stated range is excluded if even its upper bound is below $60,000/year (hourly rates are compared using 2,080 hours/year). Target pay and individual-contributor preferences remain available to the board's existing scoring and filtering.

Charlotte-area cities include the places explicitly named in the request. Where a listing supplies coordinates, locations within 50 straight-line miles of Charlotte are also accepted. US remote roles are included. Role matching includes common operations, controls, regulatory, AML/KYC and onboarding titles alongside the requested titles; the existing board performs final filtering and scoring.

## Pause and resume

**Cloud:** In GitHub Actions, open **Hourly staffing feed**, choose the workflow menu, then disable or enable the workflow. Alternatively:

```sh
gh workflow disable collect.yml --repo slimfrmdafo/staffing-job-feed
gh workflow enable collect.yml --repo slimfrmdafo/staffing-job-feed
```

**Mac collector:** Use these commands to pause and resume the background service:

```sh
launchctl disable gui/501/com.staffing.jobfeed
launchctl bootout gui/501/com.staffing.jobfeed

# Resume:
launchctl enable gui/501/com.staffing.jobfeed
launchctl bootstrap gui/501 "$HOME/Library/LaunchAgents/com.staffing.jobfeed.plist"
```

The second command also starts a run immediately. To check the service, use `launchctl print gui/501/com.staffing.jobfeed` and inspect its last exit code and run count. Separately pause or resume the **Hourly Mac staffing fallback** health check in Codex Automations (or ask Codex to do so by name). Pause both collectors to stop all data updates. Pausing does not delete the published file. A cloud run already in progress may finish; cancel it too if an immediate stop is required.

## Data protection

A complete, successful pull replaces only its own firm's rows. A failed search, missing pagination, challenged detail page or incomplete detail rejects that firm's entire attempt and carries its previous successful rows forward. An older pull cannot replace a newer successful pull, even if it finishes later.

The publisher reads the latest shared state, merges each firm's snapshots, validates the entire CSV, and creates a Git commit containing the CSV, status and state together. It advances the published branch without force. If another runner publishes first, it rereads that runner's state and retries the merge. Readers never see a partially written CSV. Firm IDs, titles, dates, pay and contacts come from the source, not estimates generated by an AI model.

External maintenance and human security checks are recorded as failures. The collectors do not solve CAPTCHAs or substitute search snippets for unread detail pages. Such firms are retried hourly from cloud and Mac, with old rows retained where available. The status file distinguishes a firm with no successful snapshot from a completed search with zero matching roles.

## Implementation and validation

`collectors.py` contains firm-specific discovery and detail parsing. `core.py` implements the CSV contract, filtering and timestamped snapshot merge. `pipeline.py` handles cloud/Mac selection and atomic publication. `run_mac.py` provides a local overlap lock and unattended code update before collection.

The regression suite covers exact CSV round trips, duplicates and allowed values, failure carry-forward, successful empty snapshots, stale writers, hidden closed-page templates, malformed source metadata, partial detail failures, and a simulated cloud/Mac publication collision that must preserve both firms.

```sh
python -m pip install -r requirements-dev.txt
PYTHONPATH=.:tests python -m pytest tests -q
```

Dependencies for cloud collection are in `requirements.txt`. The installed Mac environment also includes Playwright and its Chromium browser for firms that need normal browser rendering; those dependencies are listed in `requirements-mac.txt`.
