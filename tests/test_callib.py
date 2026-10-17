import datetime
import os
import unittest

from calmd import callib as c

HERE = os.path.dirname(__file__)
D = datetime.date


def fixture(name):
    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8", newline="") as f:
        return f.read()


def codes(model):
    return [(f.line, f.code) for f in model.findings]


def year_with(year, blocks):
    """A skeleton file for `year` with some day lines replaced by `blocks`."""
    lines = c.skeleton_text(year).split("\n")
    for date, block in blocks.items():
        pre = c.day_prefix(date)
        k = next(i for i, l in enumerate(lines) if l.startswith(pre))
        lines[k:k + 1] = block
    return "\n".join(lines)


def words(model):
    """(kind, words) per day, for content preservation (G3)."""
    out = {}
    for d, day in model.days.items():
        out[d] = [(k, t.split()) for e in day.events
                  for k, t in [("event", e.text)] + [("detail", x.text) for x in e.details]]
    return out


class Width(unittest.TestCase):
    def test_emoji(self):
        self.assertEqual(c.width("🏖️"), 2)      # U+1F3D6 U+FE0F
        self.assertEqual(c.width("⛲️"), 2)
        self.assertEqual(c.width("🎂"), 2)
        self.assertEqual(c.width("abc"), 3)
        self.assertEqual(c.width("👩‍💻"), 4)    # two wide code points, ZWJ is 0

    def test_every_emoji_in_files_is_two(self):
        for y in (2026, 2027):
            m = c.parse("x.md", fixture("%d-before.md" % y))
            for day in m.days.values():
                for e in day.events:
                    em = c.leading_emoji(e.text.strip("~"))
                    if em:
                        self.assertEqual(c.width(em), 2, em)


class Wrap(unittest.TestCase):
    def test_fits(self):
        self.assertEqual(c.wrap("a b", "x ", "  "), ["x a b"])

    def test_greedy(self):
        text = "word " * 20
        lines = c.wrap(text.strip(), " " * 19, " " * 22)
        self.assertTrue(all(c.width(l) <= 64 for l in lines))
        self.assertTrue(all(l.startswith(" " * 22) for l in lines[1:]))

    def test_long_word_overflows(self):
        url = "https://example.com/" + "x" * 80
        self.assertEqual(c.wrap("see " + url, " " * 19, " " * 22),
                         [" " * 19 + "see", " " * 22 + url])

    def test_continuation_never_starts_with_dash(self):
        # 19 + 40 chars, then " -" would overflow at 64.
        text = "a" * 40 + " bb - cc"
        lines = c.wrap(text, " " * 19, " " * 22)
        for l in lines[1:]:
            self.assertFalse(l.strip().startswith("- "), lines)
            self.assertNotEqual(l.strip(), "-")
        self.assertEqual(" ".join(" ".join(lines).split()), text)


class Fixtures(unittest.TestCase):
    """Two year files as first written by hand, before any formatting."""

    def test_findings(self):
        m26 = c.parse("2026.md", fixture("2026-before.md"))
        m27 = c.parse("2027.md", fixture("2027-before.md"))
        self.assertEqual(codes(m26), [(346, "L01"), (352, "L04"), (354, "L01"),
                                      (362, "L01"), (367, "L01")])
        self.assertEqual(codes(m27), [(195, "L01"), (195, "L04")])

    def test_format_changes_exactly_section_11(self):
        for y, changed in ((2026, {346, 352, 354, 362, 367}), (2027, {195})):
            before = fixture("%d-before.md" % y)
            after, _ = c.format_text("%d.md" % y, before)
            a, b = before.split("\n"), after.split("\n")
            import difflib
            touched = set()
            for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, a, b).get_opcodes():
                if tag != "equal":
                    touched |= set(range(i1 + 1, i2 + 1))
            self.assertEqual(touched, changed)
            self.assertEqual(len(b) - len(a), {2026: 1, 2027: 1}[y])

    def test_round_trip_after_fixes(self):
        for y in (2026, 2027):
            after, _ = c.format_text("%d.md" % y, fixture("%d-before.md" % y))
            m = c.parse("%d.md" % y, after)
            self.assertEqual(m.findings, [])
            self.assertEqual(c.format_text("%d.md" % y, after)[0], after)

    def test_counts(self):
        m26 = c.parse("2026.md", fixture("2026-before.md"))
        m27 = c.parse("2027.md", fixture("2027-before.md"))
        n = lambda m: sum(len(d.events) for d in m.days.values())
        self.assertEqual((n(m26), n(m27)), (43, 18))


