import os

SECRET_KEY = "benchmark-secret-key-not-for-production"

DEBUG = False

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "benchmark",
]

MIDDLEWARE = []

ROOT_URLCONF = "benchmark.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
    },
]

WSGI_APPLICATION = "benchmark.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.environ.get("DB_HOST", "postgres"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "NAME": os.environ.get("DB_NAME", "hello_world"),
        "USER": os.environ.get("DB_USER", "benchmarkdbuser"),
        "PASSWORD": os.environ.get("DB_PASS", "benchmarkdbpass"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
}
