#!/usr/bin/env python3

import logging
from pathlib import Path

import yaml
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus

from oci_image import OCIImageResource, OCIImageResourceError

log = logging.getLogger()


class Operator(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)

        if not self.model.unit.is_leader():
            log.info("Not a leader, skipping set_pod_spec")
            self.model.unit.status = ActiveStatus()
            return

        self.image = OCIImageResource(self, "oci-image")

        self.framework.observe(self.on.install, self.set_pod_spec)
        self.framework.observe(self.on.upgrade_charm, self.set_pod_spec)
        self.framework.observe(self.on.config_changed, self.set_pod_spec)

        for rel in self.model.relations.keys():
            self.framework.observe(
                self.on[rel].relation_changed,
                self.set_pod_spec,
            )

    def set_pod_spec(self, event):
        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            log.info(e)
            return

        config = self.model.config
        self.model.unit.status = MaintenanceStatus("Setting pod spec")
        self.model.pod.set_spec(
            {
                "version": 3,
                "serviceAccount": {
                    "roles": [
                        {
                            "global": True,
                            "rules": [
                                {
                                    "apiGroups": ["kubeflow.org"],
                                    "resources": [
                                        "tfjobs",
                                        "tfjobs/status",
                                        "tfjobs/finalizers",
                                    ],
                                    "verbs": ["*"],
                                },
                                {
                                    "apiGroups": ["apiextensions.k8s.io"],
                                    "resources": ["customresourcedefinitions"],
                                    "verbs": ["*"],
                                },
                                {
                                    "apiGroups": [""],
                                    "resources": [
                                        "pods",
                                        "services",
                                        "endpoints",
                                        "events",
                                    ],
                                    "verbs": ["*"],
                                },
                                {
                                    "apiGroups": ["apps", "extensions"],
                                    "resources": ["deployments"],
                                    "verbs": ["*"],
                                },
                            ],
                        }
                    ]
                },
                "containers": [
                    {
                        "name": "tf-operator",
                        "imageDetails": image_details,
                        "args": [f"--monitoring-port={config['monitoring-port']}"],
                        "envConfig": {
                            "MY_POD_NAMESPACE": self.model.name,
                            "MY_POD_NAME": self.model.app.name,
                        },
                        "ports": [
                            {
                                "name": "monitoring",
                                "containerPort": int(config["monitoring-port"]),
                            },
                        ],
                    }
                ],
            },
            k8s_resources={
                "kubernetesResources": {
                    "customResourceDefinitions": [
                        {"name": crd["metadata"]["name"], "spec": crd["spec"]}
                        for crd in yaml.safe_load_all(Path("src/crds.yaml").read_text())
                    ],
                }
            },
        )
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(Operator)