class Guarantees(unittest.TestCase):
    CASES = {
        D(2026, 3, 2): ["W10 2026-03-02 Mon 🦷 Dentist @ 10",
                        "                      - Dr. Lee, 450 Main St, Suite 200 and a lot more text that runs long",
                        "                   🏋️ Gym @ 4  "],
        D(2026, 3, 3): ["W10 2026-03-03 Tue ~~🎸 The Paper Lanterns at Elm Hall / Riverdome (BUY TICKETS) presale~~  "],
        D(2026, 3, 4): ["W10 2026-03-04 Wed ⛲️ Fountain with selector   "],
        D(2026, 3, 5): ["W10 2026-03-05 Thu ", "                    🎂 indented twenty  "],
        D(2026, 3, 6): ["W10 2026-03-06 Fri 🎂 x" + " ab" * 13 + " - and a dash continues on  "],
        D(2026, 3, 7): ["W10 2026-03-07 Sat 📞 one ", "                      - detail one"],
    }

    def text(self):
        return year_with(2026, self.CASES)

    def test_idempotent_and_preserving(self):
        t = self.text()
        m = c.parse("2026.md", t)
        self.assertTrue(m.ok, m.findings)
        once, _ = c.format_text("2026.md", t)
        twice, _ = c.format_text("2026.md", once)
        self.assertEqual(once, twice)                                     # G1
        self.assertEqual(c.parse("2026.md", once).findings, [])          # G2
        self.assertEqual(words(c.parse("2026.md", once)), words(m))      # G3
        strip = lambda s: [l for l in s.split("\n") if not l.startswith(" ")]
        skel = [l[:18] if c.DAY_RE.match(l) else l for l in strip(once)]
        want = [l[:18] if c.DAY_RE.match(l) else l for l in strip(c.skeleton_text(2026))]
        self.assertEqual(skel, want)                                     # G4

    def test_first_event_moves_to_day_line(self):
        out, _ = c.format_text("2026.md", self.text())
        self.assertIn("W10 2026-03-05 Thu 🎂 indented twenty  \n", out)

    def test_cancelled_wraps_keep_tildes(self):
        out, _ = c.format_text("2026.md", self.text())
        day = c.parse("2026.md", out).days[D(2026, 3, 3)]
        self.assertTrue(day.events[0].text.startswith("~~") and day.events[0].text.endswith("~~"))
        self.assertIn("\n                      ", out.split("W10 2026-03-03")[1][:120])

    def test_unfixable_changes_nothing(self):
        t = self.text().replace("W10 2026-03-08 Sun", "W10 2026-03-08 Mon")
        out, findings = c.format_text("2026.md", t)
        self.assertIsNone(out)
        self.assertIn("L06", [f.code for f in findings])
        t = self.text().replace("\nW10 2026-03-08 Sun  ", "\nW10 2026-03-08 Sun\tx  ")
        self.assertIsNone(c.format_text("2026.md", t)[0])

    def test_l01_cases(self):
        # Each "missing hard break" case in section 8, step 2.
        base = {
            "blank": ["W10 2026-03-08 Sun 🎂 a"],                    # next is blank
            "day": ["W10 2026-03-07 Sat 🎂 a"],                       # next is a day
            "event": ["W10 2026-03-06 Fri 🎂 a", "                   🎂 b  "],
            "detail": ["W10 2026-03-05 Thu 🎂 a", "                      - b  "],
        }
        for name, block in base.items():
            date = D(2026, 3, int(block[0][12:14]))
            m = c.parse("2026.md", year_with(2026, {date: block}))
            self.assertEqual([f.code for f in m.findings], ["L01"], name)
            out, _ = c.format_text("2026.md", year_with(2026, {date: block}))
            self.assertEqual(c.parse("2026.md", out).findings, [], name)
        # Before the heading and before the footer.
        m = c.parse("2026.md", c.skeleton_text(2026).replace(
            "W05 2026-01-31 Sat  ", "W05 2026-01-31 Sat 🎂 a").replace(
            "W53 2026-12-31 Thu  ", "W53 2026-12-31 Thu 🎂 b"))
        self.assertEqual([f.code for f in m.findings], ["L01", "L01"])

    def test_l05_kept(self):
        block = ["W10 2026-03-02 Mon 🦷 Dentist", "                      at 10  ",
                 "                   🏋️ Gym", "                      @ 4 and more  "]
        t = year_with(2026, {D(2026, 3, 2): block})
        m = c.parse("2026.md", t)
        self.assertEqual([f.code for f in m.findings], ["L05", "L05"])
        out, _ = c.format_text("2026.md", t)
        self.assertIn("W10 2026-03-02 Mon 🦷 Dentist\n                      at 10  \n", out)
        self.assertEqual(c.format_text("2026.md", out)[0], out)

    def test_soft_wrap_ok(self):
        block = ["W10 2026-03-02 Mon 🎸 The Paper Lanterns at Elm Hall / Riverdome",
                 "                      (BUY TICKETS)  "]
        m = c.parse("2026.md", year_with(2026, {D(2026, 3, 2): block}))
        self.assertEqual(m.findings, [])
        self.assertEqual(m.days[D(2026, 3, 2)].events[0].text,
                         "🎸 The Paper Lanterns at Elm Hall / Riverdome (BUY TICKETS)")

    def test_file_level(self):
        t = c.skeleton_text(2026)
        for bad in ("﻿" + t, t.replace("\n", "\r\n"), t + "\n", t[:-1],
                    t.replace("## March\n", "\n## March\n")):
            m = c.parse("2026.md", bad)
            self.assertIn("L08", [f.code for f in m.findings])
            self.assertEqual(c.format_text("2026.md", bad)[0], t)

    def test_footer(self):
        t = c.skeleton_text(2026)
        for bad in (t.replace("\nhttps://jgarofoli.github.io/calendar/?year=2026&format=iso\n", "\n"),
                    t.replace("format=iso", "format=short")):
            self.assertIn("L11", [f.code for f in c.parse("2026.md", bad).findings])
            self.assertEqual(c.format_text("2026.md", bad)[0], t)
        bad = t + "stray words\n"
        self.assertIn("L07", [f.code for f in c.parse("2026.md", bad).findings])

    def test_detail_without_event(self):
        t = year_with(2026, {D(2026, 3, 2): ["W10 2026-03-02 Mon  ", "                      - lost  "]})
        self.assertIn("L07", [f.code for f in c.parse("2026.md", t).findings])


