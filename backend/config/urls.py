from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.core.urls")),
]

# Demo-only cookie ingestion — NOT FOR THE JUDGES. Mounted only under DEBUG, so
# a production build does not expose it. See apps/personal/demo_only/README.md.
if settings.DEBUG:
    urlpatterns += [path("api/", include("apps.personal.demo_only.urls"))]

