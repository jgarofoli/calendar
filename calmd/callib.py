"""Parse, format, and lint calendar files (SPEC.md; TOOLS.md sections 3-6).

Everything that knows the file format lives here. No third-party imports.

Section numbers in comments refer to SPEC.md unless they name TOOLS.md.
"""

import calendar
import datetime
import difflib
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

WIDTH = 64
SITE = "https://jgarofoli.github.io/calendar/"
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

DAY_RE = re.compile(
    r"^W(\d\d) (\d{4})-(\d\d)-(\d\d) (Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?= |$)")
# An annual.md date (8.2): MM-DD, MM-nDdd (n = 1-4 or L for last),
# MM-DD-nDdd / MM-DD+nDdd (nth weekday before / after a date), or Easter
# with an optional day offset.
_DDD = "(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
ENTRY_RE = re.compile(r"^(\d\d-\d\d[+-][1-9]" + _DDD + r"|\d\d-(?:\d\d|[1-4L]" + _DDD + r")"
                      r"|Easter(?:[+-]\d{1,3})?)(?= |$)")
URL_RE = re.compile(r"^https?://\S+$")
YEAR_FILE_RE = re.compile(r"^\d{4}\.md$")
COUNTER_RE = re.compile(r"\{([^{}]*)\}")
COUNTER_OK_RE = re.compile(r"^(nth|n):(\d{4})$")

PREFIX = 18          # len("W42 2026-10-15 Thu")
EVENT = 19           # first-line indent of an event (section 4.2)
EVENT_CONT = 22      # event continuation, detail first line (4.3, 4.4)
DETAIL_CONT = 24     # detail continuation
A_EVENT = 6          # annual.md: entry text column (8.1)
A_CONT = 9                     # the least continuation indent; see Entry.indents

SEVERITY = {
    "L01": "error", "L02": "error", "L03": "warning", "L04": "warning",
    "L05": "warning", "L06": "error", "L07": "error", "L08": "error",
    "L09": "error", "L10": "error", "L11": "warning", "L12": "warning",
}
SAFE = {"L01", "L02", "L03", "L04", "L08", "L11"}
UNFIXABLE = {"L06", "L07", "L09", "L10"}


def is_data_file(name: str) -> bool:
    return bool(YEAR_FILE_RE.match(name)) or name == "annual.md"


