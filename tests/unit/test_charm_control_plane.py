#
# Copyright 2023 Canonical, Ltd.
#
import json
import subprocess
from unittest import mock

import ops
import ops.testing
import pytest
from conftest import Environment


@pytest.mark.parametrize("is_leader", [True, False])
def test_install(e: Environment, is_leader: bool):
    e.microk8s.get_unit_status.return_value = ops.model.ActiveStatus("fakestatus")

    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(is_leader)
    e.harness.begin_with_initial_hooks()

    e.util.install_required_packages.assert_called_once_with()
    e.microk8s.install.assert_called_once_with()
    e.microk8s.wait_ready.assert_called_once_with()

    if not is_leader:
        assert isinstance(e.harness.charm.unit.status, ops.model.WaitingStatus)
        e.microk8s.configure_hostpath_storage.assert_not_called()
    else:
        e.microk8s.configure_hostpath_storage.assert_called()
        e.microk8s.disable_cert_reissue.assert_not_called()
        assert e.harness.charm.unit.status == ops.model.ActiveStatus("fakestatus")
        assert e.harness.charm._state.joined

    assert e.harness.charm.model.unit.opened_ports() == {
        ops.model.OpenedPort(protocol="tcp", port=16443),
    }


def test_leader_peer_relation(e: Environment):
    e.microk8s.add_node.return_value = "01010101010101010101010101010101"
    e.microk8s.get_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.gethostname.return_value = "fakehostname"

    e.harness.add_network("10.10.10.10")
    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(True)
    e.harness.begin_with_initial_hooks()

    rel_id = e.harness.charm.model.get_relation("peer").id
    e.harness.add_relation_unit(rel_id, f"{e.harness.charm.app.name}/1")
    e.harness.update_relation_data(rel_id, f"{e.harness.charm.app.name}/1", {"hostname": "f-1"})

    e.microk8s.add_node.assert_called_once_with()
    relation_data = e.harness.get_relation_data(rel_id, e.harness.charm.app)
    assert relation_data["join_url"] == "10.10.10.10:25000/01010101010101010101010101010101"
    assert e.harness.charm._state.hostnames[f"{e.harness.charm.app.name}/1"] == "f-1"

    e.harness.remove_relation_unit(rel_id, f"{e.harness.charm.app.name}/1")
    e.microk8s.remove_node.assert_called_once_with("f-1")


def test_leader_peer_relation_leave(e: Environment):
    e.microk8s.get_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.gethostname.return_value = "fakehostname"
    fakeaddress = "10.10.10.10"

    e.harness.add_network(fakeaddress)
    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(True)
    e.harness.begin_with_initial_hooks()

    rel = e.harness.charm.model.get_relation("peer")
    e.harness.add_relation_unit(rel.id, f"{e.harness.charm.app.name}/1")
    e.harness.update_relation_data(rel.id, f"{e.harness.charm.app.name}/1", {"hostname": "f-1"})
    e.microk8s.get_unit_status.return_value = ops.model.WaitingStatus("waiting for node")

    # NOTE(neoaggelos): mock self departed event
    e.harness.charm.on.peer_relation_departed.emit(
        relation=rel,
        app=e.harness.charm.app,
        unit=e.harness.charm.unit,
        departing_unit_name=e.harness.charm.unit.name,
    )

    relation_data = e.harness.get_relation_data(rel.id, e.harness.charm.app.name)
    assert relation_data["remove_nodes"] == '["fakehostname"]'


