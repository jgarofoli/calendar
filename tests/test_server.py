"""calsd against a temporary bare repository (TOOLS.md 9, "Sync")."""

import datetime
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from calmd import callib, server

HERE = os.path.dirname(__file__)


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def git_env():
    os.environ.setdefault("GIT_AUTHOR_NAME", "test")
    os.environ.setdefault("GIT_AUTHOR_EMAIL", "test@example.com")
    os.environ.setdefault("GIT_COMMITTER_NAME", "test")
    os.environ.setdefault("GIT_COMMITTER_EMAIL", "test@example.com")


class Base(unittest.TestCase):
    def setUp(self):
        git_env()
        self.tmp = tempfile.mkdtemp()
        self.bare = os.path.join(self.tmp, "origin.git")
        sh(self.tmp, "git", "init", "-q", "--bare", self.bare)
        sh(self.bare, "git", "symbolic-ref", "HEAD", "refs/heads/main")
        seed = os.path.join(self.tmp, "seed")
        sh(self.tmp, "git", "clone", "-q", self.bare, seed)
        with open(os.path.join(HERE, "fixtures", "2026-before.md"), encoding="utf-8") as f:
            text, _ = callib.format_text("2026.md", f.read())
        with open(os.path.join(seed, "2026.md"), "w", encoding="utf-8") as f:
            f.write(text)
        with open(os.path.join(seed, "annual.md"), "w", encoding="utf-8") as f:
            f.write("# Annual events\n\n## Birthdays\n\n01-01 🎂 Lena's Birthday  \n")
        sh(seed, "git", "checkout", "-q", "-b", "main")
        sh(seed, "git", "add", ".")
        sh(seed, "git", "commit", "-q", "-m", "seed")
        sh(seed, "git", "push", "-q", "origin", "main")
        self.data = os.path.join(self.tmp, "data")
        self.phone = os.path.join(self.tmp, "phone")     # stands in for Working Copy
        sh(self.tmp, "git", "clone", "-q", self.bare, self.data)
        sh(self.tmp, "git", "clone", "-q", self.bare, self.phone)
        server.Handler.log_message = lambda *a: None
        self.store = server.Store(self.data)
        self.srv = server.make_server(self.store, "127.0.0.1", 0)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp)

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read()
                if r.headers.get_content_type() == "application/json":
                    return r.status, json.loads(raw)
                return r.status, raw.decode()
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def phone_edit(self, old, new, msg="Auto-Sync by Working Copy"):
        sh(self.phone, "git", "pull", "-q", "--ff-only")
        p = os.path.join(self.phone, "2026.md")
        with open(p, encoding="utf-8") as f:
            t = f.read()
        assert old in t, old
        with open(p, "w", encoding="utf-8") as f:
            f.write(t.replace(old, new))
        sh(self.phone, "git", "commit", "-q", "-am", msg)
        sh(self.phone, "git", "push", "-q", "origin", "main")

    def origin_file(self, name="2026.md"):
        return sh(self.tmp, "git", "--git-dir", self.bare, "show", "main:" + name)

    def origin_log(self):
        return sh(self.tmp, "git", "--git-dir", self.bare, "log", "--format=%s", "main").split("\n")


