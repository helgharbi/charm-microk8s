#
# Copyright 2023 Canonical, Ltd.
#
import base64
import json
import logging
from typing import List, Optional

import pydantic
import tomli
from urllib3.util import parse_url

import microk8s
import util

LOG = logging.getLogger(__name__)


class Registry(pydantic.BaseModel, extra=pydantic.Extra.forbid):
    # e.g. "https://registry-1.docker.io"
    url: pydantic.AnyHttpUrl

    # e.g. "docker.io", or "registry.example.com:32000"
    host: Optional[str] = None

    # authentication settings
    username: Optional[str] = None
    password: Optional[str] = None

    # TLS configuration
    ca_file: Optional[str] = None
    cert_file: Optional[str] = None
    key_file: Optional[str] = None
    skip_verify: Optional[bool] = None

    # misc configuration
    override_path: Optional[bool] = None

    @pydantic.validator("host")
    def populate_host(cls, v, values):
        return v or parse_url(values["url"]).netloc

    @pydantic.validator("ca_file")
    def parse_base64_ca_file(cls, v):
        return base64.b64decode(v.encode()).decode()

    @pydantic.validator("cert_file")
    def parse_base64_cert_file(cls, v):
        return base64.b64decode(v.encode()).decode()

    @pydantic.validator("key_file")
    def parse_base64_key_file(cls, v):
        return base64.b64decode(v.encode()).decode()

    def get_auth_config(self):
        """return auth configuration for registry"""
        if not self.username or not self.password:
            return {}

        return {self.url: {"auth": {"username": self.username, "password": self.password}}}


class RegistryConfigs(pydantic.BaseModel, extra=pydantic.Extra.forbid):
    registries: List[Registry]


def parse_registries(json_str: str) -> List[Registry]:
    """parse registry configurations from json string. Raises ValueError
    if configuration is not valid"""
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"not valid JSON: {e}") from e

    return RegistryConfigs(registries=parsed).registries


def ensure_registry_configs(registries: List[Registry]):
    """ensure containerd configuration files match the specified registries.
    restart containerd service if needed"""
    auth_config = {}
    for r in registries:
        host_certs_dir = microk8s.snap_data_dir() / "args" / "certs.d" / r.host
        LOG.info("Configure registry %s (%s)", host_certs_dir, r.host)

        hosts_toml = {
            "server": r.url,
            "host": {r.url: {"capabilities": ["pull", "resolve"]}},
        }

        ca_file_path = host_certs_dir / "ca.crt"
        if r.ca_file:
            LOG.debug("Configure custom CA %s", ca_file_path)
            hosts_toml["host"][r.host]["ca"] = ca_file_path
            util.ensure_file(ca_file_path, r.ca_file, 0o600, 0, 0)
        else:
            ca_file_path.unlink(missing_ok=True)

        cert_file_path = host_certs_dir / "client.crt"
        if r.cert_file:
            LOG.debug("Configure client certificate %s", cert_file_path)
            util.ensure_file(cert_file_path, r.cert_file, 0o600, 0, 0)
        else:
            cert_file_path.unlink(missing_ok=True)

        key_file_path = host_certs_dir / "client.key"
        if r.key_file:
            LOG.debug("Configure client key %s", key_file_path)
            util.ensure_file(key_file_path, r.key_file, 0o600, 0, 0)
        else:
            key_file_path.unlink(missing_ok=True)

        if r.cert_file and r.key_file:
            hosts_toml["host"][r.host]["client"] = [[cert_file_path, key_file_path]]
        elif r.cert_file:
            hosts_toml["host"][r.host]["client"] = cert_file_path

        if r.skip_verify:
            hosts_toml["host"][r.host]["skip_verify"] = True
        if r.override_path:
            hosts_toml["host"][r.host]["override_path"] = True

        # configure hosts.toml
        util.ensure_file(host_certs_dir / "hosts.toml", tomli.dumps(hosts_toml), 0o600, 0, 0)

        if r.username and r.password:
            LOG.debug("Configure username and password for %s (%s)", r.url, r.host)
            auth_config.update(**r.get_auth_config())

    if not auth_config:
        return
    
    registry_configs = {
        "plugins": {"io.containerd.grpc.v1.cri": {"registry": {"configs": auth_config}}}
    }

    containerd_toml_path = microk8s.snap_data_dir() / "args" / "containerd-template.toml"
    containerd_toml = containerd_toml_path.read_text()
    new_containerd_toml = util.ensure_block(
        containerd_toml, tomli.dumps(registry_configs), "# {mark} managed by microk8s charm"
    )
    if util.ensure_file(containerd_toml_path, new_containerd_toml, 0o600, 0, 0):
        LOG.info("Restart containerd to apply registry configurations")
        util.ensure_call(["snap", "restart", "microk8s.daemon-containerd"])
