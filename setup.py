import subprocess
from setuptools import setup, find_packages

from pathlib import Path
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(name='boilerio',
      version='0.0.5',
      description='A software thermostat and heating control system',
      url='https://github.com/adpeace/boilerio.git',
      author='Andy Peace',
      author_email='andrew.peace@gmail.com',
      license='MIT',
      long_description=long_description,
      long_description_content_type='text/markdown',
      classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'License :: OSI Approved :: MIT License',
        ],
      packages=find_packages(),
      scripts=['bin/boiler_to_mqtt', 'bin/boilersim'],
      entry_points={'console_scripts': [
        'scheduler=boilerio.scheduler:main',
        ]},
      setup_requires=['pytest-runner'],
      install_requires=[
          'Flask', 'requests', 'psycopg2-binary', 'paho-mqtt',
          'flask_restx', 'pyserial', 'flask-login', 'basicauth',
          'cachecontrol', 'google-auth-oauthlib'],
      tests_require=['pytest', 'requests-mock', 'mock'],
      zip_safe=False)
