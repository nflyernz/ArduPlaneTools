from pathlib import Path

import yaml

from .resources import resource_path


class Config:

    def __init__(self, filename):

        path = Path(filename)

        if not path.is_absolute():
            path = resource_path(path)

        self.filename = path

        with open(path, "r") as f:
            self.data = yaml.safe_load(f)

    def get(self, key, default=None):
        """
        Retrieve a configuration value.

        Supports dotted paths, e.g.

            config.get("barometer.smoothing_samples")
            config.get("rangefinder.continuous_seconds")
        """

        value = self.data

        for part in key.split("."):

            if not isinstance(value, dict):
                return default

            if part not in value:
                return default

            value = value[part]

        return value