class Notes(unittest.TestCase):
    def test_notes(self):
        t = c.skeleton_text(2026).replace(
            "## October\n\n",
            "## October\n\n> Goal: finish the calendar editor P1  \n"
            "> Sonoma trip budget is shared with Nate and Sam; settle up by\n"
            "> the end of the month  \n\n").replace(
            "# 2026\n\n", "# 2026\n\n> Year theme  \n\n")
        m = c.parse("2026.md", t)
        self.assertEqual(m.findings, [])
        self.assertEqual([n.text for n in m.month_notes[10]][1],
                         "Sonoma trip budget is shared with Nate and Sam; settle up by the end of the month")
        self.assertEqual(m.notes[0].text, "Year theme")
        self.assertEqual(c.format_text("2026.md", t)[0], t)

    def test_misplaced_note(self):
        t = c.skeleton_text(2026).replace("W10 2026-03-02 Mon  \n", "W10 2026-03-02 Mon  \n> x  \n")
        self.assertIn("L07", [f.code for f in c.parse("2026.md", t).findings])

    def test_rewrite_notes(self):
        t = c.skeleton_text(2026)
        m = c.parse("2026.md", t)
        t2 = c.rewrite_notes(t, m, 10, [c.Note("hello")])
        self.assertIn("## October\n\n> hello  \n\nW40", t2)
        m2 = c.parse("2026.md", t2)
        self.assertEqual(m2.findings, [])
        self.assertEqual(c.rewrite_notes(t2, m2, 10, []), t)


