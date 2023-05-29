#
# Copyright 2023 Canonical, Ltd.
#
from unittest import mock

import ops
import ops.testing
import pytest
from conftest import Environment


@pytest.mark.parametrize("is_leader", [True, False])
def test_install(e: Environment, is_leader: bool):
    e.uname.return_value.release = "fakerelease"
    e.node_to_unit_status.return_value = ops.model.ActiveStatus("fakestatus")

    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(is_leader)
    e.harness.begin_with_initial_hooks()

    e.uname.assert_called_once()
    assert e.harness.charm.model.unit.opened_ports() == {
        ops.model.OpenedPort(protocol="tcp", port=80),
        ops.model.OpenedPort(protocol="tcp", port=443),
        ops.model.OpenedPort(protocol="tcp", port=16443),
    }


def test_install_follower(e: Environment):
    e.uname.return_value.release = "fakerelease"
    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(False)

    e.harness.begin_with_initial_hooks()

    assert e.check_call.mock_calls == [
        mock.call(["apt-get", "install", "--yes", "nfs-common"]),
        mock.call(["apt-get", "install", "--yes", "open-iscsi"]),
        mock.call(["apt-get", "install", "--yes", "linux-modules-extra-fakerelease"]),
        mock.call(["snap", "install", "microk8s", "--classic"]),
        mock.call(["microk8s", "status", "--wait-ready", "--timeout=30"]),
    ]

    assert isinstance(e.harness.charm.unit.status, ops.model.WaitingStatus)


def test_install_leader(e: Environment):
    e.uname.return_value.release = "fakerelease"
    e.node_to_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(True)

    e.harness.begin_with_initial_hooks()

    assert e.check_call.call_args_list == [
        mock.call(["apt-get", "install", "--yes", "nfs-common"]),
        mock.call(["apt-get", "install", "--yes", "open-iscsi"]),
        mock.call(["apt-get", "install", "--yes", "linux-modules-extra-fakerelease"]),
        mock.call(["snap", "install", "microk8s", "--classic"]),
        mock.call(["microk8s", "status", "--wait-ready", "--timeout=30"]),
        mock.call(["microk8s", "enable", "dns"]),
        mock.call(["microk8s", "enable", "rbac"]),
        mock.call(["microk8s", "enable", "hostpath-storage"]),
        mock.call(["microk8s", "enable", "ingress"]),
    ]

    assert e.harness.charm.unit.status == ops.model.ActiveStatus("fakestatus")
    assert e.harness.charm._state.joined


def test_leader_peer_relation(e: Environment):
    faketoken = b"\x01" * 16
    fakeaddress = "10.10.10.10"
    e.node_to_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.get_hostname.return_value = "fakehostname"
    e.urandom.return_value = faketoken

    e.harness.add_network(fakeaddress)
    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(True)
    e.harness.begin_with_initial_hooks()

    e.check_call.reset_mock()

    rel_id = e.harness.charm.model.get_relation("peer").id
    e.harness.add_relation_unit(rel_id, f"{e.harness.charm.app.name}/1")
    e.harness.update_relation_data(rel_id, f"{e.harness.charm.app.name}/1", {"hostname": "fake1"})

    e.check_call.assert_called_with(
        ["microk8s", "add-node", "--token", faketoken.hex(), "--token-ttl", "7200"]
    )
    e.urandom.assert_called_once_with(16)
    relation_data = e.harness.get_relation_data(rel_id, e.harness.charm.app)
    assert relation_data["join_url"] == f"{fakeaddress}:25000/{faketoken.hex()}"
    assert e.harness.charm._state.hostnames[f"{e.harness.charm.app.name}/1"] == "fake1"

    e.check_call.reset_mock()
    e.harness.remove_relation_unit(rel_id, f"{e.harness.charm.app.name}/1")
    e.check_call.assert_called_once_with(["microk8s", "remove-node", "fake1", "--force"])