def blob_hash(data: bytes) -> str:
    """The git blob hash of `data`, as `git hash-object` prints it."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# ---------------------------------------------------------------- width (7)

def width(s: str) -> int:
    w = 0
    prev = None
    for ch in s:
        o = ord(ch)
        if o == 0xFE0F:
            if prev is not None and unicodedata.east_asian_width(prev) in "NA":
                w += 1
        elif (o == 0x200D or 0xFE00 <= o <= 0xFE0E or 0xE0100 <= o <= 0xE01EF
              or unicodedata.category(ch) in ("Mn", "Me")):
            pass
        elif unicodedata.east_asian_width(ch) in "WF":
            w += 2
        else:
            w += 1
        prev = ch
    return w


def wrap(text: str, first: str, cont: str, limit: int = WIDTH) -> List[str]:
    """Greedy wrap (section 7). Returns physical lines without hard breaks.

    Runs of spaces inside the text are kept where no break falls, so a
    line that fits comes back unchanged.
    """
    words = re.findall(r"( *)([^ ]+)", text)
    lines = []
    prefix, cur = first, []

    def render(prefix, cur):
        return prefix + "".join((sp if k else "") + w for k, (sp, w) in enumerate(cur))

    for sp, w in words:
        if cur and width(render(prefix, cur + [(sp, w)])) > limit:
            if w == "-":
                if len(cur) == 1:
                    # Nothing can move down with it; overflow rather than
                    # start a continuation with "-" (rule 5).
                    cur.append((sp, w))
                    continue
                carry = [cur.pop()]
            else:
                carry = []
            lines.append(render(prefix, cur))
            prefix, cur = cont, carry
        cur.append((sp, w))
    lines.append(render(prefix, cur))
    return [l.rstrip(" ") for l in lines]


def hard(lines: List[str]) -> List[str]:
    return lines[:-1] + [lines[-1] + "  "]


# ---------------------------------------------------------------- model

@dataclass
class Finding:
    code: str
    line: int          # 1-based, in the file as read
    message: str

    @property
    def severity(self):
        return SEVERITY[self.code]

    def to_dict(self):
        return {"code": self.code, "line": self.line, "message": self.message,
                "severity": self.severity, "fixable": self.code in SAFE}

    def __str__(self):
        return "%d: %s %s: %s" % (self.line, self.code, self.severity, self.message)


@dataclass
class Src:
    """Where a logical line came from: its physical lines in the file."""
    start: int                 # 0-based index into the normalised lines
    raw: List[str]
    keep: bool = False         # L05: formatter keeps these lines as they are


@dataclass
class Detail:
    text: str
    src: Optional[Src] = None


@dataclass
class Event:
    text: str
    details: List[Detail] = field(default_factory=list)
    src: Optional[Src] = None

    def to_dict(self):
        return {"text": self.text, "details": [d.text for d in self.details]}

    @staticmethod
    def from_dict(d):
        return Event(clean_text(d.get("text", "")),
                     [Detail(clean_text(t)) for t in d.get("details", []) if clean_text(t)])


@dataclass
class Note:
    text: str
    src: Optional[Src] = None


@dataclass
class Day:
    date: datetime.date
    events: List[Event] = field(default_factory=list)
    start: int = -1            # original 0-based line range of the day block
    end: int = -1              # inclusive

    @property
    def week(self):
        return self.date.isocalendar()[1]

    @property
    def weekday(self):
        return WEEKDAYS[self.date.weekday()]

    @property
    def prefix(self):
        return day_prefix(self.date)


@dataclass
class YearFile:
    year: int
    days: Dict[datetime.date, Day]
    notes: List[Note] = field(default_factory=list)
    month_notes: Dict[int, List[Note]] = field(default_factory=dict)
    # Original 0-based line ranges of notes blocks: key 0 = year, 1..12 = month.
    # (start, end) of the block, or (insert_at, None) where an empty block goes.
    note_spans: Dict[int, Tuple[int, Optional[int]]] = field(default_factory=dict)
    findings: List[Finding] = field(default_factory=list)
    lines: List[str] = field(default_factory=list)   # original physical lines

    @property
    def ok(self):
        """True when the parse can be trusted for formatting (G4)."""
        return not any(f.code in UNFIXABLE for f in self.findings)

    def day(self, date):
        return self.days.get(date)


def clean_text(s: str) -> str:
    """Text typed in the editor: one logical line, no stray whitespace."""
    return " ".join(str(s).replace("\t", " ").split())


def day_prefix(d: datetime.date) -> str:
    return "W%02d %04d-%02d-%02d %s" % (d.isocalendar()[1], d.year, d.month,
                                         d.day, WEEKDAYS[d.weekday()])


def footer(year: int) -> str:
    return "%s?year=%d&format=iso" % (SITE, year)


def year_dates(year: int):
    d = datetime.date(year, 1, 1)
    while d.year == year:
        yield d
        d += datetime.timedelta(days=1)


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suffix)


# ---------------------------------------------------------------- formatting

def format_note(note: Note) -> List[str]:
    if note.src and note.src.keep:
        return _kept(note.src.raw)
    return hard(wrap(note.text, "> ", "> "))


def format_event(ev: Event, first_line: str, cont: str, dfirst: str,
                 dcont: str, on_day_line: bool) -> List[str]:
    if ev.src and ev.src.keep and _starts_ok(ev.src.raw[0], on_day_line):
        out = _kept(ev.src.raw)
    else:
        out = hard(wrap(ev.text, first_line, cont))
    for d in ev.details:
        if d.src and d.src.keep:
            out += _kept(d.src.raw)
        elif d.text:
            out += hard(wrap(d.text, dfirst + "- ", dcont))
        else:
            out += [dfirst + "-  "]
    return out


def _starts_ok(raw0, on_day_line):
    return bool(DAY_RE.match(raw0)) == on_day_line


def _kept(raw: List[str]) -> List[str]:
    """An L05 logical line: physical lines as written, whitespace fixed."""
    return hard([l.rstrip(" \t") for l in raw])


def format_day(day: Day) -> List[str]:
    if not day.events:
        return [day.prefix + "  "]
    out = []
    for i, ev in enumerate(day.events):
        first = day.prefix + " " if i == 0 else " " * EVENT
        out += format_event(ev, first, " " * EVENT_CONT, " " * EVENT_CONT,
                            " " * DETAIL_CONT, i == 0)
    return out


def skeleton(year: int):
    """The generator's structure (docs/index.html, format=iso; TOOLS.md 4)."""
    out = [("h1", str(year))]
    for m in range(1, 13):
        out.append(("h2", MONTHS[m - 1]))
        week = None
        for d in year_dates(year):
            if d.month != m:
                continue
            w = d.isocalendar()[1]
            if week is not None and w != week:
                out.append(("gap", None))
            week = w
            out.append(("day", d))
    return out


def render_year(model: YearFile) -> str:
    lines = ["# %d" % model.year, ""]
    if model.notes:
        for n in model.notes:
            lines += format_note(n)
        lines.append("")
    first = True
    for kind, val in skeleton(model.year):
        if kind == "h1":
            continue
        if kind == "h2":
            if not first:
                lines.append("")
            first = False
            lines += ["## " + val, ""]
            notes = model.month_notes.get(MONTHS.index(val) + 1)
            if notes:
                for n in notes:
                    lines += format_note(n)
                lines.append("")
        elif kind == "gap":
            lines.append("")
        else:
            lines += format_day(model.days.get(val) or Day(val))
    lines += ["", footer(model.year)]
    return "\n".join(lines) + "\n"


def skeleton_text(year: int) -> str:
    return render_year(YearFile(year, {}))


# ---------------------------------------------------------------- parsing

