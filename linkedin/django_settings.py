# linkedin/django_settings.py
"""
Minimal Django settings for using DjangoCRM's ORM + admin.
"""
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

# Playwright's sync API runs inside an async event loop, which triggers
# Django's async-safety check. We only use the ORM synchronously, so this is safe.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

ROOT_DIR = Path(__file__).resolve().parent.parent

BASE_DIR = ROOT_DIR


def _load_dotenv():
    """Load project-root `.env` into os.environ (setdefault — never overrides)."""
    env_file = ROOT_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()

SECRET_KEY = "openoutreach-local-dev-key-change-in-production"

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Allow the dashboard to embed the admin pages (Unibox/Accounts/Leads/Campaigns
# tabs are same-origin iframes). Django's default DENY blocks even same-origin.
X_FRAME_OPTIONS = "SAMEORIGIN"

INSTALLED_APPS = [
    "django.contrib.sites",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "crm.apps.CrmConfig",
    "chat.apps.ChatConfig",
    "linkedin",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "linkedin.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


def _database_config():
    """Postgres by default for localhost; SQLite via USE_SQLITE=1 or DATABASE_URL=sqlite..."""
    use_sqlite = os.environ.get("USE_SQLITE", "").lower() in ("1", "true", "yes")
    database_url = os.environ.get("DATABASE_URL", "").strip()

    if use_sqlite or database_url.startswith("sqlite"):
        name = str(ROOT_DIR / "data" / "db.sqlite3")
        if database_url.startswith("sqlite"):
            if database_url.endswith(":memory:"):
                name = ":memory:"
            elif "sqlite:///" in database_url:
                path = database_url.split("sqlite:///", 1)[-1]
                if path and path != ":memory:":
                    name = path if path.startswith("/") else str(ROOT_DIR / path)
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": name,
        }

    if database_url:
        u = urlparse(database_url)
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(u.path.lstrip("/")) or "openoutreach",
            "USER": unquote(u.username or "openoutreach"),
            "PASSWORD": unquote(u.password or ""),
            "HOST": u.hostname or "localhost",
            "PORT": str(u.port or 5432),
        }

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "openoutreach"),
        "USER": os.environ.get("POSTGRES_USER", "openoutreach"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "openoutreach"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }


DATABASES = {"default": _database_config()}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SITE_ID = 1

STATIC_URL = "/static/"
STATIC_ROOT = ROOT_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = ROOT_DIR / "media"

LOGIN_URL = "/admin/login/"

DEFAULT_FROM_EMAIL = "noreply@localhost"
EMAIL_SUBJECT_PREFIX = "CRM: "

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English")]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

TESTING = sys.argv[1:2] == ["test"]
