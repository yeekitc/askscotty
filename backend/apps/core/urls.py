from django.urls import path

from .views import AskView, HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("ask/", AskView.as_view(), name="ask"),
]
