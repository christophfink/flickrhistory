#!/usr/bin/env python3
# -*- coding: utf-8 -*-


"""Import global configuration from a default location."""


__all__ = ["Config"]


import os
import os.path
import warnings

import yaml


class Config:
    """
    Global configuration object.

    Tries to load configuration from YAML files in default locations
    (/etc/{module}.yml, ~/.config/{module}.yml, %APPDATA%/{module}.yml,
    ${XDG_CONFIG_HOME}/{module}.yml).

    Configuration file location can be overriden by specifying
    `config_files` or a base name `config_filesBaseName` (replaces
    “{module}” in the file locations listed above)

    Arguments:
        content of the config file

    Args:
        config_files (list of str, optional): override configuration
            file locations
        config_files_basename (str): override configuration file names

    """

    # implementing Config() as a pseudo-singleton:
    # `_config` is a class attribute, it is shared
    # between instances of Config()

    _config = {}

    def __init__(self, config=None, config_files=None, config_files_basename=None):
        """Initialise a Config object, load configuration from file."""
        if not self._config:
            self._config.update(self._load_config(config_files, config_files_basename))
        if config is not None:
            self._config.update(config)

    def _load_config(self, config_files, config_files_basename):
        config = {}

        if config_files is not None:
            if not isinstance(config_files, (list, tuple)):
                config_files = [config_files]

        elif config_files_basename is None:
            config_files_basename = self.__module__.split(".")[0]

            config_files = [
                f"/etc/{config_files_basename}.yml",
                os.path.abspath(
                    os.path.join(
                        (
                            os.environ.get("APPDATA")
                            or os.environ.get("XDG_CONFIG_HOME")
                            or os.path.join(os.environ["HOME"], ".config")
                        ),
                        f"{config_files_basename}.yml",
                    )
                ),
            ]

        for config_file in config_files:
            try:
                config.update(yaml.safe_load(open(config_file, "r", encoding="utf-8")))
            except FileNotFoundError:
                pass

        if config == {}:
            warnings.warn(f"No configuration found in files {', '.join(config_files)}.")

        return config

    def __getitem__(self, pos):
        """Retrieve configuration value."""
        return self._config[pos]

    def __setitem__(self, pos, value):
        """Set configuration value."""
        self._config[pos] = value

    def __iter__(self):
        """Iterate over configuration file entries."""
        return iter(self._config)

    def __enter__(self):
        """Enter config context."""
        return self

    def __exit__(self, *_):
        """Exit config context."""
        pass
