"""`campus_search` registered via @register_tool, mode="rag".

Every result carries `url` and `indexed_at` (PRD §4). The import of
apps.tools.registry is safe here: apps.rag loads before apps.tools in
INSTALLED_APPS, but registry.py is a plain module, not a model — it is
importable as soon as apps.tools is on the Python path.
"""

from apps.tools.registry import register_tool


@register_tool(
    name="campus_search",
    description=(
        "Search the CMU campus index for policies, deadlines, course info, "
        "student services, how-to guides, and general CMU information. "
        "Use this before web_search for any CMU-specific question."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "The search query. Use terms the source page would contain — "
                    "e.g. 'drop deadline fall semester' not 'when can I withdraw'."
                ),
            },
            "k": {
                "type": "integer",
                "description": "Number of results to return (default 6, max 20).",
                "default": 6,
            },
        },
        "required": ["query"],
    },
    mode="rag",
    is_mock=False,
)
def campus_search(query: str, k: int = 6) -> list[dict]:
    from apps.rag.search import campus_search as _search

    return _search(query, k=min(k, 20))