class _Reader:
    """Splits a file into physical lines and joins logical lines (TOOLS.md 3)."""

    def __init__(self, text: str, annual: bool):
        self.annual = annual
        self.findings: List[Finding] = []
        self.orig = text.split("\n")      # for surgical rewrites
        f = self.findings
        if text.startswith("﻿"):
            f.append(Finding("L08", 1, "byte-order mark"))
            text = text[1:]
        if "\r\n" in text:
            f.append(Finding("L08", text[:text.index("\r\n")].count("\n") + 1,
                             "CRLF line endings"))
            text = text.replace("\r\n", "\n")
        raw = text.split("\n")
        if raw and raw[-1] == "":
            raw.pop()
        elif text:
            f.append(Finding("L08", len(raw), "missing final newline"))
        while raw and raw[-1].strip(" \t") == "":
            f.append(Finding("L08", len(raw), "extra blank line at end of file"))
            raw.pop()
        self.lines: List[str] = []
        self.lno: List[int] = []          # 0-based original line index
        for i, s in enumerate(raw):
            if "\t" in s:
                f.append(Finding("L09", i + 1, "tab character"))
            if s.strip(" \t") == "":
                if s:
                    f.append(Finding("L02", i + 1, "whitespace on a blank line"))
                if self.lines and self.lines[-1] == "":
                    f.append(Finding("L08", i + 1, "consecutive blank lines"))
                    continue
                s = ""
            self.lines.append(s)
            self.lno.append(i)
        self.cls = [self._classify(s) for s in self.lines]

    def _classify(self, s):
        if s == "":
            return "blank"
        if s.startswith("#"):
            return "heading"
        if self.annual:
            if ENTRY_RE.match(s):
                return "entry"
        else:
            if DAY_RE.match(s):
                return "day"
            if s.startswith(">"):
                return "note"
            if URL_RE.match(s.rstrip(" ")):
                return "url"
        if s.startswith(" "):
            return "indented"
        return "bad"

    def find(self, code, i, msg):
        self.findings.append(Finding(code, self.lno[i] + 1, msg))

    def _continues(self, kind, j):
        """TOOLS.md 3, step 2: does physical line j soft-continue a line?"""
        if j >= len(self.lines):
            return False
        if kind == "note":
            return self.cls[j] == "note"
        if self.cls[j] != "indented":
            return False
        s = self.lines[j]
        ind = len(s) - len(s.lstrip(" "))
        return ind >= (A_CONT if self.annual else EVENT_CONT) and not _is_detail(s.strip())

    def logical(self, i):
        """Join the logical line starting at i. Returns (raw lines, next i)."""
        kind = self.cls[i]
        raw = []
        while True:
            s = self.lines[i]
            raw.append(s)
            body = s.rstrip(" \t")
            trail = s[len(body):]
            if len(trail) >= 2:
                if trail != "  ":
                    self.find("L02", i, "trailing whitespace is not exactly two spaces")
                return raw, i + 1
            if self._continues(kind, i + 1):
                if trail:
                    self.find("L02", i, "trailing space on a soft-wrapped line")
                i += 1
                continue
            self.find("L01", i, "missing hard break (two trailing spaces)")
            return raw, i + 1


def _is_detail(t: str) -> bool:
    return t == "-" or t.startswith("- ")


def _join(raw: List[str], first_cut: int, note=False) -> str:
    parts = []
    for k, s in enumerate(raw):
        if note:
            s = s[1:]
        elif k == 0:
            s = s[first_cut:]
        parts.append(s.strip(" \t"))
    return " ".join(p for p in parts if p)


def _check_l05(r: _Reader, i0: int, raw: List[str], canonical: List[str],
               note=False) -> bool:
    """Flags a soft wrap whose next word would have fit (L05)."""
    if _kept(raw) == canonical or len(raw) < 2:
        return False
    for k in range(1, len(raw)):
        nxt = raw[k][1:] if note else raw[k]
        words = nxt.split()
        if not words:
            continue
        prev = raw[k - 1].rstrip(" \t")
        if width(prev) + 1 + width(words[0]) <= WIDTH:
            r.find("L05", i0 + k, "soft wrap where %r would fit on the line above;"
                   " a hard break or '- ' may be missing" % words[0])
            return True
    return False


def _diagnose(r: _Reader, i0: int, raw: List[str], canonical: List[str],
              indents: List[int]):
    """Explains why a logical line is not canonical (L03/L04)."""
    if _kept(raw) == canonical:
        return
    for k, s in enumerate(raw):
        if width(s.rstrip(" \t")) > WIDTH:
            r.find("L04", i0 + k, "line is %d columns, over the %d-column limit"
                   % (width(s.rstrip(" \t")), WIDTH))
            return
    for k, s in enumerate(raw):
        want = indents[0] if k == 0 else indents[1]
        if want is not None and len(s) - len(s.lstrip(" ")) != want:
            r.find("L03", i0 + k, "indentation is %d, expected %d"
                   % (len(s) - len(s.lstrip(" ")), want))
            return
    r.find("L03", i0, "line is not in canonical form")


