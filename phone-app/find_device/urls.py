from django.urls import path
from . import views, auth_views, device_views
from .discovery import views as discovery_views

urlpatterns = [
    # ── Health / status ──────────────────────────────────────────────────────
    path('',             views.health),
    path('state/',       views.get_state),
    path('devices/',     views.get_devices),
    path('diagnostics/', views.get_diagnostics),

    # ── DALI dimmers ─────────────────────────────────────────────────────────
    path('dali/all/brightness/',            views.set_dali_brightness_all),
    path('dali/<int:channel>/brightness/',  views.set_dali_brightness),

    # ── Room-level brightness ────────────────────────────────────────────────
    path('room/<str:room_name>/brightness/', views.set_room_brightness),

    # ── Wall relay lights ────────────────────────────────────────────────────
    path('relay/<int:channel>/',            views.set_relay),

    # ── Curtain motors ───────────────────────────────────────────────────────
    path('curtain/all/',                    views.set_curtain_all),
    path('curtain/<int:index>/',            views.set_curtain),

    # ── Smart appliances ─────────────────────────────────────────────────────
    path('appliance/<str:gvl_name>/',       views.set_appliance),

    # ── Sensors (read-only) ──────────────────────────────────────────────────
    path('sensors/',                        views.get_sensors),

    # ── Security ────────────────────────────────────────────────────────────
    path('security/alarm/',                 views.set_alarm),
    path('security/lockdown/',              views.set_lockdown),
]

# Mounted at /auth/ in PLC_Project/urls.py
auth_urlpatterns = [
    path('register/',  auth_views.register,      name='auth-register'),
    path('login/',     auth_views.login,          name='auth-login'),
    path('refresh/',   auth_views.refresh_token,  name='auth-refresh'),
    path('me/',        auth_views.me,             name='auth-me'),
    path('logout/',    auth_views.logout,         name='auth-logout'),
]

# Mounted at /manage/devices/ in PLC_Project/urls.py
device_urlpatterns = [
    path('',                    device_views.device_list,         name='device-list'),
    path('<int:pk>/',            device_views.device_detail,       name='device-detail'),
    path('<int:pk>/test/',       device_views.device_test,         name='device-test'),
    path('<int:pk>/set-default/', device_views.device_set_default, name='device-set-default'),
]

# Mounted at /manage/discovery/ in PLC_Project/urls.py
discovery_urlpatterns = [
    path('<int:device_id>/scan/',    discovery_views.scan,          name='discovery-scan'),
    path('<int:device_id>/symbols/', discovery_views.symbols,       name='discovery-symbols'),
    path('<int:device_id>/widgets/', discovery_views.widget_layout, name='discovery-widgets'),
]
