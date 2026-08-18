"""Demo-only routes. Included by config/urls.py only under DEBUG — see the
README in this folder."""

from __future__ import annotations

from django.urls import path

from .views import DemoCookieConnectView

urlpatterns = [
    path("personal/demo/cookies/", DemoCookieConnectView.as_view(), name="demo-cookies"),
]
