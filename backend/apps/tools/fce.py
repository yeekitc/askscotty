"""FCE ratings tool — mock fixture.

The real Faculty Course Evaluations are behind an Andrew SSO wall; we do not
scrape them (PRD §10). This module supplies mock records for ~25 courses
(SCS core, popular electives, CIT/ECE) across multiple recent semesters.

Every result carries is_mock=True (PRD §9).
"""

from __future__ import annotations

from apps.tools.registry import ToolError, register_tool

# fields: course_id, course_name, semester, instructor,
#         workload_hours (hrs/week), overall_rating (1-5),
#         instructor_rating (1-5), response_count
_FCE: list[dict] = [
    # 15-122 Principles of Imperative Computation
    {"course_id": "15-122", "course_name": "Principles of Imperative Computation", "semester": "F2024", "instructor": "Iliano Cervesato", "workload_hours": 9.2, "overall_rating": 3.8, "instructor_rating": 4.1, "response_count": 210},
    {"course_id": "15-122", "course_name": "Principles of Imperative Computation", "semester": "S2024", "instructor": "Dilsun Kaynar", "workload_hours": 8.7, "overall_rating": 3.9, "instructor_rating": 4.3, "response_count": 195},
    {"course_id": "15-122", "course_name": "Principles of Imperative Computation", "semester": "F2023", "instructor": "Iliano Cervesato", "workload_hours": 9.4, "overall_rating": 3.7, "instructor_rating": 4.0, "response_count": 202},
    # 15-150 Principles of Functional Programming
    {"course_id": "15-150", "course_name": "Principles of Functional Programming", "semester": "F2024", "instructor": "Robert Harper", "workload_hours": 10.5, "overall_rating": 4.0, "instructor_rating": 4.5, "response_count": 140},
    {"course_id": "15-150", "course_name": "Principles of Functional Programming", "semester": "S2024", "instructor": "Stefan Muller", "workload_hours": 9.8, "overall_rating": 3.9, "instructor_rating": 4.2, "response_count": 130},
    {"course_id": "15-150", "course_name": "Principles of Functional Programming", "semester": "F2023", "instructor": "Robert Harper", "workload_hours": 10.8, "overall_rating": 4.1, "instructor_rating": 4.6, "response_count": 135},
    # 15-210 Parallel and Sequential Data Structures and Algorithms
    {"course_id": "15-210", "course_name": "Parallel and Sequential Data Structures and Algorithms", "semester": "F2024", "instructor": "Guy Blelloch", "workload_hours": 12.3, "overall_rating": 4.0, "instructor_rating": 4.4, "response_count": 165},
    {"course_id": "15-210", "course_name": "Parallel and Sequential Data Structures and Algorithms", "semester": "S2024", "instructor": "Umut Acar", "workload_hours": 11.9, "overall_rating": 3.9, "instructor_rating": 4.2, "response_count": 155},
    # 15-213 Introduction to Computer Systems
    {"course_id": "15-213", "course_name": "Introduction to Computer Systems", "semester": "F2024", "instructor": "Brandon Lucia", "workload_hours": 16.2, "overall_rating": 4.1, "instructor_rating": 4.2, "response_count": 285},
    {"course_id": "15-213", "course_name": "Introduction to Computer Systems", "semester": "S2024", "instructor": "Seth Goldstein", "workload_hours": 15.8, "overall_rating": 4.0, "instructor_rating": 4.1, "response_count": 270},
    {"course_id": "15-213", "course_name": "Introduction to Computer Systems", "semester": "F2023", "instructor": "Brandon Lucia", "workload_hours": 16.5, "overall_rating": 4.0, "instructor_rating": 4.1, "response_count": 278},
    # 15-251 Great Ideas in Theoretical Computer Science
    {"course_id": "15-251", "course_name": "Great Ideas in Theoretical Computer Science", "semester": "F2024", "instructor": "Venkatesan Guruswami", "workload_hours": 13.1, "overall_rating": 4.2, "instructor_rating": 4.5, "response_count": 220},
    {"course_id": "15-251", "course_name": "Great Ideas in Theoretical Computer Science", "semester": "S2024", "instructor": "Anil Ada", "workload_hours": 12.7, "overall_rating": 4.1, "instructor_rating": 4.4, "response_count": 210},
    {"course_id": "15-251", "course_name": "Great Ideas in Theoretical Computer Science", "semester": "F2023", "instructor": "Venkatesan Guruswami", "workload_hours": 13.4, "overall_rating": 4.2, "instructor_rating": 4.5, "response_count": 215},
    # 15-295 Competition Programming and Problem Solving
    {"course_id": "15-295", "course_name": "Competition Programming and Problem Solving", "semester": "F2024", "instructor": "Danny Sleator", "workload_hours": 8.0, "overall_rating": 4.5, "instructor_rating": 4.6, "response_count": 45},
    {"course_id": "15-295", "course_name": "Competition Programming and Problem Solving", "semester": "S2024", "instructor": "Danny Sleator", "workload_hours": 7.8, "overall_rating": 4.6, "instructor_rating": 4.7, "response_count": 40},
    # 15-410 Operating System Design and Implementation
    {"course_id": "15-410", "course_name": "Operating System Design and Implementation", "semester": "F2024", "instructor": "Dave Eckhardt", "workload_hours": 20.1, "overall_rating": 4.4, "instructor_rating": 4.7, "response_count": 90},
    {"course_id": "15-410", "course_name": "Operating System Design and Implementation", "semester": "S2024", "instructor": "Dave Eckhardt", "workload_hours": 19.8, "overall_rating": 4.3, "instructor_rating": 4.6, "response_count": 85},
    {"course_id": "15-410", "course_name": "Operating System Design and Implementation", "semester": "F2023", "instructor": "Dave Eckhardt", "workload_hours": 20.5, "overall_rating": 4.4, "instructor_rating": 4.7, "response_count": 88},
    # 15-451 Algorithm Design and Analysis
    {"course_id": "15-451", "course_name": "Algorithm Design and Analysis", "semester": "F2024", "instructor": "David Woodruff", "workload_hours": 14.3, "overall_rating": 3.9, "instructor_rating": 4.1, "response_count": 175},
    {"course_id": "15-451", "course_name": "Algorithm Design and Analysis", "semester": "S2024", "instructor": "Anupam Gupta", "workload_hours": 13.8, "overall_rating": 4.1, "instructor_rating": 4.4, "response_count": 168},
    {"course_id": "15-451", "course_name": "Algorithm Design and Analysis", "semester": "F2023", "instructor": "David Woodruff", "workload_hours": 14.7, "overall_rating": 3.8, "instructor_rating": 4.0, "response_count": 171},
    # 15-418 Parallel Computer Architecture and Programming
    {"course_id": "15-418", "course_name": "Parallel Computer Architecture and Programming", "semester": "S2025", "instructor": "Kayvon Fatahalian", "workload_hours": 15.5, "overall_rating": 4.5, "instructor_rating": 4.8, "response_count": 110},
    {"course_id": "15-418", "course_name": "Parallel Computer Architecture and Programming", "semester": "S2024", "instructor": "Kayvon Fatahalian", "workload_hours": 15.2, "overall_rating": 4.5, "instructor_rating": 4.7, "response_count": 105},
    # 15-440 Distributed Systems
    {"course_id": "15-440", "course_name": "Distributed Systems", "semester": "F2024", "instructor": "Srini Seshan", "workload_hours": 13.6, "overall_rating": 4.0, "instructor_rating": 4.2, "response_count": 130},
    {"course_id": "15-440", "course_name": "Distributed Systems", "semester": "S2024", "instructor": "Peter Steenkiste", "workload_hours": 13.1, "overall_rating": 3.9, "instructor_rating": 4.1, "response_count": 122},
    # 15-462 Computer Graphics
    {"course_id": "15-462", "course_name": "Computer Graphics", "semester": "F2024", "instructor": "Keenan Crane", "workload_hours": 14.8, "overall_rating": 4.6, "instructor_rating": 4.9, "response_count": 95},
    {"course_id": "15-462", "course_name": "Computer Graphics", "semester": "F2023", "instructor": "Keenan Crane", "workload_hours": 14.5, "overall_rating": 4.6, "instructor_rating": 4.9, "response_count": 90},
    # 10-301 Introduction to Machine Learning
    {"course_id": "10-301", "course_name": "Introduction to Machine Learning", "semester": "F2024", "instructor": "Matt Gormley", "workload_hours": 11.4, "overall_rating": 4.1, "instructor_rating": 4.4, "response_count": 310},
    {"course_id": "10-301", "course_name": "Introduction to Machine Learning", "semester": "S2024", "instructor": "Ameet Talwalkar", "workload_hours": 10.9, "overall_rating": 4.0, "instructor_rating": 4.2, "response_count": 290},
    {"course_id": "10-301", "course_name": "Introduction to Machine Learning", "semester": "F2023", "instructor": "Matt Gormley", "workload_hours": 11.7, "overall_rating": 4.1, "instructor_rating": 4.3, "response_count": 305},
    # 10-315 Introduction to Machine Learning (SCS)
    {"course_id": "10-315", "course_name": "Introduction to Machine Learning (SCS)", "semester": "F2024", "instructor": "Zico Kolter", "workload_hours": 12.2, "overall_rating": 4.2, "instructor_rating": 4.5, "response_count": 185},
    {"course_id": "10-315", "course_name": "Introduction to Machine Learning (SCS)", "semester": "F2023", "instructor": "Zico Kolter", "workload_hours": 12.5, "overall_rating": 4.1, "instructor_rating": 4.4, "response_count": 178},
    # 11-711 Advanced NLP
    {"course_id": "11-711", "course_name": "Advanced NLP", "semester": "F2024", "instructor": "Graham Neubig", "workload_hours": 14.0, "overall_rating": 4.3, "instructor_rating": 4.6, "response_count": 80},
    {"course_id": "11-711", "course_name": "Advanced NLP", "semester": "F2023", "instructor": "Graham Neubig", "workload_hours": 13.8, "overall_rating": 4.3, "instructor_rating": 4.5, "response_count": 75},
    # 11-785 Introduction to Deep Learning
    {"course_id": "11-785", "course_name": "Introduction to Deep Learning", "semester": "F2024", "instructor": "Bhiksha Raj", "workload_hours": 16.8, "overall_rating": 4.0, "instructor_rating": 4.2, "response_count": 240},
    {"course_id": "11-785", "course_name": "Introduction to Deep Learning", "semester": "S2024", "instructor": "Bhiksha Raj", "workload_hours": 16.2, "overall_rating": 4.0, "instructor_rating": 4.1, "response_count": 225},
    {"course_id": "11-785", "course_name": "Introduction to Deep Learning", "semester": "F2023", "instructor": "Bhiksha Raj", "workload_hours": 17.1, "overall_rating": 3.9, "instructor_rating": 4.1, "response_count": 235},
    # 18-213 Introduction to Computer Systems (ECE)
    {"course_id": "18-213", "course_name": "Introduction to Computer Systems (ECE)", "semester": "F2024", "instructor": "Ken Mai", "workload_hours": 15.0, "overall_rating": 3.9, "instructor_rating": 4.0, "response_count": 160},
    {"course_id": "18-213", "course_name": "Introduction to Computer Systems (ECE)", "semester": "F2023", "instructor": "Ken Mai", "workload_hours": 15.3, "overall_rating": 3.8, "instructor_rating": 3.9, "response_count": 155},
    # 18-240 Structure and Design of Digital Systems
    {"course_id": "18-240", "course_name": "Structure and Design of Digital Systems", "semester": "F2024", "instructor": "Larry Pileggi", "workload_hours": 11.5, "overall_rating": 3.7, "instructor_rating": 3.9, "response_count": 145},
    {"course_id": "18-240", "course_name": "Structure and Design of Digital Systems", "semester": "F2023", "instructor": "Larry Pileggi", "workload_hours": 11.8, "overall_rating": 3.6, "instructor_rating": 3.8, "response_count": 140},
    # 18-290 Signals and Systems
    {"course_id": "18-290", "course_name": "Signals and Systems", "semester": "S2025", "instructor": "Yuejie Chi", "workload_hours": 9.8, "overall_rating": 3.8, "instructor_rating": 4.1, "response_count": 135},
    {"course_id": "18-290", "course_name": "Signals and Systems", "semester": "S2024", "instructor": "Yuejie Chi", "workload_hours": 9.5, "overall_rating": 3.9, "instructor_rating": 4.2, "response_count": 130},
    # 18-447 Introduction to Computer Architecture
    {"course_id": "18-447", "course_name": "Introduction to Computer Architecture", "semester": "S2025", "instructor": "James Hoe", "workload_hours": 13.2, "overall_rating": 4.0, "instructor_rating": 4.3, "response_count": 105},
    {"course_id": "18-447", "course_name": "Introduction to Computer Architecture", "semester": "S2024", "instructor": "James Hoe", "workload_hours": 12.9, "overall_rating": 3.9, "instructor_rating": 4.2, "response_count": 100},
    # 36-226 Introduction to Statistical Inference
    {"course_id": "36-226", "course_name": "Introduction to Statistical Inference", "semester": "F2024", "instructor": "Peter Freeman", "workload_hours": 7.2, "overall_rating": 3.6, "instructor_rating": 3.8, "response_count": 170},
    {"course_id": "36-226", "course_name": "Introduction to Statistical Inference", "semester": "F2023", "instructor": "Mikael Kuusela", "workload_hours": 7.5, "overall_rating": 3.7, "instructor_rating": 4.0, "response_count": 165},
    # 36-315 Statistical Graphics and Visualization
    {"course_id": "36-315", "course_name": "Statistical Graphics and Visualization", "semester": "S2025", "instructor": "Ron Yurko", "workload_hours": 6.5, "overall_rating": 4.2, "instructor_rating": 4.5, "response_count": 90},
    {"course_id": "36-315", "course_name": "Statistical Graphics and Visualization", "semester": "S2024", "instructor": "Ron Yurko", "workload_hours": 6.3, "overall_rating": 4.3, "instructor_rating": 4.6, "response_count": 85},
    # 21-241 Matrices and Linear Transformations
    {"course_id": "21-241", "course_name": "Matrices and Linear Transformations", "semester": "F2024", "instructor": "John Mackey", "workload_hours": 7.8, "overall_rating": 3.8, "instructor_rating": 4.1, "response_count": 250},
    {"course_id": "21-241", "course_name": "Matrices and Linear Transformations", "semester": "S2024", "instructor": "Irina Gheorghiciuc", "workload_hours": 7.4, "overall_rating": 3.7, "instructor_rating": 4.0, "response_count": 240},
    # 21-259 Calculus in Three Dimensions
    {"course_id": "21-259", "course_name": "Calculus in Three Dimensions", "semester": "F2024", "instructor": "Clive Newstead", "workload_hours": 8.1, "overall_rating": 3.9, "instructor_rating": 4.2, "response_count": 280},
    {"course_id": "21-259", "course_name": "Calculus in Three Dimensions", "semester": "S2024", "instructor": "Clive Newstead", "workload_hours": 7.9, "overall_rating": 4.0, "instructor_rating": 4.3, "response_count": 265},
]