def test_leader_control_plane_relation(e: Environment):
    e.microk8s.add_node.return_value = "01010101010101010101010101010101"
    e.microk8s.get_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.gethostname.return_value = "fakehostname"

    e.harness.add_network("10.10.10.10")
    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(True)
    e.harness.begin_with_initial_hooks()

    rel_id = e.harness.add_relation("workers", "microk8s-worker")
    e.harness.add_relation_unit(rel_id, "microk8s-worker/0")
    e.harness.update_relation_data(rel_id, "microk8s-worker/0", {"hostname": "f-1"})

    e.microk8s.add_node.assert_called_once_with()
    relation_data = e.harness.get_relation_data(rel_id, e.harness.charm.app)
    relation_data = e.harness.get_relation_data(rel_id, e.harness.charm.app)
    assert relation_data["join_url"] == "10.10.10.10:25000/01010101010101010101010101010101"
    assert e.harness.charm._state.hostnames["microk8s-worker/0"] == "f-1"

    e.harness.remove_relation_unit(rel_id, "microk8s-worker/0")
    e.microk8s.remove_node.assert_called_once_with("f-1")
    assert e.harness.charm.unit.status == ops.model.ActiveStatus("fakestatus")


def test_follower_peer_relation(e: Environment):
    e.microk8s.get_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.gethostname.return_value = "fakehostname"

    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(True)
    e.harness.begin_with_initial_hooks()
    e.harness.set_leader(False)

    rel_id = e.harness.charm.model.get_relation("peer").id
    e.harness.add_relation_unit(rel_id, f"{e.harness.charm.app.name}/1")
    e.harness.update_relation_data(rel_id, f"{e.harness.charm.app.name}/1", {"hostname": "f-1"})

    relation_data = e.harness.get_relation_data(rel_id, e.harness.charm.app)
    assert "join_url" not in relation_data
    e.microk8s.add_node.assert_not_called()
    assert e.harness.charm._state.hostnames[f"{e.harness.charm.app.name}/1"] == "f-1"

    e.harness.remove_relation_unit(rel_id, f"{e.harness.charm.app.name}/1")
    e.microk8s.remove_node.assert_not_called()


def test_follower_control_plane_relation(e: Environment):
    e.microk8s.get_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.gethostname.return_value = "fakehostname"
    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(True)
    e.harness.begin_with_initial_hooks()
    e.harness.set_leader(False)

    rel_id = e.harness.add_relation("workers", "microk8s-worker")
    e.harness.add_relation_unit(rel_id, "microk8s-worker/0")
    e.harness.update_relation_data(rel_id, "microk8s-worker/0", {"hostname": "f-1"})

    relation_data = e.harness.get_relation_data(rel_id, e.harness.charm.app)
    assert "join_url" not in relation_data
    e.microk8s.add_node.assert_not_called()
    assert e.harness.charm._state.hostnames["microk8s-worker/0"] == "f-1"

    e.harness.remove_relation_unit(rel_id, "microk8s-worker/0")
    e.microk8s.remove_node.assert_not_called()


def test_follower_retrieve_join_url(e: Environment):
    e.microk8s.get_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.gethostname.return_value = "fakehostname"

    e.harness.update_config({"role": "control-plane", "automatic_certificate_reissue": False})
    e.harness.set_leader(False)
    e.harness.begin_with_initial_hooks()

    e.microk8s.disable_cert_reissue.assert_not_called()
    assert not e.harness.charm._state.joined
    e.microk8s.wait_ready.reset_mock()

    rel_id = e.harness.charm.model.get_relation("peer").id
    e.harness.add_relation_unit(rel_id, f"{e.harness.charm.app.name}/1")
    e.harness.update_relation_data(rel_id, e.harness.charm.app.name, {"join_url": "fakejoinurl"})

    e.microk8s.join.assert_called_once_with("fakejoinurl", False)
    e.microk8s.wait_ready.assert_called_once_with()
    e.microk8s.get_unit_status.assert_called_once_with("fakehostname")

    assert e.harness.charm.unit.status == ops.model.ActiveStatus("fakestatus")
    assert e.harness.charm._state.joined


