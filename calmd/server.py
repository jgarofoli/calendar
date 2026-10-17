"""calsd: the calendar editor's HTTP server (TOOLS.md 7 and 8).

    python3 -m calmd.server --data ~/.local/share/calsd/data --host 127.0.0.1 --port 8642

`--data` is a git clone of the data repository that the server owns. Every save
is a commit pushed to origin/main. Standard library only.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import callib

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
FETCH_EVERY = 5        # seconds; reads within this window reuse the last fetch
BACKGROUND_FETCH = 15  # seconds between fetches by the background thread (main only)


class HTTPError(Exception):
    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status = status
        self.body = dict(error=message, **extra)


class Store:
    """The git working tree: a cache of origin/main (TOOLS.md 8)."""

    def __init__(self, root, remote="origin", branch="main", push=True):
        self.root = os.path.abspath(root)
        self.remote = remote
        self.branch = branch
        self.push = push
        self.lock = threading.RLock()
        self.fetch_lock = threading.Lock()  # one git fetch at a time
        self.broken = None          # set when the tree diverged; writes stop
        self.fetch_error = None
        self.last_fetch = 0.0
        self.fetch_every = FETCH_EVERY

    # -- git

    def git(self, *args, check=True):
        r = subprocess.run(["git", "-C", self.root] + list(args),
                           capture_output=True, text=True)
        if check and r.returncode != 0:
            raise HTTPError(500, "git %s failed: %s" % (args[0], r.stderr.strip()))
        return r

    def sync(self, force=True):
        """Fetch, then fast-forward. Never merges (TOOLS.md 8.1)."""
        if not self.push:
            return
        if not force and time.time() - self.last_fetch < self.fetch_every:
            return
        # The network part runs outside self.lock, so reads are not held up.
        with self.fetch_lock:
            r = self.git("fetch", "-q", self.remote, self.branch, check=False)
        if r.returncode != 0:
            self.fetch_error = r.stderr.strip() or "git fetch failed"
            return
        self.fetch_error = None
        self.last_fetch = time.time()
        with self.lock:
            r = self.git("merge", "-q", "--ff-only", "%s/%s" % (self.remote, self.branch),
                         check=False)
            if r.returncode != 0:
                self.broken = ("the server's copy has diverged from %s/%s, so saving is off. "
                               "Fix the clone in %s by hand. (%s)"
                               % (self.remote, self.branch, self.root, r.stderr.strip()))

    def sync_forever(self, every=BACKGROUND_FETCH):
        """Keep the tree fresh in the background, so requests rarely wait on GitHub."""
        self.fetch_every = 4 * every
        def loop():
            while True:
                time.sleep(every)
                try:
                    self.sync()
                except Exception:   # noqa: BLE001 - keep the thread alive
                    traceback.print_exc()
        threading.Thread(target=loop, name="calsd-fetch", daemon=True).start()

    def writable(self):
        if self.broken:
            raise HTTPError(503, self.broken)
        if self.fetch_error:
            raise HTTPError(503, "cannot reach GitHub, so saving is off: " + self.fetch_error)

    def commit(self, names, message):
        """Commit and push; on a rejected push, rebase once more and retry."""
        self.git("add", "--", *names)
        if not self.git("diff", "--cached", "--quiet", check=False).returncode:
            return False
        self.git("commit", "-q", "-m", message)
        if not self.push:
            return True
        upstream = "%s/%s" % (self.remote, self.branch)
        for _ in range(3):
            if self.git("push", "-q", self.remote, "HEAD:" + self.branch, check=False).returncode == 0:
                self.last_fetch = time.time()
                return True
            with self.fetch_lock:
                self.git("fetch", "-q", self.remote, self.branch)
            if self.git("rebase", "-q", upstream, check=False).returncode != 0:
                self.git("rebase", "--abort", check=False)
                self.git("reset", "-q", "--hard", upstream)
                raise HTTPError(409, "someone else changed the same lines at the same "
                                "time; your edit was not saved. Re-apply it.")
        self.git("reset", "-q", "--hard", upstream)
        raise HTTPError(503, "push kept being rejected; your edit was not saved")

    # -- files

    def path(self, name):
        return os.path.join(self.root, name)

    def read(self, name):
        try:
            with open(self.path(name), "rb") as f:
                data = f.read()
        except FileNotFoundError:
            raise HTTPError(404, "%s does not exist" % name)
        return data.decode("utf-8"), callib.blob_hash(data)

    def write(self, name, text):
        with open(self.path(name), "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def years(self):
        return sorted(int(f[:4]) for f in os.listdir(self.root) if callib.YEAR_FILE_RE.match(f))

    # -- edits

    def blob(self, sha):
        """The text of a blob by hash, or None (a base the client loaded earlier)."""
        if not re.fullmatch(r"[0-9a-f]{40}", sha or ""):
            return None
        r = self.git("cat-file", "blob", sha, check=False)
        return r.stdout if r.returncode == 0 else None

    def edit(self, name, base, change, message, same=None):
        """Read-check-change-commit-push for one file.

        `change(text)` returns the new text. A base older than the file is
        accepted when `same(base_text, text)` says the part being edited has
        not changed since, so an edit made to another day on another device
        is not a conflict. When the push is rejected, the edit is applied
        again on top of the newer file instead of rebasing, because git would
        report neighbouring days as a conflict.
        """
        with self.lock:
            self.writable()
            self.sync(force=False)
            self.writable()
            upstream = "%s/%s" % (self.remote, self.branch)
            for _ in range(3):
                text, cur = self.read(name)
                if base != cur:
                    old = self.blob(base) if same else None
                    if old is None or not same(old, text):
                        raise HTTPError(409, "%s changed since you loaded it (another device?). "
                                        "Here is the current version; re-apply your edit." % name)
                new = change(text)
                if new == text:
                    return False
                self.write(name, new)
                self.git("add", "--", name)
                self.git("commit", "-q", "-m", message() if callable(message) else message)
                if not self.push:
                    return True
                if self.git("push", "-q", self.remote, "HEAD:" + self.branch,
                            check=False).returncode == 0:
                    self.last_fetch = time.time()
                    return True
                # Rejected (or GitHub unreachable): drop our commit and retry on
                # top of whatever is there now.
                with self.fetch_lock:
                    f = self.git("fetch", "-q", self.remote, self.branch, check=False)
                self.git("reset", "-q", "--hard", upstream)
                if f.returncode != 0:
                    self.fetch_error = f.stderr.strip() or "git fetch failed"
                    raise HTTPError(503, "cannot reach GitHub; your edit was not saved")
            raise HTTPError(503, "push kept being rejected; your edit was not saved")

    def create(self, name, text, message):
        with self.lock:
            self.writable()
            self.sync()
            if os.path.exists(self.path(name)):
                raise HTTPError(409, "%s already exists" % name)
            self.write(name, text)
            try:
                return self.commit([name], message)
            except HTTPError:
                os.remove(self.path(name))
                raise


# ---------------------------------------------------------------- payloads

def year_name(year):
    return "%04d.md" % year


def parse_date(s):
    try:
        return datetime.date.fromisoformat(s)
    except (TypeError, ValueError):
        raise HTTPError(400, "not a date: %r" % (s,))


def year_payload(store, year, refresh=True):
    with store.lock:
        if refresh:
            store.sync(force=False)
        text, base = store.read(year_name(year))
    model = callib.parse_year(text, year)
    days_by_line = []
    months = []
    for m in range(1, 13):
        days = []
        for d in sorted(x for x in model.days if x.month == m):
            day = model.days[d]
            days.append({"date": d.isoformat(), "week": day.week, "weekday": day.weekday,
                         "line": day.start + 1, "events": [e.to_dict() for e in day.events]})
            days_by_line.append((day.start + 1, day.end + 1, d.isoformat()))
        months.append({"month": m, "name": callib.MONTHS[m - 1], "days": days,
                       "notes": [n.text for n in model.month_notes.get(m, [])]})
    findings = []
    for f in model.findings:
        fd = f.to_dict()
        fd["date"] = next((d for a, b, d in days_by_line if a <= f.line <= b), None)
        findings.append(fd)
    return {"year": year, "file": year_name(year), "base": base, "ok": model.ok,
            "notes": [n.text for n in model.notes], "months": months,
            "ranges": callib.find_ranges(model), "findings": findings,
            "status": status(store)}


def status(store):
    return {"broken": store.broken, "offline": store.fetch_error}


def load_model(text, year):
    return callib.parse_year(text, year)


def check_events(events):
    out = []
    if not isinstance(events, list):
        raise HTTPError(400, "events must be a list")
    for e in events:
        ev = callib.Event.from_dict(e if isinstance(e, dict) else {"text": e})
        if not ev.text:
            continue
        if ev.text == "-" or ev.text.startswith("- "):
            raise HTTPError(400, "an event cannot start with '- ' (that marks a detail)")
        out.append(ev)
    return out


def annual_or_none(store):
    try:
        text, _ = store.read("annual.md")
    except HTTPError:
        return None
    af = callib.parse_annual(text)
    if not af.ok:
        raise HTTPError(409, "annual.md has errors that need fixing by hand",
                        findings=[f.to_dict() for f in af.findings])
    return af


def ics_escape(s):
    return (s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\n", "\\n"))


def ics_fold(line):
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def make_ics(year, date, index, model):
    """One all-day event (TOOLS.md 7.1). A range becomes one multi-day event."""
    day = model.days.get(date)
    if day is None or not (0 <= index < len(day.events)):
        raise HTTPError(404, "no such event")
    ev = day.events[index]
    end = date
    em = callib.range_head(ev.text)
    if em:
        end = callib.range_end(model, date, em)
    summary = ev.text
    if summary.startswith("~~") and summary.endswith("~~"):
        summary = "Cancelled: " + summary[2:-2]
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//jgarofoli//calsd//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "BEGIN:VEVENT",
        "UID:%s-%d-%s@calsd" % (date.isoformat(), index, callib.blob_hash(ev.text.encode())[:12]),
        "DTSTAMP:" + stamp,
        "DTSTART;VALUE=DATE:" + date.strftime("%Y%m%d"),
        "DTEND;VALUE=DATE:" + (end + datetime.timedelta(days=1)).strftime("%Y%m%d"),
        "SUMMARY:" + ics_escape(summary),
    ]
    if ev.details:
        lines.append("DESCRIPTION:" + ics_escape("\n".join(d.text for d in ev.details)))
    lines += ["TRANSP:TRANSPARENT", "END:VEVENT", "END:VCALENDAR"]
    return "".join(ics_fold(l) + "\r\n" for l in lines)


# ---------------------------------------------------------------- API

class API:
    def __init__(self, store):
        self.store = store
        self.routes = [
            ("GET", r"/api/years", self.list_years),
            ("POST", r"/api/years", self.new_year),
            ("GET", r"/api/years/(\d{4})", self.get_year),
            ("PUT", r"/api/days/(\d{4}-\d\d-\d\d)", self.put_day),
            ("PUT", r"/api/notes/(\d{4})(?:-(\d\d))?", self.put_notes),
            ("POST", r"/api/years/(\d{4})/format", self.format_year),
            ("POST", r"/api/years/(\d{4})/annual", self.apply_annual),
            ("POST", r"/api/ranges", self.ranges),
            ("GET", r"/api/annual", self.get_annual),
            ("PUT", r"/api/annual", self.put_annual),
            ("POST", r"/api/annual/entries", self.add_entry),
            ("GET", r"/api/ics/(\d{4}-\d\d-\d\d)/(\d+)(?:\.ics)?", self.ics),
        ]

    def dispatch(self, method, path, body):
        for m, pattern, fn in self.routes:
            match = re.fullmatch(pattern, path)
            if match and m == method:
                return fn(body, *match.groups())
        if any(re.fullmatch(p, path) for _, p, _ in self.routes):
            raise HTTPError(405, "method not allowed")
        raise HTTPError(404, "not found")

    def conflict(self, year):
        def wrap(e):
            if e.status == 409:
                try:
                    e.body["year"] = year_payload(self.store, year, refresh=False)
                except HTTPError:
                    pass
            raise e
        return wrap

    # -- years

    def list_years(self, body):
        with self.store.lock:
            self.store.sync(force=False)
            years = self.store.years()
            annual = os.path.exists(self.store.path("annual.md"))
        return {"years": years, "annual": annual, "today": datetime.date.today().isoformat(),
                "status": status(self.store)}

    def get_year(self, body, year):
        return year_payload(self.store, int(year))

    def new_year(self, body):
        year = body.get("year")
        if not isinstance(year, int) or not 1 <= year <= 9999:
            raise HTTPError(400, "year must be a number")
        af = annual_or_none(self.store)
        text, n = callib.new_year(year, af)
        if not body.get("commit"):
            return {"preview": text, "count": n}
        self.store.create(year_name(year), text,
                          "%d: new year with %d annual event%s" % (year, n, "" if n == 1 else "s"))
        return year_payload(self.store, year, refresh=False)

    # -- edits

    def _edit_year(self, year, base, change, message, same=None):
        try:
            self.store.edit(year_name(year), base, change, message, same)
        except HTTPError as e:
            self.conflict(year)(e)
        return year_payload(self.store, year, refresh=False)

    def put_day(self, body, date):
        date = parse_date(date)
        events = check_events(body.get("events"))

        def change(text):
            model = load_model(text, date.year)
            day = model.days.get(date)
            if day is None or day.start < 0:
                raise HTTPError(409, "%s is not in %s" % (date, year_name(date.year)))
            day.events = events
            new = callib.rewrite_days(text, model, [date])
            got = callib.parse_year(new, date.year).days.get(date)
            if got is None or [e.to_dict() for e in got.events] != [e.to_dict() for e in events]:
                raise HTTPError(400, "that text would not read back the same; "
                                "avoid starting a line with '- '")
            return new

        def same(old, cur):
            a = callib.parse_year(old, date.year).days.get(date)
            b = callib.parse_year(cur, date.year).days.get(date)
            return (a is not None and b is not None
                    and [e.to_dict() for e in a.events] == [e.to_dict() for e in b.events])

        return self._edit_year(date.year, body.get("base"), change,
                               "%s: edit via calsd" % date.isoformat(), same)

    def put_notes(self, body, year, month):
        year = int(year)
        key = int(month) if month else 0
        if not 0 <= key <= 12:
            raise HTTPError(400, "no such month")
        notes = [callib.Note(callib.clean_text(n)) for n in body.get("notes", [])
                 if callib.clean_text(n)]

        def change(text):
            model = load_model(text, year)
            new = callib.rewrite_notes(text, model, key, notes)
            got = callib.parse_year(new, year)
            have = got.notes if key == 0 else got.month_notes.get(key, [])
            if [n.text for n in have] != [n.text for n in notes]:
                raise HTTPError(400, "those notes would not read back the same")
            return new

        def same(old, cur):
            a, b = callib.parse_year(old, year), callib.parse_year(cur, year)
            pick = (lambda m: m.notes) if key == 0 else (lambda m: m.month_notes.get(key, []))
            return [n.text for n in pick(a)] == [n.text for n in pick(b)]

        label = "%d" % year if key == 0 else "%d-%02d" % (year, key)
        return self._edit_year(year, body.get("base"), change, "%s: notes via calsd" % label,
                               same)

    def format_year(self, body, year):
        year = int(year)
        name = year_name(year)
        with self.store.lock:
            self.store.sync(force=False)
            text, base = self.store.read(name)
        out, findings = callib.format_text(name, text)
        if out is None:
            raise HTTPError(409, "the file has errors the formatter cannot fix",
                            findings=[f.to_dict() for f in findings])
        if not body.get("commit"):
            return {"diff": callib.unified_diff(name, text, out), "base": base}
        n = sum(1 for f in findings if f.code in callib.SAFE)

        def change(cur):
            return callib.format_text(name, cur)[0] or cur

        return self._edit_year(year, body.get("base"), change,
                               "calfmt: fix %d finding%s in %s" % (n, "" if n == 1 else "s", name))

    def apply_annual(self, body, year):
        year = int(year)
        name = year_name(year)
        af = annual_or_none(self.store)
        if af is None:
            raise HTTPError(404, "there is no annual.md yet")
        result = {}

        def change(text):
            model = load_model(text, year)
            tagged = []
            added = callib.apply_annual(model, af, tagged)
            result["added"] = [{"date": d.isoformat(), "text": t} for d, t in added]
            result["tagged"] = [{"date": d.isoformat(), "text": t} for d, t in tagged]
            return callib.rewrite_days(text, model, [d for d, _ in added + tagged])

        if not body.get("commit"):
            with self.store.lock:
                self.store.sync(force=False)
                text, base = self.store.read(name)
            new = change(text)
            return {"diff": callib.unified_diff(name, text, new), "base": base, **result}
        def message():
            n, m = len(result.get("added", [])), len(result.get("tagged", []))
            msg = "%d: apply %d annual event%s" % (year, n, "" if n == 1 else "s")
            return msg + (", tag %d" % m if m else "")

        payload = self._edit_year(year, body.get("base"), change, message)
        payload["added"] = result.get("added", [])
        payload["tagged"] = result.get("tagged", [])
        return payload

    def ranges(self, body):
        op = body.get("op")
        start = parse_date(body.get("start"))
        emoji = callib.clean_text(body.get("emoji", ""))
        if not emoji:
            raise HTTPError(400, "a range needs an emoji")
        year = start.year

        def change(text):
            model = load_model(text, year)
            try:
                if op == "create":
                    end = parse_date(body.get("end"))
                    changed = callib.create_range(model, start, end, emoji, body.get("title", ""))
                elif op == "resize":
                    end = parse_date(body.get("end"))
                    if end.year != year:
                        raise ValueError("a range must stay within %d" % year)
                    changed = callib.set_range_end(model, start, emoji, end)
                elif op == "delete":
                    changed = callib.delete_range(model, start, emoji, int(body.get("index", 0)))
                else:
                    raise HTTPError(400, "op must be create, resize, or delete")
            except ValueError as e:
                raise HTTPError(400, str(e))
            return callib.rewrite_days(text, model, changed)

        end = body.get("end") or ""
        msg = {"create": "%s..%s: new range via calsd" % (start, end),
               "resize": "%s..%s: resize range via calsd" % (start, end),
               "delete": "%s: delete range via calsd" % start}.get(op, "range via calsd")
        return self._edit_year(year, body.get("base"), change, msg)

    # -- annual.md

    def get_annual(self, body):
        with self.store.lock:
            self.store.sync(force=False)
            try:
                text, base = self.store.read("annual.md")
            except HTTPError:
                return {"exists": False, "text": "", "base": None, "entries": [],
                        "groups": [], "findings": []}
        af = callib.parse_annual(text)
        return {"exists": True, "text": text, "base": base, "entries": [e.to_dict() for e in af.entries],
                "groups": af.groups, "findings": [f.to_dict() for f in af.findings]}

    def _save_annual(self, base, change, message):
        def checked(text):
            new = change(text)
            out, findings = callib.format_text("annual.md", new)
            if out is None:
                raise HTTPError(400, "annual.md would have errors",
                                findings=[f.to_dict() for f in findings])
            return out

        with self.store.lock:
            if base is None and not os.path.exists(self.store.path("annual.md")):
                self.store.create("annual.md", checked("# Annual events\n"), message)
                return self.get_annual({})
        try:
            self.store.edit("annual.md", base, checked, message)
        except HTTPError as e:
            if e.status == 409:
                e.body["annual"] = self.get_annual({})
            raise
        return self.get_annual({})

    def put_annual(self, body):
        text = body.get("text", "")
        if not isinstance(text, str):
            raise HTTPError(400, "text must be a string")
        text = text.replace("\r\n", "\n")
        if not text.endswith("\n"):
            text += "\n"
        return self._save_annual(body.get("base"), lambda _: text, "annual.md: edit via calsd")

    def add_entry(self, body):
        when = str(body.get("date", "")).strip()
        m = callib.ENTRY_RE.match(when)
        if not m or m.group(1) != when or callib.date_error(when):
            raise HTTPError(400, "date must be MM-DD, MM-nDdd (11-4Thu, 05-LMon), "
                                 "MM-DD±nDdd (12-25-4Sun), or Easter[±N]")
        entry = callib.Entry(when, callib.clean_text(body.get("text", "")),
                             [callib.Detail(callib.clean_text(t)) for t in body.get("details", [])
                              if callib.clean_text(t)])
        if not entry.text:
            raise HTTPError(400, "the entry needs text")
        group = body.get("group") or ""

        def change(text):
            af = callib.parse_annual(text)
            items = af.items
            if group:
                k = next((i for i, (kind, v) in enumerate(items)
                          if kind == "line" and v == "## " + group), None)
                if k is None:
                    items += [("line", ""), ("line", "## " + group), ("line", "")]
                    k = len(items) - 1
                # After the last entry of that group.
                j = k + 1
                while j < len(items) and not (items[j][0] == "line" and items[j][1].startswith("#")):
                    j += 1
                while j > k + 1 and items[j - 1] == ("line", ""):
                    j -= 1
                items.insert(j, ("entry", entry))
            else:
                while items and items[-1] == ("line", ""):
                    items.pop()
                items.append(("entry", entry))
            return callib.render_annual(af)

        return self._save_annual(body.get("base"), change,
                                 "annual.md: add %s %s" % (when, entry.text))

    def ics(self, body, date, index):
        date = parse_date(date)
        with self.store.lock:
            text, _ = self.store.read(year_name(date.year))
        return ("text/calendar", make_ics(date.year, date, int(index),
                                          callib.parse_year(text, date.year)))


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    api = None
    server_version = "calsd/1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.command, fmt % args))

    def send(self, status, body, ctype="application/json; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else (
            body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8"))
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def handle_any(self):
        path = urlparse(self.path).path
        if self.command == "GET" and path in ("/", "/index.html"):
            with open(os.path.join(WEB, "index.html"), "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        if not path.startswith("/api/"):
            return self.send(404, {"error": "not found"})
        body = {}
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8"))
            except ValueError:
                return self.send(400, {"error": "body is not JSON"})
            if not isinstance(body, dict):
                return self.send(400, {"error": "body must be a JSON object"})
        try:
            result = self.api.dispatch(self.command, path, body)
        except HTTPError as e:
            return self.send(e.status, e.body)
        except Exception as e:      # noqa: BLE001 - report, keep serving
            traceback.print_exc()
            return self.send(500, {"error": "%s: %s" % (type(e).__name__, e)})
        if isinstance(result, tuple):
            ctype, text = result
            return self.send(200, text, ctype + "; charset=utf-8",
                             {"Content-Disposition": 'inline; filename="event.ics"'})
        self.send(200, result)

    do_GET = do_PUT = do_POST = handle_any


def make_server(store, host, port):
    handler = type("BoundHandler", (Handler,), {"api": API(store)})
    return ThreadingHTTPServer((host, port), handler)


def main(argv=None):
    p = argparse.ArgumentParser(prog="calsd", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", required=True, help="git clone of the calendar repository")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8642)
    p.add_argument("--remote", default="origin")
    p.add_argument("--branch", default="main")
    p.add_argument("--no-push", action="store_true", help="commit locally only (testing)")
    a = p.parse_args(argv)
    store = Store(a.data, a.remote, a.branch, push=not a.no_push)
    store.sync()
    store.sync_forever()
    srv = make_server(store, a.host, a.port)
    print("calsd: serving %s on http://%s:%d/" % (store.root, a.host, a.port), file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