class Skeleton(unittest.TestCase):
    def test_matches_files(self):
        for y in (2026, 2027):
            m = c.parse("x.md", fixture("%d-before.md" % y))
            self.assertNotIn("L06", [f.code for f in m.findings])

    def test_53_week_year(self):
        t = c.skeleton_text(2026)
        self.assertIn("W53 2026-12-31 Thu  \n", t)
        self.assertIn("W53 2027-01-01 Fri  \n", c.skeleton_text(2027))

    def test_against_generator(self):
        """The generator page, docs/index.html, agrees for 1990-2100 (TOOLS.md 9)."""
        import json
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        with open(os.path.join(HERE, "..", "docs", "index.html"), encoding="utf-8") as f:
            page = f.read()
        script = page.split("<script>")[1].split("const $ =")[0]
        js = ("global.location = {search: '?format=iso'};\n" + script +
              "\nconst out = {};\nfor (let y = 1990; y <= 2100; y++) {"
              " const e = build(y); e.push({gap: true}, {url: SITE + '?year=' + y + '&format=iso'});"
              " out[y] = toMarkdown(e); }\nconsole.log(JSON.stringify(out));")
        res = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        got = json.loads(res.stdout)
        for y in range(1990, 2101):
            self.assertEqual(c.skeleton_text(y), got[str(y)], y)


class Annual(unittest.TestCase):
    TEXT = ("# Annual events\n\n## Birthdays\n\n"
            "02-29 🎂 Leap's Birthday  \n"
            "04-04 🎂 Sam's {nth:1990} Birthday  \n"
            "         - send a card a week ahead  \n"
            "10-10 🎂 Nate's Birthday  \n"
            "10-10 🎂 Riley's Birthday  \n"
            "\n## Anniversaries\n\n"
            "06-20 💍 Wedding anniversary, {n:2015} years  \n")

    def test_parse_clean(self):
        af = c.parse_annual(self.TEXT)
        self.assertEqual(af.findings, [])
        self.assertEqual(len(af.entries), 5)
        self.assertEqual(af.entries[1].details[0].text, "send a card a week ahead")
        self.assertEqual(c.render_annual(af), self.TEXT)

    def test_l10(self):
        for bad in ("02-30 🎂 x  \n", "01-01 a {nth:99} b  \n", "01-01 {n:2000} {nth:2001}  \n",
                    "01-01 🎂 x  \n01-01 🎂  x  \n"):
            af = c.parse_annual("# Annual events\n\n" + bad)
            self.assertIn("L10", [f.code for f in af.findings], bad)

    def test_ordinals(self):
        got = [c.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111, 112)]
        self.assertEqual(got, ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st",
                               "22nd", "23rd", "101st", "111th", "112th"])

    def test_events(self):
        af = c.parse_annual(self.TEXT)
        ev = {(d, e.text) for d, e in c.annual_events(af, 2026)}
        self.assertIn((D(2026, 2, 28), "🎂 Leap's Birthday (02-29)"), ev)
        self.assertIn((D(2026, 4, 4), "🎂 Sam's 36th Birthday"), ev)
        self.assertIn((D(2026, 6, 20), "💍 Wedding anniversary, 11 years"), ev)
        self.assertIn((D(2028, 2, 29), "🎂 Leap's Birthday"),
                      {(d, e.text) for d, e in c.annual_events(af, 2028)})
        texts = [e.text for _, e in c.annual_events(af, 2015)]
        self.assertFalse(any("anniversary" in t for t in texts))
        self.assertTrue(any("Sam's 25th" in t for t in texts))
        self.assertFalse(any("Sam" in t for _, e in c.annual_events(af, 1990) for t in [e.text]))

    def test_apply_idempotent(self):
        af = c.parse_annual(self.TEXT)
        t = year_with(2026, {D(2026, 10, 10): ["W41 2026-10-10 Sat ~~🎂 Nate's Birthday~~  ",
                                               "                   🛰️ Tour  "]})
        m = c.parse("2026.md", t)
        added = c.apply_annual(m, af)
        self.assertNotIn("🎂 Nate's Birthday", [x for _, x in added])     # struck counts
        t2 = c.rewrite_days(t, m, [d for d, _ in added])
        self.assertIn("W41 2026-10-10 Sat ~~🎂 Nate's Birthday~~  \n"
                      "                   🎂 Riley's Birthday  \n"
                      "                   🛰️ Tour  \n", t2)
        self.assertIn("W14 2026-04-04 Sat 🎂 Sam's 36th Birthday  \n"
                      "                      - send a card a week ahead  \n", t2)
        m2 = c.parse("2026.md", t2)
        self.assertEqual(m2.findings, [])
        self.assertEqual(c.apply_annual(m2, af), [])

    def test_new_year(self):
        af = c.parse_annual(self.TEXT)
        text, n = c.new_year(2028, af)
        self.assertEqual(n, 5)
        m = c.parse("2028.md", text)
        self.assertEqual(m.findings, [])
        self.assertEqual(sum(len(d.events) for d in m.days.values()), 5)
        stripped = [l[:18] + "  " if c.DAY_RE.match(l) else l
                    for l in text.split("\n") if not l.startswith(" ")]
        self.assertEqual("\n".join(stripped), c.skeleton_text(2028))

    def test_bootstrap(self):
        models = [c.parse("x.md", fixture("%d-before.md" % y)) for y in (2026, 2027)]
        af = c.parse_annual(c.bootstrap_annual(models))
        self.assertEqual(af.findings, [])
        self.assertEqual(len(af.entries), 18)
        m27 = models[1]
        added = c.apply_annual(m27, af)
        self.assertEqual(added, [(D(2027, 10, 24), "🎂 Sam's Birthday")])


