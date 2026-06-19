"""
Lumina PLC — Database models.

PLCDevice   : A Beckhoff TwinCAT 3 controller the user wants to manage.
UserProfile : Per-user preferences (default device, theme).
DiscoveryCache : Cached symbol table from a PLCDevice scan.
"""
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class PLCDevice(models.Model):
    """
    Connection details for one TwinCAT 3 runtime.

    The AMS Net ID is the 6-octet identifier TwinCAT uses for routing,
    e.g. "192.168.0.158.1.1".  The IP address is the TCP/IP address of
    the host that runs TwinCAT.  Port 851 is the default TC3 runtime port.
    """

    owner       = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="plc_devices",
    )
    name        = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    ip_address  = models.GenericIPAddressField(protocol="both")
    ams_net_id  = models.CharField(
        max_length=23,
        help_text="TwinCAT AMS Net ID, e.g. 192.168.0.158.1.1",
    )
    ads_port    = models.PositiveIntegerField(
        default=851,
        help_text="TwinCAT 3 runtime port (default 851)",
    )
    is_active   = models.BooleanField(default=True)
    is_default  = models.BooleanField(
        default=False,
        help_text="Whether this is the user's primary device",
    )
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering        = ["-updated_at"]
        unique_together = [("owner", "name")]
        verbose_name    = "PLC Device"
        verbose_name_plural = "PLC Devices"

    def __str__(self) -> str:
        return f"{self.name} ({self.ams_net_id})"

    def save(self, *args, **kwargs):
        # Ensure only one default per user.
        if self.is_default:
            PLCDevice.objects.filter(
                owner=self.owner, is_default=True,
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class UserProfile(models.Model):
    """Per-user preferences — auto-created on User creation via signal."""

    THEME_DARK  = "dark"
    THEME_LIGHT = "light"
    THEME_CHOICES = [(THEME_DARK, "Dark"), (THEME_LIGHT, "Light")]

    user    = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="profile",
    )
    theme   = models.CharField(
        max_length=10, choices=THEME_CHOICES, default=THEME_DARK,
    )
    push_notifications_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Profile"

    def __str__(self) -> str:
        return f"Profile({self.user.username})"


@receiver(post_save, sender=User)
def _create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


class DiscoveryCache(models.Model):
    """
    Cached TwinCAT symbol discovery result for a PLCDevice.

    symbols_json is a list of symbol descriptor dicts, each containing:
      {name, full_name, type_name, comment, gvl, widget_type, unit, min, max}
    """

    device      = models.OneToOneField(
        PLCDevice, on_delete=models.CASCADE, related_name="discovery_cache",
    )
    symbols_json = models.JSONField(default=list)
    scanned_at  = models.DateTimeField(auto_now=True)
    scan_duration_ms = models.PositiveIntegerField(default=0)
    symbol_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Discovery Cache"

    def __str__(self) -> str:
        return f"DiscoveryCache({self.device.name}, {self.symbol_count} symbols)"
