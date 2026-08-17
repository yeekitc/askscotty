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

from apps.planner import client as planner_client
from apps.planner import prompt
from apps.planner.client import get_client
from apps.planner.errors import PlannerError
from apps.tools.registry import tools_for_session

AGENT_NAME = "AskScotty planner"
ENVIRONMENT_NAME = "askscotty"

ENVIRONMENT_CONFIG = {"type": "cloud", "networking": {"type": "unrestricted"}}


def agent_tools() -> list[dict]:
    """The agent's own toolset: the prebuilt one plus every public tool we have.

    The prebuilt half is kept whole deliberately — bash/read/write/edit/glob/grep
    are never used, but the schemas are cheap at demo scale and disabling them is
    config surface to keep in sync (docs/b4-planner.md "What it costs").

    Our tools are here as well as on each session because a session opened by
    anything other than `create_session` — the Console, a script — gets only what
    the agent itself declares. An agent holding nothing but the prebuilt toolset
    made a Console question a different product: the model had the open web and
    nothing else, and answered "9-unit ML elective, no Friday" with 23 web calls
    and $0.86 instead of one `search_courses` and $0.04.

    **Personal tools are excluded, and that is load-bearing.** They are offered
    per session only where the connector exists (PRD §7); declaring one here
    would tell every session it had a capability nobody had connected.

    A public tool's schema changing therefore means re-running this command.
    """
    return planner_client.toolset(tools_for_session(None))


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
        tools = agent_tools()

        agent_id = getattr(settings, "PLANNER_AGENT_ID", "") or ""
        environment_id = getattr(settings, "PLANNER_ENVIRONMENT_ID", "") or ""

        named = [tool["name"] for tool in tools if "name" in tool]
        self.stdout.write(f"model       {model['id']} (effort {model['effort']})")
        self.stdout.write(f"system      {len(system)} chars")
        self.stdout.write(f"tools       {tools[0]['type']} + {len(named)}: {', '.join(named)}")
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
                    tools=tools,
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Updated agent {agent.id} → version {agent.version}")
                )
            else:
                agent = client.beta.agents.create(
                    name=AGENT_NAME,
                    model=model,
                    system=system,
                    tools=tools,
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
