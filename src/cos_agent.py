#
# Copyright 2023 Canonical, Ltd.
#
from typing import Callable

from charms.grafana_agent.v0.cos_agent import *


class Provider(COSAgentProvider):
    @property
    def _scrape_jobs(self) -> List[Dict]:
        return self._metrics_endpoints()
