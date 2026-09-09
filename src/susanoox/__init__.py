"""Susanoox terminal coding agent."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("susanoox")
except PackageNotFoundError:
    __version__ = "0.0.0+uninstalled"
