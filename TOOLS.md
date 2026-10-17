# Calendar tools

Tools for calendar files in the [Calendar File Format](SPEC.md): a parser,
formatter, and linter (`calfmt`), a GitHub Action that lints on push, and a
small self-hosted web editor (`calsd`). They are one Python package, `calmd`,
for Python 3.8 or later with no dependencies outside the standard library.

The calendar itself lives in a separate repository of its own, the **data
repository**, which uses tagged releases of these tools (section 10, D1).
Section numbers below refer to this document unless they name `SPEC.md`.

## 1. Data repository

```
2026.md, 2027.md, …     year files
annual.md               annual events
README.md, …            anything else
.github/workflows/lint.yml
```

Only files named `<four digits>.md` and `annual.md` are data. The tools never
read or write any other file, including other Markdown files.

## 2. Using the tools

### 2.1 calfmt

```
pip install --user git+https://github.com/jgarofoli/calendar@v1.4.0
```

Run it from the data repository. With no file named, every data file is used.

```
calfmt --check                 # lint; exit 1 on errors
calfmt --diff 2026.md          # show what --write would change
calfmt --write 2026.md         # format in place
calfmt new 2028 --write        # a new year file with annual events
calfmt annual --apply 2027     # preview missing annual events (add --write)
calfmt annual --bootstrap      # build annual.md from 🎂 events (add --write)
```

From a checkout of this repository, `python3 -m calmd.calfmt` does the same
without installing.

### 2.2 Lint on push

```yaml
# .github/workflows/lint.yml in the data repository
name: Lint calendar files
on:
  push:
    branches: [main]
    paths: ["[0-9][0-9][0-9][0-9].md", "annual.md"]
  workflow_dispatch:
permissions:
  contents: write
  issues: write
concurrency:
  group: lint
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main
      - uses: jgarofoli/calendar@v1.4.0
```

What the Action does is in section 8.3.

### 2.3 calsd

`calsd` serves the editor and owns a git clone of the data repository. Every
save is a commit pushed to `main`.

```
git clone <data repository> /tmp/cal-data
python3 -m calmd.server --data /tmp/cal-data --no-push --port 8650
```

`--no-push` commits locally only, for trying it out. `--host` defaults to
`127.0.0.1`.

**Hosting.** `deploy/deploy.sh` installs `calsd` as a systemd *user* service,
so no root is needed to install, update, or restart it. It reads
`~/.config/calsd/env`:

```
CALSD_DATA_REPO=git@github.com:you/your-calendar.git
CALSD_DEPLOY_KEY=~/.ssh/calendar_deploy    # optional: write access to the data repo only
CALSD_HOST=100.64.0.1                      # the address to listen on
CALSD_PORT=8642
```

```
deploy/deploy.sh            # install or update to the newest v* tag
deploy/deploy.sh v1.4.0     # a specific tag
systemctl --user status calsd
journalctl --user -u calsd -f
```

It keeps two checkouts under `~/.local/share/calsd`: `app`, this repository
at a release tag, and `data`, the clone that `calsd` edits. Keeping them
apart means a pull of the data never changes the running code.

`calsd` has no login. Serve it on an address only you can reach, such as a
Tailscale address (decision D7).

## 3. Parsing

Parsing is lenient, so hand edits do not break the tools. Formatting is
strict (section 4).

1. Split the file into physical lines and classify each one: blank, heading
   (`#`), footer (a single URL line after December's last day), note (`> `,
   where `SPEC.md` section 5 allows one), day line (`SPEC.md` section 4.1),
   or indented. Anything else is unparseable (`L07`).
2. Join physical lines into logical lines. When a physical line does not end
   in a hard break, look at the **next** physical line. If it is any of
   these, the hard break is missing (`L01`, fixable):
   - blank, a heading, the footer, or the end of the file;
   - a day line;
   - indented fewer than 22 spaces (an event);
   - indented and starting with `- ` (a detail).

   Otherwise it is a soft wrap: the next line continues this one, joined
   with a single space.
3. An indented logical line that starts with `- ` is a detail; any other is
   an event. Exact indentation does not matter after this step.
4. A detail belongs to the nearest event above it in the same day.

In `annual.md`, the same rules apply with an entry's indents (`SPEC.md`
section 8.1) in place of 19, 22, and 24. An indented line that follows an
entry, is indented at least 9 spaces, and does not start with `- ` continues
it.