def parse_year(text: str, year_hint: Optional[int] = None) -> YearFile:
    r = _Reader(text, annual=False)
    L, C = r.lines, r.cls
    year = year_hint
    if L and re.match(r"^# (\d{4})$", L[0].rstrip(" ")):
        year = int(L[0][2:6])
    if year is None:
        year = datetime.date.today().year
        if L:
            r.find("L06", 0, "no '# <year>' title")
    model = YearFile(year, {}, lines=r.orig)

    stripped = []          # skeleton view: (text, line index)
    i = 0
    day = None             # current Day, while inside a day block
    last_heading = None    # 0 for the title, 1..12 for months
    notes_ok = False       # just after "heading, blank"
    after_notes = False
    last_day_end = -1      # index after the last day block
    while i < len(L):
        c = C[i]
        s = L[i]
        if c != "indented":
            if day is not None:
                day.end = r.lno[i - 1]
            day = None
        if c == "blank":
            if after_notes:
                after_notes = False
                notes_ok = False
            else:
                stripped.append(("", i))
                notes_ok = _notes_ok(stripped)
            i += 1
            continue
        if after_notes:
            r.find("L03", i, "a blank line must follow a notes block")
            after_notes = False
        if c == "heading":
            t = s.rstrip(" \t")
            if t != s:
                r.find("L02", i, "trailing whitespace on a heading")
            stripped.append((t, i))
            if t.startswith("## ") and t[3:] in MONTHS:
                last_heading = MONTHS.index(t[3:]) + 1
            elif t.startswith("# "):
                last_heading = 0
            notes_ok = False
            i += 1
            continue
        if c == "note":
            if not notes_ok or last_heading is None:
                r.find("L07", i, "a '>' notes line is only allowed right after "
                       "the title or a month heading")
                i += 1
                continue
            start = i
            notes = []
            while i < len(L) and C[i] == "note":
                raw, j = r.logical(i)
                if not raw[0].startswith("> ") or any(
                        x[2:3] == " " or not x.startswith("> ") for x in raw):
                    r.find("L03", i, "note lines start with '> ' and one space")
                n = Note(_join(raw, 0, note=True), Src(i, raw))
                canon = hard(wrap(n.text, "> ", "> "))
                if _check_l05(r, i, raw, canon, note=True):
                    n.src.keep = True
                elif _kept(raw) != canon:
                    _diagnose(r, i, raw, canon, [None, None])
                notes.append(n)
                i = j
            if last_heading == 0:
                model.notes = notes
            else:
                model.month_notes[last_heading] = notes
            model.note_spans[last_heading] = (r.lno[start], r.lno[i - 1])
            notes_ok = False
            after_notes = True
            continue
        notes_ok = False
        if c == "day":
            m = DAY_RE.match(s)
            try:
                d = datetime.date(int(m.group(2)), int(m.group(3)), int(m.group(4)))
            except ValueError:
                r.find("L06", i, "not a valid date")
                d = None
            raw, j = r.logical(i)
            stripped.append((s[:PREFIX] + "  ", i))
            if d is not None and s[:PREFIX] != day_prefix(d):
                r.find("L06", i, "expected '%s'" % day_prefix(d))
            day = Day(d, start=r.lno[i]) if d else Day(datetime.date.min, start=r.lno[i])
            if d is not None:
                if d in model.days:
                    r.find("L06", i, "duplicate day %s" % d)
                elif d.year == year:
                    model.days[d] = day
            etext = _join(raw, PREFIX)
            if etext:
                rest = raw[0][PREFIX:]
                if not rest.startswith(" ") or rest.startswith("  "):
                    r.find("L03", i, "one space goes between the date and the first event")
                ev = Event(etext, src=Src(i, raw))
                _check_event(r, i, ev, raw, on_day_line=True, prefix=s[:PREFIX] + " ")
                day.events.append(ev)
            i = j
            last_day_end = i
            continue
        if c == "indented":
            raw, j = r.logical(i)
            etext = _join(raw, 0)
            if day is None:
                r.find("L07", i, "indented line outside a day block")
            elif _is_detail(etext):
                if not day.events:
                    r.find("L07", i, "a detail needs an event above it")
                else:
                    dt = Detail(etext[2:].strip(), Src(i, raw))
                    canon = (hard(wrap(dt.text, " " * EVENT_CONT + "- ", " " * DETAIL_CONT))
                             if dt.text else [" " * EVENT_CONT + "-  "])
                    if _check_l05(r, i, raw, canon):
                        dt.src.keep = True
                    else:
                        _diagnose(r, i, raw, canon, [EVENT_CONT, DETAIL_CONT])
                    day.events[-1].details.append(dt)
            else:
                ev = Event(etext, src=Src(i, raw))
                if not day.events:
                    r.find("L03", i, "a day's first event goes on the day line")
                    canon = hard(wrap(etext, day.prefix + " ", " " * EVENT_CONT))
                    if _check_l05(r, i, raw, canon):
                        ev.src.keep = True
                else:
                    _check_event(r, i, ev, raw, on_day_line=False, prefix=" " * EVENT)
                day.events.append(ev)
            if day is not None:
                day.end = r.lno[j - 1]
            i = j
            last_day_end = i
            continue
        if c == "url":
            # Footer candidates are handled after the loop.
            i += 1
            continue
        r.find("L07", i, "unparseable line")
        i += 1
    if day is not None:
        day.end = r.lno[len(L) - 1]

    _check_footer(r, model, last_day_end)
    stripped = [(t, k) for t, k in stripped if k < last_day_end]
    _check_skeleton(r, model, stripped)
    _note_insert_points(model, r)
    model.findings = r.findings
    if model.ok and not model.findings and render_year(model) != text:
        _first_diff(r, text, render_year(model))
        model.findings = r.findings
    _check_tags(r)
    model.findings.sort(key=lambda f: (f.line, f.code))
    return model


def _notes_ok(stripped):
    return (len(stripped) >= 2 and stripped[-1][0] == ""
            and stripped[-2][0].startswith("#"))


