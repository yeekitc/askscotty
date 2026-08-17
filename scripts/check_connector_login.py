#!/usr/bin/env python3
"""Phase 0's one check that cannot be a test: does a real login actually work?

docs/b5-piazza-gradescope.md builds on two unofficial libraries that sign in
with a student's real email and password. Every call shape they use was
confirmed by reading the installed packages, but three things need an account:

  1. **2FA.** Neither library's docs mention it. If CMU routes Piazza or
     Gradescope through Andrew SSO / Duo, an automated `login()` hangs or fails
     at that step rather than quietly succeeding — and a connector that stalls
     mid-demo is worse than one that was never built.
  2. **The Piazza search response body.** `search_feed()`'s call shape is
     confirmed; what it returns is not. `apps/personal/tools.py:_feed_items`
     tolerates both documented shapes and degrades to no results on a third,
     so this reports which one really arrives.
  3. **The class URL.** Citations link to `piazza.com/class/{network_id}`,
     which is the form piazza-api's own docstring documents. This prints one so
     it can be opened once and confirmed.

Run it on your own machine, against your own account:

    python3 scripts/check_connector_login.py            # both
    python3 scripts/check_connector_login.py piazza     # one

The password is read with `getpass`, so it is never echoed, never a command
argument, and never in shell history. Nothing here writes to disk, and the
output below is deliberately safe to paste back into a chat: it prints counts,
types and verdicts — never a credential, a post body, a grade, or a classmate's
name.
"""

from __future__ import annotations

import getpass
import sys
import traceback

_OK = "  ok      "
_FAIL = "  FAILED  "
_INFO = "          "


def _prompt(service: str) -> tuple[str, str]:
    print(f"\n--- {service} ---")
    email = input("  email: ").strip()
    password = getpass.getpass("  password (not echoed): ")
    return email, password


def _report_failure(exc: BaseException) -> None:
    """Type and module only.

    A login failure's message is assembled from the sign-in page, which is one
    of the few places a submitted field can come back — the same reason
    apps/personal/tools.py raises `from None`.
    """
    print(f"{_FAIL}{type(exc).__module__}.{type(exc).__name__}")
    print(f"{_INFO}(message withheld — it can echo the login form)")


def check_piazza() -> bool:
    from piazza_api import Piazza

    email, password = _prompt("Piazza")

    piazza = Piazza()
    try:
        piazza.user_login(email=email, password=password)
    except Exception as exc:
        _report_failure(exc)
        print(f"{_INFO}If this hung before failing, suspect a 2FA/SSO redirect.")
        return False
    print(f"{_OK}logged in without an interactive prompt or a 2FA step")

    try:
        classes = piazza.get_user_classes()
    except Exception as exc:
        _report_failure(exc)
        return False
    print(f"{_OK}get_user_classes() returned {len(classes)} class(es)")

    if not classes:
        print(f"{_INFO}No classes on this account — cannot check search or the URL.")
        return True

    network_id = classes[0].get("nid")
    print(f"{_OK}citation URL to open once and confirm:")
    print(f"{_INFO}https://piazza.com/class/{network_id}")

    try:
        payload = piazza.network(network_id).search_feed("exam")
    except Exception as exc:
        _report_failure(exc)
        return False

    # The one genuinely unverified thing in the Piazza tool.
    if isinstance(payload, list):
        shape, count = "a bare list", len(payload)
    elif isinstance(payload, dict) and isinstance(payload.get("feed"), list):
        shape, count = "a dict with 'feed'", len(payload["feed"])
    elif isinstance(payload, dict):
        shape, count = f"a dict with keys {sorted(payload)[:8]}", 0
    else:
        shape, count = f"a bare {type(payload).__name__}", 0

    print(f"{_OK}search_feed() returned {shape}, {count} item(s)")
    if "list" not in shape and "feed" not in shape:
        print(f"{_INFO}NOT a shape _feed_items() handles — searches will come back empty.")
        return False

    first = (payload if isinstance(payload, list) else payload["feed"])[:1]
    if first and isinstance(first[0], dict):
        keys = sorted(first[0])
        snippet_key = next((k for k in keys if k.startswith("content_snip")), None)
        print(f"{_OK}post snippet key is {snippet_key!r} (tool reads either spelling)")
        # Key names only. A post body is a classmate's writing.
        print(f"{_INFO}post keys: {', '.join(keys[:12])}")

    return True


def check_gradescope() -> bool:
    from gradescopeapi.classes.connection import GSConnection

    email, password = _prompt("Gradescope")

    connection = GSConnection()
    try:
        connection.login(email, password)
    except Exception as exc:
        _report_failure(exc)
        print(f"{_INFO}If this hung before failing, suspect a 2FA/SSO redirect.")
        return False
    print(f"{_OK}logged in without an interactive prompt or a 2FA step")

    try:
        courses = connection.account.get_courses()
    except Exception as exc:
        _report_failure(exc)
        return False

    student = courses.get("student", {})
    print(f"{_OK}get_courses() gave roles {sorted(courses)}, {len(student)} as student")

    if not student:
        print(f"{_INFO}No student courses — cannot check assignments.")
        return True

    course_id = next(iter(student))
    try:
        assignments = connection.account.get_assignments(course_id)
    except Exception as exc:
        _report_failure(exc)
        return False

    print(f"{_OK}get_assignments() returned {len(assignments)} assignment(s)")
    if assignments:
        # Field names, not values: an assignment carries a grade.
        fields = sorted(vars(assignments[0]))
        print(f"{_INFO}assignment fields: {', '.join(fields)}")
        expected = {"assignment_id", "name", "due_date", "submissions_status"}
        missing = expected - set(fields)
        if missing:
            print(f"{_FAIL}the tool reads fields this version does not have: {missing}")
            return False
        print(f"{_OK}every field apps/personal/tools.py reads is present")

    return True


CHECKS = {"piazza": check_piazza, "gradescope": check_gradescope}


def main() -> int:
    wanted = [name.lower() for name in sys.argv[1:]] or list(CHECKS)

    unknown = [name for name in wanted if name not in CHECKS]
    if unknown:
        print(f"Unknown: {', '.join(unknown)}. Choose from: {', '.join(CHECKS)}")
        return 2

    print(__doc__.split("Run it on")[0].strip())

    results = {}
    for name in wanted:
        try:
            results[name] = CHECKS[name]()
        except ImportError as exc:
            print(f"{_FAIL}{exc}")
            print(f"{_INFO}pip install piazza-api gradescopeapi")
            results[name] = False
        except KeyboardInterrupt:
            print("\n  cancelled")
            return 130
        except Exception:
            # A bug in this script, not a failed login — that path is handled
            # above and never prints a message.
            print(f"{_FAIL}unexpected error in the check itself:")
            traceback.print_exc()
            results[name] = False

    print("\n--- verdict ---")
    for name, passed in results.items():
        print(f"  {name:12} {'PASS' if passed else 'FAIL'}")
    print("\nSafe to paste this output back — it contains no credential.")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
