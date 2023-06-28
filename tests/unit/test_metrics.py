#
# Copyright 2023 Canonical, Ltd.
#
from pathlib import Path
from unittest import mock

import metrics


@mock.patch("util.ensure_call")
@mock.patch("util.charm_dir")
def test_apply_required_resources(charm_dir: mock.MagicMock, ensure_call: mock.MagicMock):
    charm_dir.return_value = Path("some/dir")
    metrics.apply_required_resources()

    ensure_call.assert_called_once_with(
        ["microk8s", "kubectl", "apply", "-f", "some/dir/manifests/metrics.yaml"]
    )


@mock.patch("util.ensure_call")
def test_get_bearer_token(ensure_call: mock.MagicMock):
    ensure_call.return_value.stdout = b"faketoken\n"

    token = metrics.get_bearer_token()
    assert token == "faketoken"

    ensure_call.assert_called_once_with(
        [
            "microk8s",
            "kubectl",
            "create",
            "token",
            "--namespace=kube-system",
            "microk8s-observability",
        ],
        capture_output=True,
    )


def test_build_scrape_configs():
    res = metrics.build_scrape_configs(
        "faketoken",
        [("cp1", "1.1.1.1"), ("cp2", "2.2.2.2")],
        [("w1", "3.3.3.3"), ("w2", "4.4.4.4")],
    )

    assert res == [
        {
            "scheme": "https",
            "tls_config": {"insecure_skip_verify": True},
            "authorization": {"credentials": "faketoken"},
            "job_name": "apiserver",
            "static_configs": [{"targets": ["1.1.1.1:16443", "2.2.2.2:16443"]}],
        },
        {
            "scheme": "https",
            "tls_config": {"insecure_skip_verify": True},
            "authorization": {"credentials": "faketoken"},
            "job_name": "kube-scheduler",
            "static_configs": [{"targets": ["1.1.1.1:16443", "2.2.2.2:16443"]}],
        },
        {
            "scheme": "https",
            "tls_config": {"insecure_skip_verify": True},
            "authorization": {"credentials": "faketoken"},
            "job_name": "kube-controller-manager",
            "static_configs": [{"targets": ["1.1.1.1:16443", "2.2.2.2:16443"]}],
        },
        {
            "scheme": "https",
            "tls_config": {"insecure_skip_verify": True},
            "authorization": {"credentials": "faketoken"},
            "job_name": "kube-proxy",
            "static_configs": [
                {"targets": ["1.1.1.1:10250"], "labels": {"node": "cp1"}},
                {"targets": ["2.2.2.2:10250"], "labels": {"node": "cp2"}},
                {"targets": ["3.3.3.3:10250"], "labels": {"node": "w1"}},
                {"targets": ["4.4.4.4:10250"], "labels": {"node": "w2"}},
            ],
        },
        {
            "scheme": "https",
            "tls_config": {"insecure_skip_verify": True},
            "authorization": {"credentials": "faketoken"},
            "job_name": "kubelet",
            "metrics_path": "/metrics",
            "static_configs": [
                {"targets": ["1.1.1.1:10250"], "labels": {"node": "cp1"}},
                {"targets": ["2.2.2.2:10250"], "labels": {"node": "cp2"}},
                {"targets": ["3.3.3.3:10250"], "labels": {"node": "w1"}},
                {"targets": ["4.4.4.4:10250"], "labels": {"node": "w2"}},
            ],
            "relabel_configs": [
                {"target_label": "metrics_path", "replacement": "/metrics"},
                {"target_label": "job", "replacement": "kubelet"},
            ],
        },
        {
            "scheme": "https",
            "tls_config": {"insecure_skip_verify": True},
            "authorization": {"credentials": "faketoken"},
            "job_name": "kubelet-cadvisor",
            "metrics_path": "/metrics/cadvisor",
            "static_configs": [
                {"targets": ["1.1.1.1:10250"], "labels": {"node": "cp1"}},
                {"targets": ["2.2.2.2:10250"], "labels": {"node": "cp2"}},
                {"targets": ["3.3.3.3:10250"], "labels": {"node": "w1"}},
                {"targets": ["4.4.4.4:10250"], "labels": {"node": "w2"}},
            ],
            "relabel_configs": [
                {"target_label": "metrics_path", "replacement": "/metrics/cadvisor"},
                {"target_label": "job", "replacement": "kubelet"},
            ],
        },
        {
            "scheme": "https",
            "tls_config": {"insecure_skip_verify": True},
            "authorization": {"credentials": "faketoken"},
            "job_name": "kubelet-probes",
            "metrics_path": "/metrics/probes",
            "static_configs": [
                {"targets": ["1.1.1.1:10250"], "labels": {"node": "cp1"}},
                {"targets": ["2.2.2.2:10250"], "labels": {"node": "cp2"}},
                {"targets": ["3.3.3.3:10250"], "labels": {"node": "w1"}},
                {"targets": ["4.4.4.4:10250"], "labels": {"node": "w2"}},
            ],
            "relabel_configs": [
                {"target_label": "metrics_path", "replacement": "/metrics/probes"},
                {"target_label": "job", "replacement": "kubelet"},
            ],
        },
    ]
