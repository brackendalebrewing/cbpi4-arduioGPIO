from setuptools import setup, find_packages

setup(
    name='cbpi4-arduinoGPIO',
    version='0.1.0',
    description='CraftBeerPi4 plugin for Arduino GPIO integration',
    author='Cooper',
    author_email='squamishcoop@gmail.com',
    url='https://github.com/brackendalebrewing/Arduino_GPIO.git',
    include_package_data=True,
    packages=find_packages(),  # Automatically find packages
    package_data={
        '': ['*.txt', '*.rst', '*.yaml'],
        'cbpi4-arduinoGPIO': ['*', '*.txt', '*.rst', '*.yaml']
    },
    install_requires=[
        'telemetrix-aio',
        'pyserial'
    ],
    entry_points={
        'cbpi4': ['cbpi4-arduinoGPIO = cbpi4_arduinoGPIO:setup']
    }
)