class Holidays(unittest.TestCase):
    def test_resolve(self):
        cases = {
            ("11-4Thu", 2026): D(2026, 11, 26), ("11-4Thu", 2027): D(2027, 11, 25),
            ("05-LMon", 2026): D(2026, 5, 25), ("05-LMon", 2027): D(2027, 5, 31),
            ("01-3Mon", 2026): D(2026, 1, 19), ("09-1Mon", 2026): D(2026, 9, 7),
            ("05-2Sun", 2026): D(2026, 5, 10), ("06-3Sun", 2027): D(2027, 6, 20),
            ("Easter", 2024): D(2024, 3, 31), ("Easter", 2025): D(2025, 4, 20),
            ("Easter", 2026): D(2026, 4, 5), ("Easter", 2027): D(2027, 3, 28),
            ("Easter-2", 2026): D(2026, 4, 3), ("Easter+1", 2026): D(2026, 4, 6),
            ("02-29", 2027): D(2027, 2, 28),
            ("12-25-4Sun", 2026): D(2026, 11, 29), ("12-25-4Sun", 2027): D(2027, 11, 28),
            ("12-25-4Sun", 2022): D(2022, 11, 27),   # Christmas on a Sunday
            ("12-25-4Sun", 2023): D(2023, 12, 3),    # Christmas on a Monday
            ("12-25-1Sun", 2022): D(2022, 12, 18),   # strictly before
            ("11-01+1Tue", 2026): D(2026, 11, 3), ("11-01+1Tue", 2022): D(2022, 11, 8),
        }
        for (when, year), want in cases.items():
            self.assertEqual(c.resolve(when, year)[0], want, (when, year))

    def test_layout(self):
        t = ("# Annual events\n\n## Holidays\n\n"
             "11-4Thu 🦃 Thanksgiving dinner at Sam and Nate's this year,\n"
             "           bring pie  \n"
             "           - and the folding chairs  \n"
             "Easter 🐣 Easter  \n"
             "05-LMon 🇺🇸 Memorial Day  \n")
        af = c.parse_annual(t)
        self.assertEqual(af.findings, [])
        self.assertEqual([e.when for e in af.entries], ["11-4Thu", "Easter", "05-LMon"])
        self.assertEqual(c.render_annual(af), t)
        t2 = ("# Annual events\n\n12-25-4Sun 🕯️ First Sunday of Advent  \n"
              "              - light the first candle  \n")
        self.assertEqual(c.parse_annual(t2).findings, [])
        out = c.format_text("annual.md", t.replace("           - and", "         - and"))[0]
        self.assertEqual(out, t)

    def test_bad_dates(self):
        for when in ("13-1Mon", "00-LSun", "02-30", "02-29-1Sun", "04-31+2Fri"):
            af = c.parse_annual("# Annual events\n\n%s 🎉 x  \n" % when)
            self.assertEqual([f.code for f in af.findings], ["L10"], when)
        af = c.parse_annual("# Annual events\n\n11-5Thu 🎉 x  \n")
        self.assertEqual([f.code for f in af.findings], ["L07"])

    def test_apply(self):
        af = c.parse_annual("# Annual events\n\n11-4Thu 🦃 Thanksgiving  \n"
                            "Easter 🐣 Easter  \n")
        got = [(d, e.text) for d, e in c.annual_events(af, 2027)]
        self.assertEqual(got, [(D(2027, 11, 25), "🦃 Thanksgiving"), (D(2027, 3, 28), "🐣 Easter")])