## 4. Formatting

The formatter writes a parsed file back out in canonical form: the layout in
`SPEC.md` sections 2–5, wrapped as in `SPEC.md` section 7, with every day's
first event on its day line. It guarantees:

- **G1 Idempotent:** formatting twice gives the same result as formatting
  once.
- **G2 Fixed point:** a file with no lint findings comes back byte-identical.
- **G3 Content-preserving:** for every day, the ordered list of
  `(kind, words)` pairs is unchanged, where `kind` is event or detail and
  `words` is the text split on whitespace. Only whitespace and line
  structure change.
- **G4 Skeleton-preserving:** the formatter never adds, removes, reorders, or
  renames a day or heading. The only skeleton line it may write is the
  canonical footer (`L11`). If the file has an unfixable error, the formatter
  changes nothing and exits non-zero.

A run of spaces inside a line is kept where no wrap falls. Collapsing it
would let the formatter change a line the linter accepts.

**The skeleton** is a year file with all events, details, and notes removed.
It must be byte-identical to the output of the generator page,
`docs/index.html` in this repository, published at
<https://jgarofoli.github.io/calendar/>, for that year with `format=iso`.
`callib` has a Python port of the generator, and a test checks the two agree
for 1990–2100.

## 5. Lint rules

| Code | Severity | Fixed by the formatter |
|------|----------|------------------------|
| L01–L04, L08, L11 | error or warning | yes |
| L05, L12 | warning | no |
| L06, L07, L09, L10 | error | no, and nothing else in the file is fixed |

- **L01** error: a logical line is missing its hard break: zero or one
  trailing space where section 3, step 2, says a hard break must be.
- **L02** error: wrong trailing whitespace: three or more spaces, a tab, or
  any trailing space on a soft-wrapped line, a heading, or a blank line.
- **L03** warning: indentation is not canonical, for example an event
  indented 18 or 20 spaces. It is also the catch-all for any other
  non-canonical layout, such as a first event not on its day line or a
  missing blank line after notes. If no other rule explains why the
  formatter would change a file, `L03` reports the first line that differs,
  so a file with no findings is always a fixed point (G2).
- **L04** warning: a physical line is wider than 64 columns and can be
  wrapped.
- **L05** warning: a soft wrap where the continuation's first word would
  have fit on the line above. This usually means a hard break or a `- ` was
  forgotten and two lines were joined. Reflowing would merge them for good,
  so the formatter leaves that line's physical lines exactly as they are and
  fixes the rest of the file. Fix it by hand: add the hard break or `- `, or
  join the lines if the wrap was meant.
- **L06** error: the skeleton does not match the generator (section 4). A day
  is missing, duplicated, or out of order; a weekday or week is wrong; or a
  heading or the blank-line structure differs.
- **L07** error: an unparseable line, a detail with no event above it, a `>`
  line outside a notes block, or text after December's last day other than
  the footer. The formatter never deletes something you wrote.
- **L08** error: a file-level problem: a byte-order mark, `CRLF` line endings,
  a missing or extra final newline, or two blank lines in a row.
- **L09** error: a tab character.
- **L10** error, `annual.md` only: an invalid date (section 6.1), two entries
  with the same date and text, or a malformed `{…}` counter.
- **L11** warning: the footer is missing or not canonical. The formatter
  rewrites it.
- **L12** warning: a tag looks like a variant of another tag in the same file
  that is used more often. The two differ only by hyphens or a plural `s` or
  `es`, or, when both are at least 6 characters, by one character added,
  dropped, or swapped with its neighbour. `#hikes` and `#bikes` differ by a
  changed character, so they are not variants. It is reported on each line
  that uses the rarer tag.

In `annual.md`, `L06` and `L11` do not apply.

## 6. Annual events

### 6.1 Dates

Beyond `SPEC.md` section 8.2:

- `MM` outside `01`–`12`, or an `MM-DD` that is not a date in a leap year
  (`02-30`), is `L10`. `02-29` is allowed.
- `MM-5Ddd` is unparseable (`L07`): a fifth weekday does not occur every
  year, so use `L`.
- Counting from `02-29` (`02-29+1Mon`) is `L10`, since that day is missing
  in most years.