# Semester ordering: most-recent first. Later years first; within a year, Fall after Spring.
_SEMESTER_KEY: dict[str, int] = {}
for _i, _sem in enumerate(["S2025", "F2024", "S2024", "F2023", "S2023"]):
    _SEMESTER_KEY[_sem] = _i


def _sem_sort_key(record: dict) -> int:
    return _SEMESTER_KEY.get(record["semester"], 999)


def _normalize_course_id(raw: str) -> str:
    """Accept '15213' or '15-213' and return '15-213'."""
    raw = raw.strip()
    if "-" not in raw and len(raw) >= 5:
        return raw[:-3] + "-" + raw[-3:]
    return raw


@register_tool(
    name="get_fce_ratings",
    description=(
        "Look up FCE (Faculty Course Evaluation) ratings for CMU courses. "
        "Returns workload hours, overall course rating, and instructor rating. "
        "Coverage: SCS core courses, popular electives, and CIT/ECE courses. "
        "Data is a mock fixture — the real FCE portal requires an Andrew login. "
        "At least one of course_id, course_name, or instructor must be provided."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "course_id": {
                "type": "string",
                "description": "Course number, e.g. '15-213' or '15213'.",
            },
            "course_name": {
                "type": "string",
                "description": "Partial course name match, e.g. 'Operating System'.",
            },
            "instructor": {
                "type": "string",
                "description": "Partial instructor last name match, e.g. 'Crane'.",
            },
        },
        "required": [],
    },
    mode="fce",
    is_mock=True,
)
def get_fce_ratings(
    course_id: str | None = None,
    course_name: str | None = None,
    instructor: str | None = None,
) -> dict:
    if course_id is None and course_name is None and instructor is None:
        raise ToolError(
            "At least one of course_id, course_name, or instructor must be provided."
        )

    matches = list(_FCE)

    if course_id is not None:
        norm = _normalize_course_id(course_id).lower()
        matches = [r for r in matches if r["course_id"].lower() == norm]

    if course_name is not None:
        q = course_name.lower()
        matches = [r for r in matches if q in r["course_name"].lower()]

    if instructor is not None:
        q = instructor.lower()
        matches = [r for r in matches if q in r["instructor"].lower()]

    matches.sort(key=_sem_sort_key)

    results = [
        {
            "course_id": r["course_id"],
            "course_name": r["course_name"],
            "semester": r["semester"],
            "instructor": r["instructor"],
            "workload_hours": r["workload_hours"],
            "overall_rating": r["overall_rating"],
            "instructor_rating": r["instructor_rating"],
            "response_count": r["response_count"],
            "is_mock": True,
        }
        for r in matches
    ]
    citations = [
        {
            "title": f"{r['course_id']} FCE · {r['semester']}",
            "url": "",
            "snippet": (
                f"{r['course_name']} · {r['instructor']} · "
                f"{r['workload_hours']} hrs/week · "
                f"overall {r['overall_rating']}/5 · "
                f"instructor {r['instructor_rating']}/5 "
                f"({r['response_count']} responses)"
            ),
            "indexed_at": None,
        }
        for r in matches
    ]

    return {"results": results, "citations": citations}