class Tags(unittest.TestCase):
    def test_tags(self):
        self.assertEqual(c.tags("#birthdays"), ["birthdays"])
        self.assertEqual(c.tags("Dentist #Doctor and #day-trip"), ["doctor", "day-trip"])
        self.assertEqual(c.tags("https://x.com/#frag C# #a, #"), [])
        self.assertTrue(c.is_tag_line("#a #b"))
        self.assertFalse(c.is_tag_line("#a and b"))
        self.assertEqual(c.event_tags(c.Event("🦷 #doctor", [c.Detail("#doctor #health")])),
                         ["doctor", "health"])

    def test_similar(self):
        for a, b in [("birthday", "birthdays"), ("day-trip", "daytrip"), ("box", "boxes"),
                     ("birthdays", "birthdys"), ("birthdays", "brithdays")]:
            self.assertTrue(c.similar_tags(a, b), (a, b))
        for a, b in [("hikes", "bikes"), ("sumo", "sum"), ("doctor", "dentist"),
                     ("cycling", "cyclists")]:
            self.assertFalse(c.similar_tags(a, b), (a, b))

    def test_l12(self):
        m = c.parse("2027.md", c.skeleton_text(2027))
        m.days[D(2027, 3, 1)].events = [c.Event("🎂 A", [c.Detail("#birthdays")])]
        m.days[D(2027, 3, 2)].events = [c.Event("🎂 B", [c.Detail("#birthdays #family")])]
        m.days[D(2027, 3, 3)].events = [c.Event("🎂 C #birthday")]
        got = c.parse("2027.md", c.render_year(m)).findings
        self.assertEqual([(f.code, f.message) for f in got],
                         [("L12", "#birthday looks like a variant of #birthdays (used 2 times)")])
        self.assertEqual(got[0].line, c.render_year(m).split("\n").index(
            "W09 2027-03-03 Wed 🎂 C #birthday  ") + 1)
        af = c.parse_annual("# Annual events\n\n01-02 🎂 A  \n         - #holidays  \n"
                            "01-03 🎂 B  \n         - #holiday  \n")
        self.assertEqual([f.code for f in af.findings], ["L12"])

    def test_apply_adds_missing_tags(self):
        af = c.parse_annual("# Annual events\n\n10-10 🎂 Nate's Birthday  \n"
                            "         - #birthdays  \n10-24 🎂 Sam's Birthday  \n"
                            "         - #birthdays  \n")
        m = c.parse("2027.md", c.skeleton_text(2027))
        m.days[D(2027, 10, 10)].events = [c.Event("🎂 Nate's Birthday", [c.Detail("dinner")])]
        m.days[D(2027, 10, 24)].events = [c.Event("🎂 Sam's Birthday", [c.Detail("#birthdays")])]
        tagged = []
        self.assertEqual(c.apply_annual(m, af, tagged), [])
        self.assertEqual(tagged, [(D(2027, 10, 10), "🎂 Nate's Birthday")])
        self.assertEqual([d.text for d in m.days[D(2027, 10, 10)].events[0].details],
                         ["dinner", "#birthdays"])
        self.assertEqual(len(m.days[D(2027, 10, 24)].events[0].details), 1)
        again = []
        c.apply_annual(m, af, again)
        self.assertEqual(again, [])