- An entry whose date falls outside the target year (`Easter+300`,
  `12-25+2Sun`) is skipped for that year.
- Observed holidays (a Saturday holiday taken on Friday) are not computed.
- All counters in one entry must use the same year.

### 6.2 New year

`calfmt new 2028` writes the skeleton with every annual event on its date.

### 6.3 Applying to an existing year

`calfmt annual --apply 2027` adds each annual event to its date in that year
unless the day already has it. Every day of the year is covered, including
days that have passed, so the year file ends up a complete record (D4).

- **Already there** means an event on that day with the same text after
  collapsing whitespace. The text compared is the copy's: counters filled
  in, and ` (02-29)` added where it applies. A struck-through copy
  (`~~🎂 Sam's Birthday~~`) counts as there, so a cancelled annual event is
  not added back.
- **Order:** annual events go before the day's other events, in `annual.md`
  order.
- **Tags:** a copy that is already there but lacks some of its entry's tags
  gets them as one more tag-only detail. This is the only change applying
  makes to an existing event.
- **Idempotent:** applying twice changes nothing the second time.

Applying never deletes events and does not track edits. Removing an entry
from `annual.md` leaves its copies alone. If a year file says
`🎂 Sam's Birthday, dinner downtown` and you apply again, `🎂 Sam's Birthday`
is added beside it. The diff preview shows this before anything is written.

### 6.4 Bootstrap

`calfmt annual --bootstrap` builds a first `annual.md` from the 🎂 events in
every year file, one entry per month and day.

## 7. The editor

`calsd` is one Python process built on `http.server`. It serves one page,
`calmd/web/index.html` (vanilla JavaScript, no build step), and a JSON API.

### 7.1 Features

**View**

- Opens with today about one third of the way down the screen; "Today"
  scrolls back there.
- Month headings stay at the top while scrolling. Each week starts with its
  week number; tapping it folds the week. Months fold too.
- Details fold per event, or all at once.
- Filter by text or emoji, by date range or the next 30 days, and by tag.
  Empty days can be hidden. A filter that matches the first day of a range
  shows the whole range.
- A tag-only detail (`- #travel`) shows as labels on its event. The filter
  panel lists every tag with a count; tapping a tag or a label filters to
  it, and `?tag=travel` in the URL does the same, so a filter can be
  bookmarked. Several tags match any of them.
- Lint findings show as a badge and on the days they concern.

**Edit**

- Tap a day to edit its events and details as plain text. The server writes
  canonical form, and only that day's lines change in the file.
- Strike through or restore an event.
- Ranges: create one across dates, then extend, shorten, or delete it as a
  unit.
- Year and month notes, edited like a day.
- "Format file": preview the formatter's diff, then commit it.
- "Add to calendar" on an event downloads it as a one-event `.ics` file.
  The event is all-day; a range becomes one multi-day event, and details
  become its notes.
- Edit `annual.md`, apply it to a year, and start a new year.

### 7.2 API

| Method and path                 | Purpose                                    |
|---------------------------------|--------------------------------------------|
| `GET /api/years`                | List the year files                        |
| `GET /api/years/2026`           | Parsed year, findings, ranges, `base`      |
| `POST /api/years`               | Create a year file                         |
| `PUT /api/days/2026-10-15`      | Replace one day's events                   |
| `PUT /api/notes/2026[-10]`      | Replace year or month notes                |
| `POST /api/years/2026/format`   | Preview or commit a full format            |
| `POST /api/years/2026/annual`   | Preview or commit applying `annual.md`     |
| `POST /api/ranges`              | Create, resize, or delete a range          |
| `GET`, `PUT /api/annual`        | Read or replace `annual.md`                |
| `POST /api/annual/entries`      | Add one annual entry                       |
| `GET /api/ics/2026-10-15/0.ics` | One event as an `.ics` file                |

`base` is the git blob hash of the file the page loaded; writes send it back
(section 8.2). Filtering and folding happen in the browser, which holds the
whole year.

## 8. Sync and conflicts

`calsd`'s clone is a cache. The data repository's `main` on GitHub is the
shared truth, which `calsd`, other editors, and the Action all write to.

### 8.1 Reading

A background thread runs `git fetch` and `git merge --ff-only` every 15
seconds, so requests do not wait on the network. If the fast-forward fails,
the clone has diverged, which should not happen because `calsd` pushes every
commit at once. Then `calsd` stops writing and reports the error.

