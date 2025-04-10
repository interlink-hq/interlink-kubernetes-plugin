# pylint: disable=redefined-outer-name
import pytest
import requests
import interlink as i


@pytest.fixture()
def rest_server() -> str:
    return "http://172.18.0.3:30400/status"


_I_POD = i.Pod(
    **{
        "pod": {
            "metadata": {
                "name": "test-pod",
                "namespace": "default",
                "annotations": {
                    "test": "test",
                },
            },
            "spec": {
                "containers": [
                    {
                        "name": "test-container",
                        "image": "busybox",
                        "command": [
                            "sh",
                            "-c",
                            "i=0; while true; do echo $i;  i=$((i+1)); sleep 3; done",
                        ],
                        "resources": {
                            "limits": {"cpu": "10m", "memory": "32Mi"},
                            "requests": {"cpu": "10m", "memory": "32Mi"},
                        },
                        "volumeMounts": [
                            {
                                "name": "kube-api-access-g7qmm",
                                "readOnly": True,
                                "mountPath": "/var/run/secrets/kubernetes.io/serviceaccount",
                            }
                        ],
                    }
                ],
                "volumes": [
                    {
                        "name": "kube-api-access-g7qmm",
                        "projected": {
                            "sources": [
                                {
                                    "serviceAccountToken": {
                                        "expirationSeconds": 3607,
                                        "path": "token",
                                    }
                                },
                            ],
                        },
                    }
                ],
                "nodeName": "ivk-edge",
                "tolerations": [
                    {
                        "key": "virtual-node.interlink/no-schedule",
                        "operator": "Equal",
                        "value": "false",
                        "effect": "NoSchedule",
                    },
                    {
                        "key": "node.kubernetes.io/not-ready",
                        "operator": "Exists",
                        "effect": "NoExecute",
                        "tolerationSeconds": 300,
                    },
                    {
                        "key": "node.kubernetes.io/unreachable",
                        "operator": "Exists",
                        "effect": "NoExecute",
                        "tolerationSeconds": 300,
                    },
                ],
            },
        },
        "container": [
            {
                "name": "",
                "configMaps": None,
                "secrets": None,
                "emptyDirs": None,
                "persistent_volume_claims": None,
            }
        ],
    }
)


def test_create(rest_server: str):
    response = requests.get(f"{rest_server}/status", timeout=5)
    assert response.status_code == 200
    status_result: list[i.PodStatus] = response.json()
    assert status_result is list and len(status_result) == 0

    response = requests.post(
        "http://localhost:30400/create",
        timeout=5,
        json=[_I_POD.model_dump()],
    )
    assert response.status_code == 200
    create_result: i.CreateStruct = response.json()
    assert create_result is i.CreateStruct
    assert create_result.pod_uid and create_result.pod_jid

    response = requests.post(
        "http://localhost:30400/status",
        timeout=5,
        json=[_I_POD.pod.model_dump()],
    )
    assert response.status_code == 200
    status_result: list[i.PodStatus] = response.json()
    assert status_result is list and len(status_result) == 1 and status_result[0] is i.PodStatus
    assert status_result[0].name == _I_POD.pod.metadata.name
    assert status_result[0].namespace == _I_POD.pod.metadata.namespace
    assert status_result[0].uid == create_result[0].jid
