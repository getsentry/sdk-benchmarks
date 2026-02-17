import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "benchmark.settings")

# Conditionally initialize Sentry SDK when SENTRY_INIT is set.
# The instrumented Dockerfile sets this env var; baseline does not.
if os.environ.get("SENTRY_INIT"):
    import sentry_init  # noqa: F401

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
