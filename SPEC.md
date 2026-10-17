# Calendar File Format

Version 1.0. Dedicated to the public domain under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).

A plain-text format for a yearly calendar. Each year is one file, with one
line per day and events written beside the day they happen. A companion file
lists events that repeat every year. The files read well in any monospace
text view and render as Markdown.

## 1. Example

Part of `2026.md`:

```
## October

> Theme: get the garden ready for winter␣␣
> The cabin trip budget is shared with Sam and Alex; settle up
> by the end of the month␣␣

W40 2026-10-01 Thu␣␣
W40 2026-10-02 Fri␣␣
W40 2026-10-03 Sat 🏋️ Gym at 10␣␣
W40 2026-10-04 Sun␣␣

W41 2026-10-05 Mon␣␣
W41 2026-10-06 Tue␣␣
W41 2026-10-07 Wed 🏢 Office day, 🏟️ all-hands at the conference
                      center downtown␣␣
W41 2026-10-08 Thu␣␣
W41 2026-10-09 Fri␣␣
W41 2026-10-10 Sat 🎂 Sam's Birthday␣␣
                   🎂 Jordan's Birthday␣␣
W41 2026-10-11 Sun␣␣

W42 2026-10-12 Mon␣␣
W42 2026-10-13 Tue␣␣
W42 2026-10-14 Wed ~~🎭 Comedy night @ 7~~␣␣
                   🤒 Caught a cold␣␣
W42 2026-10-15 Thu 🦷 Dentist @ 10␣␣
                      - Dr. Lee, 450 Main St, Suite 200␣␣
                      - Bring the new insurance card; the front
                        desk needs the group number and member
                        ID before the visit␣␣
                   🏋️ Gym @ 4␣␣
W42 2026-10-16 Fri␣␣
W42 2026-10-17 Sat␣␣
W42 2026-10-18 Sun␣␣

W43 2026-10-19 Mon␣␣
W43 2026-10-20 Tue␣␣
W43 2026-10-21 Wed␣␣
W43 2026-10-22 Thu␣␣
W43 2026-10-23 Fri␣␣
W43 2026-10-24 Sat 🎂 Alex's Birthday␣␣
                   🏖️ Cabin trip␣␣
W43 2026-10-25 Sun 🏖️␣␣

W44 2026-10-26 Mon 🏖️␣␣
                   📞 Call the plumber␣␣
W44 2026-10-27 Tue␣␣
W44 2026-10-28 Wed␣␣
W44 2026-10-29 Thu␣␣
W44 2026-10-30 Fri␣␣
W44 2026-10-31 Sat␣␣
```

In this document, `␣␣` marks two space characters at the end of a line.

## 2. Lines

Files are UTF-8 with `LF` line endings and end with a single `LF`. They
contain no tabs and never two blank lines in a row. Blank lines are empty.

An event, detail, or note is a **logical line**. It ends with two spaces (a
**hard break**). When it is too long for one line, it wraps: every line but
the last ends with no trailing space, and the next line continues it.

Headings, blank lines, and the footer have no trailing spaces.

## 3. Year file

A year file is named `<year>.md` and contains, in order:

1. The title `# <year>`.
2. Optionally, year notes (section 5).
3. Twelve month sections, January to December, each made of:
   - the heading `## <Month>`, with the month's English name;
   - optionally, month notes;
   - a day block (section 4) for every day of the month, in order.
4. The footer, `https://jgarofoli.github.io/calendar/?year=<year>&format=iso`.

A blank line follows the title, each heading, each notes block, and the last
day of each month.

Days are grouped by ISO 8601 week, with a blank line between one week and
the next. A week that spans two months is split at the month boundary.

```
# 2026

## January

W01 2026-01-01 Thu␣␣
W01 2026-01-02 Fri␣␣
W01 2026-01-03 Sat␣␣
W01 2026-01-04 Sun␣␣

W02 2026-01-05 Mon␣␣
⋮
W05 2026-01-31 Sat␣␣

## February

W05 2026-02-01 Sun␣␣

W06 2026-02-02 Mon␣␣
⋮
W53 2026-12-31 Thu␣␣

https://jgarofoli.github.io/calendar/?year=2026&format=iso
```

