#
# Copyright 2023 Canonical, Ltd.
#
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from ops.model import ActiveStatus, MaintenanceStatus, WaitingStatus

import util

LOG = logging.getLogger(__name__)


def snap_dir() -> Path:
    return Path("/snap/microk8s/current")


def snap_data_dir() -> Path:
    return Path("/var/snap/microk8s/current")


def snap_common_dir() -> Path:
    return Path("/var/snap/microk8s/common")


def install(channel: Optional[str] = None):
    """`snap install microk8s`"""
    LOG.info("Installing MicroK8s (channel %s)", channel)
    cmd = ["snap", "install", "microk8s", "--classic"]
    if channel:
        cmd.extend(["--channel", channel])

    util.check_call(cmd)


def wait_ready(timeout: int = 30):
    """`microk8s status --wait-ready`"""
    LOG.info("Wait for MicroK8s to become ready")
    util.check_call(["microk8s", "status", "--wait-ready", f"--timeout={timeout}"])


def uninstall():
    """`snap remove microk8s --purge`"""
    LOG.info("Uninstall MicroK8s")
    util.check_call(["snap", "remove", "microk8s", "--purge"])


def remove_node(hostname: str):
    """`microk8s remove-node --force`"""
    LOG.info("Removing node %s from cluster", hostname)
    util.check_call(["microk8s", "remove-node", hostname, "--force"])


def join(join_url: str, worker: bool):
    """`microk8s join`"""
    LOG.info("Joining cluster")
    cmd = ["microk8s", "join", join_url]
    if worker:
        cmd.append("--worker")

    util.check_call(cmd)


def add_node() -> str:
    """`microk8s add-node` and return join token"""
    LOG.info("Generating token for new node")
    token = os.urandom(16).hex()
    util.check_call(["microk8s", "add-node", "--token", token, "--token-ttl", "7200"])
    return token


def get_unit_status(hostname: str):
    """Retrieve node Ready condition from Kubernetes and convert to Juju unit status."""
    try:
        # use the kubectl binary with the kubelet config directly
        output = subprocess.check_output(
            [
                f"{snap_dir()}/kubectl",
                f"--kubeconfig={snap_data_dir()}/credentials/kubelet.config",
                "get",
                "node",
                hostname,
                "-o",
                "jsonpath={.status.conditions[?(@.type=='Ready')]}",
            ]
        )
        node_ready_condition = json.loads(output)
        if node_ready_condition["status"] == "False":
            LOG.warning("node %s is not ready: %s", hostname, node_ready_condition)
            return WaitingStatus(f"node is not ready: {node_ready_condition['reason']}")

        return ActiveStatus("node is ready")

    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
        LOG.warning("could not retrieve status of node %s: %s", hostname, e)
        return MaintenanceStatus("waiting for node")


def reconcile_addons(enabled_addons: list, target_addons: list):
    """disable removed and enable missing addons"""
    LOG.info("Reconciling addons (current=%s, wanted=%s)", enabled_addons, target_addons)
    for addon in enabled_addons:
        if addon not in target_addons:
            # drop any arguments from the addon (if any)
            # e.g. 'dns:10.0.0.10' -> 'dns'
            addon_name, *_ = addon.split(":", maxsplit=2)
            LOG.info("Disabling addon %s", addon_name)
            util.check_call(["microk8s", "disable", addon_name])

    for addon in target_addons:
        if addon not in enabled_addons:
            LOG.info("Enabling addon %s", addon)
            util.check_call(["microk8s", "enable", addon])


def set_containerd_env(containerd_env: str):
    """update containerd environment configuration"""
    if not containerd_env:
        LOG.debug("No custom containerd_env set, will not change anything")
        return

    LOG.info("Set containerd environment configuration")
    if util.ensure_file(snap_data_dir() / "args" / "containerd_env", containerd_env, 0o600, 0, 0):
        LOG.info("Restart containerd to apply environment configuration")
        util.check_call(["snap", "restart", "microk8s.daemon-containerd"])


def set_cert_reissue(disable: bool):
    """pass disable=True to disable automatic cert re-issue, False to re-enable"""
    LOG.info("Apply cert-reissue configuration (disable=%s)", disable)

    path = snap_data_dir() / "var" / "lock" / "no-cert-reissue"
    if disable and path.exists():
        LOG.debug("Removing %s", path)
        path.unlink()
    elif not disable:
        LOG.debug("Make sure that %s exists", path)
        util.ensure_file(path, "", 0o600, 0, 0)
