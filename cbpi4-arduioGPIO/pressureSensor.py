import os
import logging
import asyncio
import time
from cbpi.api import *
from cbpi.api.dataclasses import NotificationAction, NotificationType
from collections import deque

from .TelemetrixAioService import TelemetrixAioService

logger = logging.getLogger(__name__)




@parameters([
    Property.Select(label="ADCPin", options=[0,1, 2, 3, 4, 5], description="Select the ADC pin (1-5)"),
    Property.Select("sensorType", options=["ADC",  "Pressure", "Liquid Level", "Volume"], description="Select which type of data to register for this sensor"),
    Property.Select("pressureType", options=["kPa", "PSI"]),
    Property.Number("adcLow", configurable=True, default_value=0, description="ADC value at minimum pressure, usually 0"),
    Property.Number("adcHigh", configurable=True, default_value=1024, description="ADC value at maximum pressure, usually 1024"),
    Property.Number("pressureLow", configurable=True, default_value=0, description="Pressure value at minimum ADC value, value in kPa"),
    Property.Number("pressureHigh", configurable=True, default_value=10, description="Pressure value at maximum ADC value, value in kPa"),
    Property.Number("sensorHeight", configurable=True, default_value=0, description="Location of Sensor from the bottom of the kettle in inches"),
    Property.Number("kettleDiameter", configurable=True, default_value=0, description="Diameter of kettle in inches"),
    Property.Select(label="Simulation Mode", options=["True", "False"], description="Enable simulation mode"),
    Property.Select(label="Volume Unit", options=["Gallons", "Liters"], description="Select the unit for volume measurement"),
    Property.Number("sampleRate", configurable=True, default_value=1, description="Sample rate in Hz"),
    Property.Number("averageWindowSize", configurable=True, default_value=5, description="Number of samples to average for running average")
])
class PressureSensor(CBPiSensor):

    def __init__(self, cbpi, id, props):
        super(PressureSensor, self).__init__(cbpi, id, props)
        self.value = 0
        # ADC related properties
        self.adc_pin = int(props.get("ADCPin", 1))
        self.simulation_mode = str(props.get("Simulation Mode", "False")).lower() == "true"
        self.current_adc_value = None
        
        # Initialize the simulated ADC value for the simulation mode
        self.simulated_adc_value = 0

        # Variables to be used with calculations
        self.GRAVITY = 9.807
        self.PI = 3.1415
        # Conversion values
        self.kpa_psi = 0.145
        self.bar_psi = 14.5038
        self.inch_mm = 25.4
        self.gallons_cubicinch = 231
        self.liters_cubicinch = 61.0237
        
        self.sensor_type = self.props.get("sensorType", "Liquid Level")
        self.sensorHeight = float(self.props.get("sensorHeight", 0))
        self.kettleDiameter = float(self.props.get("kettleDiameter", 0))
        self.pressureHigh = self.convert_pressure(int(self.props.get("pressureHigh", 10)))
        self.pressureLow = self.convert_pressure(int(self.props.get("pressureLow", 0)))
        self.volume_unit = self.props.get("Volume Unit", "Gallons")
        
        # Assuming the ADC range is from 0 to 1024
        self.adc_max = int(self.props.get("adcHigh", 1024))  # Maximum ADC value
        self.adc_min = int(self.props.get("adcLow", 0))     # Minimum ADC value

        # Calculate the linear conversion factors based on ADC values
        self.calcX = self.adc_max - self.adc_min
        self.calcM = (self.pressureHigh - self.pressureLow) / self.calcX
        self.calcB = self.pressureLow

        # Sample rate and running average setup
        self.sample_rate = float(self.props.get("sampleRate", 1))
        self.sample_interval = 1 / self.sample_rate  # Calculate interval based on rate
        self.average_window_size = int(self.props.get("averageWindowSize", 5))
        self.adc_values = deque(maxlen=self.average_window_size)

    def convert_pressure(self, value):
        if self.props.get("pressureType", "kPa") == "PSI":
            return value * self.kpa_psi
        else:
            return value

    def convert_bar(self, value):
        if self.props.get("pressureType", "kPa") == "PSI":
            return value / self.bar_psi
        else:
            return value / 100

    async def on_start(self):
        if not self.simulation_mode:
            try:
                await TelemetrixAioService.initialize(self.cbpi.config.get)
                self.board = TelemetrixAioService.get_arduino_instance()
                await self.board.set_pin_mode_analog_input(self.adc_pin,5, self.analog_callback)
                logger.debug(f"ADC pin {self.adc_pin} initialized successfully")
                await self.board.disable_analog_reporting(self.adc_pin)  # Initially disable reporting
            except Exception as e:
                logger.error(f"Failed to initialize ADC pin {self.adc_pin}: {str(e)}")
        else:
            logger.info("Pressure sensor running in simulation mode")

    async def analog_callback(self, data):
        self.current_adc_value = data[2]
        formatted_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(data[3]))
        logger.debug(f'pressure Analog Call Input Callback: pin={data[1]}, Value={data[2]} Time={formatted_time} ')

        await self.board.disable_analog_reporting(self.adc_pin)  # Disable immediately after capturing the first sample

    async def read_adc(self):
        if self.simulation_mode:
            # Increment the simulated ADC value
            self.simulated_adc_value += 1

            # Ensure the value stays within the range of 0 to 1024
            if self.simulated_adc_value >= 1024:
                self.simulated_adc_value = 0
            logger.debug(f"simulated_adc_value--> {self.simulated_adc_value} ")
            return self.simulated_adc_value

        if self.current_adc_value is not None:
            value = self.current_adc_value
            self.current_adc_value = None  # Reset for the next sampling period
            return value
        else:
            logger.error("ADC value not captured yet")
            return 0

    def calculate_running_average(self, new_value):
        self.adc_values.append(new_value)
        average_value = sum(self.adc_values) / len(self.adc_values)
        logger.debug(f"pressure Running Average ADC Value: {average_value}")
        return average_value

    async def run(self):
        while self.running:
            try:
                await self.board.enable_analog_reporting(self.adc_pin)
                await asyncio.sleep(0.1)  # Allow a brief time to capture a single sample
                adc_value = await self.read_adc()

                average_adc_value = self.calculate_running_average(adc_value)

                pressureValue = (self.calcM * average_adc_value) + self.calcB
                liquidLevel = self.calculate_liquid_level(pressureValue)
                volume = self.calculate_volume(liquidLevel)
                logger.debug(f"run   Sensor {self.id} - liquid Vol liters--> {volume}") 
                
                sensor_type = self.props.get("sensorType", "Liquid Level")
                logger.debug(f"run   Sensor type  {self.id} ---> {sensor_type}") 
                if sensor_type == "ADC":
                    self.value = average_adc_value
                elif sensor_type == "Pressure":
                    self.value = pressureValue
                elif sensor_type == "Liquid Level":
                    self.value = liquidLevel
                elif sensor_type == "Volume":
                    self.value = volume
                else:
                    self.value = average_adc_value  # Default to ADC

                self.push_update(self.value)
            except Exception as e:
                logger.error(f"ADC read error: {str(e)}")
                self.value = None
                self.push_update(self.value)

            await asyncio.sleep(self.sample_interval)  # Use the interval derived from sample rate

    def calculate_liquid_level(self, pressureValue):
        liquidLevel = ((self.convert_bar(pressureValue) / self.GRAVITY) * 100000) / self.inch_mm
        if liquidLevel > 0.49:
            liquidLevel += self.sensorHeight
        logger.debug(f"liquidLevel--> {liquidLevel}")    
        return liquidLevel

    def calculate_volume(self, liquidLevel):
        kettleRadius = self.kettleDiameter / 2
        radiusSquared = kettleRadius * kettleRadius
        volumeCI = self.PI * radiusSquared * liquidLevel
        logger.debug(f"  ******************* calculate_volume--> unit set to {self.volume_unit}")
        if self.volume_unit == "Liters":
            logger.debug(f"Sensor {self.id} - liquid Vol liters--> {volumeCI / self.liters_cubicinch}") 
            return volumeCI / self.liters_cubicinch
        else:
            logger.debug(f"Sensor {self.id} - liquid Vol gal--> {volumeCI / self.gallons_cubicinch}")
            return volumeCI / self.gallons_cubicinch

    def get_state(self):
        return dict(value=self.value)

    def reset(self):
        self.value = 0
        logger.debug("Pressure sensor reset")
        return "OK"