def _check_event(r, i, ev, raw, on_day_line, prefix):
    canon = hard(wrap(ev.text, prefix, " " * EVENT_CONT))
    if _check_l05(r, i, raw, canon):
        ev.src.keep = True
    else:
        _diagnose(r, i, raw, canon, [None if on_day_line else EVENT, EVENT_CONT])


def _check_footer(r: _Reader, model: YearFile, last_day_end: int):
    L, C = r.lines, r.cls
    tail = list(range(last_day_end, len(L)))
    urls = [k for k in tail if C[k] == "url"]
    # Other lines in the tail are already reported by the main loop.
    for k in tail:
        if C[k] == "heading":
            r.find("L07", k, "text after December's last day")
    for k in urls[1:]:
        r.find("L07", k, "more than one line after December's last day")
    want = footer(model.year)
    for k in range(0, last_day_end):
        if C[k] == "url":
            r.find("L07", k, "unparseable line")
    if not urls:
        r.find("L11", len(L) - 1 if L else 0, "footer is missing")
    elif L[urls[0]].rstrip(" ") != want or [L[k] for k in tail] != ["", want]:
        r.find("L11", urls[0], "footer should be exactly a blank line, then " + want)


def _check_skeleton(r: _Reader, model: YearFile, stripped):
    want = skeleton_text(model.year).split("\n")[:-3]   # drop blank, URL, ""
    got = [t for t, _ in stripped]
    if got == want:
        return
    for k in range(max(len(got), len(want))):
        g = got[k] if k < len(got) else None
        w = want[k] if k < len(want) else None
        if g != w:
            line = stripped[k][1] if k < len(stripped) else (stripped[-1][1] if stripped else 0)
            r.find("L06", line, "skeleton differs from the generator: expected %r, found %r"
                   % (w if w is not None else "end of file",
                      g if g is not None else "end of file"))
            return


def _note_insert_points(model: YearFile, r: _Reader):
    """Where an empty notes block would go: after the heading's blank line."""
    for k, s in enumerate(r.lines):
        if r.cls[k] != "heading" or k + 1 >= len(r.lines) or r.cls[k + 1] != "blank":
            continue
        t = s.rstrip()
        key = None
        if re.match(r"^# \d{4}$", t):
            key = 0
        elif t.startswith("## ") and t[3:] in MONTHS:
            key = MONTHS.index(t[3:]) + 1
        if key is not None and key not in model.note_spans:
            model.note_spans[key] = (r.lno[k + 1] + 1, None)


def _first_diff(r: _Reader, have: str, want: str):
    a, b = have.split("\n"), want.split("\n")
    for k in range(min(len(a), len(b))):
        if a[k] != b[k]:
            r.findings.append(Finding("L03", k + 1, "line is not in canonical form"))
            return
    r.findings.append(Finding("L03", min(len(a), len(b)), "file is not in canonical form"))


# ---------------------------------------------------------------- annual.md (8)

def easter(year: int) -> datetime.date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return datetime.date(year, month, day + 1)


def date_error(when: str) -> Optional[str]:
    """Why an annual.md date token is invalid (L10), or None."""
    if when.startswith("Easter"):
        return None
    mm = int(when[:2])
    if not 1 <= mm <= 12:
        return "%s: no month %s" % (when, when[:2])
    if len(when) in (5, 10):             # MM-DD, MM-DD±nDdd
        try:
            datetime.date(2000, mm, int(when[3:5]))
        except ValueError:
            return "%s is not a valid date" % when[:5]
        if len(when) == 10 and when[:5] == "02-29":
            return "%s: count from 02-28 or 03-01, not 02-29" % when
    return None


def resolve(when: str, year: int) -> Optional[Tuple[datetime.date, bool]]:
    """The date `when` falls on in `year`, and whether it is a moved 02-29."""
    if when.startswith("Easter"):
        return easter(year) + datetime.timedelta(days=int(when[6:] or 0)), False
    mm = int(when[:2])
    if len(when) == 10:                  # MM-DD-nDdd, MM-DD+nDdd
        base = datetime.date(year, mm, int(when[3:5]))
        wd, n = WEEKDAYS.index(when[7:]), int(when[6])
        if when[5] == "-":
            d = base - datetime.timedelta(days=(base.weekday() - wd - 1) % 7 + 1)
            return d - datetime.timedelta(weeks=n - 1), False
        d = base + datetime.timedelta(days=(wd - base.weekday() - 1) % 7 + 1)
        return d + datetime.timedelta(weeks=n - 1), False
    if len(when) == 5:                   # MM-DD
        dd = int(when[3:])
        if (mm, dd) == (2, 29) and not calendar.isleap(year):
            return datetime.date(year, 2, 28), True
        return datetime.date(year, mm, dd), False
    wd = WEEKDAYS.index(when[4:])
    if when[3] == "L":
        d = datetime.date(year, mm, calendar.monthrange(year, mm)[1])
        return d - datetime.timedelta(days=(d.weekday() - wd) % 7), False
    d = datetime.date(year, mm, 1)
    d += datetime.timedelta(days=(wd - d.weekday()) % 7 + 7 * (int(when[3]) - 1))
    return d, False


