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

Open `docs/index.html`. Pick a year (defaults to the current year),
then view the rendered or raw markdown, copy it, or download it as `calendar-<year>.md`.

The **Format** button opens a dialog to pick the day format (default: ISO date; remembered in the browser):

| Format   | Example              |
|----------|----------------------|
| Short    | `Thu 01`             |
| ISO date | `W01 2026-01-01 Thu` (no `### Week` headings; weeks are separated by a blank line) |
| Natural  | `Thu, Jan 1`         |

Both settings can be set by URL: `?year=2027&format=iso` (`format` is `short`, `iso` or `natural`).
The URL overrides the remembered choice.

The markdown ends with a link back to the page at
`https://jgarofoli.github.io/calendar/` with the current year and format as parameters.

No build step, no dependencies.

## Hosting on GitHub Pages

Push the repo, then Settings → Pages → deploy from the branch, folder `/docs`. Only `docs/` is served, not the whole repo.