def test_leader_peer_relation_leave(e: Environment):
    e.node_to_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.get_hostname.return_value = "fakehostname"
    fakeaddress = "10.10.10.10"

    e.harness.add_network(fakeaddress)
    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(True)
    e.harness.begin_with_initial_hooks()

    e.check_call.reset_mock()

    rel = e.harness.charm.model.get_relation("peer")
    e.harness.add_relation_unit(rel.id, f"{e.harness.charm.app.name}/1")
    e.harness.update_relation_data(rel.id, f"{e.harness.charm.app.name}/1", {"hostname": "fake1"})

    e.check_call.reset_mock()

    # NOTE(neoaggelos): mock self departed event
    e.harness.charm.on["peer"].relation_departed.emit(
        relation=rel,
        app=e.harness.charm.app,
        unit=e.harness.charm.unit,
        departing_unit_name=e.harness.charm.unit.name,
    )

    relation_data = e.harness.get_relation_data(rel.id, e.harness.charm.app.name)
    assert relation_data["remove_nodes"] == '["fakehostname"]'


def test_leader_microk8s_provides_relation(e: Environment):
    faketoken = b"\x01" * 16
    fakeaddress = "10.10.10.10"
    e.node_to_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.get_hostname.return_value = "fakehostname"
    e.urandom.return_value = faketoken

    e.harness.add_network(fakeaddress)
    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(True)
    e.harness.begin_with_initial_hooks()

    e.check_call.reset_mock()

    rel_id = e.harness.add_relation("microk8s-provides", "microk8s-worker")
    e.harness.add_relation_unit(rel_id, "microk8s-worker/0")
    e.harness.update_relation_data(rel_id, "microk8s-worker/0", {"hostname": "fake1"})

    e.check_call.assert_called_with(
        ["microk8s", "add-node", "--token", faketoken.hex(), "--token-ttl", "7200"]
    )
    e.urandom.assert_called_once_with(16)
    relation_data = e.harness.get_relation_data(rel_id, e.harness.charm.app)
    assert relation_data["join_url"] == f"{fakeaddress}:25000/{faketoken.hex()}"
    assert e.harness.charm._state.hostnames["microk8s-worker/0"] == "fake1"

    e.check_call.reset_mock()
    e.harness.remove_relation_unit(rel_id, "microk8s-worker/0")
    e.check_call.assert_called_once_with(["microk8s", "remove-node", "fake1", "--force"])


def test_follower_peer_relation(e: Environment):
    e.node_to_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.get_hostname.return_value = "fakehostname"

    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(True)
    e.harness.begin_with_initial_hooks()
    e.harness.set_leader(False)

    e.check_call.reset_mock()
    rel_id = e.harness.charm.model.get_relation("peer").id
    e.harness.add_relation_unit(rel_id, f"{e.harness.charm.app.name}/1")
    e.harness.update_relation_data(rel_id, f"{e.harness.charm.app.name}/1", {"hostname": "fake1"})

    relation_data = e.harness.get_relation_data(rel_id, e.harness.charm.app)
    assert "join_url" not in relation_data
    e.check_call.assert_not_called()
    e.urandom.assert_not_called()
    assert e.harness.charm._state.hostnames[f"{e.harness.charm.app.name}/1"] == "fake1"

    e.check_call.reset_mock()
    e.harness.remove_relation_unit(rel_id, f"{e.harness.charm.app.name}/1")
    e.check_call.assert_not_called()


def test_follower_microk8s_provides_relation(e: Environment):
    e.node_to_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.get_hostname.return_value = "fakehostname"
    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(True)
    e.harness.begin_with_initial_hooks()
    e.harness.set_leader(False)

    e.check_call.reset_mock()

    rel_id = e.harness.add_relation("microk8s-provides", "microk8s-worker")
    e.harness.add_relation_unit(rel_id, "microk8s-worker/0")
    e.harness.update_relation_data(rel_id, "microk8s-worker/0", {"hostname": "fake1"})

    relation_data = e.harness.get_relation_data(rel_id, e.harness.charm.app)
    assert "join_url" not in relation_data
    e.check_call.assert_not_called()
    e.urandom.assert_not_called()
    assert e.harness.charm._state.hostnames["microk8s-worker/0"] == "fake1"

    e.check_call.reset_mock()
    e.harness.remove_relation_unit(rel_id, "microk8s-worker/0")
    e.check_call.assert_not_called()


