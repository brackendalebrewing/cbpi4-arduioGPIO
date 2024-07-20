import logging
import asyncio
import random
import time
from cbpi.api import *
from cbpi.api.dataclasses import NotificationAction, NotificationType
from cbpi.api.dataclasses import Sensor, Kettle, Props
from cbpi.api.config import ConfigType

logger = logging.getLogger(__name__)

class Flowmeter_Config(CBPiExtension):
    def __init__(self, cbpi):
        self.cbpi = cbpi
        self.name = "cbpi4-flowmeter"
        self.version = "0.0.1"  # Update this with your actual version
        self._task = asyncio.create_task(self.init_flowmeter())

    async def init_flowmeter(self):
        logger.info("Initializing Flow Sensor Configuration")
        await self.flowunit_config()
        await self.flowmeter_interval_config()
        await self.flow_logging_level_config()
        await self.update_version()

    async def flowunit_config(self):
        flowunit = self.cbpi.config.get("flowunit", None)
        if flowunit is None:
            logger.info("INIT flowunit")
            try:
                await self.cbpi.config.add("flowunit", "L", type=ConfigType.SELECT, 
                                           description="Flowmeter unit",
                                           source=self.name,
                                           options=[
                                               {"label": "L", "value": "L"},
                                               {"label": "gal(us)", "value": "gal(us)"},
                                               {"label": "gal(uk)", "value": "gal(uk)"},
                                               {"label": "qt", "value": "qt"}
                                           ])
            except:
                logger.warning('Unable to update database: flowunit')

    async def flowmeter_interval_config(self):
        flowmeter_interval = self.cbpi.config.get("flowmeter_interval", None)
        if flowmeter_interval is None:
            logger.info("INIT flowmeter_interval")
            try:
                await self.cbpi.config.add("flowmeter_interval", 1, type=ConfigType.SELECT, 
                                           description="Flowmeter Readout Interval",
                                           source=self.name,
                                           options=[
                                               {"label": "1s", "value": 1},
                                               {"label": "2s", "value": 2},
                                               {"label": "5s", "value": 5},
                                               {"label": "10s", "value": 10}
                                           ])
            except:
                logger.warning('Unable to update database: flowmeter_interval')
        else:
            try:
                await self.cbpi.config.add("flowmeter_interval", flowmeter_interval, type=ConfigType.SELECT, 
                                           description="Flowmeter Readout Interval",
                                           source=self.name,
                                           options=[
                                               {"label": "1s", "value": 1},
                                               {"label": "2s", "value": 2},
                                               {"label": "5s", "value": 5},
                                               {"label": "10s", "value": 10}
                                           ])
            except:
                logger.warning('Unable to update database: flowmeter_interval')

    async def flow_logging_level_config(self):
        flow_logging_level = self.cbpi.config.get("flow_logging_level", None)
        if flow_logging_level is None:
            logger.info("INIT flow_logging_level")
            try:
                await self.cbpi.config.add("flow_logging_level", "INFO", type=ConfigType.SELECT, 
                                           description="Flow Logging Level",
                                           source=self.name,
                                           options=[
                                               {"label": "INFO", "value": "INFO"},
                                               {"label": "DEBUG", "value": "DEBUG"},
                                               {"label": "ERROR", "value": "ERROR"}
                                           ])
            except:
                logger.warning('Unable to update database: flow_logging_level')
        else:
            try:
                await self.cbpi.config.add("flow_logging_level", flow_logging_level, type=ConfigType.SELECT, 
                                           description="Flow Logging Level",
                                           source=self.name,
                                           options=[
                                               {"label": "INFO", "value": "INFO"},
                                               {"label": "DEBUG", "value": "DEBUG"},
                                               {"label": "ERROR", "value": "ERROR"}
                                           ])
            except:
                logger.warning('Unable to update database: flow_logging_level')

    async def update_version(self):
        current_version = self.cbpi.config.get(self.name + "_update", None)
        if current_version is None or current_version != self.version:
            try:
                await self.cbpi.config.add(self.name + "_update", self.version, 
                                           type=ConfigType.STRING, 
                                           description='Flowmeter Plugin Version', 
                                           source='hidden')
            except Exception as e:
                logger.warning('Unable to update database: version')
                logger.warning(e)

