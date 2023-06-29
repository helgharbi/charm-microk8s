#
# Copyright 2023 Canonical, Ltd.
#
"""
Requirements:

NOTES:

- a better way would be to authenticate with x509 certificates, but this is not currently supported
  by the observability stack. Therefore, we stick to short-lived bearer tokens for authentication
- the scrape jobs below are created as defined by the kube-prom-stack, so that all dashboards
  from that project can work out of the box.
- we are polling the metrics endpoints from the apiserver (16443) and kubelet (10250) only. this
  works because the kube-scheduler, kube-controller-manager and kube-proxy are running in the same
  process. it would be enough to poll them once, but the dashboards use `metric{job="kube-proxy"}`
  to populate data.
- a potential option would be to poll kubelets through the apiserver proxy url, e.g. instead of

    target="$ip:10250", metrics_path="/metrics/cadvisor"

  have:

    target="$apiserver:16443", metrics_path="/api/v1/nodes/$hostname/proxy/metrics/cadvisor"

  but that would require more relabel configs to not break the metrics

END RESULT:

We should have the following jobs for each component (on the right are required labels):

- apiserver                     job="apiserver"
- kube-controller-manager       job="kube-controller-manager"
- kube-scheduler                job="kube-scheduler"
- kube-proxy                    job="kube-proxy"
- kubelet                       job="kubelet", metrics_path="/metrics", node="$nodename"
- kubelet (cadvisor)            job="kubelet", metrics_path="/metrics/cadvisor", node="$nodename"
- kubelet (probes)              job="kubelet", metrics_path="/metrics/probes", node="$nodename"
"""

import re

import util


def apply_required_resources():
    """kubectl apply manifests that create the required roles and RBAC rules for observability"""
    path = util.charm_dir() / "manifests" / "metrics.yaml"
    util.ensure_call(["microk8s", "kubectl", "apply", "-f", path.as_posix()])


def get_bearer_token():
    """return bearer token that can be used to authenticate as the observability user"""

    p = util.ensure_call(
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
    return p.stdout.decode().strip()


def build_scrape_configs(token, control_plane_nodes, worker_nodes):
    """
    needs
    token = 'token with permissions above'
    control_plane_nodes = ((hostname, ip), (hostname2, ip2), ...)
    worker_nodes = ((hostname, ip), (hostname2, ip2), ...)
    """

    scrape_configs = []

    apiserver_targets = [{"targets": [f"{address}:16443" for (_, address) in control_plane_nodes]}]
    kubelet_targets = [
        {"targets": [f"{address}:10250"], "labels": {"node": hostname}}
        for (hostname, address) in control_plane_nodes + worker_nodes
    ]

    base_job = {
        "scheme": "https",
        "tls_config": {
            "insecure_skip_verify": True,
        },
        "authorization": {
            "credentials": token,
        },
    }

    # apiserver, kube-scheduler, kube-controller-manager (through apiserver)
    for job_name in ["apiserver", "kube-scheduler", "kube-controller-manager"]:
        scrape_configs.append(
            {**base_job, "job_name": job_name, "static_configs": apiserver_targets}
        )

    # kube-proxy (through kubelet)
    scrape_configs.append(
        {**base_job, "job_name": "kube-proxy", "static_configs": kubelet_targets}
    )

    # kubelet
    for job_name, metrics_path in (
        ("kubelet", "/metrics"),
        ("kubelet-cadvisor", "/metrics/cadvisor"),
        ("kubelet-probes", "/metrics/probes"),
    ):
        scrape_configs.append(
            {
                **base_job,
                "job_name": job_name,
                "metrics_path": metrics_path,
                "static_configs": kubelet_targets,
                "relabel_configs": [
                    {"target_label": "metrics_path", "replacement": metrics_path},
                    {"target_label": "job", "replacement": "kubelet"},
                ],
            }
        )

    return scrape_configs
