#
# Copyright 2023 Canonical, Ltd.
#
from unittest import mock

import pytest

import containerd


@pytest.mark.parametrize(
    "url,host,expected_host",
    [
        ("https://registry-1.docker.io", "docker.io", "docker.io"),
        ("https://registry-1.docker.io/", "docker.io", "docker.io"),
        ("https://quay.io", None, "quay.io"),
        ("https://quay.io/", None, "quay.io"),
        ("https://custom:5000/v2", None, "custom:5000"),
    ],
)
def test_registry_host(url: str, host: str, expected_host: str):
    assert containerd.Registry(url=url, host=host).host == expected_host


@pytest.mark.parametrize("key", ["ca_file", "cert_file", "key_file"])
def test_registry_parse_certs_base64(key: str):
    r = containerd.Registry(url="https://fakeurl", **{key: "dGVzdA=="})
    assert getattr(r, key) == "test"


def test_registry_get_auth_config():
    assert containerd.Registry(
        url="https://fakeurl", username="user", password="pass"
    ).get_auth_config() == {"https://fakeurl": {"auth": {"username": "user", "password": "pass"}}}

    assert containerd.Registry(url="https://fakeurl").get_auth_config() == {}
