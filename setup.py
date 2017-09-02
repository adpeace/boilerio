from setuptools import setup

setup(name='boilerio',
      version='0.0.1',
      description='A software thermostat and heating control system',
      url='https://github.com/adpeace/boilerio.git',
      author='Andy Peace',
      author_email='andrew.peace@gmail.com',
      license='MIT',
      classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'License :: OSI Approved :: MIT License',
        ],
      packages=['boilerio'],
      scripts=['bin/boiler_to_mqtt', 'bin/boilersim'],
      entry_points={'console_scripts': [
        'scheduler=boilerio.scheduler:main',
        'maintaintemp=boilerio.maintaintemp:main',
        ]},
      setup_requires=['pytest-runner'],
      install_requires=['Flask', 'requests', 'psycopg2', 'paho-mqtt'],
      tests_require=['pytest', 'requests-mock', 'mock'],
      zip_safe=False)
