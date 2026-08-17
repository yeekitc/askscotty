from django.urls import path

from .views import (
    AskStreamView,
    AskView,
    ConnectionDetailView,
    ConnectionsView,
    HealthView,
    SourcesView,
    ThreadDetailView,
    ThreadListView,
)

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("ask/", AskView.as_view(), name="ask"),
    # Same answer, delivered as progress events. See AskStreamView.
    path("ask/stream/", AskStreamView.as_view(), name="ask-stream"),
    path("sources/", SourcesView.as_view(), name="sources"),
    # Scoped to an anonymous session via the X-Session-Id header, not the URL.
    path("threads/", ThreadListView.as_view(), name="thread-list"),
    path("threads/<str:thread_id>/", ThreadDetailView.as_view(), name="thread-detail"),
    path("connections/", ConnectionsView.as_view(), name="connections"),
    path(
        "connections/<str:provider>/",
        ConnectionDetailView.as_view(),
        name="connection-detail",
    ),
]
