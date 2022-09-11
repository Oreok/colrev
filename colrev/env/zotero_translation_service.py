#! /usr/bin/env python
from __future__ import annotations

import time

import docker
import requests
from docker.errors import APIError

import colrev.env.environment_manager


class ZoteroTranslationService:
    def __init__(self):
        pass

    def start_zotero_translators(self) -> None:

        if self.zotero_service_available():
            return

        zotero_image = colrev.env.environment_manager.EnvironmentManager.docker_images[
            "zotero/translation-server"
        ]

        client = docker.from_env()
        for container in client.containers.list():
            if zotero_image in str(container.image):
                return
        try:
            container = client.containers.run(
                zotero_image,
                ports={"1969/tcp": ("127.0.0.1", 1969)},
                auto_remove=True,
                detach=True,
            )
        except APIError:
            pass

        i = 0
        while i < 45:
            if self.zotero_service_available():
                break
            time.sleep(1)
            i += 1
        return

    def zotero_service_available(self) -> bool:

        url = "https://www.sciencedirect.com/science/article/abs/pii/S096386872100041X"
        content_type_header = {"Content-type": "text/plain"}
        try:
            ret = requests.post(
                "http://127.0.0.1:1969/web",
                headers=content_type_header,
                data=url,
            )
            if ret.status_code == 200:
                return True
        except requests.exceptions.ConnectionError:
            pass
        return False


if __name__ == "__main__":
    pass