"""
Requirements:

## 1. The following ClusterRole (and a ClusterRoleBinding)

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: charm-microk8s-cos-role
rules:
- apiGroups:
  - ""
  resources:
  - nodes/metrics
  verbs:
  - get
- nonResourceURLs:
  - /metrics
  verbs:
  - get
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: charm-microk8s-cos-role
  namespace: kube-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: charm-microk8s-cos-role
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: charm-microk8s-cos-role
subjects:
- kind: ServiceAccount
  name: charm-microk8s-cos-role
  namespace: kube-system
```

## 2. Create a token

Note that this is a short-lived token (duration 1 hour by default), must be rotated:

token = $(kubectl create token --namespace kube-system charm-microk8s-cos-role)

## 3. Get list of control plane nodes and worker nodes

control_plane_nodes = []
rel = model.get_relation("peer")
for unit in rel.units:
    control_plane_nodes.append((rel.data[unit]["hostname"], rel.data[unit]["private-address"]))

worker_nodes = []
rel = model.get_relation("workers")
for unit in rel.units:
    worker_nodes.append((rel.data[unit]["hostname"], rel.data[unit]["private-address"]))

NOTES:

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
        {"targets": [f"{address}:10250" for (_, address) in control_plane_nodes + worker_nodes]}
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

    # kube-scheduler, kube-controller-manager and apiserver (through apiserver)
    for job_name in ["kube-scheduler", "kube-controller-manager", "apiserver"]:
        scrape_configs.append(
            {**base_job, "job_name": job_name, "static_configs": apiserver_targets}
        )

    # kube-proxy (through kubelet)
    scrape_configs.append(
        {**base_job, "job_name": "kube-proxy", "static_configs": kubelet_targets}
    )

    # relabel configs to set the label "node" for each kubelet scrape job
    # based on its __address__
    node_relabel_configs = [
        {
            "target_label": "node",
            "source_labels": ["__address__"],
            "regex": re.escape(f"{address}:10250"),
            "replacement": host,
        }
        for (host, address) in control_plane_nodes + worker_nodes
    ]

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
                    *node_relabel_configs,
                    {"target_label": "metrics_path", "replacement": metrics_path},
                    {"target_label": "job", "replacement": "kubelet"},
                ],
            }
        )