@dataclass
class Entry:
    when: str                   # the date token: 10-24, 11-4Thu, Easter-2
    text: str
    details: List[Detail] = field(default_factory=list)
    src: Optional[Src] = None
    line: int = 0               # 1-based

    @property
    def indents(self) -> Tuple[int, int]:
        """(entry continuation and detail, detail continuation) (8.1)."""
        t = len(self.when) + 1
        return t + 3, t + 5

    def to_dict(self):
        return {"date": self.when, "text": self.text,
                "details": [d.text for d in self.details], "line": self.line}


@dataclass
class AnnualFile:
    items: list                 # ("line", str) for headings/blanks, ("entry", Entry)
    findings: List[Finding] = field(default_factory=list)

    @property
    def ok(self):
        return not any(f.code in UNFIXABLE for f in self.findings)

    @property
    def entries(self) -> List[Entry]:
        return [v for k, v in self.items if k == "entry"]

    @property
    def groups(self) -> List[str]:
        return [v[3:].strip() for k, v in self.items if k == "line" and v.startswith("## ")]


def parse_annual(text: str) -> AnnualFile:
    r = _Reader(text, annual=True)
    L, C = r.lines, r.cls
    af = AnnualFile([])
    entry = None
    i = 0
    seen = {}
    while i < len(L):
        c = C[i]
        if c in ("blank", "heading"):
            t = L[i].rstrip(" \t")
            if t != L[i]:
                r.find("L02", i, "trailing whitespace on a heading")
            af.items.append(("line", t))
            entry = None
            i += 1
            continue
        if c == "entry":
            when = ENTRY_RE.match(L[i]).group(1)
            raw, j = r.logical(i)
            etext = _join(raw, len(when))
            err = date_error(when)
            if err:
                r.find("L10", i, err)
            if not etext:
                r.find("L07", i, "entry without event text")
            entry = Entry(when, etext, src=Src(i, raw), line=r.lno[i] + 1)
            cont, dcont = entry.indents
            rest = raw[0][len(when):]
            if etext and (not rest.startswith(" ") or rest.startswith("  ")):
                r.find("L03", i, "one space goes between the date and the event")
            canon = hard(wrap(etext, when + " ", " " * cont))
            if _check_l05(r, i, raw, canon):
                entry.src.keep = True
            else:
                _diagnose(r, i, raw, canon, [None, cont])
            key = (when, " ".join(etext.split()))
            if key in seen:
                r.find("L10", i, "same date and text as line %d" % seen[key])
            else:
                seen[key] = r.lno[i] + 1
            af.items.append(("entry", entry))
            i = j
            continue
        if c == "indented":
            raw, j = r.logical(i)
            etext = _join(raw, 0)
            if entry is None or not _is_detail(etext):
                r.find("L07", i, "indented line that is not a detail of an entry")
            else:
                dt = Detail(etext[2:].strip(), Src(i, raw))
                cont, dcont = entry.indents
                canon = (hard(wrap(dt.text, " " * cont + "- ", " " * dcont))
                         if dt.text else [" " * cont + "-  "])
                if _check_l05(r, i, raw, canon):
                    dt.src.keep = True
                else:
                    _diagnose(r, i, raw, canon, [cont, dcont])
                entry.details.append(dt)
            i = j
            continue
        r.find("L07", i, "unparseable line")
        i += 1
    for e in af.entries:
        years = set()
        for t in [e.text] + [d.text for d in e.details]:
            for g in COUNTER_RE.findall(t):
                m = COUNTER_OK_RE.match(g)
                if not m:
                    r.findings.append(Finding("L10", e.line, "malformed counter {%s}" % g))
                else:
                    years.add(m.group(2))
        if len(years) > 1:
            r.findings.append(Finding("L10", e.line, "counters use different years"))
    af.findings = r.findings
    if af.ok and not af.findings and render_annual(af) != text:
        _first_diff(r, text, render_annual(af))
    _check_tags(r)
    af.findings.sort(key=lambda f: (f.line, f.code))
    return af


def format_entry(e: Entry) -> List[str]:
    cont, dcont = e.indents
    if e.src and e.src.keep:
        out = _kept(e.src.raw)
    else:
        out = hard(wrap(e.text, e.when + " ", " " * cont))
    for d in e.details:
        if d.src and d.src.keep:
            out += _kept(d.src.raw)
        elif d.text:
            out += hard(wrap(d.text, " " * cont + "- ", " " * dcont))
        else:
            out += [" " * cont + "-  "]
    return out


def render_annual(af: AnnualFile) -> str:
    out = []
    for kind, v in af.items:
        out += [v] if kind == "line" else format_entry(v)
    return "\n".join(out) + "\n"


def entry_year(e: Entry) -> Optional[int]:
    for t in [e.text] + [d.text for d in e.details]:
        for g in COUNTER_RE.findall(t):
            m = COUNTER_OK_RE.match(g)
            if m:
                return int(m.group(2))
    return None


def expand(text: str, year: int) -> str:
    def sub(m):
        c = COUNTER_OK_RE.match(m.group(1))
        if not c:
            return m.group(0)
        n = year - int(c.group(2))
        return ordinal(n) if c.group(1) == "nth" else str(n)
    return COUNTER_RE.sub(sub, text)


