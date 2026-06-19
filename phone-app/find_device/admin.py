from django.contrib import admin
from .models import PLCDevice, UserProfile, DiscoveryCache


@admin.register(PLCDevice)
class PLCDeviceAdmin(admin.ModelAdmin):
    list_display  = ("name", "owner", "ip_address", "ams_net_id", "is_active", "is_default", "updated_at")
    list_filter   = ("is_active", "is_default", "owner")
    search_fields = ("name", "ip_address", "ams_net_id", "owner__username")
    readonly_fields = ("created_at", "updated_at", "last_seen_at")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display  = ("user", "theme", "push_notifications_enabled", "updated_at")
    list_filter   = ("theme",)
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(DiscoveryCache)
class DiscoveryCacheAdmin(admin.ModelAdmin):
    list_display  = ("device", "symbol_count", "scan_duration_ms", "scanned_at")
    search_fields = ("device__name",)
    readonly_fields = ("scanned_at", "symbol_count", "scan_duration_ms")