def test_follower_retrieve_join_url(e: Environment):
    e.node_to_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.get_hostname.return_value = "fakehostname"

    e.harness.update_config({"role": "control-plane"})
    e.harness.set_leader(False)
    e.harness.begin_with_initial_hooks()

    e.check_call.reset_mock()
    rel_id = e.harness.charm.model.get_relation("peer").id
    e.harness.add_relation_unit(rel_id, f"{e.harness.charm.app.name}/1")
    e.harness.update_relation_data(rel_id, e.harness.charm.app.name, {"join_url": "fakejoinurl"})

    e.check_call.assert_called_once_with(["microk8s", "join", "fakejoinurl"])
    e.node_to_unit_status.assert_called_once_with("fakehostname")

    assert e.harness.charm.unit.status == ops.model.ActiveStatus("fakestatus")
    assert e.harness.charm._state.joined


@pytest.mark.parametrize("become_leader", [True, False])
def test_follower_become_leader_remove_departing_nodes(e: Environment, become_leader: bool):
    e.node_to_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.get_hostname.return_value = "fakehostname"

    e.harness.update_config({"role": "control-plane", "addons": ""})
    e.harness.set_leader(False)
    e.harness.begin_with_initial_hooks()

    prel_id = e.harness.charm.model.get_relation("peer").id
    e.harness.add_relation_unit(prel_id, f"{e.harness.charm.app.name}/1")
    e.harness.add_relation_unit(prel_id, f"{e.harness.charm.app.name}/2")
    e.harness.update_relation_data(prel_id, f"{e.harness.charm.app.name}/1", {"hostname": "fake2"})
    e.harness.update_relation_data(prel_id, e.harness.charm.app.name, {"join_url": "fakejoinurl"})

    rel_id = e.harness.add_relation("microk8s-provides", "microk8s-worker")
    e.harness.add_relation_unit(rel_id, "microk8s-worker/0")
    e.harness.add_relation_unit(rel_id, "microk8s-worker/1")
    e.harness.update_relation_data(rel_id, "microk8s-worker/0", {"hostname": "fake1"})

    if become_leader:
        e.harness.set_leader(become_leader)

    e.check_call.reset_mock()
    e.harness.remove_relation_unit(rel_id, "microk8s-worker/0")
    e.harness.remove_relation_unit(rel_id, "microk8s-worker/1")
    e.harness.remove_relation_unit(prel_id, f"{e.harness.charm.app.name}/1")
    e.harness.remove_relation_unit(prel_id, f"{e.harness.charm.app.name}/2")

    if become_leader:
        assert sorted(e.check_call.mock_calls) == [
            mock.call(["microk8s", "remove-node", "fake1", "--force"]),
            mock.call(["microk8s", "remove-node", "fake2", "--force"]),
        ]
    else:
        e.check_call.assert_not_called()


@pytest.mark.parametrize("become_leader", [True, False])
def test_follower_become_leader_remove_already_departed_nodes(e: Environment, become_leader: bool):
    e.node_to_unit_status.return_value = ops.model.ActiveStatus("fakestatus")
    e.get_hostname.return_value = "fakehostname"

    e.harness.update_config({"role": "control-plane", "addons": ""})
    e.harness.set_leader(False)
    e.harness.begin_with_initial_hooks()

    prel_id = e.harness.charm.model.get_relation("peer").id
    e.harness.add_relation_unit(prel_id, f"{e.harness.charm.app.name}/1")
    e.harness.add_relation_unit(prel_id, f"{e.harness.charm.app.name}/2")
    e.harness.update_relation_data(prel_id, f"{e.harness.charm.app.name}/1", {"hostname": "fake2"})

    e.harness.update_relation_data(prel_id, e.harness.charm.app.name, {"join_url": "fakejoinurl"})

    e.check_call.reset_mock()
    e.harness.update_relation_data(
        prel_id, e.harness.charm.app.name, {"remove_nodes": '["fake1", "fake2", "fakehostname"]'}
    )

    e.harness.set_leader(become_leader)
    if become_leader:
        assert sorted(e.check_call.mock_calls) == [
            mock.call(["microk8s", "remove-node", "fake1", "--force"]),
            mock.call(["microk8s", "remove-node", "fake2", "--force"]),
        ]
    else:
        e.check_call.assert_not_called()