def annual_events(af: AnnualFile, year: int) -> List[Tuple[datetime.date, Event]]:
    """The events annual.md puts in `year`, in file order (12.2, 12.3)."""
    out = []
    for e in af.entries:
        sy = entry_year(e)
        if sy is not None and year <= sy or date_error(e.when):
            continue
        date, moved = resolve(e.when, year)
        if date.year != year:           # counted across New Year
            continue
        text = expand(e.text, year) + (" (02-29)" if moved else "")
        out.append((date, Event(text, [Detail(expand(x.text, year)) for x in e.details])))
    return out


def norm(text: str) -> str:
    t = " ".join(text.split())
    if t.startswith("~~") and t.endswith("~~") and len(t) >= 4:
        t = " ".join(t[2:-2].split())
    return t


def apply_annual(model: YearFile, af: AnnualFile,
                 tagged: Optional[list] = None) -> List[Tuple[datetime.date, str]]:
    """Adds missing annual events to `model` in place (TOOLS.md 6.3).

    Returns the (date, text) pairs that were added. A copy that is already
    there but lacks some of its entry's tags gets them as one more tag-only
    detail; those (date, text) pairs are appended to `tagged`.
    """
    added = []
    pos: Dict[datetime.date, int] = {}
    for date, ev in annual_events(af, model.year):
        day = model.days.get(date)
        if day is None:
            continue
        p = pos.get(date, 0)
        texts = [norm(e.text) for e in day.events]
        if norm(ev.text) in texts:
            k = texts.index(norm(ev.text))
            pos[date] = max(p, k + 1)
            copy = day.events[k]
            have = set(event_tags(copy))
            missing = [t for t in event_tags(ev) if t not in have]
            if missing:
                copy.details.append(Detail(" ".join("#" + t for t in missing)))
                if tagged is not None:
                    tagged.append((date, copy.text))
            continue
        day.events.insert(p, ev)
        pos[date] = p + 1
        added.append((date, ev.text))
    return added


# ---------------------------------------------------------------- tags (6.4)

TAG_RE = re.compile(r"(?:^|(?<=\s))#([A-Za-z0-9][A-Za-z0-9-]*)(?=\s|$)")


def tags(text: str) -> List[str]:
    """The tags in a piece of text, lowercased, in order: `#doctor` -> doctor."""
    return [t.lower() for t in TAG_RE.findall(text)]


def is_tag_line(text: str) -> bool:
    """A detail made only of tags, such as `#birthdays #family`."""
    return bool(text.strip()) and not TAG_RE.sub("", text).strip()


def event_tags(ev: "Event") -> List[str]:
    out = []
    for t in tags(ev.text) + [x for d in ev.details for x in tags(d.text)]:
        if t not in out:
            out.append(t)
    return out


def similar_tags(a: str, b: str) -> bool:
    """Near-duplicates (L12): the same but for hyphens or a plural `s`/`es`,
    or, at 6 letters or more, one letter added, dropped, or swapped with
    its neighbour (`#birthdys`, `#brithdays`). A changed letter is not
    enough: `#hikes` and `#bikes` are different tags."""
    a, b = a.replace("-", ""), b.replace("-", "")
    if a == b:
        return True
    a, b = sorted((a, b), key=len)
    if b in (a + "s", a + "es"):
        return True
    if len(a) < 6 or len(b) - len(a) > 1:
        return False
    if len(b) == len(a) + 1:
        return any(b[:k] + b[k + 1:] == a for k in range(len(b)))
    return any(a[:k] + a[k + 1] + a[k] + a[k + 2:] == b for k in range(len(a) - 1))


def _check_tags(r: "_Reader"):
    """L12: a tag that looks like a variant of a more-used one."""
    uses = {}                       # tag -> [line index, ...]
    for k, s in enumerate(r.lines):
        if r.cls[k] not in ("heading", "url", "blank"):
            for t in tags(s):
                uses.setdefault(t, []).append(k)
    for t in uses:
        main = max((u for u in uses if u != t and similar_tags(t, u)),
                   key=lambda u: (len(uses[u]), u), default=None)
        if main and (len(uses[main]), main) > (len(uses[t]), t):
            n = len(uses[main])
            for k in uses[t]:
                r.find("L12", k, "#%s looks like a variant of #%s (used %d time%s)"
                       % (t, main, n, "" if n == 1 else "s"))


def new_year(year: int, af: Optional[AnnualFile]) -> Tuple[str, int]:
    model = YearFile(year, {d: Day(d) for d in year_dates(year)})
    n = len(apply_annual(model, af)) if af else 0
    return render_year(model), n


def bootstrap_annual(models: List[YearFile], emoji: str = "🎂") -> str:
    """TOOLS.md 6.4: the union of all `emoji` events across `models`, by month and day."""
    found = {}
    for model in models:
        for d in sorted(model.days):
            for ev in model.days[d].events:
                t = norm(ev.text)
                if t.startswith(emoji) and not ev.text.strip().startswith("~~"):
                    found.setdefault((d.month, d.day, t), (d.month, d.day, t))
    lines = ["# Annual events", "", "## Birthdays", ""]
    for m, d, t in sorted(found.values(), key=lambda x: (x[0], x[1])):
        lines += hard(wrap(t, "%02d-%02d " % (m, d), " " * A_CONT))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- surgical edits

