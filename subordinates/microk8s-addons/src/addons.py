from typing import Dict, List, Any
import logging
from dataclasses import dataclass


class Addon(dataclass):
    enabled: bool

    enable_args: List[str] = []
    disable_args: List[str] = []


def generate_addons(config: Dict[str, Any]) -> Dict[str, Addon]:
    addons = {}

    addons["dns"] = Addon(enabled=config["dns"])
    if config["dns_nameserver"]:
        addons["dns"].enable_args.append(config["dns_nameserver"])

    addons["rbac"] = Addon(enabled=config["rbac"])

    addons["ingress"] = Addon(enabled=config["ingress"])

    addons["hostpath_storage"] = Addon(enabled=config["hostpath_storage"])

    addons["metallb"]

    addons["gpu"] = Addon(
        enabled=config["gpu"],
        enable_args=["--version", config["gpu_version"]],
    )
    if not config["gpu_set_as_default_runtime"]:
        addons["gpu"].enable_args.append("--no-set-as-default-runtime")
