from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health),
    path("json", views.json_view),
    path("db", views.db),
    path("queries", views.queries),
    path("fortunes", views.fortunes),
]