def rewrite_days(text: str, model: YearFile, dates) -> str:
    """Replaces only the blocks of `dates` with their formatted form.

    Every other byte of the file stays as it was (TOOLS.md 8.2).
    """
    lines = text.split("\n")
    blocks = sorted((model.days[d] for d in set(dates)), key=lambda d: d.start, reverse=True)
    for day in blocks:
        if day.start < 0:
            raise ValueError("day %s is not in the file" % day.date)
        lines[day.start:day.end + 1] = format_day(day)
    return "\n".join(lines)


def rewrite_notes(text: str, model: YearFile, key: int, notes: List[Note]) -> str:
    """Replaces the year (key 0) or month notes block, or inserts one."""
    if key not in model.note_spans:
        raise ValueError("no place for notes %d" % key)
    start, end = model.note_spans[key]
    lines = text.split("\n")
    new = []
    for n in notes:
        new += format_note(n)
    if end is None:
        if new:
            lines[start:start] = new + [""]
    elif new:
        lines[start:end + 1] = new
    else:
        # Remove the block and the blank line after it.
        stop = end + 2 if end + 1 < len(lines) and lines[end + 1].strip() == "" else end + 1
        lines[start:stop] = []
    return "\n".join(lines)


# ---------------------------------------------------------------- ranges (6.2)

def leading_emoji(text: str) -> Optional[str]:
    tok = text.split(" ", 1)[0]
    if not tok or "~" in tok:
        return None
    if any(unicodedata.category(c)[0] in "LNPZ" for c in tok):
        return None
    if not any(unicodedata.category(c) == "So" for c in tok):
        return None
    return tok


def range_head(text: str) -> Optional[str]:
    """The emoji of a range's first day (6.2), or None.

    The first day is `<emoji> <title>`, and may be struck through as a
    whole (`~~<emoji> <title>~~`); a bare emoji is never a first day.
    """
    t = norm(text)
    em = leading_emoji(t)
    return em if em and t != em else None


def _bare(day: Optional[Day], emoji: str) -> int:
    if day is None:
        return -1
    for k, e in enumerate(day.events):
        if e.text.strip() == emoji:
            return k
    return -1


def range_end(model: YearFile, start: datetime.date, emoji: str) -> datetime.date:
    d = start + datetime.timedelta(days=1)
    while _bare(model.days.get(d), emoji) >= 0:
        d += datetime.timedelta(days=1)
    return d - datetime.timedelta(days=1)


def find_ranges(model: YearFile):
    out = []
    for d in sorted(model.days):
        for k, e in enumerate(model.days[d].events):
            em = range_head(e.text)
            if em:
                end = range_end(model, d, em)
                if end > d:
                    out.append({"emoji": em, "title": e.text, "start": d.isoformat(),
                                "end": end.isoformat(), "index": k})
    return out


def set_range_end(model: YearFile, start: datetime.date, emoji: str,
                  new_end: datetime.date) -> List[datetime.date]:
    end = range_end(model, start, emoji)
    changed = []
    one = datetime.timedelta(days=1)
    if new_end < start:
        raise ValueError("a range cannot end before it starts")
    d = end + one
    while d <= new_end:
        day = model.days.get(d)
        if day is None:
            raise ValueError("%s is not in this year's file" % d)
        day.events.append(Event(emoji))
        changed.append(d)
        d += one
    d = new_end + one
    while d <= end:
        day = model.days[d]
        del day.events[_bare(day, emoji)]
        changed.append(d)
        d += one
    return changed


def create_range(model: YearFile, start, end, emoji: str, title: str):
    if end < start:
        raise ValueError("a range cannot end before it starts")
    day = model.days.get(start)
    if day is None or model.days.get(end) is None:
        raise ValueError("the range must lie within %d" % model.year)
    if not title.strip():
        # A bare emoji on the first day would not be a range (6.2).
        raise ValueError("a range needs a title")
    day.events.append(Event(clean_text(emoji + " " + title)))
    return [start] + set_range_end(model, start, emoji, end)


def delete_range(model: YearFile, start, emoji: str, index: int):
    day = model.days[start]
    end = range_end(model, start, emoji)
    if not (0 <= index < len(day.events)) or range_head(day.events[index].text) != emoji:
        raise ValueError("no range starting with %s on %s" % (emoji, start))
    del day.events[index]
    set_range_end(model, start, emoji, start)
    out = [start]
    d = start + datetime.timedelta(days=1)
    while d <= end:
        out.append(d)
        d += datetime.timedelta(days=1)
    return out


# ---------------------------------------------------------------- lint/format API

def parse(name: str, text: str):
    if name.endswith("annual.md"):
        return parse_annual(text)
    m = re.search(r"(\d{4})\.md$", name)
    return parse_year(text, int(m.group(1)) if m else None)


def format_text(name: str, text: str) -> Tuple[Optional[str], List[Finding]]:
    """Formats a data file. Returns (None, findings) on an unfixable error (G4)."""
    model = parse(name, text)
    if not model.ok:
        return None, model.findings
    if isinstance(model, AnnualFile):
        return render_annual(model), model.findings
    return render_year(model), model.findings


def unified_diff(name: str, a: str, b: str) -> str:
    return "".join(difflib.unified_diff(
        a.splitlines(True), b.splitlines(True), "a/" + name, "b/" + name))
