import logging
import os

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class FindDeviceConfig(AppConfig):
    name = 'find_device'

    def ready(self):
        try:
            from .plc.registry import DeviceRegistry
            apt_id = int(os.getenv('APARTMENT_ID', '16'))
            DeviceRegistry.instance()
            logger.info(
                "FindDeviceConfig: DeviceRegistry ready for apartment %d", apt_id,
            )
        except Exception as exc:
            logger.warning(
                "DeviceRegistry startup failed (PLC may be offline): %s", exc,
            )