## 4. Days

### 4.1 Day line

```
W42 2026-10-15 Thu 🦷 Dentist @ 10␣␣
```

A day line starts with the week, date, and weekday:

| Part    | Form         | Example      |
|---------|--------------|--------------|
| week    | `W` + 2 digits, the ISO 8601 week | `W42` |
| date    | `YYYY-MM-DD` | `2026-10-15` |
| weekday | `Mon` `Tue` `Wed` `Thu` `Fri` `Sat` `Sun` | `Thu` |

These 18 characters are separated by single spaces. The ISO week can belong
to the neighbouring year: `W53 2027-01-01 Fri`.

A day with no events ends right after the weekday, with a hard break. A day
with events has its first event after one more space, at column 19.

### 4.2 Events

Further events go on their own lines, indented 19 spaces:

```
W41 2026-10-10 Sat 🎂 Sam's Birthday␣␣
                   🎂 Jordan's Birthday␣␣
```

### 4.3 Details

A **detail** adds information to the event above it. It is indented 22
spaces and starts with `- `:

```
W42 2026-10-15 Thu 🦷 Dentist @ 10␣␣
                      - Dr. Lee, 450 Main St, Suite 200␣␣
                   🏋️ Gym @ 4␣␣
```

Details do not nest.

### 4.4 Indentation

| Line                    | Column |
|-------------------------|--------|
| day line                | 0      |
| event                   | 19     |
| event, wrapped          | 22     |
| detail                  | 22     |
| detail, wrapped         | 24     |

## 5. Notes

Year and month notes hold text that belongs to no single day. They are
blockquotes, placed after the title or a month heading:

```
## October

> Theme: get the garden ready for winter␣␣
> The cabin trip budget is shared with Sam and Alex; settle up
> by the end of the month␣␣

W40 2026-10-01 Thu␣␣
```

Every line starts with `> `. Each note ends with a hard break and wraps onto
further `> ` lines.

## 6. Conventions

### 6.1 Emoji

An event usually starts with an emoji that says what kind of event it is:
🎂 birthday, 🏖️ time off, 🏋️ gym. Any emoji may be used.

### 6.2 Multi-day events

An event spanning several days is written on each day. The first day has the
emoji and a title; the following days have the emoji alone:

```
W43 2026-10-24 Sat 🏖️ Cabin trip␣␣
W43 2026-10-25 Sun 🏖️␣␣

W44 2026-10-26 Mon 🏖️␣␣
```

This run of days is a **range**. A range stays within one year: one that
continues into January is started again in the next year's file, with its
title on 1 January.

### 6.3 Cancelled events

A cancelled event is struck through, emoji included:

```
W42 2026-10-14 Wed ~~🎭 Comedy night @ 7~~␣␣
```

A cancelled first day still starts a range.

### 6.4 Tags

A **tag** is `#` followed by letters, digits, and hyphens, such as `#doctor`
or `#day-trip`. It starts the text or follows a space, and ends at a space or
the end of the text. Tags are compared without regard to case; lowercase
plurals (`#birthdays`, `#flights`) are the convention.

Tags usually go on a detail line of their own, which may hold several:

```
W43 2026-10-24 Sat 🎂 Alex's Birthday␣␣
                      - #birthdays␣␣
                   🏖️ Cabin trip␣␣
                      - #travel␣␣
W43 2026-10-25 Sun 🏖️␣␣
```

A tag on the first day of a range applies to the whole range, so the 25th
above is also `#travel`.

### 6.5 Markdown

Events and details may contain Markdown such as links or `**bold**`. They
should not start with `- `, `#`, `>`, or a number followed by `.`, so a tag
does not begin an event.

## 7. Width and wrapping

Lines are at most **64 columns** wide. A logical line that is longer is
wrapped greedily: each line takes as many words as fit, and the rest move to
a continuation line (section 4.4). A word that cannot fit on a line by itself
is not split. A continuation line never starts with the word `-`; the word
before it moves down with it.

Width is counted per character:

