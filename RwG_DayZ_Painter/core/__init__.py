"""
RwG DayZ conversion core (bundled inside the plugin).

This package __init__ deliberately does NOT import ``conversion`` (which needs
numpy + Pillow). That keeps ``rvmat_writer`` and ``paa_tools`` importable inside
Substance Painter's embedded Python, which has neither. The numpy-heavy
``conversion`` module is only imported by ``cli.py`` when run in an external
Python.
"""
