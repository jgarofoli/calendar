"""calfmt: lint and format calendar files (TOOLS.md 2.1).

    calfmt --check [FILE...]      lint; exit 1 on errors
    calfmt --write [FILE...]      format in place
    calfmt --diff  [FILE...]      show what --write would change
    calfmt new YEAR [--write]     a new year file with annual events (6.2)
    calfmt annual --apply YEAR [--write]   add missing annual events (6.3)
    calfmt annual --bootstrap [--write]    build annual.md from 🎂 events (6.4)

With no FILE, every data file in the current directory is used:
<four digits>.md and annual.md. Other Markdown files are never touched.
"""

import argparse
import os
import sys

from . import callib


def data_files(directory="."):
    return sorted(f for f in os.listdir(directory) if callib.is_data_file(f))


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def check_names(files):
    for f in files:
        if not callib.is_data_file(os.path.basename(f)):
            sys.exit("calfmt: %s is not a data file (<year>.md or annual.md)" % f)


def lint_main(args):
    files = args.files or data_files()
    check_names(files)
    status = 0
    for path in files:
        text = read(path)
        out, findings = callib.format_text(path, text)
        if args.check or (not args.write and not args.diff):
            for f in findings:
                print("%s:%s" % (path, f))
            if any(f.severity == "error" for f in findings):
                status = 1
            continue
        if out is None:
            for f in findings:
                print("%s:%s" % (path, f))
            print("%s: unfixable errors; file left unchanged" % path, file=sys.stderr)
            status = 1
            continue
        if args.diff:
            sys.stdout.write(callib.unified_diff(path, text, out))
        elif out != text:
            write(path, out)
            fixed = sum(1 for f in findings if f.code in callib.SAFE)
            print("%s: fixed %d finding%s" % (path, fixed, "" if fixed == 1 else "s"))
        for f in findings:
            if f.code not in callib.SAFE:
                print("%s:%s" % (path, f))
    return status


def new_main(args):
    path = "%d.md" % args.year
    if os.path.exists(path):
        sys.exit("calfmt: %s already exists" % path)
    af = load_annual()
    text, n = callib.new_year(args.year, af)
    if args.write:
        write(path, text)
        print("%s: new year with %d annual events" % (path, n))
    else:
        sys.stdout.write(text)
    return 0


def load_annual(required=False):
    if not os.path.exists("annual.md"):
        if required:
            sys.exit("calfmt: annual.md not found")
        return None
    af = callib.parse_annual(read("annual.md"))
    if not af.ok:
        for f in af.findings:
            print("annual.md:%s" % f)
        sys.exit("calfmt: annual.md has unfixable errors")
    return af


def annual_main(args):
    if args.bootstrap:
        if os.path.exists("annual.md") and args.write:
            sys.exit("calfmt: annual.md already exists")
        models = [callib.parse_year(read(f)) for f in data_files() if f != "annual.md"]
        text = callib.bootstrap_annual(models)
        if args.write:
            write("annual.md", text)
            print("annual.md: %d entries" % len(callib.parse_annual(text).entries))
        else:
            sys.stdout.write(text)
        return 0
    af = load_annual(required=True)
    path = "%d.md" % args.apply
    text = read(path)
    model = callib.parse_year(text)
    if not model.ok:
        for f in model.findings:
            print("%s:%s" % (path, f))
        sys.exit("calfmt: %s has unfixable errors" % path)
    tagged = []
    added = callib.apply_annual(model, af, tagged)
    out = callib.rewrite_days(text, model, [d for d, _ in added + tagged])
    if args.write:
        write(path, out)
        print("%s: added %d annual event%s, tagged %d" % (path, len(added),
                                                         "" if len(added) == 1 else "s", len(tagged)))
    else:
        sys.stdout.write(callib.unified_diff(path, text, out))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "new":
        p = argparse.ArgumentParser(prog="calfmt new")
        p.add_argument("year", type=int)
        p.add_argument("--write", action="store_true", help="create <year>.md")
        return new_main(p.parse_args(argv[1:]))
    if argv and argv[0] == "annual":
        p = argparse.ArgumentParser(prog="calfmt annual")
        g = p.add_mutually_exclusive_group(required=True)
        g.add_argument("--apply", type=int, metavar="YEAR")
        g.add_argument("--bootstrap", action="store_true")
        p.add_argument("--write", action="store_true", help="change files (default: preview)")
        return annual_main(p.parse_args(argv[1:]))
    p = argparse.ArgumentParser(prog="calfmt", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="lint (default)")
    g.add_argument("--write", action="store_true", help="format in place")
    g.add_argument("--diff", action="store_true", help="preview --write")
    p.add_argument("files", nargs="*")
    return lint_main(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