@pytest.mark.parametrize("become_leader", [True, False])
def test_follower_become_leader_remove_departing_nodes(e: Environment, become_leader: bool):
    e.microk8s.get_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.gethostname.return_value = "fakehostname"

    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(False)
    e.harness.begin_with_initial_hooks()

    prel_id = e.harness.charm.model.get_relation("peer").id
    e.harness.add_relation_unit(prel_id, f"{e.harness.charm.app.name}/1")
    e.harness.add_relation_unit(prel_id, f"{e.harness.charm.app.name}/2")
    e.harness.update_relation_data(prel_id, f"{e.harness.charm.app.name}/1", {"hostname": "f-2"})
    e.harness.update_relation_data(prel_id, e.harness.charm.app.name, {"join_url": "fakejoinurl"})

    rel_id = e.harness.add_relation("workers", "microk8s-worker")
    e.harness.add_relation_unit(rel_id, "microk8s-worker/0")
    e.harness.add_relation_unit(rel_id, "microk8s-worker/1")
    e.harness.update_relation_data(rel_id, "microk8s-worker/0", {"hostname": "f-1"})

    if become_leader:
        e.harness.set_leader(become_leader)

    e.harness.remove_relation_unit(rel_id, "microk8s-worker/0")
    e.harness.remove_relation_unit(rel_id, "microk8s-worker/1")
    e.harness.remove_relation_unit(prel_id, f"{e.harness.charm.app.name}/1")
    e.harness.remove_relation_unit(prel_id, f"{e.harness.charm.app.name}/2")

    if become_leader:
        assert sorted(e.microk8s.remove_node.mock_calls) == [mock.call("f-1"), mock.call("f-2")]
    else:
        e.microk8s.remove_node.assert_not_called()

    assert e.harness.charm.unit.status == ops.model.ActiveStatus("fakestatus")


@pytest.mark.parametrize("become_leader", [True, False])
def test_follower_become_leader_remove_already_departed_nodes(e: Environment, become_leader: bool):
    e.microk8s.get_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.gethostname.return_value = "fakehostname"

    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(False)
    e.harness.begin_with_initial_hooks()

    prel_id = e.harness.charm.model.get_relation("peer").id
    e.harness.add_relation_unit(prel_id, f"{e.harness.charm.app.name}/1")
    e.harness.add_relation_unit(prel_id, f"{e.harness.charm.app.name}/2")
    e.harness.update_relation_data(prel_id, f"{e.harness.charm.app.name}/1", {"hostname": "f-2"})

    e.harness.update_relation_data(prel_id, e.harness.charm.app.name, {"join_url": "fakejoinurl"})

    e.harness.update_relation_data(
        prel_id, e.harness.charm.app.name, {"remove_nodes": '["f-1", "f-2", "fakehostname"]'}
    )

    e.harness.set_leader(become_leader)
    if become_leader:
        assert sorted(e.microk8s.remove_node.mock_calls) == [mock.call("f-1"), mock.call("f-2")]
    else:
        e.microk8s.remove_node.assert_not_called()

    assert e.harness.charm.unit.status == ops.model.ActiveStatus("fakestatus")


