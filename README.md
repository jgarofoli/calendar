# Linear Calendar

A plain-text calendar: one Markdown file per year, one line per day, events
written beside the day they happen.

```
W42 2026-10-15 Thu 🦷 Dentist @ 10␣␣
                      - Dr. Lee, 450 Main St, Suite 200␣␣
                   🏋️ Gym @ 4␣␣
W42 2026-10-16 Fri␣␣
```

This repository holds:

- [`SPEC.md`](SPEC.md): the Calendar File Format, version 1.0.
- [`docs/index.html`](docs/index.html): the generator page, which makes an
  empty year to fill in. Live at <https://jgarofoli.github.io/calendar/>.
- [`calmd/`](calmd): tools for the format, described in [`TOOLS.md`](TOOLS.md):
  - `calfmt` lints and formats files, starts new years, and copies annual
    events such as birthdays into them;
  - a GitHub Action ([`action.yml`](action.yml)) that lints every push and
    fixes what is safe to fix;
  - `calsd`, a small self-hosted web editor that commits each edit to git.

A calendar lives in a repository of its own and uses a tagged release of
these tools. Python 3.8 or later, standard library only.

```
pip install --user git+https://github.com/jgarofoli/calendar@v1.4.0
calfmt --check
```

```
python3 -m unittest discover -s tests -t .
```

## The generator page

Pick a year (defaults to the current year), then view the rendered or raw
Markdown, copy it, or download it as `calendar-<year>.md`. Days are grouped
by month and ISO week (Monday start), one line per day. Weeks that span two
months appear under both.

The **Format** button picks the day format (remembered in the browser):

| Format   | Example              |
|----------|----------------------|
| Short    | `Thu 01`, under `### Week 1` headings |
| ISO date | `W01 2026-01-01 Thu`, weeks separated by a blank line (the default, and the one `SPEC.md` uses) |
| Natural  | `Thu, Jan 1`, under `### Week 1` headings |

Both can be set in the URL, which overrides the remembered choice:
`?year=2027&format=iso` (`format` is `short`, `iso`, or `natural`). The
Markdown ends with a link back to the page with the same parameters.

No build step, no dependencies. GitHub Pages serves `docs/` from `master`
(Settings → Pages → deploy from a branch, folder `/docs`).
