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
    # apps.personal is listed before apps.tools because ToolsConfig.ready()
    # imports the personal tool modules; Django loads app configs in order, so
    # personal's models are ready by the time that import runs.
    "apps.personal",
    "apps.tools",
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
    # Defining STORAGES replaces Django's default wholesale, so "default" must be
    # listed explicitly. Without it, any FileField or default_storage use raises
    # InvalidStorageError at request time.
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

# In development the frontend can appear on a lot of origins: Expo web on :8081,
# a LAN IP when testing on a physical phone, a tunnel URL, or a different port if
# 8081 was taken. Rather than have teammates debug CORS errors, allow any origin
# while DEBUG is on. When DEBUG is off, only CORS_ALLOWED_ORIGINS is honoured.
CORS_ALLOW_ALL_ORIGINS = DEBUG and not CORS_ALLOWED_ORIGINS

CORS_ALLOW_CREDENTIALS = True

# The app identifies its anonymous session with an X-Session-Id header (see
# apps/core/views._session_id). It is not one of the headers browsers allow
# cross-origin by default, so without this every /api/threads/ request fails
# its CORS preflight — and the failure looks like a network error, not a
# permissions one, which is a miserable thing to debug.
CORS_ALLOW_HEADERS = (*default_headers, "x-session-id")

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    # Form parsers are needed for the browsable API at /api/ask/ to be able to
    # submit — with JSONParser alone its form returns 415. That page is the
    # easiest way for a non-technical teammate to poke the API.
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    # One error shape for every failure: {"error": {"code", "message"}}.
    # See apps/core/errors.py for why DRF's default isn't good enough here.
    "EXCEPTION_HANDLER": "apps.core.errors.api_exception_handler",
}

# --- External services --------------------------------------------------------
#
# Read from the environment with empty defaults, so the backend still boots
# without any of them — you get a clear error when a feature that needs a key is
# actually used, rather than a crash at startup that blocks the whole team.
# Every key here must also appear in .env.example (never .env, which is
# gitignored), so a teammate cloning the repo can see what exists.

# Planner LLM. Anthropic tool-use drives the multi-hop answer (PRD §6).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Claude Sonnet 5 — the cost/quality middle of the current generation, and the
# cheaper-fallback option named in tasklist §1. Override to claude-opus-5 if
# multi-hop routing needs the extra headroom.
# `or` rather than a getenv default: an env var that is present but blank is the
# normal state of a freshly copied .env, and it should mean "use the default"
# rather than "use the empty string". Same below.
PLANNER_MODEL = os.getenv("PLANNER_MODEL") or "claude-sonnet-5"

# Embeddings for the vector half of hybrid retrieval. Anthropic has no
# embeddings endpoint, so this is a separate provider by necessity (tasklist §1).
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL") or "text-embedding-3-small"
# 1536 for text-embedding-3-small. Must match the pgvector column width, so
# changing the model means a migration, not just an env var.
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS") or 1536)

# No web-search key here on purpose. The verify lane (PRD §6) uses Claude's
# *server-side* web_search / web_fetch tools, which run on Anthropic's
# infrastructure under ANTHROPIC_API_KEY — there is no second provider and no
# second key. Domain allow/deny lists are passed per tool call, not configured
# here; see apps/tools/ for the verify tools.

# Encrypts personal access tokens at rest (PRD §9). Falls back to a key derived
# from DJANGO_SECRET_KEY while DEBUG is on; required once DEBUG is off — see
# apps/personal/crypto.py.
CONNECTOR_ENCRYPTION_KEY = os.getenv("CONNECTOR_ENCRYPTION_KEY", "")

# Identifies our crawler to the sites we index. PRD §3 requires that we say who
# we are and honour robots.txt.
CRAWLER_USER_AGENT = (
    os.getenv("CRAWLER_USER_AGENT")
    or "AskScottyBot/0.1 (CMU student project; +https://github.com/askscotty)"
)
