#!/usr/bin/env python

from distutils.core import setup
from setuptools import find_packages

PACKAGES = find_packages()

setup(
    name='Osmosis',
    version='1.0',
    description='A Django app for importing files into a database on the Google AppEngine platform ',
    author='Potato London Ltd',
    url='https://github.com/potatolondon/osmosis',
    packages=PACKAGES,
    include_package_data=True,
    install_requires=[
        'unicodecsv',
        'GoogleAppEngineCloudStorageClient',
    ],
)
