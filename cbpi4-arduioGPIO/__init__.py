from telemetrix_aio import telemetrix_aio
import logging
import asyncio
from cbpi.api import *
import serial
import serial.tools.list_ports

logger = logging.getLogger(__name__)

# Define Arduino types
Uno = {
    "total_count": 20,
    "digital_pins": [i for i in range(28)],
    "pwm_count": 6,
    "pwm_pins": [3, 5, 6, 9, 10, 11],
    "analog_count": 6,
    "name": "Uno"
}

Nano = {
    "total_count": 20,
    "digital_pins": [i for i in range(28)],
    "pwm_count": 6,
    "pwm_pins": [3, 5, 6, 9, 10, 11],
    "analog_count": 6,
    "name": "Nano"
}

Mega = {
    "total_count": 70,
    "digital_pins": [i for i in range(54)],
    "pwm_count": 15,
    "pwm_pins": [2, 3, 5, 6, 9, 10, 11, 12, 13, 44, 45, 46],
    "analog_count": 16,
    "name": "Mega"
}

global board

async def TelemetrixInitialize():
    global board
    logger.info("***************** Start Telemetrix  ************************")
    try:
        loop1 = asyncio.get_event_loop()
        board = telemetrix_aio.TelemetrixAIO(autostart=False, loop=loop1)
        await board.start_aio()
        logger.info("Telemetrix initialized successfully")
    except Exception as e:
        logger.error(f"Error. Could not activate Telemetrix: {e}")
        board = None

class AtrduinoTelemetrix(CBPiExtension):
    def __init__(self, cbpi):
        self.cbpi = cbpi
        self._task = asyncio.create_task(self.init_actor())

    async def init_actor(self):
        await TelemetrixInitialize()

@parameters([Property.Select(label="GPIO", options=Mega['digital_pins']), Property.Select(label="Inverted", options=["Yes", "No"], description="No: Active on high; Yes: Active on low")])
class ArduinoGPIOActor(CBPiActor):
    async def setpower(self, Power=100, **kwargs):
        self.power = min(max(int(Power), 0), 255)
        await self.set_power(self.power)


    async def on_start(self):
        global board
        if not self.initialized:
            if board is None:
                logger.error("Board not initialized. Re-initializing...")
                await TelemetrixInitialize()
            
            try:
                await board.set_pin_mode_digital_output(self.gpio)
                await board.digital_write(self.gpio, 0)
                self.state = False
                await self.cbpi.actor.actor_update(self.id, 0)
                self.initialized = True
                logger.info(f"GPIO Actor {self.id} initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize GPIO Actor {self.id}: {e}")

    async def on(self, power=0):
        global board
        if board is None:
            logger.error("Board not initialized. Re-initializing...")
            await TelemetrixInitialize()
        
        logger.info(f"ACTOR {self.id} ON - GPIO {self.gpio}")
        try:
            await board.digital_write(self.gpio, 1 if not self.inverted else 0)
            self.state = True
            await self.cbpi.actor.actor_update(self.id, 1)
        except Exception as e:
            logger.error(f"Failed to turn on GPIO {self.gpio}: {e}")

    async def off(self):
        global board
        if board is None:
            logger.error("Board not initialized. Re-initializing...")
            await TelemetrixInitialize()
        
        logger.info(f"ACTOR {self.id} OFF - GPIO {self.gpio}")
        try:
            await board.digital_write(self.gpio, 0 if not self.inverted else 1)
            self.state = False
            await self.cbpi.actor.actor_update(self.id, 0)
        except Exception as e:
            logger.error(f"Failed to turn off GPIO {self.gpio}: {e}")

    def get_state(self):
        return self.state

    async def run(self):
        while self.running:
            await asyncio.sleep(1)

@parameters([
    Property.Select(label="GPIO", options=Mega['pwm_pins']), 
    Property.Number(label="Initial Power", configurable=True, description="Initial PWM Power (0-255)", default_value=0)
])
class ArduinoGPIOPWMActor(CBPiActor):
    @action("Set Power", parameters=[Property.Number(label="Power", configurable=True, description="Power Setting [0-255]")])
    async def setpower(self, Power=100, **kwargs):
        self.power = min(max(int(Power), 0), 255)
        await self.set_power(self.power)

    async def on_start(self):
        global board
        if board is None:
            logger.error("Board not initialized. Re-initializing...")
            await TelemetrixInitialize()
        
        self.gpio = int(self.props['GPIO'])
        self.initial_power = int(self.props['Initial Power'])
        
        try:
            await board.set_pin_mode_analog_output(self.gpio)
            self.power = self.initial_power
            await board.analog_write(self.gpio, self.power)
            self.state = False
            await self.cbpi.actor.actor_update(self.id, self.power)
            logger.info(f"PWM Actor {self.id} initialized successfully with initial power {self.initial_power}.")
        except Exception as e:
            logger.error(f"Failed to initialize PWM Actor {self.id}: {e}")

    async def on(self, power=None):
        global board
        if board is None:
            logger.error("Board not initialized. Re-initializing...")
            await TelemetrixInitialize()
        
        if power is not None:
            self.power = power
        else:
            self.power = self.initial_power
        logger.info(f"PWM ACTOR {self.id} ON - GPIO {self.gpio} - Power {self.power}")
        
        try:
            await board.analog_write(self.gpio, self.power)
            self.state = True
            await self.cbpi.actor.actor_update(self.id, self.power)
        except Exception as e:
            logger.error(f"Failed to turn on PWM GPIO {self.gpio}: {e}")

    async def off(self):
        global board
        if board is None:
            logger.error("Board not initialized. Re-initializing...")
            await TelemetrixInitialize()
        
        logger.info(f"PWM ACTOR {self.id} OFF - GPIO {self.gpio}")
        
        try:
            await board.analog_write(self.gpio, 0)
            self.state = False
            await self.cbpi.actor.actor_update(self.id, 0)
        except Exception as e:
            logger.error(f"Failed to turn off PWM GPIO {self.gpio}: {e}")

    async def set_power(self, power):
        global board
        if board is None:
            logger.error("Board not initialized. Re-initializing...")
            await TelemetrixInitialize()
        
        if self.state:
            try:
                await board.analog_write(self.gpio, int(power))
                await self.cbpi.actor.actor_update(self.id, int(power))
            except Exception as e:
                logger.error(f"Failed to set power for PWM GPIO {self.gpio}: {e}")

    def get_state(self):
        return self.state

    async def run(self):
        while self.running:
            await asyncio.sleep(1)

async def init_all_actors(cbpi):
    for actor in cbpi.actor.get_all():
        if isinstance(actor.instance, ArduinoGPIOActor) or isinstance(actor.instance, ArduinoGPIOPWMActor):
            await actor.instance.on_start()

def setup(cbpi):
    cbpi.plugin.register("ArduinoGPIOActor", ArduinoGPIOActor)
    cbpi.plugin.register("ArduinoGPIOPWMActor", ArduinoGPIOPWMActor)
    cbpi.plugin.register("AtrduinoTelemetrix", AtrduinoTelemetrix)
    
    asyncio.run(init_all_actors(cbpi))
