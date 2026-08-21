"""Django settings for AskScotty."""

from pathlib import Path
import os

from corsheaders.defaults import default_headers
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "dev-only-change-me-askscotty-hackathon",
)

DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() in {"1", "true", "yes"}

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,backend").split(",")
    if host.strip()
]

# Render injects the real public hostname here. Worth trusting over anything the
# blueprint can express: `fromService … property: host` yields the *service name*
# ("askscotty-api"), not the hostname, so a deploy configured that way rejects
# every request — including the platform's own health check — as DisallowedHost.
# A 400 on a health check reads like the app crashed; nothing says "hostname".
_render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
if _render_hostname and _render_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_render_hostname)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "apps.core",
    # Before apps.tools, same as apps.personal: ToolsConfig.ready() imports
    # apps.rag.tools, so rag's models must be loaded first.
    "apps.rag",
    # Before apps.tools: ToolsConfig.ready() imports the personal tool modules,
    # and app configs load in order, so personal's models must be ready first.
    "apps.personal",
    "apps.tools",
    # After apps.tools: the planner reads the registry rather than owning any of
    # it, so every tool must be registered before a request reaches the loop.
    "apps.planner",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "askscotty"),
        "USER": os.getenv("POSTGRES_USER", "askscotty"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "askscotty"),
        "HOST": os.getenv("POSTGRES_HOST", "db"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    # Defining STORAGES replaces Django's default wholesale, so "default" must
    # be listed explicitly or any default_storage use raises InvalidStorageError
    # at request time.
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django's default config only wires up the `django` logger, so everything our
# own code logs at INFO — the per-tool-call line in tools/registry.py, the
# planner's cache counters — went nowhere at all without this.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"apps": {"format": "%(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "apps"}},
    "loggers": {
        "apps": {
            "handlers": ["console"],
            "level": os.getenv("LOG_LEVEL") or "INFO",
            "propagate": False,
        }
    },
}

# Render, Fly and every other managed host terminate TLS at a proxy and forward
# plain HTTP, so without this Django believes an https:// request is insecure and
# rejects its own admin login as a CSRF failure.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Needed once the site is served over https from a host Django did not originate
# — /admin/ and the browsable API POST both fail with 403 otherwise. The JSON
# endpoints are unaffected: their authentication_classes are empty, so DRF never
# reaches the session-auth CSRF check.
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

# In development the frontend appears on many origins: Expo web on :8081, a LAN
# IP from a physical phone, a tunnel URL, another port if 8081 was taken. Allow
# any while DEBUG is on rather than have teammates debug CORS; with DEBUG off,
# only CORS_ALLOWED_ORIGINS is honoured.
CORS_ALLOW_ALL_ORIGINS = DEBUG and not CORS_ALLOWED_ORIGINS

CORS_ALLOW_CREDENTIALS = True

# x-session-id is not a header browsers allow cross-origin by default, so
# without this every /api/threads/ request fails its CORS preflight — and the
# failure surfaces as a network error, not a permissions one.
CORS_ALLOW_HEADERS = (*default_headers, "x-session-id")

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    # Form parsers so the browsable API at /api/ask/ can submit — with
    # JSONParser alone its form returns 415, and that page is the easiest way
    # for a non-technical teammate to poke the API.
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    # One error shape for every failure. See apps/core/errors.py for why DRF's
    # default isn't good enough here.
    "EXCEPTION_HANDLER": "apps.core.errors.api_exception_handler",
}

# --- External services --------------------------------------------------------
#
# Empty defaults so the backend boots without any of them: a missing key becomes
# a clear error when the feature is used, not a startup crash blocking the team.
# Every key here must also appear in .env.example (never .env, which is
# gitignored).

# Planner LLM. Anthropic tool-use drives the multi-hop answer (PRD §6).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# The cheaper-fallback option named in tasklist §1. Override to claude-opus-5 if
# multi-hop routing needs the extra headroom.
# `or` rather than a getenv default: a present-but-blank env var is the normal
# state of a freshly copied .env, and should mean "use the default" rather than
# "use the empty string". Same below.
PLANNER_MODEL = os.getenv("PLANNER_MODEL") or "claude-sonnet-5"

