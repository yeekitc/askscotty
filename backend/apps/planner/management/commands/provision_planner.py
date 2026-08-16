"""Create or update the planner's Managed Agents objects.

Run by hand. The agent and the environment are configuration, not per-request
state: they are created once, their ids go in `.env`, and the request path only
ever calls `sessions.create` against those ids. A request that provisions its own
agent orphans one per worker boot, so nothing outside this command may create
them.

Re-running is the normal way to ship a prompt change. With the ids already in
settings it updates in place, which mints a new agent *version* under the same
id — sessions already running keep the version they started on.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.planner import prompt
from apps.planner.client import get_client
from apps.planner.errors import PlannerError

AGENT_NAME = "AskScotty planner"
ENVIRONMENT_NAME = "askscotty"

# The whole toolset, deliberately. bash/read/write/edit/glob/grep are never used
# — every real capability is a custom tool running in Django — but the schemas
# are cheap at demo scale and disabling them is config surface we'd have to keep
# in sync. See docs/b4-planner.md "What it costs".
TOOLS = [{"type": "agent_toolset_20260401"}]

ENVIRONMENT_CONFIG = {"type": "cloud", "networking": {"type": "unrestricted"}}


class Command(BaseCommand):
    help = "Create or update the Managed Agents agent and environment for the planner."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be sent and exit without calling the API.",
        )

    def handle(self, *args, **options):
        system = prompt.agent_system_text()
        model = {"id": settings.PLANNER_MODEL, "effort": settings.PLANNER_EFFORT}

        agent_id = getattr(settings, "PLANNER_AGENT_ID", "") or ""
        environment_id = getattr(settings, "PLANNER_ENVIRONMENT_ID", "") or ""

        self.stdout.write(f"model       {model['id']} (effort {model['effort']})")
        self.stdout.write(f"system      {len(system)} chars")
        self.stdout.write(f"tools       {TOOLS[0]['type']}")
        self.stdout.write(f"agent       {agent_id or '(create)'}")
        self.stdout.write(f"environment {environment_id or '(create)'}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("\n--dry-run: nothing sent."))
            return

        try:
            client = get_client()
        except PlannerError as exc:
            raise CommandError(str(exc)) from exc

        try:
            if environment_id:
                self.stdout.write(f"\nReusing environment {environment_id}.")
            else:
                environment = client.beta.environments.create(
                    name=ENVIRONMENT_NAME,
                    config=ENVIRONMENT_CONFIG,
                )
                environment_id = environment.id
                self.stdout.write(self.style.SUCCESS(f"\nCreated environment {environment_id}"))

            if agent_id:
                agent = client.beta.agents.update(
                    agent_id,
                    model=model,
                    system=system,
                    tools=TOOLS,
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Updated agent {agent.id} → version {agent.version}")
                )
            else:
                agent = client.beta.agents.create(
                    name=AGENT_NAME,
                    model=model,
                    system=system,
                    tools=TOOLS,
                )
                agent_id = agent.id
                self.stdout.write(
                    self.style.SUCCESS(f"Created agent {agent_id} (version {agent.version})")
                )
        except Exception as exc:  # noqa: BLE001 - surface the API's own message
            raise CommandError(f"{type(exc).__name__}: {exc}") from exc

        self.stdout.write("\nPut these in .env:\n")
        self.stdout.write(f"PLANNER_AGENT_ID={agent_id}")
        self.stdout.write(f"PLANNER_ENVIRONMENT_ID={environment_id}")
