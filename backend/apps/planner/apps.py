from django.apps import AppConfig
from django.conf import settings
from django.core import checks


class PlannerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.planner"
    label = "planner"

    def ready(self) -> None:
        checks.register(_check_provisioned)


def _check_provisioned(app_configs, **kwargs):
    """Say at startup when the planner has not been provisioned.

    A warning rather than an error, and that is deliberate: `setup.sh` starts the
    API *before* it provisions, so an error-level check would make a fresh clone
    unbootable and provisioning impossible. This is the loud half — it prints on
    every `runserver` and `manage.py check`. The other half is a hard failure
    with the same instruction the first time anyone asks a question, in
    `apps/planner/client.py`. Neither ever self-provisions.
    """
    if not settings.PLANNER_MANAGED_AGENTS:
        return []
    if settings.PLANNER_AGENT_ID and settings.PLANNER_ENVIRONMENT_ID:
        return []

    missing = " and ".join(
        name
        for name, value in (
            ("PLANNER_AGENT_ID", settings.PLANNER_AGENT_ID),
            ("PLANNER_ENVIRONMENT_ID", settings.PLANNER_ENVIRONMENT_ID),
        )
        if not value
    )
    return [
        checks.Warning(
            f"The planner is not provisioned: {missing} is unset, so /api/ask/ "
            "will fail on the first question.",
            hint=(
                "Run: docker compose exec backend python manage.py provision_planner\n"
                "then copy the ids it prints into the root .env and restart the backend."
            ),
            id="planner.W001",
        )
    ]