@pytest.mark.parametrize("is_leader", (True, False))
def test_metrics_relation(e: Environment, is_leader: bool):
    e.microk8s.get_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.gethostname.return_value = "fakehostname"
    e.metrics.build_scrape_configs.return_value = {"fakekey": "fakevalue"}
    e.metrics.get_bearer_token.return_value = "faketoken"

    e.harness.add_network("10.10.10.10")
    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(True)
    e.harness.begin_with_initial_hooks()

    e.harness.set_leader(is_leader)

    e.metrics.apply_required_resources.assert_not_called()
    e.metrics.get_bearer_token.assert_not_called()
    e.metrics.build_scrape_configs.assert_not_called()

    def helper_assert_calls(*args, apply_called=False):
        """helper method for less repetition"""
        if not is_leader:
            e.metrics.apply_required_resources.assert_not_called()
            e.metrics.get_bearer_token.assert_not_called()
            e.metrics.build_scrape_configs.assert_not_called()
            assert e.harness.charm.model.get_relation("metrics").data.get("microk8s") is None

            return

        if apply_called:
            e.metrics.apply_required_resources.assert_called_once_with()
        else:
            e.metrics.apply_required_resources.assert_not_called()

        e.metrics.get_bearer_token.assert_called_once_with()
        e.metrics.build_scrape_configs.assert_called_once_with(*args)

        e.metrics.apply_required_resources.reset_mock()
        e.metrics.get_bearer_token.reset_mock()
        e.metrics.build_scrape_configs.reset_mock()

        relation_data = e.harness.get_relation_data(metrics_rel_id, "microk8s")
        assert json.loads(relation_data["scrape_jobs"]) == {"fakekey": "fakevalue"}
        assert json.loads(relation_data["scrape_metadata"]) == {
            "model": e.harness.model.name,
            "model_uuid": e.harness.model.uuid,
            "application": e.harness.charm.app.name,
        }

    metrics_rel_id = e.harness.add_relation("metrics", "prometheus")
    e.harness.add_relation_unit(metrics_rel_id, "prometheus/0")

    helper_assert_calls(
        "faketoken", [("microk8s/0", "fakehostname", "10.10.10.10")], [], apply_called=True
    )

    # add peer control plane node
    peer_rel_id = e.harness.charm.model.get_relation("peer").id
    e.harness.add_relation_unit(peer_rel_id, "microk8s/1")
    e.harness.update_relation_data(peer_rel_id, "microk8s/1", {"private-address": "fakeaddr2"})
    e.harness.update_relation_data(peer_rel_id, "microk8s/1", {"hostname": "fakehostname2"})

    helper_assert_calls(
        "faketoken",
        [
            ("microk8s/0", "fakehostname", "10.10.10.10"),
            ("microk8s/1", "fakehostname2", "fakeaddr2"),
        ],
        [],
    )

    # add worker node
    rel_id = e.harness.add_relation("workers", "microk8s-worker")
    e.harness.add_relation_unit(rel_id, "microk8s-worker/0")
    e.harness.update_relation_data(
        rel_id, "microk8s-worker/0", {"hostname": "fakehostname3", "private-address": "fakeaddr2"}
    )

    helper_assert_calls(
        "faketoken",
        [
            ("microk8s/0", "fakehostname", "10.10.10.10"),
            ("microk8s/1", "fakehostname2", "fakeaddr2"),
        ],
        [("microk8s-worker/0", "fakehostname3", "fakeaddr2")],
    )

    # remove control plane node
    e.harness.remove_relation_unit(peer_rel_id, "microk8s/1")
    helper_assert_calls(
        "faketoken",
        [("microk8s/0", "fakehostname", "10.10.10.10")],
        [("microk8s-worker/0", "fakehostname3", "fakeaddr2")],
    )

    # remove worker node
    e.harness.remove_relation_unit(rel_id, "microk8s-worker/0")
    helper_assert_calls("faketoken", [("microk8s/0", "fakehostname", "10.10.10.10")], [])

    # failed to retrieve token
    if is_leader:
        e.metrics.build_scrape_configs.return_value = {"fakekey2": "fakevalue2"}
        e.metrics.get_bearer_token.side_effect = subprocess.CalledProcessError("cmd", 1)
        e.harness.add_relation_unit(rel_id, "microk8s-worker/0")
        e.harness.update_relation_data(
            rel_id,
            "microk8s-worker/0",
            {"hostname": "fakehostname3", "private-address": "fakeaddr2"},
        )
        e.metrics.get_bearer_token.assert_called_once_with()
        e.metrics.build_scrape_configs.assert_not_called()

        relation_data = e.harness.get_relation_data(metrics_rel_id, "microk8s")
        assert json.loads(relation_data["scrape_jobs"]) == {"fakekey": "fakevalue"}