### 8.2 Writing

1. If the file's blob hash differs from the page's `base`, the file changed
   since the page loaded it. Compare the edited day in the `base` version
   and now. If it is unchanged, go on, keeping the other change. If it
   changed, refuse with `409 Conflict` and the current file (D2). Notes work
   the same way, with the notes block in place of the day.
2. Rewrite only the edited day. The rest of the file stays byte-identical,
   even if it has lint findings, so each commit shows only the edit.
3. Commit (`2026-10-15: edit via calsd`) and push (D3).
4. If the push is rejected because someone else pushed first, fetch, reset
   to `origin/main`, and start again from step 1, up to three times. The
   edit is applied again rather than rebased, because git reports changes to
   neighbouring days as a conflict.

The page shows an edit as soon as it is saved and sends saves in the
background, one at a time, each with the `base` the previous one returned.
"Saving…" shows while saves are pending. If a save fails, the page reloads
the file and reopens the editor with the unsaved edit.

Hand edits show up on the next read. `calsd` never fixes their lint findings
as a side effect of editing another day; the Action or "Format file" does.

### 8.3 Lint on push

GitHub cannot reject a push because of a check, and requiring pull requests
would stop phone git clients from pushing to `main`. So the Action fixes what
is safe and reports the rest (D6):

1. On a push to `main` that changes a data file, lint every data file.
2. If a file has fixable findings and no unfixable error, format it and push
   a follow-up commit such as `calfmt: fix 2 findings in 2026.md`. These
   fixes change only whitespace and line structure (G3). A push made with
   the Action's own token does not start another run.
3. If anything is left (`L05`, `L12`, or an unfixable error), the job fails,
   and the Action keeps one open issue, "Calendar lint findings", listing
   each `file:line`. It closes the issue once the files are clean.
4. If someone pushes while the Action runs, its push is rejected; it fetches
   and starts again on the new head, up to three times.

Pull after pushing to pick up a fix commit.

## 9. Testing

```
python3 -m unittest discover -s tests -t .
```

- Formatting: G1–G4 on two fixture years written by hand before the tools
  existed, and on cases built for each `L01` repair, long words, emoji with
  and without `U+FE0F`, and continuations that would start with `-`.
- Skeleton: the Python port matches `docs/index.html` for 1990–2100, run
  with Node (skipped without it), including 53-week years.
- Annual events: idempotent applying, struck-through copies, `02-29`,
  counters (1st, 2nd, 3rd, 11th, 12th, 13th, 21st, 111th), weekday rules,
  Easter, and tags.
- Sync: `calsd` against a temporary bare repository, with a simulated push
  from another device.

## 10. Decisions

- **D1 Where the code lives.** Here, in one public repository with the spec
  and the generator page. A calendar lives in its own data repository, which
  uses a tagged release: the Action by tag, `calsd` by `deploy.sh`, `calfmt`
  by `pip`. There is one copy of the code.
- **D2 Conflicts are per day.** A save on an out-of-date `base` goes through
  if its day has not changed since, and is refused if it has. Nothing is
  merged within a day.
- **D3 One commit per saved day**, with no batching.
- **D4 Annual events fill past days too.**
- **D5 Calendar apps:** one event at a time as `.ics`; no subscribed feed.
- **D6 The Action fixes on `main`** with a follow-up commit, rather than
  blocking pushes.
- **D7 No HTTPS or login.** `calsd` listens on a private address, such as
  Tailscale's, which already encrypts the traffic.
- **Q1 Width:** 64 columns, so lines read well on a phone.
- **Q2 Detail marker:** `- `, easy to type on a phone.
- **Q3 Notes:** for the year and each month; not for weeks.
- **Q4 The footer** belongs to the tools (`L11`).
- **Q5 29 February** falls on 28 February in other years, marked
  ` (02-29)`.
- **Q6 Counters** (`{nth:YYYY}`, `{n:YYYY}`) for ages and anniversaries.
- **Q7 Weekday rules** are written in the date (`11-4Thu`, `12-25-4Sun`,
  `Easter-2`), so a line reads as its rule at a glance. Considered and
  dropped: the earliest date plus a weekday (`11-22+Thu`), and a marker in
  the text (`{on:Thu}`); both read as the wrong date.
