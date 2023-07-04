#
# Copyright 2023 Canonical, Ltd.
#

from unittest import mock

import ops
import ops.testing
import pytest
from conftest import Environment


def test_install(e: Environment):
    e.harness.update_config({"role": "worker"})
    e.harness.begin_with_initial_hooks()

    e.util.install_required_packages.assert_called_once_with()
    e.microk8s.install.assert_called_once_with()
    e.microk8s.wait_ready.assert_called_once_with()

    assert not e.harness.charm.model.unit.opened_ports()

    assert isinstance(e.harness.charm.model.unit.status, ops.model.WaitingStatus)


@pytest.mark.parametrize("is_leader", [True, False])
def test_control_plane_relation(e: Environment, is_leader: bool):
    e.microk8s.get_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.gethostname.return_value = "fakehostname"

    e.harness.update_config({"role": "worker"})
    e.harness.set_leader(is_leader)
    e.harness.begin_with_initial_hooks()
    unit = e.harness.charm.model.unit
    assert isinstance(unit.status, ops.model.WaitingStatus)

    e.microk8s.wait_ready.reset_mock()

    rel_id = e.harness.add_relation("control-plane", "microk8s-cp")
    e.harness.add_relation_unit(rel_id, "microk8s-cp/0")
    e.harness.update_relation_data(rel_id, "microk8s-cp", {"join_url": "fakejoinurl"})

    e.microk8s.join.assert_called_once_with("fakejoinurl", True)
    e.microk8s.wait_ready.assert_called_once_with()
    e.microk8s.get_unit_status.assert_called_once_with("fakehostname")
    assert unit.status == ops.model.ActiveStatus("fakestatus")
    assert e.harness.get_relation_data(rel_id, e.harness.charm.unit)["hostname"] == "fakehostname"

    e.harness.remove_relation(rel_id)
    e.microk8s.uninstall.assert_called_once_with()

    assert isinstance(unit.status, ops.model.WaitingStatus)

    # after joining, ensure microk8s is installed
    e.microk8s.install.reset_mock()
    rel_id = e.harness.add_relation("control-plane", "microk8s-cp")
    e.harness.add_relation_unit(rel_id, "microk8s-cp/0")
    e.microk8s.install.assert_called_once_with()


def test_control_plane_relation_invalid(e: Environment):
    e.microk8s.get_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.gethostname.return_value = "fakehostname"

    e.harness.update_config({"role": "worker"})
    e.harness.begin_with_initial_hooks()
    assert isinstance(e.harness.charm.model.unit.status, ops.model.WaitingStatus)

    rel_id = e.harness.add_relation("control-plane", "microk8s")
    e.harness.add_relation_unit(rel_id, "microk8s/0")
    e.harness.update_relation_data(rel_id, "microk8s", {"not_a_join_url": "fakejoinurl"})

    assert e.harness.get_relation_data(rel_id, e.harness.charm.unit)["hostname"] == "fakehostname"

    e.microk8s.join.assert_not_called()
    assert isinstance(e.harness.charm.model.unit.status, ops.model.WaitingStatus)

    e.harness.remove_relation_unit(rel_id, "microk8s/0")
    e.harness.remove_relation(rel_id)

    e.microk8s.uninstall.assert_not_called()
    assert isinstance(e.harness.charm.model.unit.status, ops.model.WaitingStatus)


@pytest.mark.parametrize("is_leader", [True, False])
def test_control_plane_relation_departed(e: Environment, is_leader: bool):
    e.microk8s.get_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.gethostname.return_value = "fakehostname"

    e.harness.update_config({"role": "worker"})
    e.harness.set_leader(is_leader)
    e.harness.begin_with_initial_hooks()

    e.microk8s.wait_ready.reset_mock()

    unit = e.harness.charm.model.unit
    assert isinstance(unit.status, ops.model.WaitingStatus)

    rel_id = e.harness.add_relation("control-plane", "microk8s-cp")
    e.harness.add_relation_unit(rel_id, "microk8s-cp/0")
    e.harness.add_relation_unit(rel_id, "microk8s-cp/1")
    e.harness.update_relation_data(rel_id, "microk8s-cp", {"join_url": "fakejoinurl"})

    e.microk8s.join.assert_called_once_with("fakejoinurl", True)
    e.microk8s.wait_ready.assert_called_once_with()
    e.microk8s.get_unit_status.assert_called_once_with("fakehostname")
    assert unit.status == ops.model.ActiveStatus("fakestatus")
    assert e.harness.get_relation_data(rel_id, e.harness.charm.unit)["hostname"] == "fakehostname"

    e.harness.remove_relation_unit(rel_id, "microk8s-cp/1")
    e.microk8s.uninstall.assert_not_called()

    assert unit.status == ops.model.ActiveStatus("fakestatus")


@pytest.mark.parametrize("is_leader", (True, False))
def test_metrics_relation(e: Environment, is_leader: bool):
    e.microk8s.get_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.gethostname.return_value = "fakehostname"
    e.metrics.build_scrape_jobs.return_value = {"fakekey": "fakevalue"}
    e.metrics.get_bearer_token.return_value = "faketoken"

    e.harness.add_network("10.10.10.10")
    e.harness.update_config({"role": "worker"})
    e.harness.set_leader(True)
    e.harness.begin_with_initial_hooks()

    e.harness.set_leader(is_leader)

    e.metrics.apply_required_resources.assert_not_called()
    e.metrics.get_bearer_token.assert_not_called()
    e.metrics.build_scrape_jobs.assert_not_called()

    worker_rel_id = e.harness.add_relation("control-plane", "microk8s-cp")
    e.harness.add_relation_unit(worker_rel_id, "microk8s-cp/0")

    metrics_rel_id = e.harness.add_relation("metrics", "prometheus")
    e.harness.add_relation_unit(metrics_rel_id, "prometheus/0")

    e.MetricsEndpointProvider.assert_called_once_with(
        e.harness.charm,
        "metrics",
        refresh_event=mock.ANY,
        lookaside_jobs_callable=e.harness.charm._build_scrape_jobs,
    )

    e.metrics.apply_required_resources.assert_not_called()
    e.metrics.get_bearer_token.assert_not_called()