class ADCFlowVolumeSensor(CBPiSensor):
    def __init__(self, cbpi, id, props):
        super(ADCFlowVolumeSensor, self).__init__(cbpi, id, props)
        self.adc_pin = int(props.get("ADC Pin", 0))
        self.sensor_mode = props.get("Sensor Mode", "Flow")
        self.display = props.get("Display", "Total volume")
        self.simulation_mode = str(props.get("Simulation Mode", "False")).lower() == "true"
        self.value = 0
        self.total_volume = 0
        self.last_time = time.time()
        self.flow_constant = float(props.get("Flow Constant", 7.5))  # Pulses per liter

    async def on_start(self):
        if not self.simulation_mode:
            try:
                # Assuming the board is globally accessible
                await board.set_pin_mode_analog_input(self.adc_pin)
                logger.info(f"ADC pin {self.adc_pin} initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize ADC pin {self.adc_pin}: {str(e)}")
        else:
            logger.info("Sensor running in simulation mode")

    async def read_adc(self):
        if self.simulation_mode:
            return random.uniform(0, 1023)  # Simulating 10-bit ADC
        
        try:
            value = await board.analog_read(self.adc_pin)
            return value
        except Exception as e:
            logger.error(f"Error reading ADC pin {self.adc_pin}: {str(e)}")
            return 0

    def adc_to_flow(self, adc_value):
        # Convert ADC value to flow rate (L/min)
        # This is a placeholder conversion. Adjust based on your flow meter's characteristics
        return adc_value / 1023 * (60 / self.flow_constant)

    async def run(self):
        while self.running:
            adc_value = await self.read_adc()
            flow_rate = self.adc_to_flow(adc_value)
            
            current_time = time.time()
            time_diff = current_time - self.last_time
            volume_increment = flow_rate * (time_diff / 60)  # Convert to liters
            
            self.total_volume += volume_increment
            
            if self.sensor_mode == "Flow":
                if self.display == "Flow, unit/s":
                    self.value = self.convert(flow_rate / 60)  # Convert to L/s
                else:  # "Total volume"
                    self.value = self.convert(self.total_volume)
            else:  # "Volume" mode
                self.value = self.convert(self.total_volume)
            
            self.push_update(self.value)
            self.last_time = current_time
            await asyncio.sleep(1)

    def convert(self, value):
        unit = self.cbpi.config.get("flowunit", "L")
        if unit == "gal(us)":
            value = value * 0.264172052
        elif unit == "gal(uk)":
            value = value * 0.219969157
        elif unit == "qt":
            value = value * 1.056688
        return round(value, 2)

    def get_state(self):
        return dict(value=self.value)

    def reset(self):
        self.total_volume = 0
        self.value = 0
        logger.info("Flow sensor reset")
        return "OK"

@parameters([
    Property.Number(label="Volume", description="Volume limit for this step", configurable=True),
    Property.Actor(label="Actor", description="Actor to switch media flow on and off"),
    Property.Sensor(label="Sensor"),
    Property.Select(label="Reset", options=["Yes", "No"], description="Reset Flowmeter when done")
])
class FlowStep(CBPiStep):
    async def on_timer_done(self, timer):
        self.summary = ""
        self.cbpi.notify(self.name, f'Step finished. Transferred {round(self.current_volume, 2)} {self.unit}.', NotificationType.SUCCESS)
        if self.resetsensor == "Yes" and self.sensor and self.sensor.instance:
            await self.sensor.instance.reset()

        if self.actor is not None:
            await self.actor_off(self.actor)
        await self.next()

    async def on_timer_update(self, timer, seconds):
        await self.push_update()

    async def on_start(self):
        self.unit = self.cbpi.config.get("flowunit", "L")
        self.actor = self.props.get("Actor", None)
        self.target_volume = float(self.props.get("Volume", 0))
        self.flowsensor = self.props.get("Sensor", None)
        self.sensor = self.get_sensor(self.flowsensor)
        self.resetsensor = self.props.get("Reset", "Yes")

        if not self.sensor:
            logger.error(f"Sensor {self.flowsensor} not found.")
            self.cbpi.notify(self.name, f'Sensor {self.flowsensor} not found.', NotificationType.ERROR)
            await self.next()
            return

        if self.sensor.instance:
            await self.sensor.instance.reset()

        if self.timer is None:
            self.timer = Timer(1, on_update=self.on_timer_update, on_done=self.on_timer_done)

    async def on_stop(self):
        if self.timer is not None:
            await self.timer.stop()
        self.summary = ""
        if self.actor is not None:
            await self.actor_off(self.actor)
        await self.push_update()

    async def reset(self):
        self.timer = Timer(1, on_update=self.on_timer_update, on_done=self.on_timer_done)
        if self.actor is not None:
            await self.actor_off(self.actor)
        if self.resetsensor == "Yes" and self.sensor and self.sensor.instance:
            await self.sensor.instance.reset()

    async def run(self):
        if self.actor is not None:
            await self.actor_on(self.actor)
        self.summary = ""
        await self.push_update()
        while self.running:
            self.current_volume = self.get_sensor_value(self.flowsensor).get("value")
            self.summary = f"Volume: {self.current_volume}"
            await self.push_update()

            if self.current_volume >= self.target_volume and not self.timer.is_running:
                self.timer.start()
                self.timer.is_running = True

            await asyncio.sleep(0.2)

        return StepResult.DONE