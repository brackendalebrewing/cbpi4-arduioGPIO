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
                





class ADCFlowVolumeSensor(CBPiSensor):
    def __init__(self, cbpi, id, props):
        super(ADCFlowVolumeSensor, self).__init__(cbpi, id, props)

        self.adc_pin = int(props.get("ADC Pin", 0))
        self.sensor_mode = props.get("Sensor Mode", "Flow")
        self.simulation_mode = str(props.get("Simulation Mode", "False")).lower() == "true"
        self.alpha = float(props.get("Alpha", 0.2))  # Smoothing factor for EMA
        self.unit_type = props.get("Unit Type", "L")  # Unit type selection
        self.ema_flow_rate = None
        self.total_volume = 0
        self.last_time = time.time()

        # Zero offset and polynomial coefficients (initialized)
        self.zero_offset = 0
        self.poly_coefficients = None

        # Path to the plugin directory
        plugin_directory = os.path.dirname(__file__)
        self.calibration_file = os.path.join(plugin_directory, 'flowmeter_calibration.json')

        # Log the calibration file path
        logger.info(f"Calibration file will be saved at: {self.calibration_file}")

        # Load calibration data from JSON (or create default if not found)
        self.load_calibration_data()

    def load_calibration_data(self):
        """
        Load calibration data (ADC values, flow rates, zero offset) from a JSON file.
        If the file is not found, create a default calibration file and notify the user.
        This method also computes the polynomial coefficients for flow rate calculation.
        """
        try:
            with open(self.calibration_file, 'r') as file:
                calibration_data = json.load(file)
                self.zero_offset = calibration_data.get("zero_offset", 0)
                adc_values = calibration_data["adc_values"]
                flow_rates = calibration_data["flow_rates"]

                # Fit a second-degree polynomial (quadratic) based on the calibration data
                self.poly_coefficients = np.polyfit(adc_values, flow_rates, 2)

                logger.info("Calibration data successfully loaded from %s. Polynomial coefficients: %s", self.calibration_file, self.poly_coefficients)

        except FileNotFoundError:
            # Calibration file not found, create a default one
            logger.warning("Calibration file not found. Creating a default calibration file in %s.", self.calibration_file)
            self.create_default_calibration_file()

        except (KeyError, ValueError) as e:
            logger.error("Failed to load calibration data due to invalid format: %s", e)

    def create_default_calibration_file(self):
        """
        Create a default calibration JSON file with basic calibration data.
        """
        default_data = {
            "zero_offset": 0,  # No offset for the default
            "adc_values": [0, 210, 500, 770, 1000],  # Default ADC values
            "flow_rates": [0, 5.20, 11.25, 17.05, 22.0]  # Default flow rates
        }

        try:
            with open(self.calibration_file, 'w') as file:
                json.dump(default_data, file, indent=4)
                logger.info("Default calibration file created at '%s'. Please update for accurate calibration.", self.calibration_file)

            # Load the default data for use
            self.zero_offset = default_data["zero_offset"]
            adc_values = default_data["adc_values"]
            flow_rates = default_data["flow_rates"]

            # Fit a second-degree polynomial (quadratic)
            self.poly_coefficients = np.polyfit(adc_values, flow_rates, 2)

        except IOError as e:
            logger.error("Failed to create default calibration file: %s", e)

    def adc_to_flow(self, adc_value):
        """
        Convert an ADC value to a flow rate using the calibrated polynomial coefficients and zero offset.
        """
        # Apply zero offset to the ADC value
        calibrated_adc_value = adc_value - self.zero_offset

        # If polynomial coefficients are loaded, calculate the flow rate
        if self.poly_coefficients is not None:
            flow_rate = np.polyval(self.poly_coefficients, calibrated_adc_value)
            return max(0, flow_rate)  # Ensure flow rate is non-negative
        else:
            logger.warning("Polynomial coefficients not loaded. Cannot calculate flow rate.")
            return 0

    async def read_adc(self):
        """
        Read the ADC value from the sensor (simulation mode or real sensor).
        In simulation mode, returns a fake ADC value.
        """
        if self.simulation_mode:
            return np.random.uniform(0, 1023)  # Simulate a 10-bit ADC range
        try:
            return self.current_adc_value  # Replace this with actual ADC reading logic
        except AttributeError:
            logger.error("ADC value not set by callback yet")
            return 0

    async def run(self):
        """
        The main loop that reads ADC values and calculates the flow rate in real-time.
        """
        while self.running:
            adc_value = await self.read_adc()  # Read the ADC value
            flow_rate = self.adc_to_flow(adc_value)  # Calculate the flow rate using the polynomial

            # Apply smoothing (EMA) to the flow rate
            self.update_ema(flow_rate)

            # Volume calculation using the smoothed flow rate
            current_time = time.time()
            time_diff = current_time - self.last_time
            volume_increment = self.ema_flow_rate * (time_diff / 60)  # Convert to liters/minute

            self.total_volume += volume_increment

            # Set value to be displayed based on the mode (ADC, Flow, or Volume)
            if self.sensor_mode == "ADC":
                self.value = adc_value  # Show raw ADC value
            elif self.sensor_mode == "Flow":
                self.value = round(flow_rate, 2)  # Show current flow rate
            else:  # Volume mode
                self.value = round(self.total_volume, 2)  # Show total volume

            # Push the updated value to the system
            self.push_update(self.value)
            self.last_time = current_time
            await asyncio.sleep(1)

    def update_ema(self, flow_rate):
        """
        Update the Exponential Moving Average (EMA) for flow rate smoothing.
        """
        if self.ema_flow_rate is None:
            self.ema_flow_rate = flow_rate  # Initialize with the first value
        else:
            self.ema_flow_rate = self.alpha * flow_rate + (1 - self.alpha) * self.ema_flow_rate

    

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
