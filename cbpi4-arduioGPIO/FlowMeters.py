import logging
import asyncio
import random
import time
from cbpi.api import *
from cbpi.api import action
from cbpi.api.dataclasses import NotificationAction, NotificationType
from cbpi.api.dataclasses import Sensor, Kettle, Props
from cbpi.api.config import ConfigType
import numpy as np
from .TelemetrixAioService import TelemetrixAioService

from .shared import flowmeter_data 

logger = logging.getLogger(__name__)

class Flowmeter_Config(CBPiExtension):
    def __init__(self, cbpi):
        self.cbpi = cbpi
        self.name = "cbpi4-flowmeter"
        self.version = "0.0.1"
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
                



@parameters([
    Property.Number(label="ADC Pin", configurable=True, description="The ADC pin number on the Arduino board"),
    Property.Select(label="Sensor Mode", options=["Flow", "Volume", "ADC"], description="The mode of the sensor"),
    Property.Select(label="Simulation Mode", options=["True", "False"], description="Enable simulation mode"),
    Property.Number(label="Alpha", configurable=True, description="Smoothing factor for EMA (0 < alpha <= 1)", default_value=0.2),
    Property.Select(label="Unit Type", options=["L", "gal(us)", "gal(uk)", "qt"], description="Select the unit of measurement")
])
class ADCFlowVolumeSensor(CBPiSensor):
    def __init__(self, cbpi, id, props):
        super(ADCFlowVolumeSensor, self).__init__(cbpi, id, props)
        self.adc_pin = int(props.get("ADC Pin", 0))
        self.sensor_mode = props.get("Sensor Mode", "Flow")
        self.simulation_mode = str(props.get("Simulation Mode", "False")).lower() == "true"
        self.value = 0
        self.total_volume = 0
        self.last_time = time.time()
        self.alpha = float(props.get("Alpha", 0.2))  # Smoothing factor for EMA
        self.ema_flow_rate = None  # Initialize EMA flow rate as None
        self.current_adc_value = 0
        self.unit_type = props.get("Unit Type", "L")  # Unit type selection

        # Polynomial coefficients for flow rate calculation
        self.poly_coefficients = [-1.31526155e-06,  2.31059924e-02,  1.35807496e-01]

    def update_ema(self, flow_rate):
        if self.ema_flow_rate is None:
            self.ema_flow_rate = flow_rate  # Initialize with the first value
        else:
            self.ema_flow_rate = self.alpha * flow_rate + (1 - self.alpha) * self.ema_flow_rate

    async def on_start(self):
        if not self.simulation_mode:
            try:
                await TelemetrixAioService.initialize(self.cbpi.config.get)
                self.board = TelemetrixAioService.get_arduino_instance()
                await self.board.set_pin_mode_analog_input(self.adc_pin, 1, self.analog_callback)
                logger.info(f"ADC pin {self.adc_pin} initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize ADC pin {self.adc_pin}: {str(e)}")
        else:
            logger.info("Sensor running in simulation mode")

    async def analog_callback(self, data):
        self.current_adc_value = data[2]
        formatted_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(data[3]))
        logger.debug(f'Analog Call Input Callback: pin={data[1]}, Value={data[2]} Time={formatted_time} (Raw Time={data[3]})')

    async def read_adc(self):
        if self.simulation_mode:
            fake = random.uniform(0, 1023)  # Simulating 10-bit ADC
            return fake
            
        try:
            return self.current_adc_value
        except AttributeError:
            logger.error("ADC value not set by callback yet")
            return 0

    def adc_to_flow(self, adc_value):
        # Calculate the flow rate using the polynomial equation
        flow_rate = np.polyval(self.poly_coefficients, adc_value)
        return max(0, flow_rate)  # Ensure flow rate is not negative

    async def run(self):
        while self.running:
            adc_value = await self.read_adc()
            flow_rate = self.adc_to_flow(adc_value)  # Calculate instantaneous flow rate

            # Only use EMA for volume calculation, not for instantaneous flow rate display
            self.update_ema(flow_rate)

            # Volume calculation using EMA-smoothed flow rate
            current_time = time.time()
            time_diff = current_time - self.last_time
            volume_increment = self.ema_flow_rate * (time_diff / 60)  # Convert to liters

            self.total_volume += volume_increment

            # Display logic
            if self.sensor_mode == "ADC":
                self.value = adc_value  # Display raw ADC value
            elif self.sensor_mode == "Flow":
                self.value = self.convert(flow_rate)  # Display raw instantaneous flow rate
            else:  # "Volume" mode
                self.value = self.convert(self.total_volume)  # Display total volume

            # Update the global dictionary with the latest flow rate
            flowmeter_data[self.id] = flow_rate

            self.push_update(self.value)
            self.last_time = current_time
            await asyncio.sleep(1)

    def convert(self, value):
        if self.unit_type == "gal(us)":
            value = value * 0.264172052
        elif self.unit_type == "gal(uk)":
            value = value * 0.219969157
        elif self.unit_type == "qt":
            value = value * 1.056688
        return round(value, 2)

    def get_state(self):
        return dict(value=self.value)

    def reset(self):
        self.total_volume = 0
        self.value = 0
        self.ema_flow_rate = None  # Reset the EMA calculation
        logger.info("Flow sensor reset")
        return "OK"
    