class Ranges(unittest.TestCase):
    def model(self):
        return c.parse("2026.md", fixture("2026-before.md"))

    def test_find(self):
        rs = {(r["emoji"], r["start"], r["end"]) for r in c.find_ranges(self.model())}
        self.assertIn(("🤒", "2026-09-14", "2026-09-18"), rs)
        self.assertIn(("🏖️", "2026-10-24", "2026-11-01"), rs)
        self.assertIn(("⛺️", "2026-11-06", "2026-11-09"), rs)

    def test_resize_create_delete(self):
        m = self.model()
        changed = c.set_range_end(m, D(2026, 11, 6), "⛺️", D(2026, 11, 11))
        self.assertEqual(changed, [D(2026, 11, 10), D(2026, 11, 11)])
        self.assertEqual(c.range_end(m, D(2026, 11, 6), "⛺️"), D(2026, 11, 11))
        c.set_range_end(m, D(2026, 11, 6), "⛺️", D(2026, 11, 7))
        self.assertEqual(c.range_end(m, D(2026, 11, 6), "⛺️"), D(2026, 11, 7))
        c.create_range(m, D(2026, 12, 1), D(2026, 12, 3), "🏔️", "Tahoe")
        self.assertEqual(m.days[D(2026, 12, 1)].events[-1].text, "🏔️ Tahoe")
        self.assertEqual(m.days[D(2026, 12, 3)].events[-1].text, "🏔️")
        c.delete_range(m, D(2026, 12, 1), "🏔️", 0)
        self.assertEqual([m.days[D(2026, 12, k)].events for k in (1, 2, 3)], [[], [], []])

    def test_title_required(self):
        with self.assertRaises(ValueError):
            c.create_range(self.model(), D(2026, 12, 1), D(2026, 12, 3), "🏔️", " ")

    def test_struck_head(self):
        m = self.model()
        c.create_range(m, D(2026, 12, 1), D(2026, 12, 3), "🏔️", "Tahoe")
        m.days[D(2026, 12, 1)].events[-1].text = "~~🏔️ Tahoe~~"
        self.assertIn(("🏔️", "2026-12-01", "2026-12-03"),
                      {(r["emoji"], r["start"], r["end"]) for r in c.find_ranges(m)})
        c.delete_range(m, D(2026, 12, 1), "🏔️", 0)
        self.assertEqual([m.days[D(2026, 12, k)].events for k in (1, 2, 3)], [[], [], []])


class Rewrite(unittest.TestCase):
    def test_only_the_day_changes(self):
        t = fixture("2026-before.md")
        m = c.parse("2026.md", t)
        d = D(2026, 10, 15)
        m.days[d].events = [c.Event("🦷 Dentist @ 10", [c.Detail("Dr. Lee")])]
        t2 = c.rewrite_days(t, m, [d])
        a, b = t.split("\n"), t2.split("\n")
        self.assertEqual(b[:364], a[:364])
        self.assertEqual(b[366:], a[365:])
        self.assertEqual(b[364:366], ["W42 2026-10-15 Thu 🦷 Dentist @ 10  ",
                                      "                      - Dr. Lee  "])


if __name__ == "__main__":
    unittest.main()
