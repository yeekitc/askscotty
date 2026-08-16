"""Authoritative crawl seed list, matching PRD Appendix B and §4.

Each tuple is (url, label). Labels identify seeds in `manage.py crawl --seed=<label>`.
"""

SEEDS: list[tuple[str, str]] = [
    # ── CMU main public web ───────────────────────────────────────────────────
    ("https://www.cmu.edu/", "cmu-main"),
    ("https://www.cmu.edu/about/", "cmu-about"),
    ("https://www.cmu.edu/hub/", "cmu-hub"),
    ("https://www.cmu.edu/academics/", "cmu-academics"),
    ("https://www.cmu.edu/student-affairs/", "cmu-student-affairs"),
    ("https://www.cmu.edu/housing/", "cmu-housing"),
    ("https://www.cmu.edu/dining/", "cmu-dining"),
    ("https://www.cmu.edu/health-services/", "cmu-health"),
    ("https://www.cmu.edu/career/", "cmu-career"),
    ("https://www.cmu.edu/news/", "cmu-news"),
    ("https://admission.enrollment.cmu.edu/", "cmu-admissions"),
    # ── Colleges (PRD §4 "Should") ────────────────────────────────────────────
    ("https://scs.cmu.edu/", "scs"),
    ("https://www.cit.cmu.edu/", "cit"),
    ("https://www.cmu.edu/dietrich/", "dietrich"),
    ("https://www.tepper.cmu.edu/", "tepper"),
    ("https://www.cfa.cmu.edu/", "cfa"),
    ("https://www.cmu.edu/mcs/", "mcs"),
    ("https://www.heinz.cmu.edu/", "heinz"),
    # ── Key service sites (PRD §4 "Must") ────────────────────────────────────
    ("https://coursecatalog.cmu.edu/", "course-catalog"),
    ("https://computing.cmu.edu/", "computing"),
    ("https://library.cmu.edu/", "library"),
    # ── Student guide ─────────────────────────────────────────────────────────
    ("https://cmu.guide/", "cmu-guide"),
    # ── Student orgs directory (PRD §4 "Should"; event listing pages excluded
    #    by depth cap — they change hourly) ────────────────────────────────────
    ("https://studentorgs.cmu.edu/", "student-orgs"),
    # ── Seeded SCS course sites (PRD Appendix B) ─────────────────────────────
    ("https://www.cs.cmu.edu/~15210/", "course-15210"),
    ("https://www.cs.cmu.edu/~213/", "course-15213"),
    ("https://www.cs.cmu.edu/~15150/", "course-15150"),
    ("https://www.cs.cmu.edu/~15122/", "course-15122"),
    ("https://www.cs.cmu.edu/~15251/", "course-15251"),
    ("https://www.cs.cmu.edu/~15451/", "course-15451"),
    ("https://www.cs.cmu.edu/~mgormley/courses/10601/", "course-10601"),
    ("https://deeplearning.cs.cmu.edu/", "course-deeplearning"),
    ("https://cmu-313.github.io/", "course-17313"),
    ("https://15445.courses.cs.cmu.edu/", "course-15445"),
]
