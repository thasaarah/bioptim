from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name="bioptim",
    version="2.1.3",
    author="Pariterre",
    author_email="pariterre@hotmail.com",
    description="An optimization framework for Optimal Control Programming in biomechanics",
    long_description=long_description,
    url="https://github.com/bioptim/bioptim",
    packages=[
        ".",
        "bioptim",
        "bioptim/dynamics",
        "bioptim/dynamics/fatigue",
        "bioptim/gui",
        "bioptim/interfaces",
        "bioptim/limits",
        "bioptim/misc",
        "bioptim/optimization",
        "examples",
    ],
    license="LICENSE",
    keywords=["biorbd", "Ipopt", "CasADi", "Optimal control", "biomechanics"],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
    ],
    include_package_data=True,
    python_requires=">=3.7",
    zip_safe=False,
)
