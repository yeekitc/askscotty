from django.urls import path

from .views import AskView, HealthView, SourcesView, ThreadDetailView, ThreadListView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("ask/", AskView.as_view(), name="ask"),
    path("sources/", SourcesView.as_view(), name="sources"),
    # Scoped to an anonymous session via the X-Session-Id header, not the URL.
    path("threads/", ThreadListView.as_view(), name="thread-list"),
    path("threads/<str:thread_id>/", ThreadDetailView.as_view(), name="thread-detail"),
]
