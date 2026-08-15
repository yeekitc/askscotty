from django.apps import AppConfig


class ToolsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tools"
    label = "tools"

    def ready(self) -> None:
        # Tools and sources register themselves as a side effect of being
        # imported, so every module that defines one has to be imported before
        # the planner runs. Doing it here means "add a tool" is one decorator
        # plus one line in this list, rather than something you can forget and
        # then spend an hour wondering why the planner never calls your
        # function. Import errors are deliberately loud — a tool that silently
        # vanishes is far harder to debug than a backend that won't boot.
        from . import sources  # noqa: F401
        from apps.personal import tools as personal_tools  # noqa: F401
