#!/usr/bin/env python3
#
# Copyright 2023 Canonical, Ltd.
#

import json
import logging

from ops import CharmBase, main
from ops.charm import RelationChangedEvent, RelationJoinedEvent

LOG = logging.getLogger(__name__)

import addons


class MicroK8sAddonsCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)

        self.framework.observe(self.on.microk8s_addons_relation_joined, self._set_addons)
        self.framework.observe(self.on.microk8s_addons_relation_changed, self._set_addons)

    def _on_joined(self, event: RelationJoinedEvent):
        if not self.unit.is_leader():
            return

        event.relation.data[self.app] = json.dumps(addons.reconcile(self.config))

    def _on_changed(self, event: RelationChangedEvent):
        LOG.info("joined relation changed, data is %s", event.relation.data[event.relation.app])


if __name__ == "__main__":  # pragma: nocover
    main(MicroK8sAddonsCharm, use_juju_for_storage=True)
