import os

import setuptools


os.environ.setdefault('PBR_VERSION', '0.0.1')


setuptools.setup(
    setup_requires=['pbr>=2.0.0'],
    pbr=True,
)
