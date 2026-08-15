from django.apps import AppConfig


class ToolsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tools"
    label = "tools"

    def ready(self) -> None:
        # Tools and sources register as a side effect of being imported, so
        # every module defining one must be imported before the planner runs.
        # Errors here are deliberately loud: a tool that silently vanishes is
        # harder to debug than a backend that won't boot.
        from . import sources  # noqa: F401
        from apps.personal import tools as personal_tools  # noqa: F401
        from apps.rag import tools as rag_tools  # noqa: F401
