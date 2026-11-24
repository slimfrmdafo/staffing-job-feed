# Job feed specification

Version 1, 2026-11-24. This describes how any tool, script or person can supply job listings to the job board. You need nothing else about the board to follow it.

## What you deliver

One CSV file, published at one fixed HTTPS address, replaced in place on every run.

- File name: `staffing_jobs.csv` for the staffing-firm feed. Any other feed uses its own name, for example `government_jobs.csv`, at its own address.
- Encoding: UTF-8. Comma separated. Standard CSV quoting: wrap a field in double quotes if it contains a comma, a quote or a line break, and double any quote inside it.
- First row: the header below, exactly, in this order.
- One row per open listing. No duplicate rows for the same `firm` + `job_id`.

## Columns, in order

| # | Column | Required | Meaning and allowed values |
|---|---|---|---|
| 1 | firm | yes | The company that posted the listing, spelled the same way on every run (for example `Robert Half`). |
| 2 | job_id | yes | The poster's own id for the listing. Stable across runs. |
| 3 | title | yes | Job title as posted. |
| 4 | client_company | no | The end employer, only if the posting names it. |
| 5 | city | no | City of the job. |
| 6 | state | no | Two-letter US state, for example `NC`. |
| 7 | work_arrangement | no | `remote`, `hybrid` or `onsite`. |
| 8 | job_type | no | `contract`, `contract-to-hire` or `permanent`. |
| 9 | contract_length | no | As posted, for example `6 months` or `12+ months`. |
| 10 | pay_min | no | Number only, no symbols. |
| 11 | pay_max | no | Number only, no symbols. |
| 12 | pay_unit | no | `hour` or `year`. |
| 13 | posted_date | no | `YYYY-MM-DD`. |
| 14 | url | yes | The listing's own page, starting with `https://`. This is the apply link shown to the job seeker. |
| 15 | recruiter_name | no | Named contact on the posting. |
| 16 | recruiter_email | no | |
| 17 | recruiter_phone | no | |
| 18 | required_experience | no | As posted, for example `7 years`. |
| 19 | required_certifications | no | As posted, for example `PMP`. |
| 20 | description | no | Full posting text. Plain text preferred. |

Header row to copy:

```
firm,job_id,title,client_company,city,state,work_arrangement,job_type,contract_length,pay_min,pay_max,pay_unit,posted_date,url,recruiter_name,recruiter_email,recruiter_phone,required_experience,required_certifications,description
```

Leave a field empty when the posting does not state it. Never infer or invent a value.

## Rules that protect the data

1. **Full snapshot.** Every run writes every listing that is open right now, not only new ones. A listing that is missing from the newest file is treated as closed.
2. **Carry forward on failure.** If you could not read one firm on a run, copy that firm's rows from your previous file into the new one. Do not drop them. Dropping them would wrongly close real jobs.
3. **Same address, replaced in place.** Never publish under a new name or a new link.
4. **Write the whole file or nothing.** Build the file completely, then replace the published one in a single step, so a half-written file is never visible.

## Where to publish

Any address that returns the raw CSV over HTTPS without a sign-in page. All of these work:

- A file in a GitHub repository (the normal link to the file, or its raw link). A private repository also works if a read-only token for it is supplied to the board's owner.
- A Google Drive file shared as "anyone with the link can view" (the share link or the file id).
- Any web host or storage bucket with a stable public or signed link.

Give the board's owner the address once. It is stored on the board's side and never needs to change.

## Optional status file

Next to the CSV you may publish `staffing_status.txt` (same folder, same rules) with: run time, listings per firm, number of contract listings, and any firm that failed and why. It is for people to read. The board does not depend on it.

## What the board does with the file

- Reads the address once an hour. You can update the file on any schedule; hourly or daily both work.
- Ignores a run if the file cannot be reached, if the header does not match, or if the file is less than half the size of the previous one. Nothing breaks and nothing is closed in those cases.
- Never closes a firm's listings on a run where that firm has no rows in the file.
- Filters listings to the job seeker's criteria, scores them, and merges duplicates that also appear from other sources.
- Shows each kept listing with its firm, pay, contract length, apply link and recruiter contact.
- Marks a listing closed after it has been missing from the file on two consecutive hourly reads. Closed listings are kept, not deleted.

## Adding another feed later

Use the same columns and rules with a different file name and address. `firm` is then simply the organisation that posted the listing.
