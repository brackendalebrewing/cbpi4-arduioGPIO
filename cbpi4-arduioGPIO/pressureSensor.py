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
    Property.Select(label="ADCPin", options=[0, 1, 2, 3, 4, 5], description="Select the ADC pin (1-5)"),
    Property.Select("sensorType", options=["Liquid Level", "Volume"], description="Select the output data type"),
    Property.Number("adcLow", configurable=True, default_value=0, description="ADC value at minimum liquid level, usually 0"),
    Property.Number("adcHigh", configurable=True, default_value=1024, description="ADC value at maximum liquid level, usually 1024"),
    
    # Sensor Height and Kettle Diameter
    Property.Number("sensorHeight", configurable=True, default_value=0, description="Location of the sensor from the bottom of the kettle"),
    Property.Number("kettleDiameter", configurable=True, default_value=0, description="Diameter of the kettle"),
    
    # Unified Length Unit Selection (applies to both height and diameter)
    Property.Select(label="Length Unit", options=["Centimeters", "Inches"], description="Select the unit for both sensor height and kettle diameter"),
    
    Property.Select(label="Simulation Mode", options=["True", "False"], description="Enable simulation mode"),
    Property.Select(label="Volume Unit", options=["Liters", "Gallons"], description="Select the unit for volume measurement"),
    Property.Number("sampleRate", configurable=True, default_value=1, description="Sample rate in Hz"),
    Property.Number("averageWindowSize", configurable=True, default_value=5, description="Number of samples to average for running average")
])
class PressureSensor(CBPiSensor):

    def __init__(self, cbpi, id, props):
        super(PressureSensor, self).__init__(cbpi, id, props)
        self.value = 0
        self.adc_pin = int(props.get("ADCPin", 1))
        self.simulation_mode = str(props.get("Simulation Mode", "False")).lower() == "true"
        self.current_adc_value = None
        
        # Variables for conversions and calculations
        self.GRAVITY = 9.807
        self.PI = 3.1415
        
        # Sample rate and running average setup
        self.sample_rate = float(self.props.get("sampleRate", 1))
        self.sample_interval = 1 / self.sample_rate  # Calculate interval based on rate
        self.average_window_size = int(self.props.get("averageWindowSize", 5))
        self.adc_values = deque(maxlen=self.average_window_size)

    def convert_length_to_meters(self, length):
        """
        Convert a given length (sensor height or kettle diameter) to meters 
        based on the user-selected 'Length Unit' (Centimeters or Inches).
        """
        length_unit = self.props.get("Length Unit", "Centimeters")
        
        if length_unit == "Inches":
            return length * 0.0254  # Convert inches to meters
        else:
            return length / 100  # Convert centimeters to meters

    def get_sensor_height_in_meters(self):
        """
        Convert sensor height to meters using the unified length unit selection.
        """
        sensor_height = float(self.props.get("sensorHeight", 0))
        return self.convert_length_to_meters(sensor_height)

    def get_kettle_diameter_in_meters(self):
        """
        Convert kettle diameter to meters using the unified length unit selection.
        """
        kettle_diameter = float(self.props.get("kettleDiameter", 0))
        return self.convert_length_to_meters(kettle_diameter)

    async def on_start(self):
        """
        Initialize the TelemetrixAioService and set up the ADC pin.
        """
        if not self.simulation_mode:
            try:
                await TelemetrixAioService.initialize(self.cbpi.config.get)
                self.board = TelemetrixAioService.get_arduino_instance()
                await self.board.set_pin_mode_analog_input(self.adc_pin, 5, self.analog_callback)
                logger.info(f"ADC pin {self.adc_pin} initialized successfully")
                await self.board.disable_analog_reporting(self.adc_pin)  # Disable reporting initially
            except Exception as e:
                logger.error(f"Failed to initialize ADC pin {self.adc_pin}: {str(e)}")
        else:
            logger.info("Pressure sensor running in simulation mode")

    async def analog_callback(self, data):
        """
        Callback for handling ADC data when using TelemetrixAioService.
        """
        self.current_adc_value = data[2]  # ADC value
        formatted_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(data[3]))  # Timestamp
        logger.info(f"Analog Input Callback: pin={data[1]}, Value={data[2]}, Time={formatted_time}")

        # Disable reporting after capturing a sample to minimize noise
        await self.board.disable_analog_reporting(self.adc_pin)

    async def read_adc(self):
        """
        Read the ADC value, either from simulation or actual hardware.
        """
        if self.simulation_mode:
            # Increment the simulated ADC value
            self.simulated_adc_value += 1
            if self.simulated_adc_value >= 1024:
                self.simulated_adc_value = 0
            logger.info(f"Simulated ADC value: {self.simulated_adc_value}")
            return self.simulated_adc_value

        # For actual hardware, return the current ADC value
        if self.current_adc_value is not None:
            value = self.current_adc_value
            self.current_adc_value = None  # Reset for the next sampling period
            logger.info(f"Real ADC value: {value}")
            return value
        else:
            logger.error("ADC value not captured yet")
            return 0

    def calculate_running_average(self, new_value):
        """
        Calculate a running average of the ADC values.
        """
        self.adc_values.append(new_value)
        average_value = sum(self.adc_values) / len(self.adc_values)
        logger.debug(f"Running Average ADC Value: {average_value}")
        return average_value

    async def run(self):
        """
        Main run loop for processing the ADC values and calculating liquid level and volume.
        """
        while self.running:
            try:
                await self.board.enable_analog_reporting(self.adc_pin)
                await asyncio.sleep(0.1)  # Allow a brief time to capture a single sample
                adc_value = await self.read_adc()

                average_adc_value = self.calculate_running_average(adc_value)

                liquid_level_meters = self.calculate_liquid_level(average_adc_value)
                volume = self.calculate_volume(liquid_level_meters)

                # Output the value based on sensor type selection
                sensor_type = self.props.get("sensorType", "Liquid Level")
                if sensor_type == "Liquid Level":
                    self.value = self.convert_height_output(liquid_level_meters)
                elif sensor_type == "Volume":
                    self.value = volume

                self.push_update(self.value)

            except Exception as e:
                logger.error(f"Error during run loop: {str(e)}")
                self.value = None
                self.push_update(self.value)

            await asyncio.sleep(self.sample_interval)

    def calculate_liquid_level(self, adc_value):
        """
        Calculate the liquid level in meters based on the ADC value.
        """
        adc_low = int(self.props.get("adcLow", 0))
        adc_high = int(self.props.get("adcHigh", 1024))
        adc_range = adc_high - adc_low
        liquid_level_meters = (adc_value - adc_low) / adc_range

        # Add sensor height in meters
        liquid_level_meters += self.get_sensor_height_in_meters()

        return liquid_level_meters

    def calculate_volume(self, liquid_level_meters):
        """
        Calculate the volume of liquid based on the liquid level and kettle dimensions.
        """
        kettle_radius_meters = self.get_kettle_diameter_in_meters() / 2
        volume_cubic_meters = self.PI * (kettle_radius_meters ** 2) * liquid_level_meters

        # Convert the volume to the selected output unit (Liters or Gallons)
        if self.props.get("Volume Unit", "Liters") == "Gallons":
            volume_gallons = volume_cubic_meters * 264.172  # 1 cubic meter = 264.172 gallons
            return volume_gallons
        else:
            volume_liters = volume_cubic_meters * 1000  # 1 cubic meter = 1000 liters
            return volume_liters

    def convert_height_output(self, liquid_level_meters):
        """
        Convert the liquid level to the selected output unit (centimeters or inches).
        """
        length_unit = self.props.get("Length Unit", "Centimeters")
        if length_unit == "Inches":
            return liquid_level_meters * 39.37  # Convert meters to inches
        else:
            return liquid_level_meters * 100  # Convert meters to centimeters

    def get_state(self):
        return dict(value=self.value)

    def reset(self):
        """
        Reset the sensor's value.
        """
        self.value = 0
        logger.debug("Pressure sensor reset")
        return "OK"

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
    
