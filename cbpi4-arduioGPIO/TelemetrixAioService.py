import asyncio
import logging
from typing import Optional
from telemetrix_aio import telemetrix_aio

logger = logging.getLogger(__name__)

log_levels = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}

class TelemetrixAioService:
    Arduino: Optional[telemetrix_aio.TelemetrixAIO] = None
    _initializing: bool = False
    _initialized: bool = False
    cbpi_instance = None

    @staticmethod
    async def initialize(config_getter):
        if not TelemetrixAioService._initialized and not TelemetrixAioService._initializing:
            TelemetrixAioService._initializing = True
            log_level_str = config_getter('arduinogpio_log_level', 'Info')
            log_level = TelemetrixAioService.convert_log_level(log_level_str)
            logger.setLevel(log_level)

            TelemetrixAioService.Arduino = telemetrix_aio.TelemetrixAIO(autostart=False)
            try:
                await TelemetrixAioService.Arduino.start_aio()
                logger.info("Arduino GPIO initialized successfully.")
                logger.info(f"Connected to Arduino on port: {TelemetrixAioService.Arduino.serial_port}")
                TelemetrixAioService._initialized = True
            except Exception as e:
                logger.error(f"Error initializing Arduino GPIO: {e}")
                TelemetrixAioService.Arduino = None
                TelemetrixAioService._initialized = False
            finally:
                TelemetrixAioService._initializing = False
        else:
            logger.info("Arduino GPIO instance already exists or is initializing.")

    @staticmethod
    def is_initialized():
        return TelemetrixAioService._initialized

    @staticmethod
    def convert_log_level(log_level_str):
        return log_levels.get(log_level_str.upper(), logging.INFO)

    @staticmethod
    async def shutdown():
        if TelemetrixAioService.Arduino is not None:
            try:
                await TelemetrixAioService.Arduino.shutdown()
                logger.info("Arduino GPIO shut down successfully.")
                TelemetrixAioService._initialized = False
            except Exception as e:
                logger.error(f"Error shutting down Arduino GPIO: {e}")

    @staticmethod
    def get_arduino_instance():
        return TelemetrixAioService.Arduino

    @staticmethod
    async def init_service(cbpi):
        TelemetrixAioService.cbpi_instance = cbpi
        await TelemetrixAioService.initialize(cbpi.config.get)