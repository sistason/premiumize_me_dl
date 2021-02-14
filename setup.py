#!/usr/bin/env python

from distutils.core import setup
from setuptools import find_packages

setup(name='Premiumize.me API',
      version='1.1',
      description='Download/Upload your premiumize.me torrents via cli',
      author='Sistason',
      url='https://github.com/sistason/premiumize_me_dl',
      classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)',
        'Programming Language :: Python :: 3',
      ],
      packages=find_packages(),
      )