| Character                                                    | Columns |
|--------------------------------------------------------------|---------|
| East Asian Width `W` or `F`                                  | 2       |
| `U+FE0F` after a character of East Asian Width `N` or `A`    | 1       |
| other `U+FE0F`, `U+FE00`–`U+FE0E`, `U+E0100`–`U+E01EF`, `U+200D`, and combining marks (`Mn`, `Me`) | 0 |
| everything else                                              | 1       |

So every emoji is 2 columns wide, including those written with `U+FE0F`,
such as 🏖️.

## 8. Annual file

`annual.md` lists events that repeat every year. Each one is copied into
each year's file.

```
# Annual events

## Birthdays

01-24 🎂 Sam's {nth:1980} Birthday␣␣
02-29 🎂 Robin's Birthday␣␣
10-10 🎂 Jordan's Birthday␣␣
         - send a card a week ahead␣␣

## Anniversaries

06-20 💍 Wedding anniversary, {n:2015} years␣␣

## Holidays

01-01 🎆 New Year's Day␣␣
05-LMon 🇺🇸 Memorial Day␣␣
11-4Thu 🦃 Thanksgiving␣␣
           - dinner at Alex's this year␣␣
12-25-4Sun 🕯️ First Sunday of Advent␣␣
Easter 🐣 Easter␣␣
Easter-2 ✝️ Good Friday␣␣
```

### 8.1 Layout

The file starts with `# Annual events`. `##` headings group entries and are
optional. Each **entry** is a date, a space, and the event text. Details and
wrapping work as in a year file, indented 3 columns past the start of the
entry's text: column 9 after `MM-DD`, 11 after `MM-nDdd`. A wrapped detail
is indented 2 more.

### 8.2 Dates

| Date         | Means                                    | Example                              |
|--------------|------------------------------------------|--------------------------------------|
| `MM-DD`      | that day                                 | `07-04` Independence Day             |
| `MM-nDdd`    | *n*th weekday of the month, *n* = 1–4    | `11-4Thu` Thanksgiving               |
| `MM-LDdd`    | last weekday of the month                | `05-LMon` Memorial Day               |
| `MM-DD-nDdd` | *n*th weekday before the date, *n* = 1–9 | `12-25-4Sun` First Sunday of Advent  |
| `MM-DD+nDdd` | *n*th weekday after the date, *n* = 1–9  | `11-01+1Tue` US Election Day         |
| `Easter`     | Easter Sunday (Western)                  | `Easter`                             |
| `Easter±N`   | *N* days after or before Easter          | `Easter-2` Good Friday               |

`Ddd` is `Mon`, `Tue`, `Wed`, `Thu`, `Fri`, `Sat`, or `Sun`. "Before" and
"after" do not include the date itself.

An entry dated `02-29` falls on 28 February in other years, with ` (02-29)`
added to its text.

### 8.3 Counting years

A counter shows the years since a starting year:

| Counter      | Becomes             | In 2027, with 1980 |
|--------------|---------------------|--------------------|
| `{nth:YYYY}` | an ordinal          | `47th`             |
| `{n:YYYY}`   | a number            | `47`               |

An entry with a counter starts in the year after `YYYY`.

Details, including tag lines, are copied with the event:

```
10-10 🎂 Jordan's Birthday␣␣
         - #birthdays␣␣
```

### 8.4 Result

For 2027, the example above gives:

| Date       | Event                             |
|------------|-----------------------------------|
| 2027-01-01 | 🎆 New Year's Day                 |
| 2027-01-24 | 🎂 Sam's 47th Birthday            |
| 2027-02-28 | 🎂 Robin's Birthday (02-29)       |
| 2027-03-26 | ✝️ Good Friday                    |
| 2027-03-28 | 🐣 Easter                         |
| 2027-05-31 | 🇺🇸 Memorial Day                  |
| 2027-06-20 | 💍 Wedding anniversary, 12 years  |
| 2027-10-10 | 🎂 Jordan's Birthday              |
| 2027-11-25 | 🦃 Thanksgiving                   |
| 2027-11-28 | 🕯️ First Sunday of Advent         |
