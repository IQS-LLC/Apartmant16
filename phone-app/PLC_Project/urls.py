from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse

from find_device.urls import (
    auth_urlpatterns,
    device_urlpatterns,
    discovery_urlpatterns,
)


def health_check(request):
    return HttpResponse("healthy\n", content_type="text/plain")


urlpatterns = [
    path('admin/',       admin.site.urls),
    path('health/',      health_check),

    # ── PLC control (existing endpoints — no JWT by default) ─────────────────
    path('plc/',         include('find_device.urls')),

    # ── Authentication ────────────────────────────────────────────────────────
    path('auth/',        include(auth_urlpatterns)),

    # ── PLC Device management ─────────────────────────────────────────────────
    path('manage/devices/',    include(device_urlpatterns)),

    # ── TwinCAT discovery ─────────────────────────────────────────────────────
    path('manage/discovery/',  include(discovery_urlpatterns)),
]