class Read(Base):
    def test_years_and_year(self):
        st, j = self.call("GET", "/api/years")
        self.assertEqual((st, j["years"], j["annual"]), (200, [2026], True))
        st, y = self.call("GET", "/api/years/2026")
        self.assertEqual(st, 200)
        self.assertEqual(y["findings"], [])
        oct10 = y["months"][9]["days"][9]
        self.assertEqual(oct10["date"], "2026-10-10")
        self.assertEqual(oct10["events"][0]["text"], "🎂 Nate's Birthday")
        self.assertEqual(y["base"], sh(self.data, "git", "hash-object", "2026.md").strip())
        self.assertIn({"emoji": "🤒", "title": "🤒 caught Sam's cold", "start": "2026-09-14",
                       "end": "2026-09-18", "index": 1}, y["ranges"])

    def test_page(self):
        st, page = self.call("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn("<title>Calendar</title>", page)

    def test_sees_hand_edits(self):
        self.phone_edit("W42 2026-10-13 Tue  ", "W42 2026-10-13 Tue 🍕 Pizza  ")
        _, y = self.call("GET", "/api/years/2026")
        self.assertEqual(y["months"][9]["days"][12]["events"][0]["text"], "🍕 Pizza")


class Write(Base):
    def test_put_day_commits_and_pushes(self):
        _, y = self.call("GET", "/api/years/2026")
        before = self.origin_file()
        st, y2 = self.call("PUT", "/api/days/2026-10-15", {"base": y["base"], "events": [
            {"text": "🦷 Dentist @ 10", "details": ["Dr. Lee, 450 Main St, Suite 200",
                                                  "Bring the new insurance card; the front desk needs "
                                                  "the group number and member ID before the visit"]},
            {"text": "🏋️ Gym @ 4", "details": []}]})
        self.assertEqual(st, 200, y2)
        self.assertEqual(self.origin_log()[0], "2026-10-15: edit via calsd")
        after = self.origin_file()
        self.assertIn("W42 2026-10-15 Thu 🦷 Dentist @ 10  \n"
                      "                      - Dr. Lee, 450 Main St, Suite 200  \n"
                      "                      - Bring the new insurance card; the front\n"
                      "                        desk needs the group number and member\n"
                      "                        ID before the visit  \n"
                      "                   🏋️ Gym @ 4  \n", after)
        # Only that day's lines changed.
        a, b = before.split("\n"), after.split("\n")
        self.assertTrue(a[365].startswith("W42 2026-10-15"))
        self.assertEqual(a[:365], b[:365])
        self.assertEqual(a[366:], b[371:])
        self.assertNotEqual(y2["base"], y["base"])

    def test_stale_base_same_day_is_409(self):
        _, y = self.call("GET", "/api/years/2026")
        self.phone_edit("W42 2026-10-13 Tue  ", "W42 2026-10-13 Tue 🍕 Pizza  ")
        self.store.last_fetch = 0
        st, j = self.call("PUT", "/api/days/2026-10-13", {"base": y["base"], "events": [{"text": "x"}]})
        self.assertEqual(st, 409)
        self.assertEqual(j["year"]["months"][9]["days"][12]["events"][0]["text"], "🍕 Pizza")
        self.assertNotIn("W42 2026-10-13 Tue x", self.origin_file())

    def test_stale_base_next_day_is_saved(self):
        # The phone edits the day before; both edits are kept (no git rebase
        # conflict on neighbouring lines). Once with the server's copy already
        # fetched, once with it still stale.
        for fresh, (day, other) in ((True, ("13", "14")), (False, ("20", "21"))):
            _, y = self.call("GET", "/api/years/2026")
            wk, wd = {"13": ("W42", "Tue"), "20": ("W43", "Tue")}[day]
            self.phone_edit("%s 2026-10-%s %s  " % (wk, day, wd), "%s 2026-10-%s %s 🍕 Pizza  " % (wk, day, wd))
            if fresh:
                self.store.last_fetch = 0
            st, j = self.call("PUT", "/api/days/2026-10-" + other,
                              {"base": y["base"], "events": [{"text": "x"}]})
            self.assertEqual(st, 200, j)
            t = self.origin_file()
            self.assertIn("2026-10-%s %s 🍕 Pizza  \n" % (day, wd), t)
            self.assertIn("2026-10-%s %s x  \n" % (other, {"14": "Wed", "21": "Wed"}[other]), t)

    def test_rejects_detail_marker(self):
        _, y = self.call("GET", "/api/years/2026")
        st, j = self.call("PUT", "/api/days/2026-10-14", {"base": y["base"], "events": [{"text": "- x"}]})
        self.assertEqual(st, 400)

    def test_concurrent_push_other_day_rebases(self):
        _, y = self.call("GET", "/api/years/2026")
        real = self.store.git
        fired = []

        def git(*args, **kw):
            if args[0] == "push" and not fired:
                fired.append(1)
                self.phone_edit("W42 2026-10-13 Tue  ", "W42 2026-10-13 Tue 🍕 Pizza  ")
            return real(*args, **kw)

        self.store.git = git
        st, j = self.call("PUT", "/api/days/2026-10-16", {"base": y["base"], "events": [{"text": "🎬 Movie"}]})
        self.assertEqual(st, 200, j)
        t = self.origin_file()
        self.assertIn("W42 2026-10-13 Tue 🍕 Pizza  ", t)
        self.assertIn("W42 2026-10-16 Fri 🎬 Movie  ", t)
        self.assertEqual(self.origin_log()[:2], ["2026-10-16: edit via calsd", "Auto-Sync by Working Copy"])

    def test_concurrent_push_same_day_is_409(self):
        _, y = self.call("GET", "/api/years/2026")
        real = self.store.git
        fired = []

        def git(*args, **kw):
            if args[0] == "push" and not fired:
                fired.append(1)
                self.phone_edit("W42 2026-10-16 Fri  ", "W42 2026-10-16 Fri 🍕 Pizza  ")
            return real(*args, **kw)

        self.store.git = git
        st, j = self.call("PUT", "/api/days/2026-10-16", {"base": y["base"], "events": [{"text": "🎬 Movie"}]})
        self.assertEqual(st, 409, j)
        self.assertIn("W42 2026-10-16 Fri 🍕 Pizza  ", self.origin_file())
        # The server's tree is back on origin/main and keeps working.
        self.assertEqual(sh(self.data, "git", "rev-parse", "HEAD"),
                         sh(self.data, "git", "rev-parse", "origin/main"))
        _, y = self.call("GET", "/api/years/2026")
        st, _ = self.call("PUT", "/api/days/2026-10-17", {"base": y["base"], "events": [{"text": "🎬 Movie"}]})
        self.assertEqual(st, 200)

    def test_diverged_tree_stops_writes(self):
        sh(self.data, "git", "commit", "-q", "--allow-empty", "-m", "local only")
        self.phone_edit("W42 2026-10-13 Tue  ", "W42 2026-10-13 Tue 🍕 Pizza  ")
        _, y = self.call("GET", "/api/years/2026")
        self.assertTrue(y["status"]["broken"])
        st, _ = self.call("PUT", "/api/days/2026-10-14", {"base": y["base"], "events": []})
        self.assertEqual(st, 503)

    def test_notes(self):
        _, y = self.call("GET", "/api/years/2026")
        st, y = self.call("PUT", "/api/notes/2026-10", {"base": y["base"], "notes": ["Goal: finish P1"]})
        self.assertEqual(st, 200, y)
        self.assertEqual(y["months"][9]["notes"], ["Goal: finish P1"])
        self.assertIn("## October\n\n> Goal: finish P1  \n\nW40", self.origin_file())
        st, y = self.call("PUT", "/api/notes/2026", {"base": y["base"], "notes": ["Year theme"]})
        self.assertIn("# 2026\n\n> Year theme  \n\n## January", self.origin_file())
        self.assertEqual(y["findings"], [])

    def test_ranges(self):
        _, y = self.call("GET", "/api/years/2026")
        st, y = self.call("POST", "/api/ranges", {"base": y["base"], "op": "create", "emoji": "🏔️",
                                                  "title": "Tahoe", "start": "2026-12-01", "end": "2026-12-03"})
        self.assertEqual(st, 200, y)
        self.assertIn({"emoji": "🏔️", "title": "🏔️ Tahoe", "start": "2026-12-01", "end": "2026-12-03",
                       "index": 0}, y["ranges"])
        st, y = self.call("POST", "/api/ranges", {"base": y["base"], "op": "resize", "emoji": "🏔️",
                                                  "start": "2026-12-01", "end": "2026-12-05"})
        self.assertIn("W49 2026-12-05 Sat 🏔️  ", self.origin_file())
        st, y = self.call("POST", "/api/ranges", {"base": y["base"], "op": "delete", "emoji": "🏔️",
                                                  "start": "2026-12-01", "index": 0})
        self.assertNotIn("🏔️", self.origin_file())
        self.assertEqual(y["findings"], [])

    def test_format(self):
        self.phone_edit("W42 2026-10-13 Tue  ", "W42 2026-10-13 Tue 🍕 Pizza")
        _, y = self.call("GET", "/api/years/2026")
        self.assertEqual([f["code"] for f in y["findings"]], ["L01"])
        self.assertEqual(y["findings"][0]["date"], "2026-10-13")
        _, p = self.call("POST", "/api/years/2026/format", {"commit": False})
        self.assertIn("+W42 2026-10-13 Tue 🍕 Pizza  ", p["diff"])
        st, y = self.call("POST", "/api/years/2026/format", {"commit": True, "base": p["base"]})
        self.assertEqual(y["findings"], [])
        self.assertEqual(self.origin_log()[0], "calfmt: fix 1 finding in 2026.md")

    def test_annual(self):
        _, a = self.call("GET", "/api/annual")
        st, a = self.call("POST", "/api/annual/entries", {"base": a["base"], "date": "02-29",
                                                          "text": "🎂 Leap's Birthday", "group": "Birthdays"})
        self.assertEqual(st, 200, a)
        self.assertIn("01-01 🎂 Lena's Birthday  \n02-29 🎂 Leap's Birthday  \n", a["text"])
        _, p = self.call("POST", "/api/years/2026/annual", {"commit": False})
        self.assertEqual(len(p["added"]), 2)
        st, y = self.call("POST", "/api/years/2026/annual", {"commit": True, "base": p["base"]})
        self.assertEqual(st, 200, y)
        self.assertEqual(self.origin_log()[0], "2026: apply 2 annual events")
        self.assertIn("W09 2026-02-28 Sat 🎂 Leap's Birthday (02-29)  ", self.origin_file())
        _, p = self.call("POST", "/api/years/2026/annual", {"commit": False})
        self.assertEqual(p["added"], [])
        st, j = self.call("POST", "/api/years", {"year": 2028, "commit": True})
        self.assertEqual(st, 200, j)
        self.assertIn("W09 2028-02-29 Tue 🎂 Leap's Birthday  ", self.origin_file("2028.md"))
        self.assertEqual(self.origin_log()[0], "2028: new year with 2 annual events")
        st, _ = self.call("PUT", "/api/annual", {"base": "stale", "text": "# Annual events\n"})
        self.assertEqual(st, 409)
        st, j = self.call("PUT", "/api/annual", {"base": a["base"], "text": "# Annual events\n\n02-30 x  \n"})
        self.assertEqual(st, 400)
        self.assertEqual(j["findings"][0]["code"], "L10")

    def test_ics(self):
        st, ics = self.call("GET", "/api/ics/2026-10-24/1.ics")
        self.assertEqual(st, 200)
        self.assertIn("SUMMARY:🏖️ vacation\r\n", ics)
        self.assertIn("DTSTART;VALUE=DATE:20261024\r\n", ics)
        self.assertIn("DTEND;VALUE=DATE:20261102\r\n", ics)       # through 2026-11-01
        st, ics = self.call("GET", "/api/ics/2026-09-14/0.ics")
        self.assertIn("SUMMARY:Cancelled: 🦷 Dentist appointment", ics)
        self.assertEqual(self.call("GET", "/api/ics/2026-09-14/7.ics")[0], 404)


if __name__ == "__main__":
    unittest.main()
