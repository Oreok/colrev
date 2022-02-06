#! /usr/bin/env python
import logging
import os
import subprocess
import time

import requests

GROBID_URL = "http://localhost:8070"
# grobid_image = "grobid/grobid:0.7.1-SNAPSHOT"
grobid_image = "lfoppiano/grobid:0.7.0"
# grobid_image = "lfoppiano/grobid:0.6.2"


def get_grobid_url() -> str:
    return GROBID_URL


def check_grobid_availability() -> None:
    i = 0
    while True:
        i += 1
        time.sleep(1)
        try:
            r = requests.get(GROBID_URL + "/api/isalive")
            if r.text == "true":
                i = -1
        except requests.exceptions.ConnectionError:
            pass
        if i == -1:
            break
        if i > 20:
            raise requests.exceptions.ConnectionError()
    return


def start_grobid():
    logging.info(f"Running docker container created from {grobid_image}")
    try:
        r = requests.get(GROBID_URL + "/api/isalive")
        if r.text == "true":
            logging.debug("Docker running")
            return
    except requests.exceptions.ConnectionError:
        logging.info("Starting grobid service...")
        subprocess.Popen(
            [
                'docker run -t --rm -m "4g" -p 8070:8070 '
                + f"-p 8071:8071 {grobid_image}"
            ],
            shell=True,
            stdin=None,
            stdout=open(os.devnull, "wb"),
            stderr=None,
            close_fds=True,
        )
        pass