"""The lint-on-push job (TOOLS.md 8.3).

Fixes safe findings with a follow-up commit, then reports what is left in
an issue titled "Calendar lint findings" and fails if anything is left.
Run from the repository root by .github/workflows/lint.yml.
"""

import json
import os
import subprocess
import sys

from . import callib
from .calfmt import data_files, read, write

ISSUE = "Calendar lint findings"


def git(*args, check=True):
    return subprocess.run(["git"] + list(args), check=check, capture_output=True, text=True)


def fix_all():
    """Formats every data file that has safe findings. Returns commit lines."""
    done = []
    for name in data_files():
        text = read(name)
        out, findings = callib.format_text(name, text)
        if out is None or out == text:
            continue
        write(name, out)
        n = sum(1 for f in findings if f.code in callib.SAFE)
        done.append("%d finding%s in %s" % (n, "" if n == 1 else "s", name))
    return done


def remaining():
    left = []
    for name in data_files():
        model = callib.parse(name, read(name))
        for f in model.findings:
            if not model.ok or f.code not in callib.SAFE:
                left.append("%s:%s" % (name, f))
    return left


def gh(*args):
    return subprocess.run(["gh"] + list(args), check=True, capture_output=True, text=True).stdout


def update_issue(left):
    found = json.loads(gh("issue", "list", "--state", "open", "--search",
                          'in:title "%s"' % ISSUE, "--json", "number,title"))
    number = next((i["number"] for i in found if i["title"] == ISSUE), None)
    if left:
        body = ("`calfmt` found problems it does not fix by itself. Fix them by hand "
                "(see TOOLS.md section 5 in jgarofoli/calendar); this issue closes when the files are clean.\n\n"
                + "\n".join("- `%s`" % l for l in left))
        if number:
            gh("issue", "edit", str(number), "--body", body)
        else:
            gh("issue", "create", "--title", ISSUE, "--body", body)
    elif number:
        gh("issue", "close", str(number), "--comment", "All calendar files are lint-clean.")


def main():
    for attempt in range(3):
        done = fix_all()
        if not done:
            break
        git("add", "--", *data_files())
        git("commit", "-m", "calfmt: fix " + ", ".join(done))
        if git("push", "origin", "HEAD:main", check=False).returncode == 0:
            print("pushed: calfmt: fix " + ", ".join(done))
            break
        print("push rejected; starting again from the new head", file=sys.stderr)
        git("fetch", "origin", "main")
        git("reset", "--hard", "origin/main")
    else:
        sys.exit("gave up after three rejected pushes")
    left = remaining()
    for l in left:
        print(l)
    if os.environ.get("GH_TOKEN"):
        update_issue(left)
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