def setup(cbpi):
    cbpi.plugin.register("PressureSensor", PressureSensor)

@parameters([
    Property.Sensor(label="Volume Sensor", description="Select the volume sensor to calculate flow from."),
    Property.Select(label="Flow Unit", options=['Liters/min', 'Gallons/min'], description="Select the unit of flow measurement."),
    Property.Select(label="Volume Unit", options=['Liters', 'Gallons'], description="Select the unit of volume measurement."),
])
class FlowFromVolumeSensor(CBPiSensor):

    def __init__(self, cbpi, id, props):
        super(FlowFromVolumeSensor, self).__init__(cbpi, id, props)
        self.volume_sensor = self.props.get("Volume Sensor", None)
        self.flow_unit = self.props.get("Flow Unit", "Liters/min")
        self.volume_unit = self.props.get("Volume Unit", "Liters")
        self.previous_volume = None
        self.previous_time = time.time()
        self.flow_rate = 0

        # Conversion factors
        self.volume_conversion_factor = 3.78541 if self.volume_unit == 'Gallons' else 1  # Liters to Gallons
        self.flow_conversion_factor = 0.264172 if self.flow_unit == 'Gallons/min' else 1  # Liters/min to Gallons/min

        logging.info(f"FlowFromVolumeSensor initialized with volume sensor: {self.volume_sensor}, volume unit: {self.volume_unit}, flow unit: {self.flow_unit}")

    def get_state(self):
        return dict(value=self.flow_rate)

    async def run(self):
        while self.running:
            try:
                if self.volume_sensor:
                    current_volume = self.cbpi.sensor.get_sensor_value(self.volume_sensor).get("value")
                    current_time = time.time()

                    if current_volume is not None and self.previous_volume is not None:
                        # Convert volume to Liters if necessary
                        current_volume *= self.volume_conversion_factor

                        # Calculate flow rate
                        volume_change = current_volume - self.previous_volume
                        time_change = (current_time - self.previous_time) / 60  # Convert to minutes
                        self.flow_rate = (volume_change / time_change) * self.flow_conversion_factor

                        logging.debug(f"Calculated flow rate: {self.flow_rate} {self.flow_unit}")

                    # Update previous values for next iteration
                    self.previous_volume = current_volume
                    self.previous_time = current_time

                else:
                    logging.info("No volume sensor selected for flow calculation")

            except Exception as e:
                logging.error(f"Error in FlowFromVolumeSensor plugin (ID: {self.volume_sensor}): {e}")

            self.push_update(self.flow_rate)
            await asyncio.sleep(1)
    