# How hard the model thinks before answering. The API default is `high`; `low` is
# measured as ~13% faster end to end and ~27% to first token than `medium` on the
# signature multi-hop, with no loss of tool routing (docs/b4-planner.md).
#
# Read only by `manage.py provision_planner`. Effort lives on the agent, and an
# effort set inside a per-session override is *silently ignored* — so changing
# this without re-provisioning does nothing at all.
#
# Note what is *not* here: temperature, top_p and top_k are a 400 on this model
# at any non-default value, so the planner never sends them.
PLANNER_EFFORT = os.getenv("PLANNER_EFFORT") or "low"

# Managed Agents config objects, created once by `manage.py provision_planner`
# and referenced by every session after that. Not secret. Empty until someone
# provisions; the planner must fail loudly rather than create its own, because a
# request that provisions orphans one agent per worker boot.
PLANNER_AGENT_ID = os.getenv("PLANNER_AGENT_ID") or ""
PLANNER_ENVIRONMENT_ID = os.getenv("PLANNER_ENVIRONMENT_ID") or ""

# What bounds a runaway tool loop now that the wall-clock deadline is gone.
# Dollar-denominated because that is the shape the problem actually has, in
# minor units (cents) because that is what the API takes. It bounds a whole
# *conversation*, not one question: the session outlives the turn, and the cap
# is fixed when the session opens. 0 removes it.
PLANNER_SESSION_BUDGET_CENTS = int(os.getenv("PLANNER_SESSION_BUDGET_CENTS") or 500)

# Control-plane calls only — open a session, send events, list events. The event
# stream sets its own, far longer, ceiling; a 45-second read timeout would kill a
# long answer mid-thought.
PLANNER_REQUEST_TIMEOUT = float(os.getenv("PLANNER_REQUEST_TIMEOUT") or 45)
PLANNER_MAX_RETRIES = int(os.getenv("PLANNER_MAX_RETRIES") or 1)

# Whether the answer keeps its inline [S1] markers. The app renders each one as
# a citation chip; with this off `loop.py` strips them and the answer still
# reads correctly, so it stays a switch rather than a hard dependency.
PLANNER_CITATION_MARKERS = os.getenv("PLANNER_CITATION_MARKERS", "true").lower() in {
    "1",
    "true",
    "yes",
}

# How old an indexed page may be before a time-sensitive question should be
# checked against the live web instead. The system prompt is frozen on the agent
# version and cannot read this at request time, so the number is also written out
# in apps/planner/prompt.py — changing it here means re-running
# `manage.py provision_planner`, or the model keeps quoting the old one.
WEB_VERIFY_STALE_AFTER_DAYS = int(os.getenv("WEB_VERIFY_STALE_AFTER_DAYS") or 30)

# Embeddings for the vector half of hybrid retrieval. A separate provider by
# necessity: Anthropic has no embeddings endpoint (tasklist §1).
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL") or "text-embedding-3-small"
# Must match the pgvector column width, so changing the model means a migration,
# not just an env var.
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS") or 1536)

# No web-search key on purpose: the verify lane (PRD §6) uses Claude's
# server-side web_search / web_fetch tools, which run under ANTHROPIC_API_KEY.
# Domain allow/deny lists are passed per tool call, not configured here.

# Encrypts personal access tokens at rest (PRD §9). Falls back to a key derived
# from DJANGO_SECRET_KEY while DEBUG is on; required once DEBUG is off — see
# apps/personal/crypto.py.
CONNECTOR_ENCRYPTION_KEY = os.getenv("CONNECTOR_ENCRYPTION_KEY", "")

# PRD §3 requires that we identify our crawler and honour robots.txt.
CRAWLER_USER_AGENT = (
    os.getenv("CRAWLER_USER_AGENT")
    or "AskScottyBot/0.1 (CMU student project; +https://github.com/askscotty)"
)