@parameters([
    Property.Sensor(label="Flow Sensor", description="Select the flow sensor to calculate volume from."),
    Property.Select(label="Flow Unit", options=['Liters', 'Gallons'], description="Select the unit of flow measurement."),
    Property.Select(label="Volume Unit", options=['Liters', 'Gallons'], description="Select the unit of volume output."),
    Property.Number(label="Alpha", configurable=True, default_value=0.2, description="Smoothing factor for EMA (0 < Alpha <= 1)")
])
class VolumeFromFlowSensor(CBPiSensor):

    def __init__(self, cbpi, id, props):
        super(VolumeFromFlowSensor, self).__init__(cbpi, id, props)
        self.value = 0      
        self.sensor = self.props.get("Flow Sensor", None)
        self.flow_unit = self.props.get("Flow Unit", "Liters")
        self.volume_unit = self.props.get("Volume Unit", "Liters")
        self.alpha = float(self.props.get("Alpha", 0.2))  # Smoothing factor for EMA
        self.ema_flow_rate = None
        self.total_volume = 0
        self.last_time = time.time()  # Initialize last time
        self.flow_conversion_factor = 3.78541 if self.flow_unit == 'Gallons' else 1
        self.volume_conversion_factor = 0.264172 if self.volume_unit == 'Gallons' else 1
        
        logging.info(f"VolumeFromFlowSensor initialized with sensor: {self.sensor}, flow unit: {self.flow_unit}, volume unit: {self.volume_unit}, alpha: {self.alpha}")

    def get_state(self):
        return dict(value=self.value)

    @action(key="ResetVolume", parameters=[])
    async def reset_volume(self, **kwargs):
        """
        Reset the total volume to 0.
        """
        self.reset()
        logging.info("Flow volume has been reset to 0.")

    def reset(self):
        """
        Resets the volume to 0 and updates the state.
        """
        self.total_volume = 0
        self.value = 0
        self.push_update(self.value)

    async def run(self):
        while self.running:
            try:
                if self.sensor:
                    sensor_value = self.cbpi.sensor.get_sensor_value(self.sensor).get("value")
                    if sensor_value is not None:
                        sensor_value *= self.flow_conversion_factor  # Convert flow unit if necessary
                        
                        # Update EMA of the flow rate
                        self.update_ema(sensor_value)
                        
                        # Volume calculation using EMA-smoothed flow rate
                        current_time = time.time()
                        time_diff = current_time - self.last_time
                        volume_increment = self.ema_flow_rate * (time_diff / 60)
                        self.total_volume += volume_increment
                        self.last_time = current_time

                        self.value = round(self.total_volume * self.volume_conversion_factor, 2)  # Convert volume unit if necessary
                    else:
                        logging.info(f"No value fetched from the selected flow sensor (ID: {self.sensor}), check connection and setup")
                else:
                    logging.info("No flow sensor selected for volume calculation")

            except Exception as e:
                logging.error(f"Error in VolumeFromFlowSensor plugin (ID: {self.sensor}): {e}")

            self.push_update(self.value)
            await asyncio.sleep(1)

    def update_ema(self, flow_rate):
        if self.ema_flow_rate is None:
            self.ema_flow_rate = flow_rate  # Initialize with the first value
        else:
            self.ema_flow_rate = self.alpha * flow_rate + (1 - self.alpha) * self.ema_flow_rate



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
