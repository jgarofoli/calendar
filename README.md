# Linear Calendar

A single static web page that generates a linear calendar for a chosen year as markdown.
Days are grouped by month and ISO week (Monday start), one line per day.

```
# 2026

## January

### Week 1
Thu 01
Fri 02
...
```

Weeks that span two months appear under both months.

## Use

Open `docs/index.html`. Pick a year (defaults to the current year; also settable via `?year=2027`),
then view the rendered or raw markdown, copy it, or download it as `calendar-<year>.md`.

The **Format** button opens a dialog to pick the day format (remembered in the browser):

| Format   | Example              |
|----------|----------------------|
| Short    | `Thu 01`             |
| ISO date | `W01 2026-01-01 Thu` |
| Natural  | `Thu, Jan 1`         |

No build step, no dependencies.

## Hosting on GitHub Pages

Push the repo, then Settings → Pages → deploy from the branch, folder `/docs`. Only `docs/` is served, not the whole repo.
