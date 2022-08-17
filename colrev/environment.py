#! /usr/bin/env python
import binascii
import collections
import hashlib
import importlib
import io
import json
import logging
import os
import pkgutil
import re
import shutil
import subprocess
import sys
import time
import typing
from copy import deepcopy
from datetime import datetime
from datetime import timedelta
from json import JSONDecodeError
from pathlib import Path
from threading import Timer

import docker
import git
import pandas as pd
import requests
import requests_cache
import yaml
from dacite.exceptions import MissingValueError
from docker.errors import APIError
from git.exc import InvalidGitRepositoryError
from git.exc import NoSuchPathError
from lxml import etree
from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError
from opensearchpy.exceptions import SerializationError
from opensearchpy.exceptions import TransportError
from pybtex.database.input import bibtex
from thefuzz import fuzz
from tqdm import tqdm
from yaml import safe_load
from zope.interface.verify import verifyObject

import colrev.exceptions as colrev_exceptions
import colrev.process
import colrev.record

# from lxml.etree import SerialisationError


class AdapterManager:
    @classmethod
    def load_scripts(
        cls, *, PROCESS, scripts, script_type: str = ""
    ) -> typing.Dict[str, typing.Dict[str, typing.Any]]:

        # avoid changes in the config
        scripts = deepcopy(scripts)
        scripts_dict: typing.Dict = {}
        for script in scripts:
            script_name = script["endpoint"]
            scripts_dict[script_name] = {}

            # 1. Load built-in scripts
            if script_name in PROCESS.built_in_scripts:
                scripts_dict[script_name]["settings"] = script
                scripts_dict[script_name]["endpoint"] = PROCESS.built_in_scripts[
                    script_name
                ]["endpoint"]

            # 2. Load module scripts
            # TODO : test the module prep_scripts
            elif not Path(script_name + ".py").is_file():
                try:
                    scripts_dict[script_name]["settings"] = script
                    scripts_dict[script_name]["endpoint"] = importlib.import_module(
                        script_name
                    )
                    scripts_dict[script_name]["custom_flag"] = True
                except ModuleNotFoundError as e:
                    raise colrev_exceptions.MissingDependencyError(
                        "Dependency " + f"{script_name} not found. "
                        "Please install it\n  pip install "
                        f"{script_name}"
                    ) from e

            # 3. Load custom scripts in the directory
            elif Path(script_name + ".py").is_file():
                sys.path.append(".")  # to import custom scripts from the project dir
                scripts_dict[script_name]["settings"] = script
                scripts_dict[script_name]["endpoint"] = importlib.import_module(
                    script_name, "."
                )
                scripts_dict[script_name]["custom_flag"] = True
            else:
                print(f"Could not load {script}")
                continue
            scripts_dict[script_name]["settings"]["name"] = scripts_dict[script_name][
                "settings"
            ]["endpoint"]
            del scripts_dict[script_name]["settings"]["endpoint"]

        if colrev.process.ProcessType.search == PROCESS.type:
            from colrev.process import SearchEndpoint

            for k, val in scripts_dict.items():
                if "custom_flag" in val:
                    scripts_dict[k]["endpoint"] = scripts_dict[k][
                        "endpoint"
                    ].CustomSearch
                    del scripts_dict[k]["custom_flag"]

            for endpoint_name, script in scripts_dict.items():
                scripts_dict[endpoint_name] = script["endpoint"](
                    SEARCH=PROCESS, SETTINGS=script["settings"]
                )
                verifyObject(SearchEndpoint, scripts_dict[endpoint_name])

        elif colrev.process.ProcessType.load == PROCESS.type:
            from colrev.process import LoadEndpoint

            for k, val in scripts_dict.items():
                if "custom_flag" in val:
                    scripts_dict[k]["endpoint"] = scripts_dict[k]["endpoint"].CustomLoad
                    del scripts_dict[k]["custom_flag"]

            for endpoint_name, script in scripts_dict.items():
                scripts_dict[endpoint_name] = script["endpoint"](
                    LOAD=PROCESS, SETTINGS=script["settings"]
                )
                verifyObject(LoadEndpoint, scripts_dict[endpoint_name])

        elif colrev.process.ProcessType.prep == PROCESS.type:
            from colrev.process import PreparationEndpoint

            for k, val in scripts_dict.items():
                if "custom_flag" in val:
                    scripts_dict[k]["endpoint"] = scripts_dict[k][
                        "endpoint"
                    ].CustomPrepare
                    del scripts_dict[k]["custom_flag"]

            for endpoint_name, script in scripts_dict.items():
                scripts_dict[endpoint_name] = script["endpoint"](
                    PREPARATION=PROCESS, SETTINGS=script["settings"]
                )
                verifyObject(PreparationEndpoint, scripts_dict[endpoint_name])

        elif colrev.process.ProcessType.prep_man == PROCESS.type:
            from colrev.process import PreparationManualEndpoint

            for k, val in scripts_dict.items():
                if "custom_flag" in val:
                    scripts_dict[k]["endpoint"] = scripts_dict[k][
                        "endpoint"
                    ].CustomPrepMan
                    del scripts_dict[k]["custom_flag"]

            for endpoint_name, script in scripts_dict.items():
                scripts_dict[endpoint_name] = script["endpoint"](
                    PREP_MAN=PROCESS, SETTINGS=script["settings"]
                )
                verifyObject(PreparationManualEndpoint, scripts_dict[endpoint_name])

        elif colrev.process.ProcessType.dedupe == PROCESS.type:
            from colrev.process import DedupeEndpoint

            for k, val in scripts_dict.items():
                if "custom_flag" in val:
                    scripts_dict[k]["endpoint"] = scripts_dict[k][
                        "endpoint"
                    ].CustomDedupe
                    del scripts_dict[k]["custom_flag"]

            for endpoint_name, script in scripts_dict.items():
                scripts_dict[endpoint_name] = script["endpoint"](
                    DEDUPE=PROCESS, SETTINGS=script["settings"]
                )
                verifyObject(DedupeEndpoint, scripts_dict[endpoint_name])

        elif colrev.process.ProcessType.prescreen == PROCESS.type:
            from colrev.process import PrescreenEndpoint

            for k, val in scripts_dict.items():
                if "custom_flag" in val:
                    scripts_dict[k]["endpoint"] = scripts_dict[k][
                        "endpoint"
                    ].CustomPrescreen
                    del scripts_dict[k]["custom_flag"]

            for endpoint_name, script in scripts_dict.items():
                scripts_dict[endpoint_name] = script["endpoint"](
                    PRESCREEN=PROCESS, SETTINGS=script["settings"]
                )
                verifyObject(PrescreenEndpoint, scripts_dict[endpoint_name])

        elif colrev.process.ProcessType.pdf_get == PROCESS.type:
            from colrev.process import PDFRetrievalEndpoint

            for k, val in scripts_dict.items():
                if "custom_flag" in val:
                    scripts_dict[k]["endpoint"] = scripts_dict[k][
                        "endpoint"
                    ].CustomPDFRetrieval
                    del scripts_dict[k]["custom_flag"]

            for endpoint_name, script in scripts_dict.items():
                scripts_dict[endpoint_name] = script["endpoint"](
                    PDF_GET=PROCESS, SETTINGS=script["settings"]
                )
                verifyObject(PDFRetrievalEndpoint, scripts_dict[endpoint_name])

        elif colrev.process.ProcessType.pdf_get_man == PROCESS.type:
            from colrev.process import PDFRetrievalManualEndpoint

            for k, val in scripts_dict.items():
                if "custom_flag" in val:
                    scripts_dict[k]["endpoint"] = scripts_dict[k][
                        "endpoint"
                    ].CustomPDFManualRetrieval
                    del scripts_dict[k]["custom_flag"]

            for endpoint_name, script in scripts_dict.items():
                scripts_dict[endpoint_name] = script["endpoint"](
                    PDF_RETRIEVAL_MAN=PROCESS, SETTINGS=script["settings"]
                )
                verifyObject(PDFRetrievalManualEndpoint, scripts_dict[endpoint_name])

        elif colrev.process.ProcessType.pdf_prep == PROCESS.type:
            from colrev.process import PDFPreparationEndpoint

            for k, val in scripts_dict.items():
                if "custom_flag" in val:
                    scripts_dict[k]["endpoint"] = scripts_dict[k][
                        "endpoint"
                    ].CustomPDFPrepratation
                    del scripts_dict[k]["custom_flag"]

            for endpoint_name, script in scripts_dict.items():
                scripts_dict[endpoint_name] = script["endpoint"](
                    PDF_PREPARATION=PROCESS, SETTINGS=script["settings"]
                )
                verifyObject(PDFPreparationEndpoint, scripts_dict[endpoint_name])

        elif colrev.process.ProcessType.pdf_prep_man == PROCESS.type:
            from colrev.process import PDFPreparationManualEndpoint

            for k, val in scripts_dict.items():
                if "custom_flag" in val:
                    scripts_dict[k]["endpoint"] = scripts_dict[k][
                        "endpoint"
                    ].CustomPDFManualPrepratation
                    del scripts_dict[k]["custom_flag"]

            for endpoint_name, script in scripts_dict.items():
                scripts_dict[endpoint_name] = script["endpoint"](
                    PDF_PREP_MAN=PROCESS, SETTINGS=script["settings"]
                )
                verifyObject(PDFPreparationManualEndpoint, scripts_dict[endpoint_name])

        elif colrev.process.ProcessType.screen == PROCESS.type:
            from colrev.process import ScreenEndpoint

            for k, val in scripts_dict.items():
                if "custom_flag" in val:
                    scripts_dict[k]["endpoint"] = scripts_dict[k][
                        "endpoint"
                    ].CustomScreen
                    del scripts_dict[k]["custom_flag"]

            for endpoint_name, script in scripts_dict.items():
                scripts_dict[endpoint_name] = script["endpoint"](
                    SCREEN=PROCESS, SETTINGS=script["settings"]
                )
                verifyObject(ScreenEndpoint, scripts_dict[endpoint_name])

        elif colrev.process.ProcessType.data == PROCESS.type:
            from colrev.process import DataEndpoint

            for k, val in scripts_dict.items():
                if "custom_flag" in val:
                    scripts_dict[k]["endpoint"] = scripts_dict[k]["endpoint"].CustomData
                    del scripts_dict[k]["custom_flag"]

            for endpoint_name, script in scripts_dict.items():
                scripts_dict[endpoint_name] = script["endpoint"](
                    DATA=PROCESS, SETTINGS=script["settings"]
                )
                verifyObject(DataEndpoint, scripts_dict[endpoint_name])

        elif colrev.process.ProcessType.check == PROCESS.type:
            if "SearchSource" == script_type:
                from colrev.process import SearchSourceEndpoint

                for k, val in scripts_dict.items():
                    if "custom_flag" in val:
                        scripts_dict[k]["endpoint"] = scripts_dict[k][
                            "endpoint"
                        ].CustomSearchSource
                        del scripts_dict[k]["custom_flag"]

                for endpoint_name, script in scripts_dict.items():
                    scripts_dict[endpoint_name] = script["endpoint"](
                        SETTINGS=script["settings"]
                    )
                    verifyObject(SearchSourceEndpoint, scripts_dict[endpoint_name])
            else:
                print(
                    f"ERROR: process type not implemented: {PROCESS.type}/{script_type}"
                )

        else:
            print(f"ERROR: process type not implemented: {PROCESS.type}")

        return scripts_dict


class EnvironmentManager:

    colrev_path = Path.home().joinpath("colrev")
    registry = "registry.yaml"

    paths = {"REGISTRY": colrev_path.joinpath(registry)}

    os_db = "opensearchproject/opensearch-dashboards:1.3.0"

    # TODO : include ports in the dict?
    docker_images = {
        "lfoppiano/grobid": "lfoppiano/grobid:0.7.1",
        "pandoc/ubuntu-latex": "pandoc/ubuntu-latex:2.14",
        "jbarlow83/ocrmypdf": "jbarlow83/ocrmypdf:v13.3.0",
        "zotero/translation-server": "zotero/translation-server:2.0.4",
        "opensearchproject/opensearch": "opensearchproject/opensearch:1.3.0",
        "opensearchproject/opensearch-dashboards": os_db,
        "browserless/chrome": "browserless/chrome:latest",
        "bibutils": "bibutils:latest",
    }

    def __init__(self):
        self.local_registry = self.load_local_registry()

    @classmethod
    def load_local_registry(cls) -> list:

        local_registry_path = EnvironmentManager.paths["REGISTRY"]
        local_registry = []
        if local_registry_path.is_file():
            with open(local_registry_path, encoding="utf8") as f:
                local_registry_df = pd.json_normalize(safe_load(f))
                local_registry = local_registry_df.to_dict("records")

        return local_registry

    @classmethod
    def save_local_registry(cls, *, updated_registry: list) -> None:

        local_registry_path = cls.paths["REGISTRY"]

        updated_registry_df = pd.DataFrame(updated_registry)
        orderedCols = [
            "repo_name",
            "repo_source_path",
        ]
        for x in [x for x in updated_registry_df.columns if x not in orderedCols]:
            orderedCols.append(x)
        updated_registry_df = updated_registry_df.reindex(columns=orderedCols)

        local_registry_path.parents[0].mkdir(parents=True, exist_ok=True)
        with open(local_registry_path, "w", encoding="utf8") as f:
            yaml.dump(
                json.loads(
                    updated_registry_df.to_json(orient="records", default_handler=str)
                ),
                f,
                default_flow_style=False,
                sort_keys=False,
            )

    @classmethod
    def register_repo(cls, *, path_to_register: Path) -> None:

        local_registry = cls.load_local_registry()
        registered_paths = [x["repo_source_path"] for x in local_registry]

        if registered_paths != []:
            if str(path_to_register) in registered_paths:
                print(f"Warning: Path already registered: {path_to_register}")
                return
        else:
            print(f"Creating {cls.paths['REGISTRY']}")

        new_record = {
            "repo_name": path_to_register.stem,
            "repo_source_path": path_to_register,
        }
        git_repo = git.Repo(path_to_register)
        for remote in git_repo.remotes:
            if remote.url:
                new_record["repo_source_url"] = remote.url
        local_registry.append(new_record)
        cls.save_local_registry(updated_registry=local_registry)
        print(f"Registered path ({path_to_register})")

    @classmethod
    def get_name_mail_from_git(cls) -> typing.Tuple[str, str]:

        ggit_conf_path = Path.home() / Path(".gitconfig")
        global_conf_details = ("NA", "NA")
        if ggit_conf_path.is_file():
            glob_git_conf = git.GitConfigParser([str(ggit_conf_path)], read_only=True)
            global_conf_details = (
                glob_git_conf.get("user", "name"),
                glob_git_conf.get("user", "email"),
            )
        return global_conf_details

    @classmethod
    def build_docker_images(cls) -> None:

        client = docker.from_env()

        repo_tags = [image.tags for image in client.images.list()]
        repo_tags = [tag[0][: tag[0].find(":")] for tag in repo_tags if tag]

        for img_name, img_version in cls.docker_images.items():
            if img_name not in repo_tags:

                if "bibutils" == img_name:
                    print("Building bibutils Docker image...")
                    filedata = pkgutil.get_data(__name__, "docker/bibutils/Dockerfile")
                    if filedata:
                        fileobj = io.BytesIO(filedata)
                        client.images.build(fileobj=fileobj, tag="bibutils:latest")
                    else:
                        print("Cannot retrieve image bibutils")
                else:
                    print(f"Pulling {img_name} Docker image...")
                    client.images.pull(img_version)

    @classmethod
    def check_git_installed(cls) -> None:
        # pylint: disable=consider-using-with

        try:
            with open("/dev/null", "w", encoding="utf8") as null:
                subprocess.Popen("git", stdout=null, stderr=null)
        except OSError as e:
            raise colrev_exceptions.MissingDependencyError("git") from e

    @classmethod
    def check_docker_installed(cls) -> None:
        # pylint: disable=consider-using-with

        try:
            with open("/dev/null", "w", encoding="utf8") as null:
                subprocess.Popen("docker", stdout=null, stderr=null)
        except OSError as e:
            raise colrev_exceptions.MissingDependencyError("docker") from e

    def get_environment_details(self) -> dict:
        # pylint: disable=redefined-outer-name
        import colrev.review_manager

        LOCAL_INDEX = LocalIndex()

        environment_details = {}

        size = 0
        last_modified = "NOT_INITIATED"
        status = ""

        def get_last_modified() -> str:

            list_of_files = LOCAL_INDEX.opensearch_index.glob(
                "**/*"
            )  # * means all if need specific format then *.csv
            latest_file = max(list_of_files, key=os.path.getmtime)
            last_mod = datetime.fromtimestamp(latest_file.lstat().st_mtime)
            return last_mod.strftime("%Y-%m-%d %H:%M")

        try:
            size = LOCAL_INDEX.os.cat.count(
                index=LOCAL_INDEX.RECORD_INDEX, params={"format": "json"}
            )[0]["count"]
            last_modified = get_last_modified()
            status = "up"
        except (NotFoundError, IndexError):
            status = "down"

        environment_details["index"] = {
            "size": size,
            "last_modified": last_modified,
            "path": str(LocalIndex.local_environment_path),
            "status": status,
        }

        local_repos = self.load_local_registry()

        repos = []
        broken_links = []
        for repo in local_repos:
            try:
                cp_REVIEW_MANAGER = colrev.review_manager.ReviewManager(
                    path_str=repo["repo_source_path"]
                )
                CHECK_PROCESS = colrev.process.CheckProcess(
                    REVIEW_MANAGER=cp_REVIEW_MANAGER
                )
                repo_stat = CHECK_PROCESS.REVIEW_MANAGER.get_status()
                repo["size"] = repo_stat["colrev_status"]["overall"]["md_processed"]
                if repo_stat["atomic_steps"] != 0:
                    repo["progress"] = round(
                        repo_stat["completed_atomic_steps"] / repo_stat["atomic_steps"],
                        2,
                    )
                else:
                    repo["progress"] = -1

                repo["remote"] = False
                REVIEW_DATASET = CHECK_PROCESS.REVIEW_MANAGER.REVIEW_DATASET
                git_repo = REVIEW_DATASET.get_repo()
                for remote in git_repo.remotes:
                    if remote.url:
                        repo["remote"] = True
                repo["behind_remote"] = REVIEW_DATASET.behind_remote()

                repos.append(repo)
            except (NoSuchPathError, InvalidGitRepositoryError):
                broken_links.append(repo)

        environment_details["local_repos"] = {
            "repos": repos,
            "broken_links": broken_links,
        }
        return environment_details

    @classmethod
    def get_curated_outlets(cls) -> list:
        curated_outlets: typing.List[str] = []
        for repo_source_path in [
            x["repo_source_path"]
            for x in EnvironmentManager.load_local_registry()
            if "colrev/curated_metadata/" in x["repo_source_path"]
        ]:
            try:
                with open(f"{repo_source_path}/readme.md", encoding="utf-8") as f:
                    first_line = f.readline()
                curated_outlets.append(first_line.lstrip("# ").replace("\n", ""))

                with open(f"{repo_source_path}/records.bib", encoding="utf-8") as r:
                    outlets = []
                    for line in r.readlines():
                        # Note : the second part ("journal:"/"booktitle:")
                        # ensures that data provenance fields are skipped
                        if (
                            "journal" == line.lstrip()[:7]
                            and "journal:" != line.lstrip()[:8]
                        ):
                            journal = line[line.find("{") + 1 : line.rfind("}")]
                            outlets.append(journal)
                        if (
                            "booktitle" == line.lstrip()[:9]
                            and "booktitle:" != line.lstrip()[:10]
                        ):
                            booktitle = line[line.find("{") + 1 : line.rfind("}")]
                            outlets.append(booktitle)

                    if len(set(outlets)) != 1:
                        raise colrev_exceptions.CuratedOutletNotUnique(
                            "Error: Duplicate outlets in curated_metadata of "
                            f"{repo_source_path} : {','.join(list(set(outlets)))}"
                        )
            except FileNotFoundError as e:
                print(e)

        return curated_outlets


class LocalIndex:

    global_keys = ["doi", "dblp_key", "colrev_pdf_id", "url"]
    max_len_sha256 = 2**256
    request_timeout = 90

    local_environment_path = Path.home().joinpath("colrev")

    opensearch_index = local_environment_path / Path("index")
    teiind_path = local_environment_path / Path(".tei_index/")
    annotators_path = local_environment_path / Path("annotators")

    # Note : records are indexed by id = hash(colrev_id)
    # to ensure that the indexing-ids do not exceed limits
    # such as the opensearch limit of 512 bytes.
    # This enables efficient retrieval based on id=hash(colrev_id)
    # but also search-based retrieval using only colrev_ids

    RECORD_INDEX = "record_index"
    TOC_INDEX = "toc_index"

    # Note: we need the local_curated_metadata field for is_duplicate()

    def __init__(self, *, startup_without_waiting: bool = False):

        self.os = OpenSearch("http://localhost:9200")

        self.opensearch_index.mkdir(exist_ok=True, parents=True)
        try:
            self.check_opensearch_docker_available()
        except TransportError:

            self.start_opensearch_docker(
                startup_without_waiting=startup_without_waiting
            )
        if not startup_without_waiting:
            self.check_opensearch_docker_available()

        logging.getLogger("opensearch").setLevel(logging.ERROR)

    def start_opensearch_docker_dashboards(self) -> None:

        self.start_opensearch_docker()

        os_dashboard_image = EnvironmentManager.docker_images[
            "opensearchproject/opensearch-dashboards"
        ]

        client = docker.from_env()
        if not any(
            "opensearch-dashboards" in container.name
            for container in client.containers.list()
        ):
            try:
                print("Start OpenSearch Dashboards")

                if not client.networks.list(names=["opensearch-net"]):
                    client.networks.create("opensearch-net")

                client.containers.run(
                    os_dashboard_image,
                    name="opensearch-dashboards",
                    ports={"5601/tcp": 5601},
                    auto_remove=True,
                    detach=True,
                    environment={
                        "OPENSEARCH_HOSTS": '["http://opensearch-node:9200"]',
                        "DISABLE_SECURITY_DASHBOARDS_PLUGIN": "true",
                    },
                    network="opensearch-net",
                )
            except docker.errors.APIError as e:
                print(e)

    def start_opensearch_docker(self, *, startup_without_waiting: bool = False) -> None:

        os_image = EnvironmentManager.docker_images["opensearchproject/opensearch"]
        client = docker.from_env()
        if not any(
            "opensearch" in container.name for container in client.containers.list()
        ):
            try:
                if not startup_without_waiting:
                    print("Start LocalIndex")

                if not client.networks.list(names=["opensearch-net"]):
                    client.networks.create("opensearch-net")
                client.containers.run(
                    os_image,
                    name="opensearch-node",
                    ports={"9200/tcp": 9200, "9600/tcp": 9600},
                    auto_remove=True,
                    detach=True,
                    environment={
                        "cluster.name": "opensearch-cluster",
                        "node.name": "opensearch-node",
                        "bootstrap.memory_lock": "true",
                        "OPENSEARCH_JAVA_OPTS": "-Xms512m -Xmx512m",
                        "DISABLE_INSTALL_DEMO_CONFIG": "true",
                        "DISABLE_SECURITY_PLUGIN": "true",
                        "discovery.type": "single-node",
                    },
                    volumes={
                        str(self.opensearch_index): {
                            "bind": "/usr/share/opensearch/data",
                            "mode": "rw",
                        }
                    },
                    ulimits=[
                        docker.types.Ulimit(name="memlock", soft=-1, hard=-1),
                        docker.types.Ulimit(name="nofile", soft=65536, hard=65536),
                    ],
                    network="opensearch-net",
                )
            except docker.errors.APIError as e:
                print(e)

        logging.getLogger("opensearch").setLevel(logging.ERROR)

        available = False
        try:
            self.os.get(index=self.RECORD_INDEX, id="test")
        except NotFoundError:
            available = True
        except (
            requests.exceptions.RequestException,
            TransportError,
            SerializationError,
        ):
            pass

        if not available and not startup_without_waiting:
            print("Waiting until LocalIndex is available")
            for _ in tqdm(range(0, 20)):
                try:
                    self.os.get(
                        index=self.RECORD_INDEX,
                        id="test",
                    )
                    break
                except NotFoundError:
                    break
                except (
                    requests.exceptions.RequestException,
                    TransportError,
                    SerializationError,
                ):
                    time.sleep(3)
        logging.getLogger("opensearch").setLevel(logging.WARNING)

    def check_opensearch_docker_available(self) -> None:
        # If not available after 120s: raise error
        self.os.info()

    def __get_record_hash(self, *, record: dict) -> str:
        # Note : may raise NotEnoughDataToIdentifyException
        string_to_hash = colrev.record.Record(data=record).create_colrev_id()
        return hashlib.sha256(string_to_hash.encode("utf-8")).hexdigest()

    def __increment_hash(self, *, paper_hash: str) -> str:

        plaintext = binascii.unhexlify(paper_hash)
        # also, we'll want to know our length later on
        plaintext_length = len(plaintext)
        plaintext_number = int.from_bytes(plaintext, "big")

        # recommendation: do not increment by 1
        plaintext_number += 10
        plaintext_number = plaintext_number % self.max_len_sha256

        new_plaintext = plaintext_number.to_bytes(plaintext_length, "big")
        new_hex = binascii.hexlify(new_plaintext)
        # print(new_hex.decode("utf-8"))

        return new_hex.decode("utf-8")

    def __get_tei_index_file(self, *, paper_hash: str) -> Path:
        return self.teiind_path / Path(f"{paper_hash[:2]}/{paper_hash[2:]}.tei.xml")

    def __store_record(self, *, paper_hash: str, record: dict) -> None:

        if "file" in record:
            try:
                tei_path = self.__get_tei_index_file(paper_hash=paper_hash)
                tei_path.parents[0].mkdir(exist_ok=True, parents=True)
                if Path(record["file"]).is_file():
                    TEI_INSTANCE = TEIParser(
                        pdf_path=Path(record["file"]),
                        tei_path=tei_path,
                    )
                    record["fulltext"] = TEI_INSTANCE.get_tei_str()
            except (
                colrev_exceptions.TEI_Exception,
                AttributeError,
                SerializationError,
                TransportError,
            ):
                pass

        RECORD = colrev.record.Record(data=record)

        if "colrev_status" in RECORD.data:
            del RECORD.data["colrev_status"]

        self.os.index(
            index=self.RECORD_INDEX, id=paper_hash, body=RECORD.get_data(stringify=True)
        )

    def __retrieve_toc_index(self, *, toc_key: str) -> dict:

        toc_item = {}
        try:
            toc_item_response = self.os.get(index=self.TOC_INDEX, id=toc_key)
            if "_source" in toc_item_response:
                toc_item = toc_item_response["_source"]
        except SerializationError:
            pass
        return toc_item

    def __amend_record(self, *, paper_hash: str, record: dict) -> None:

        try:
            saved_record_response = self.os.get(
                index=self.RECORD_INDEX,
                id=paper_hash,
            )
            saved_record = saved_record_response["_source"]

            SAVED_RECORD = colrev.record.Record(
                data=self.parse_record(record=saved_record)
            )

            RECORD = colrev.record.Record(data=record)

            # combine metadata_source_repository_paths in a semicolon-separated list
            metadata_source_repository_paths = RECORD.data[
                "metadata_source_repository_paths"
            ]
            SAVED_RECORD.data["metadata_source_repository_paths"] += (
                "\n" + metadata_source_repository_paths
            )

            record = RECORD.get_data()

            # amend saved record
            for k, v in record.items():
                # Note : the record from the first repository should take precedence)
                if k in saved_record or k in ["colrev_status"]:
                    continue

                # source_info = colrev.record.Record(data=record).
                # get_provenance_field_source(key=k)
                source_info, _ = colrev.record.Record(data=record).get_field_provenance(
                    key=k,
                    default_source=RECORD.data.get(
                        "metadata_source_repository_paths", "None"
                    ),
                )

                SAVED_RECORD.update_field(key=k, value=v, source=source_info)

            if "file" in record and "fulltext" not in SAVED_RECORD.data:
                try:
                    tei_path = self.__get_tei_index_file(paper_hash=paper_hash)
                    tei_path.parents[0].mkdir(exist_ok=True, parents=True)
                    if Path(record["file"]).is_file():
                        TEI_INSTANCE = TEIParser(
                            pdf_path=Path(record["file"]),
                            tei_path=tei_path,
                        )
                        SAVED_RECORD.data["fulltext"] = TEI_INSTANCE.get_tei_str()
                except (
                    colrev_exceptions.TEI_Exception,
                    AttributeError,
                    SerializationError,
                    TransportError,
                ):
                    pass

            # pylint: disable=unexpected-keyword-arg
            # Note : update(...) accepts the timeout keyword
            # https://opensearch-project.github.io/opensearch-py/
            # api-ref/client.html#opensearchpy.OpenSearch.update
            self.os.update(
                index=self.RECORD_INDEX,
                id=paper_hash,
                body={"doc": SAVED_RECORD.get_data(stringify=True)},
                timeout=self.request_timeout,
            )
        except NotFoundError:
            pass

    def __get_toc_key(self, *, record: dict) -> str:
        toc_key = "NA"
        if "article" == record["ENTRYTYPE"]:
            toc_key = f"{record.get('journal', '').lower()}"
            if "volume" in record:
                toc_key = toc_key + f"|{record['volume']}"
            if "number" in record:
                toc_key = toc_key + f"|{record['number']}"
            else:
                toc_key = toc_key + "|"
        elif "inproceedings" == record["ENTRYTYPE"]:
            toc_key = (
                f"{record.get('booktitle', '').lower()}" + f"|{record.get('year', '')}"
            )

        return toc_key

    def get_fields_to_remove(self, *, record: dict) -> list:
        """Compares the record to available toc items and
        returns fields to remove (if any)"""

        internal_record = deepcopy(record)
        fields_to_remove = []
        if "volume" in internal_record.keys() and "number" in internal_record.keys():

            toc_key_full = self.__get_toc_key(record=internal_record)

            wo_nr = deepcopy(internal_record)
            del wo_nr["number"]
            toc_key_wo_nr = self.__get_toc_key(record=wo_nr)
            if not self.os.exists(
                index=self.TOC_INDEX, id=toc_key_full
            ) and self.os.exists(index=self.TOC_INDEX, id=toc_key_wo_nr):
                fields_to_remove.append("number")
                return fields_to_remove

            wo_vol = deepcopy(internal_record)
            del wo_vol["volume"]
            toc_key_wo_vol = self.__get_toc_key(record=wo_vol)
            if not self.os.exists(
                index=self.TOC_INDEX, id=toc_key_full
            ) and self.os.exists(index=self.TOC_INDEX, id=toc_key_wo_vol):
                fields_to_remove.append("volume")
                return fields_to_remove

            wo_vol_nr = deepcopy(internal_record)
            del wo_vol_nr["volume"]
            del wo_vol_nr["number"]
            toc_key_wo_vol_nr = self.__get_toc_key(record=wo_vol_nr)
            if not self.os.exists(
                index=self.TOC_INDEX, id=toc_key_full
            ) and self.os.exists(index=self.TOC_INDEX, id=toc_key_wo_vol_nr):
                fields_to_remove.append("number")
                fields_to_remove.append("volume")
                return fields_to_remove

        return fields_to_remove

    def __toc_index(self, *, record) -> None:
        if not colrev.record.Record(data=record).masterdata_is_curated():
            return

        if record.get("ENTRYTYPE", "") in ["article", "inproceedings"]:
            # Note : records are md_prepared, i.e., complete

            toc_key = self.__get_toc_key(record=record)
            if "NA" == toc_key:
                return

            # print(toc_key)
            try:
                record_colrev_id = colrev.record.Record(data=record).create_colrev_id()

                if not self.os.exists(index=self.TOC_INDEX, id=toc_key):
                    toc_item = {
                        "toc_key": toc_key,
                        "colrev_ids": [record_colrev_id],
                    }
                    self.os.index(index=self.TOC_INDEX, id=toc_key, body=toc_item)
                else:
                    toc_item_response = self.os.get(
                        index=self.TOC_INDEX,
                        id=toc_key,
                    )
                    toc_item = toc_item_response["_source"]
                    if toc_item["toc_key"] == toc_key:
                        # ok - no collision, update the record
                        # Note : do not update (the record from the first repository
                        #  should take precedence - reset the index to update)
                        if record_colrev_id not in toc_item["colrev_ids"]:
                            toc_item["colrev_ids"].append(  # type: ignore
                                record_colrev_id
                            )
                            self.os.update(
                                index=self.TOC_INDEX, id=toc_key, body={"doc": toc_item}
                            )
            except (
                colrev_exceptions.NotEnoughDataToIdentifyException,
                TransportError,
                SerializationError,
            ):
                pass

        return

    def __retrieve_based_on_colrev_id(self, *, cids_to_retrieve: list) -> dict:
        # Note : may raise NotEnoughDataToIdentifyException

        for cid_to_retrieve in cids_to_retrieve:
            paper_hash = hashlib.sha256(cid_to_retrieve.encode("utf-8")).hexdigest()
            while True:  # Note : while breaks with NotFoundError
                try:
                    res = self.os.get(
                        index=self.RECORD_INDEX,
                        id=paper_hash,
                    )
                    retrieved_record = res["_source"]
                    if (
                        cid_to_retrieve
                        in colrev.record.Record(data=retrieved_record).get_colrev_id()
                    ):
                        return retrieved_record
                    # Collision
                    paper_hash = self.__increment_hash(paper_hash=paper_hash)
                except (NotFoundError, TransportError, SerializationError):
                    break
                except Exception:
                    # print(e)
                    pass

        # search colrev_id field
        for cid_to_retrieve in cids_to_retrieve:
            try:
                # match_phrase := exact match
                # TODO : the following requires some testing.
                resp = self.os.search(
                    index=self.RECORD_INDEX,
                    body={"query": {"match": {"colrev_id": cid_to_retrieve}}},
                )
                retrieved_record = resp["hits"]["hits"][0]["_source"]
                if cid_to_retrieve in retrieved_record.get("colrev_id", "NA"):
                    return retrieved_record
            except (IndexError, NotFoundError, TransportError, SerializationError) as e:
                raise colrev_exceptions.RecordNotInIndexException from e
            except Exception:
                # print(e)
                pass

        raise colrev_exceptions.RecordNotInIndexException

    def __retrieve_from_record_index(self, *, record: dict) -> dict:
        # Note : may raise NotEnoughDataToIdentifyException

        RECORD = colrev.record.Record(data=record)
        if "colrev_id" in RECORD.data:
            cid_to_retrieve = RECORD.get_colrev_id()
        else:
            cid_to_retrieve = [RECORD.create_colrev_id()]

        retrieved_record = self.__retrieve_based_on_colrev_id(
            cids_to_retrieve=cid_to_retrieve
        )
        if retrieved_record["ENTRYTYPE"] != record["ENTRYTYPE"]:
            raise colrev_exceptions.RecordNotInIndexException
        return retrieved_record

    def parse_record(self, *, record: dict) -> dict:
        # pylint: disable=redefined-outer-name
        import colrev.review_dataset

        # Note : we need to parse it through parse_records_dict (pybtex / parse_string)
        # To make sure all fields are formatted /parsed consistently
        parser = bibtex.Parser()
        load_str = (
            "@"
            + record["ENTRYTYPE"]
            + "{"
            + record["ID"]
            + "\n"
            + ",\n".join(
                [
                    f"{k} = {{{v}}}"
                    for k, v in record.items()
                    if k not in ["ID", "ENTRYTYPE"]
                ]
            )
            + "}"
        )
        bib_data = parser.parse_string(load_str)
        records_dict = colrev.review_dataset.ReviewDataset.parse_records_dict(
            records_dict=bib_data.entries
        )
        record = list(records_dict.values())[0]

        return record

    def prep_record_for_return(
        self, *, record: dict, include_file: bool = False, include_colrev_ids=False
    ) -> dict:

        record = self.parse_record(record=record)

        # Note: record['file'] should be an absolute path by definition
        # when stored in the LocalIndex
        if "file" in record:
            if not Path(record["file"]).is_file():
                del record["file"]

        if "fulltext" in record:
            del record["fulltext"]
        if "tei_file" in record:
            del record["tei_file"]
        if "grobid-version" in record:
            del record["grobid-version"]
        if include_colrev_ids:
            if "colrev_id" in record:
                pass
        else:
            if "colrev_id" in record:
                del record["colrev_id"]

        if "excl_criteria" in record:
            del record["excl_criteria"]
        if "exclusion_criteria" in record:
            del record["exclusion_criteria"]

        if "local_curated_metadata" in record:
            del record["local_curated_metadata"]

        if "metadata_source_repository_paths" in record:
            del record["metadata_source_repository_paths"]

        if not include_file:
            if "file" in record:
                del record["file"]
            if "colref_pdf_id" in record:
                del record["colref_pdf_id"]

        record["colrev_status"] = colrev.record.RecordState.md_prepared

        return record

    def duplicate_outlets(self) -> bool:

        print("Validate curated metadata")

        curated_outlets = EnvironmentManager.get_curated_outlets()

        if len(curated_outlets) != len(set(curated_outlets)):
            duplicated = [
                item
                for item, count in collections.Counter(curated_outlets).items()
                if count > 1
            ]
            print(
                f"Error: Duplicate outlets in curated_metadata : {','.join(duplicated)}"
            )
            return True

        return False

    def index_record(self, *, record: dict) -> None:
        # Note : may raise NotEnoughDataToIdentifyException

        copy_for_toc_index = deepcopy(record)

        if "colrev_status" not in record:
            return

        # Note : it is important to exclude md_prepared if the LocalIndex
        # is used to dissociate duplicates
        if record["colrev_status"] in [
            colrev.record.RecordState.md_retrieved,
            colrev.record.RecordState.md_imported,
            colrev.record.RecordState.md_prepared,
            colrev.record.RecordState.md_needs_manual_preparation,
        ]:
            return

        # TODO : remove provenance on project-specific fields

        if "screening_criteria" in record:
            del record["screening_criteria"]
        # Note: if the colrev_pdf_id has not been checked,
        # we cannot use it for retrieval or preparation.
        if record["colrev_status"] not in [
            colrev.record.RecordState.pdf_prepared,
            colrev.record.RecordState.rev_excluded,
            colrev.record.RecordState.rev_included,
            colrev.record.RecordState.rev_synthesized,
        ]:
            if "colrev_pdf_id" in record:
                del record["colrev_pdf_id"]

        # Note : this is the first run, no need to split/list
        if "colrev/curated_metadata" in record["metadata_source_repository_paths"]:
            # Note : local_curated_metadata is important to identify non-duplicates
            # between curated_metadata_repositories
            record["local_curated_metadata"] = "yes"

        # To fix pdf_hash fields that should have been renamed
        if "pdf_hash" in record:
            record["colref_pdf_id"] = "cpid1:" + record["pdf_hash"]
            del record["pdf_hash"]

        if "colrev_origin" in record:
            del record["colrev_origin"]

        # Note : file paths should be absolute when added to the LocalIndex
        if "file" in record:
            pdf_path = Path(record["file"])
            if pdf_path.is_file():
                record["file"] = str(pdf_path)
            else:
                del record["file"]

        if record.get("year", "NA").isdigit():
            record["year"] = int(record["year"])
        elif "year" in record:
            del record["year"]

        try:

            cid_to_index = colrev.record.Record(data=record).create_colrev_id()
            paper_hash = self.__get_record_hash(record=record)

            try:
                # check if the record is already indexed (based on d)
                retrieved_record = self.retrieve(record=record, include_colrev_ids=True)
                retrieved_record_cid = colrev.record.Record(
                    data=retrieved_record
                ).get_colrev_id()

                # if colrev_ids not identical (but overlapping): amend
                if not set(retrieved_record_cid).isdisjoint([cid_to_index]):
                    # Note: we need the colrev_id of the retrieved_record
                    # (may be different from record)
                    self.__amend_record(
                        paper_hash=self.__get_record_hash(record=retrieved_record),
                        record=record,
                    )
                    return
            except (
                colrev_exceptions.RecordNotInIndexException,
                TransportError,
                SerializationError,
            ):
                pass

            while True:
                if not self.os.exists(index=self.RECORD_INDEX, id=hash):
                    self.__store_record(paper_hash=paper_hash, record=record)
                    break
                saved_record_response = self.os.get(
                    index=self.RECORD_INDEX,
                    id=paper_hash,
                )
                saved_record = saved_record_response["_source"]
                saved_record_cid = colrev.record.Record(
                    data=saved_record
                ).create_colrev_id(assume_complete=True)
                if saved_record_cid == cid_to_index:
                    # ok - no collision, update the record
                    # Note : do not update (the record from the first repository
                    # should take precedence - reset the index to update)
                    self.__amend_record(paper_hash=paper_hash, record=record)
                    break
                # to handle the collision:
                print(f"Collision: {paper_hash}")
                print(cid_to_index)
                print(saved_record_cid)
                print(saved_record)
                paper_hash = self.__increment_hash(paper_hash=paper_hash)

        except (
            colrev_exceptions.NotEnoughDataToIdentifyException,
            TransportError,
            SerializationError,
        ):
            return

        # Note : only use curated journal metadata for TOC indices
        # otherwise, TOCs will be incomplete and affect retrieval
        if (
            "colrev/curated_metadata"
            in copy_for_toc_index["metadata_source_repository_paths"]
        ):
            self.__toc_index(record=copy_for_toc_index)
        return

    def index_colrev_project(self, *, repo_source_path):
        # pylint: disable=redefined-outer-name
        import colrev.review_manager

        try:
            if not Path(repo_source_path).is_dir():
                print(f"Warning {repo_source_path} not a directory")
                return

            print(f"Index records from {repo_source_path}")
            os.chdir(repo_source_path)
            REVIEW_MANAGER = colrev.review_manager.ReviewManager(
                path_str=str(repo_source_path)
            )
            CHECK_PROCESS = colrev.process.CheckProcess(REVIEW_MANAGER=REVIEW_MANAGER)
            if not CHECK_PROCESS.REVIEW_MANAGER.paths["RECORDS_FILE"].is_file():
                return
            records = CHECK_PROCESS.REVIEW_MANAGER.REVIEW_DATASET.load_records_dict()

            # Add metadata_source_repository_paths : list of repositories from which
            # the record was integrated. Important for is_duplicate(...)

            for record in records.values():
                record.update(metadata_source_repository_paths=repo_source_path)

            # Set masterdata_provenace to CURATED:{url}
            curation_url = CHECK_PROCESS.REVIEW_MANAGER.settings.project.curation_url
            if CHECK_PROCESS.REVIEW_MANAGER.settings.project.curated_masterdata:
                for record in records.values():
                    record.update(
                        colrev_masterdata_provenance=f"CURATED:{curation_url};;"
                    )

            # Add curation_url to curated fields (provenance)
            for (
                curated_field
            ) in CHECK_PROCESS.REVIEW_MANAGER.settings.project.curated_fields:

                for record in records.values():
                    colrev.record.Record(data=record).add_data_provenance(
                        key=curated_field, source=f"CURATED:{curation_url}"
                    )

            # Set absolute file paths (for simpler retrieval)
            for record in records.values():
                if "file" in record:
                    record.update(file=repo_source_path / Path(record["file"]))

            for record in tqdm(records.values()):
                self.index_record(record=record)

        except InvalidGitRepositoryError:
            print(f"InvalidGitRepositoryError: {repo_source_path}")
        except KeyError as e:
            print(f"KeyError: {e}")
        except MissingValueError as e:
            print(f"MissingValueError (settings.json): {e} ({repo_source_path})")
        return

    def index(self) -> None:
        # import shutil

        # Note : this task takes long and does not need to run often
        cache_path = EnvironmentManager.colrev_path / Path("prep_requests_cache")
        session = requests_cache.CachedSession(
            str(cache_path), backend="sqlite", expire_after=timedelta(days=30)
        )
        # pylint: disable=unnecessary-lambda
        # Note : lambda is necessary to prevent immediate function call
        Timer(0.1, lambda: session.remove_expired_responses()).start()

        print("Start LocalIndex")

        if self.duplicate_outlets():
            return

        print(f"Reset {self.RECORD_INDEX} and {self.TOC_INDEX}")
        # if self.teiind_path.is_dir():
        #     shutil.rmtree(self.teiind_path)

        self.opensearch_index.mkdir(exist_ok=True, parents=True)
        if self.RECORD_INDEX in self.os.indices.get_alias().keys():
            self.os.indices.delete(index=self.RECORD_INDEX)
        if self.TOC_INDEX in self.os.indices.get_alias().keys():
            self.os.indices.delete(index=self.TOC_INDEX)
        self.os.indices.create(index=self.RECORD_INDEX)
        self.os.indices.create(index=self.TOC_INDEX)

        repo_source_paths = [
            x["repo_source_path"] for x in EnvironmentManager.load_local_registry()
        ]
        for repo_source_path in repo_source_paths:
            self.index_colrev_project(repo_source_path=repo_source_path)

        # for annotator in self.annotators_path.glob("*/annotate.py"):
        #     print(f"Load {annotator}")
        #     import imp

        #     annotator_module = imp.load_source("annotator_module", str(annotator))
        #     annotate = getattr(annotator_module, "annotate")
        #     annotate(self)
        # Note : es.update can use functions applied to each record (for the update)

        return

    def get_year_from_toc(self, *, record: dict) -> str:
        year = "NA"

        toc_key = self.__get_toc_key(record=record)
        toc_items = []
        try:
            if self.os.exists(index=self.TOC_INDEX, id=toc_key):
                res = self.__retrieve_toc_index(toc_key=toc_key)
                toc_items = res.get("colrev_ids", [])  # type: ignore
        except (TransportError, SerializationError):
            toc_items = []

        if len(toc_items) > 0:
            try:

                toc_records_colrev_id = toc_items[0]
                paper_hash = hashlib.sha256(
                    toc_records_colrev_id.encode("utf-8")
                ).hexdigest()
                res = self.os.get(
                    index=self.RECORD_INDEX,
                    id=str(paper_hash),
                )
                if "_source" in res:
                    record = res["_source"]  # type: ignore
                    year = record.get("year", "NA")

            except (
                colrev_exceptions.NotEnoughDataToIdentifyException,
                TransportError,
                SerializationError,
            ):
                pass

        return year

    def retrieve_from_toc(
        self, *, record: dict, similarity_threshold: float, include_file=False
    ) -> dict:
        toc_key = self.__get_toc_key(record=record)

        # 1. get TOC
        toc_items = []
        if self.os.exists(index=self.TOC_INDEX, id=toc_key):
            try:
                res = self.__retrieve_toc_index(toc_key=toc_key)
                toc_items = res.get("colrev_ids", [])  # type: ignore
            except (TransportError, SerializationError):
                toc_items = []

        # 2. get most similar record
        elif len(toc_items) > 0:
            try:
                # TODO : we need to search tocs even if records are not complete:
                # and a NotEnoughDataToIdentifyException is thrown
                record_colrev_id = colrev.record.Record(data=record).create_colrev_id()
                sim_list = []
                for toc_records_colrev_id in toc_items:
                    # Note : using a simpler similarity measure
                    # because the publication outlet parameters are already identical
                    sv = fuzz.ratio(record_colrev_id, toc_records_colrev_id) / 100
                    sim_list.append(sv)

                if max(sim_list) > similarity_threshold:
                    toc_records_colrev_id = toc_items[sim_list.index(max(sim_list))]
                    paper_hash = hashlib.sha256(
                        toc_records_colrev_id.encode("utf-8")
                    ).hexdigest()
                    res = self.os.get(
                        index=self.RECORD_INDEX,
                        id=str(paper_hash),
                    )
                    record = res["_source"]  # type: ignore
                    return self.prep_record_for_return(
                        record=record, include_file=include_file
                    )
            except colrev_exceptions.NotEnoughDataToIdentifyException:
                pass

        raise colrev_exceptions.RecordNotInIndexException()

    def get_from_index_exact_match(self, *, index_name, key, value) -> dict:

        res = {}
        try:
            resp = self.os.search(
                index=index_name,
                body={"query": {"match_phrase": {key: value}}},
            )
            res = resp["hits"]["hits"][0]["_source"]
        except (JSONDecodeError, NotFoundError, TransportError, SerializationError):
            pass
        return res

    def retrieve(
        self, *, record: dict, include_file: bool = False, include_colrev_ids=False
    ) -> dict:
        """
        Convenience function to retrieve the indexed record metadata
        based on another record
        """

        retrieved_record: typing.Dict = {}

        # 1. Try the record index

        try:
            retrieved_record = self.__retrieve_from_record_index(record=record)
        except (
            NotFoundError,
            colrev_exceptions.RecordNotInIndexException,
            colrev_exceptions.NotEnoughDataToIdentifyException,
            TransportError,
            SerializationError,
        ):
            pass

        if retrieved_record:
            return self.prep_record_for_return(
                record=retrieved_record,
                include_file=include_file,
                include_colrev_ids=include_colrev_ids,
            )

        # 2. Try using global-ids
        if not retrieved_record:
            for k, v in record.items():
                if k not in self.global_keys or "ID" == k:
                    continue
                try:
                    retrieved_record = self.get_from_index_exact_match(
                        index_name=self.RECORD_INDEX, key=k, value=v
                    )
                    break
                except (
                    IndexError,
                    NotFoundError,
                    JSONDecodeError,
                    KeyError,
                    TransportError,
                    SerializationError,
                ):
                    pass

        if not retrieved_record:
            raise colrev_exceptions.RecordNotInIndexException(
                record.get("ID", "no-key")
            )

        return self.prep_record_for_return(
            record=retrieved_record,
            include_file=include_file,
            include_colrev_ids=include_colrev_ids,
        )

    def is_duplicate(self, *, record1_colrev_id: list, record2_colrev_id: list) -> str:
        """Convenience function to check whether two records are a duplicate"""

        try:

            # Ensure that we receive actual lists
            # otherwise, __retrieve_based_on_colrev_id iterates over a string and
            # self.os.search returns random results
            assert isinstance(record1_colrev_id, list)
            assert isinstance(record2_colrev_id, list)

            # Prevent errors caused by short colrev_ids/empty lists
            if (
                any(len(cid) < 20 for cid in record1_colrev_id)
                or any(len(cid) < 20 for cid in record2_colrev_id)
                or 0 == len(record1_colrev_id)
                or 0 == len(record2_colrev_id)
            ):
                return "unknown"

            # Easy case: the initial colrev_ids overlap => duplicate
            initial_colrev_ids_overlap = not set(record1_colrev_id).isdisjoint(
                list(record2_colrev_id)
            )
            if initial_colrev_ids_overlap:
                return "yes"

            # Retrieve records from LocalIndex and use that information
            # to decide whether the records are duplicates

            r1_index = self.__retrieve_based_on_colrev_id(
                cids_to_retrieve=record1_colrev_id
            )
            r2_index = self.__retrieve_based_on_colrev_id(
                cids_to_retrieve=record2_colrev_id
            )
            # Each record may originate from multiple repositories simultaneously
            # see integration of records in __amend_record(...)
            # This information is stored in metadata_source_repository_paths (list)

            r1_metadata_source_repository_paths = r1_index[
                "metadata_source_repository_paths"
            ].split("\n")
            r2_metadata_source_repository_paths = r2_index[
                "metadata_source_repository_paths"
            ].split("\n")

            # There are no duplicates within repositories
            # because we only index records that are md_processed or beyond
            # see conditions of index_record(...)

            # The condition that two records are in the same repository is True if
            # their metadata_source_repository_paths overlap.
            # This does not change if records are also in non-overlapping repositories

            same_repository = not set(r1_metadata_source_repository_paths).isdisjoint(
                set(r2_metadata_source_repository_paths)
            )

            # colrev_ids must be used instead of IDs
            # because IDs of original repositories
            # are not available in the integrated record

            colrev_ids_overlap = not set(
                colrev.record.Record(data=r1_index).get_colrev_id()
            ).isdisjoint(
                list(list(colrev.record.Record(data=r2_index).get_colrev_id()))
            )

            if same_repository:
                if colrev_ids_overlap:
                    return "yes"
                return "no"

            # Curated metadata repositories do not curate outlets redundantly,
            # i.e., there are no duplicates between curated repositories.
            # see duplicate_outlets(...)

            different_curated_repositories = (
                "CURATED:" in r1_index.get("colrev_masterdata_provenance", "")
                and "CURATED:" in r2_index.get("colrev_masterdata_provenance", "")
                and (
                    r1_index.get("colrev_masterdata_provenance", "a")
                    != r2_index.get("colrev_masterdata_provenance", "b")
                )
            )

            if different_curated_repositories:
                return "no"

        except (
            colrev_exceptions.RecordNotInIndexException,
            NotFoundError,
            colrev_exceptions.NotEnoughDataToIdentifyException,
        ):
            pass

        return "unknown"

    def analyze(self, *, threshold: float = 0.95) -> None:

        # TODO : update analyze() functionality based on es index

        # changes = []
        # for d_file in self.dind_path.rglob("*.txt"):
        #     str1, str2 = d_file.read_text().split("\n")
        #     similarity = fuzz.ratio(str1, str2) / 100
        #     if similarity < threshold:
        #         changes.append(
        #             {"similarity": similarity, "str": str1, "fname": str(d_file)}
        #         )
        #         changes.append(
        #             {"similarity": similarity, "str": str2, "fname": str(d_file)}
        #         )

        # df = pd.DataFrame(changes)
        # df = df.sort_values(by=["similarity", "fname"])
        # df.to_csv("changes.csv", index=False)
        # print("Exported changes.csv")

        # colrev_pdf_ids = []
        # https://bit.ly/3tbypkd
        # for r_file in self.rind_path.rglob("*.bib"):

        #     with open(r_file, encoding="utf8") as f:
        #         while True:
        #             line = f.readline()
        #             if not line:
        #                 break
        #             if "colrev_pdf_id" in line[:9]:
        #                 val = line[line.find("{") + 1 : line.rfind("}")]
        #                 colrev_pdf_ids.append(val)

        # colrev_pdf_ids_dupes = [
        #     item for item, count in
        #       collections.Counter(colrev_pdf_ids).items() if count > 1
        # ]

        # with open("non-unique-cpids.txt", "w", encoding="utf8") as o:
        #     o.write("\n".join(colrev_pdf_ids_dupes))
        # print("Export non-unique-cpids.txt")
        return


class Resources:

    curations_path = Path.home().joinpath("colrev/curated_metadata")
    annotators_path = Path.home().joinpath("colrev/annotators")

    def __init__(self):
        pass

    def install_curated_resource(self, *, curated_resource: str) -> bool:

        # check if url else return False
        # validators.url(curated_resource)
        if "http" not in curated_resource:
            curated_resource = "https://github.com/" + curated_resource
        self.curations_path.mkdir(exist_ok=True, parents=True)
        repo_dir = self.curations_path / Path(curated_resource.split("/")[-1])
        annotator_dir = self.annotators_path / Path(curated_resource.split("/")[-1])
        if repo_dir.is_dir():
            print(f"Repo already exists ({repo_dir})")
            return False
        print(f"Download curated resource from {curated_resource}")
        git.Repo.clone_from(curated_resource, repo_dir, depth=1)

        if (repo_dir / Path("records.bib")).is_file():
            EnvironmentManager.register_repo(path_to_register=repo_dir)
        elif (repo_dir / Path("annotate.py")).is_file():
            shutil.move(str(repo_dir), str(annotator_dir))
        elif (repo_dir / Path("readme.md")).is_file():
            text = Path(repo_dir / "readme.md").read_text(encoding="utf-8")
            for line in [x for x in text.splitlines() if "colrev env --install" in x]:
                if line == curated_resource:
                    continue
                self.install_curated_resource(
                    curated_resource=line.replace("colrev env --install ", "")
                )
        else:
            print(f"Error: repo does not contain a records.bib/linked repos {repo_dir}")
        return True


class ZoteroTranslationService:
    def __init__(self):
        pass

    def start_zotero_translators(self) -> None:

        if self.zotero_service_available():
            return

        zotero_image = EnvironmentManager.docker_images["zotero/translation-server"]

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
            et = requests.post(
                "http://127.0.0.1:1969/web",
                headers=content_type_header,
                data=url,
            )
            if et.status_code == 200:
                return True
        except requests.exceptions.ConnectionError:
            pass
        return False


class ScreenshotService:
    def __init__(self):
        pass

    # TODO : close service after the script has run

    def start_screenshot_service(self) -> None:

        if self.screenshot_service_available():
            return

        EnvironmentManager.build_docker_images()

        chrome_browserless_image = EnvironmentManager.docker_images[
            "browserless/chrome"
        ]

        client = docker.from_env()

        running_containers = [
            str(container.image) for container in client.containers.list()
        ]
        if chrome_browserless_image not in running_containers:
            client.containers.run(
                chrome_browserless_image,
                ports={"3000/tcp": ("127.0.0.1", 3000)},
                auto_remove=True,
                detach=True,
            )

        i = 0
        while i < 45:
            if self.screenshot_service_available():
                break
            time.sleep(1)
            i += 1
        return

    def screenshot_service_available(self) -> bool:

        content_type_header = {"Content-type": "text/plain"}

        browserless_chrome_available = False
        try:
            et = requests.get(
                "http://127.0.0.1:3000/",
                headers=content_type_header,
            )
            browserless_chrome_available = et.status_code == 200

        except requests.exceptions.ConnectionError:
            pass

        if browserless_chrome_available:
            return True
        return False

    def add_screenshot(self, *, RECORD, pdf_filepath):
        if "url" not in RECORD.data:
            return RECORD

        urldate = datetime.today().strftime("%Y-%m-%d")

        json_val = {
            "url": RECORD.data["url"],
            "options": {
                "displayHeaderFooter": True,
                "printBackground": False,
                "format": "A2",
            },
        }

        r = requests.post("http://127.0.0.1:3000/pdf", json=json_val)

        if 200 == r.status_code:
            with open(pdf_filepath, "wb") as f:
                f.write(r.content)

            RECORD.update_field(
                key="file",
                value=str(pdf_filepath),
                source="browserless/chrome screenshot",
            )
            RECORD.data.update(
                colrev_status=colrev.record.RecordState.rev_prescreen_included
            )
            RECORD.update_field(
                key="urldate", value=urldate, source="browserless/chrome screenshot"
            )

        else:
            print(
                "URL screenshot retrieval error "
                f"{r.status_code}/{RECORD.data['url']}"
            )

        return RECORD


class GrobidService:

    GROBID_URL = "http://localhost:8070"

    def __init__(self):
        pass

    def check_grobid_availability(self, *, wait=True) -> bool:
        i = 0
        while True:
            i += 1
            time.sleep(1)
            try:
                r = requests.get(self.GROBID_URL + "/api/isalive")
                if r.text == "true":
                    return True
            except requests.exceptions.ConnectionError:
                pass
            if not wait:
                return False
            if i == -1:
                break
            if i > 20:
                raise requests.exceptions.ConnectionError()
        return True

    def start(self) -> None:
        # pylint: disable=consider-using-with

        try:
            res = self.check_grobid_availability(wait=False)
            if res:
                return
        except requests.exceptions.ConnectionError:
            pass

        grobid_image = EnvironmentManager.docker_images["lfoppiano/grobid"]

        logging.info(f"Running docker container created from {grobid_image}")

        logging.info("Starting grobid service...")
        start_cmd = (
            f'docker run -t --rm -m "4g" -p 8070:8070 -p 8071:8071 {grobid_image}'
        )
        subprocess.Popen(
            [start_cmd],
            shell=True,
            stdin=None,
            stdout=open(os.devnull, "wb"),
            stderr=None,
            close_fds=True,
        )
        self.check_grobid_availability()
        return


class TEIParser:
    ns = {
        "tei": "{http://www.tei-c.org/ns/1.0}",
        "w3": "{http://www.w3.org/XML/1998/namespace}",
    }
    nsmap = {
        "tei": "http://www.tei-c.org/ns/1.0",
        "w3": "http://www.w3.org/XML/1998/namespace",
    }

    def __init__(
        self,
        pdf_path: Path = None,
        tei_path: Path = None,
    ):
        """Creates a TEI file
        modes of operation:
        - pdf_path: create TEI and temporarily store in self.data
        - pfd_path and tei_path: create TEI and save in tei_path
        - tei_path: read TEI from file
        """

        # pylint: disable=consider-using-with
        assert pdf_path is not None or tei_path is not None
        if pdf_path is not None:
            if pdf_path.is_symlink():
                pdf_path = pdf_path.resolve()
        self.pdf_path = pdf_path
        self.tei_path = tei_path
        if pdf_path is not None:
            assert pdf_path.is_file()
        else:
            assert tei_path.is_file()  # type: ignore

        load_from_tei = False
        if tei_path is not None:
            if tei_path.is_file():
                load_from_tei = True

        if pdf_path is not None and not load_from_tei:
            GROBID_SERVICE = GrobidService()
            GROBID_SERVICE.start()
            # Note: we have more control and transparency over the consolidation
            # if we do it in the colrev process
            options = {}
            options["consolidateHeader"] = "0"
            options["consolidateCitations"] = "0"
            try:
                r = requests.post(
                    GrobidService.GROBID_URL + "/api/processFulltextDocument",
                    files={"input": open(str(pdf_path), "rb")},
                    data=options,
                )

                # Possible extension: get header only (should be more efficient)
                # r = requests.post(
                #     GrobidService.GROBID_URL + "/api/processHeaderDocument",
                #     files=dict(input=open(filepath, "rb")),
                #     data=header_data,
                # )

                if r.status_code != 200:
                    raise colrev_exceptions.TEI_Exception()

                if b"[TIMEOUT]" in r.content:
                    raise colrev_exceptions.TEI_TimeoutException()

                self.root = etree.fromstring(r.content)

                if tei_path is not None:
                    tei_path.parent.mkdir(exist_ok=True, parents=True)
                    with open(tei_path, "wb") as tf:
                        tf.write(r.content)

                    # Note : reopen/write to prevent format changes in the enhancement
                    with open(tei_path, "rb") as tf:
                        xml_fstring = tf.read()
                    self.root = etree.fromstring(xml_fstring)

                    tree = etree.ElementTree(self.root)
                    tree.write(str(tei_path), pretty_print=True, encoding="utf-8")
            except requests.exceptions.ConnectionError as e:
                print(e)
                print(str(pdf_path))
        elif tei_path is not None:
            with open(tei_path, encoding="utf-8") as ts:
                xml_string = ts.read()
            if "[BAD_INPUT_DATA]" in xml_string[:100]:
                raise colrev_exceptions.TEI_Exception()
            self.root = etree.fromstring(xml_string)

    def get_tei_str(self) -> str:
        return etree.tostring(self.root).decode("utf-8")

    def __get_paper_title(self) -> str:
        title_text = "NA"
        file_description = self.root.find(".//" + self.ns["tei"] + "fileDesc")
        if file_description is not None:
            titleStmt_node = file_description.find(".//" + self.ns["tei"] + "titleStmt")
            if titleStmt_node is not None:
                title_node = titleStmt_node.find(".//" + self.ns["tei"] + "title")
                if title_node is not None:
                    title_text = (
                        title_node.text if title_node.text is not None else "NA"
                    )
                    title_text = (
                        title_text.replace("(Completed paper)", "")
                        .replace("(Completed-paper)", "")
                        .replace("(Research-in-Progress)", "")
                        .replace("Completed Research Paper", "")
                    )
        return title_text

    def __get_paper_journal(self) -> str:
        journal_name = "NA"
        file_description = self.root.find(".//" + self.ns["tei"] + "sourceDesc")
        if file_description is not None:
            if file_description.find(".//" + self.ns["tei"] + "monogr") is not None:
                journal_node = file_description.find(".//" + self.ns["tei"] + "monogr")
                if journal_node is not None:
                    jtitle_node = journal_node.find(".//" + self.ns["tei"] + "title")
                    if jtitle_node is not None:
                        journal_name = (
                            jtitle_node.text if jtitle_node.text is not None else "NA"
                        )
                        if "NA" != journal_name:
                            words = journal_name.split()
                            if sum(word.isupper() for word in words) / len(words) > 0.8:
                                words = [word.capitalize() for word in words]
                                journal_name = " ".join(words)
        return journal_name

    def __get_paper_journal_volume(self) -> str:
        volume = "NA"
        file_description = self.root.find(".//" + self.ns["tei"] + "sourceDesc")
        if file_description is not None:
            if file_description.find(".//" + self.ns["tei"] + "monogr") is not None:
                journal_node = file_description.find(".//" + self.ns["tei"] + "monogr")
                if journal_node is not None:
                    imprint_node = journal_node.find(".//" + self.ns["tei"] + "imprint")
                    if imprint_node is not None:
                        vnode = imprint_node.find(
                            ".//" + self.ns["tei"] + "biblScope[@unit='volume']"
                        )
                        if vnode is not None:
                            volume = vnode.text if vnode.text is not None else "NA"
        return volume

    def __get_paper_journal_issue(self) -> str:
        issue = "NA"
        file_description = self.root.find(".//" + self.ns["tei"] + "sourceDesc")
        if file_description is not None:
            if file_description.find(".//" + self.ns["tei"] + "monogr") is not None:
                journal_node = file_description.find(".//" + self.ns["tei"] + "monogr")
                if journal_node is not None:
                    imprint_node = journal_node.find(".//" + self.ns["tei"] + "imprint")
                    if imprint_node is not None:
                        issue_node = imprint_node.find(
                            ".//" + self.ns["tei"] + "biblScope[@unit='issue']"
                        )
                        if issue_node is not None:
                            issue = (
                                issue_node.text if issue_node.text is not None else "NA"
                            )
        return issue

    def __get_paper_journal_pages(self) -> str:
        pages = "NA"
        file_description = self.root.find(".//" + self.ns["tei"] + "sourceDesc")
        if file_description is not None:
            journal_node = file_description.find(".//" + self.ns["tei"] + "monogr")
            if journal_node is not None:
                imprint_node = journal_node.find(".//" + self.ns["tei"] + "imprint")
                if imprint_node is not None:
                    page_node = imprint_node.find(
                        ".//" + self.ns["tei"] + "biblScope[@unit='page']"
                    )
                    if page_node is not None:
                        if (
                            page_node.get("from") is not None
                            and page_node.get("to") is not None
                        ):
                            pages = (
                                page_node.get("from", "")
                                + "--"
                                + page_node.get("to", "")
                            )
        return pages

    def __get_paper_year(self) -> str:
        year = "NA"
        file_description = self.root.find(".//" + self.ns["tei"] + "sourceDesc")
        if file_description is not None:
            if file_description.find(".//" + self.ns["tei"] + "monogr") is not None:
                journal_node = file_description.find(".//" + self.ns["tei"] + "monogr")
                if journal_node is not None:
                    imprint_node = journal_node.find(".//" + self.ns["tei"] + "imprint")
                    if imprint_node is not None:
                        date_node = imprint_node.find(".//" + self.ns["tei"] + "date")
                        if date_node is not None:
                            year = (
                                date_node.get("when", "")
                                if date_node.get("when") is not None
                                else "NA"
                            )
                            year = re.sub(r".*([1-2][0-9]{3}).*", r"\1", year)
        return year

    def get_author_name_from_node(self, *, author_node) -> str:
        authorname = ""

        author_pers_node = author_node.find(self.ns["tei"] + "persName")
        if author_pers_node is None:
            return authorname
        surname_node = author_pers_node.find(self.ns["tei"] + "surname")
        if surname_node is not None:
            surname = surname_node.text if surname_node.text is not None else ""
        else:
            surname = ""

        forename_node = author_pers_node.find(
            self.ns["tei"] + 'forename[@type="first"]'
        )
        if forename_node is not None:
            forename = forename_node.text if forename_node.text is not None else ""
        else:
            forename = ""

        if 1 == len(forename):
            forename = forename + "."

        middlename_node = author_pers_node.find(
            self.ns["tei"] + 'forename[@type="middle"]'
        )
        if middlename_node is not None:
            middlename = (
                " " + middlename_node.text if middlename_node.text is not None else ""
            )
        else:
            middlename = ""

        if 1 == len(middlename):
            middlename = middlename + "."

        authorname = surname + ", " + forename + middlename

        authorname = (
            authorname.replace("\n", " ")
            .replace("\r", "")
            .replace("•", "")
            .replace("+", "")
            .replace("Dipl.", "")
            .replace("Prof.", "")
            .replace("Dr.", "")
            .replace("&apos", "'")
            .replace("❚", "")
            .replace("~", "")
            .replace("®", "")
            .replace("|", "")
        )

        authorname = re.sub("^Paper, Short; ", "", authorname)
        return authorname

    def __get_paper_authors(self) -> str:
        author_string = "NA"
        file_description = self.root.find(".//" + self.ns["tei"] + "sourceDesc")
        author_list = []

        if file_description is not None:
            if file_description.find(".//" + self.ns["tei"] + "analytic") is not None:
                analytic_node = file_description.find(
                    ".//" + self.ns["tei"] + "analytic"
                )
                if analytic_node is not None:
                    for author_node in analytic_node.iterfind(
                        self.ns["tei"] + "author"
                    ):

                        authorname = self.get_author_name_from_node(
                            author_node=author_node
                        )
                        if authorname in ["Paper, Short"]:
                            continue
                        if authorname not in [", ", ""]:
                            author_list.append(authorname)

                    author_string = " and ".join(author_list)

                    if author_string is None:
                        author_string = "NA"
                    if "" == author_string.replace(" ", "").replace(",", "").replace(
                        ";", ""
                    ):
                        author_string = "NA"
        return author_string

    def __get_paper_doi(self) -> str:
        doi = "NA"
        file_description = self.root.find(".//" + self.ns["tei"] + "sourceDesc")
        if file_description is not None:
            bibl_struct = file_description.find(".//" + self.ns["tei"] + "biblStruct")
            if bibl_struct is not None:
                dois = bibl_struct.findall(".//" + self.ns["tei"] + "idno[@type='DOI']")
                for res in dois:
                    if res.text is not None:
                        doi = res.text
        return doi

    def get_abstract(self) -> str:

        CLEANR = re.compile("<.*?>")

        def cleanhtml(raw_html):
            cleantext = re.sub(CLEANR, "", raw_html)
            return cleantext

        abstract_text = "NA"
        profile_description = self.root.find(".//" + self.ns["tei"] + "profileDesc")
        if profile_description is not None:
            abstract_node = profile_description.find(
                ".//" + self.ns["tei"] + "abstract"
            )
            html_str = etree.tostring(abstract_node).decode("utf-8")
            abstract_text = cleanhtml(html_str)
        return abstract_text

    def get_metadata(self) -> dict:

        record = {
            "ENTRYTYPE": "article",
            "title": self.__get_paper_title(),
            "author": self.__get_paper_authors(),
            "journal": self.__get_paper_journal(),
            "year": self.__get_paper_year(),
            "volume": self.__get_paper_journal_volume(),
            "number": self.__get_paper_journal_issue(),
            "pages": self.__get_paper_journal_pages(),
            "doi": self.__get_paper_doi(),
        }

        for k, v in record.items():
            if "file" != k:
                record[k] = v.replace("}", "").replace("{", "").rstrip("\\")
            else:
                print(f"problem in filename: {k}")

        return record

    def get_paper_keywords(self) -> list:
        keywords = []
        for keyword_list in self.root.iter(self.ns["tei"] + "keywords"):
            for keyword in keyword_list.iter(self.ns["tei"] + "term"):
                keywords.append(keyword.text)
        return keywords

    # (individual) bibliography-reference elements  ----------------------------

    def __get_reference_bibliography_id(self, *, reference) -> str:
        if "ID" in reference.attrib:
            return reference.attrib["ID"]
        return ""

    def __get_reference_bibliography_tei_id(self, *, reference) -> str:
        return reference.attrib[self.ns["w3"] + "id"]

    def __get_reference_author_string(self, *, reference) -> str:
        author_list = []
        if reference.find(self.ns["tei"] + "analytic") is not None:
            authors_node = reference.find(self.ns["tei"] + "analytic")
        elif reference.find(self.ns["tei"] + "monogr") is not None:
            authors_node = reference.find(self.ns["tei"] + "monogr")

        for author_node in authors_node.iterfind(self.ns["tei"] + "author"):

            authorname = self.get_author_name_from_node(author_node=author_node)

            if authorname not in [", ", ""]:
                author_list.append(authorname)

        author_string = " and ".join(author_list)

        author_string = (
            author_string.replace("\n", " ")
            .replace("\r", "")
            .replace("•", "")
            .replace("+", "")
            .replace("Dipl.", "")
            .replace("Prof.", "")
            .replace("Dr.", "")
            .replace("&apos", "'")
            .replace("❚", "")
            .replace("~", "")
            .replace("®", "")
            .replace("|", "")
        )

        if author_string is None:
            author_string = "NA"
        if "" == author_string.replace(" ", "").replace(",", "").replace(";", ""):
            author_string = "NA"
        return author_string

    def __get_reference_title_string(self, *, reference) -> str:
        title_string = ""
        if reference.find(self.ns["tei"] + "analytic") is not None:
            title = reference.find(self.ns["tei"] + "analytic").find(
                self.ns["tei"] + "title"
            )
        elif reference.find(self.ns["tei"] + "monogr") is not None:
            title = reference.find(self.ns["tei"] + "monogr").find(
                self.ns["tei"] + "title"
            )
        if title is None:
            title_string = "NA"
        else:
            title_string = title.text
        return title_string

    def __get_reference_year_string(self, *, reference) -> str:
        year_string = ""
        if reference.find(self.ns["tei"] + "monogr") is not None:
            year = (
                reference.find(self.ns["tei"] + "monogr")
                .find(self.ns["tei"] + "imprint")
                .find(self.ns["tei"] + "date")
            )
        elif reference.find(self.ns["tei"] + "analytic") is not None:
            year = (
                reference.find(self.ns["tei"] + "analytic")
                .find(self.ns["tei"] + "imprint")
                .find(self.ns["tei"] + "date")
            )

        if year is not None:
            for name, value in sorted(year.items()):
                if name == "when":
                    year_string = value
                else:
                    year_string = "NA"
        else:
            year_string = "NA"
        return year_string

    def __get_reference_page_string(self, *, reference) -> str:
        page_string = ""

        if reference.find(self.ns["tei"] + "monogr") is not None:
            page_list = (
                reference.find(self.ns["tei"] + "monogr")
                .find(self.ns["tei"] + "imprint")
                .findall(self.ns["tei"] + "biblScope[@unit='page']")
            )
        elif reference.find(self.ns["tei"] + "analytic") is not None:
            page_list = (
                reference.find(self.ns["tei"] + "analytic")
                .find(self.ns["tei"] + "imprint")
                .findall(self.ns["tei"] + "biblScope[@unit='page']")
            )

        for page in page_list:
            if page is not None:
                for name, value in sorted(page.items()):
                    if name == "from":
                        page_string += value
                    if name == "to":
                        page_string += "--" + value
            else:
                page_string = "NA"

        return page_string

    def __get_reference_number_string(self, *, reference) -> str:
        number_string = ""

        if reference.find(self.ns["tei"] + "monogr") is not None:
            number_list = (
                reference.find(self.ns["tei"] + "monogr")
                .find(self.ns["tei"] + "imprint")
                .findall(self.ns["tei"] + "biblScope[@unit='issue']")
            )
        elif reference.find(self.ns["tei"] + "analytic") is not None:
            number_list = (
                reference.find(self.ns["tei"] + "analytic")
                .find(self.ns["tei"] + "imprint")
                .findall(self.ns["tei"] + "biblScope[@unit='issue']")
            )

        for number in number_list:
            if number is not None:
                number_string = number.text
            else:
                number_string = "NA"

        return number_string

    def __get_reference_volume_string(self, *, reference) -> str:
        volume_string = ""

        if reference.find(self.ns["tei"] + "monogr") is not None:
            volume_list = (
                reference.find(self.ns["tei"] + "monogr")
                .find(self.ns["tei"] + "imprint")
                .findall(self.ns["tei"] + "biblScope[@unit='volume']")
            )
        elif reference.find(self.ns["tei"] + "analytic") is not None:
            volume_list = (
                reference.find(self.ns["tei"] + "analytic")
                .find(self.ns["tei"] + "imprint")
                .findall(self.ns["tei"] + "biblScope[@unit='volume']")
            )

        for volume in volume_list:
            if volume is not None:
                volume_string = volume.text
            else:
                volume_string = "NA"

        return volume_string

    def __get_reference_journal_string(self, *, reference) -> str:
        journal_title = ""
        if reference.find(self.ns["tei"] + "monogr") is not None:
            journal_title = (
                reference.find(self.ns["tei"] + "monogr")
                .find(self.ns["tei"] + "title")
                .text
            )
        if journal_title is None:
            journal_title = ""
        return journal_title

    def __get_entrytype(self, *, reference) -> str:
        ENTRYTYPE = "misc"
        if reference.find(self.ns["tei"] + "monogr") is not None:
            monogr_node = reference.find(self.ns["tei"] + "monogr")
            title_node = monogr_node.find(self.ns["tei"] + "title")
            if title_node is not None:
                if "j" == title_node.get("level", "NA"):
                    ENTRYTYPE = "article"
                else:
                    ENTRYTYPE = "book"
        return ENTRYTYPE

    def get_bibliography(self):

        bibliographies = self.root.iter(self.ns["tei"] + "listBibl")
        tei_bib_db = []
        for bibliography in bibliographies:
            for reference in bibliography:
                try:
                    ENTRYTYPE = self.__get_entrytype(reference=reference)
                    if "article" == ENTRYTYPE:
                        ref_rec = {
                            "ID": self.__get_reference_bibliography_id(
                                reference=reference
                            ),
                            "ENTRYTYPE": ENTRYTYPE,
                            "tei_id": self.__get_reference_bibliography_tei_id(
                                reference=reference
                            ),
                            "author": self.__get_reference_author_string(
                                reference=reference
                            ),
                            "title": self.__get_reference_title_string(
                                reference=reference
                            ),
                            "year": self.__get_reference_year_string(
                                reference=reference
                            ),
                            "journal": self.__get_reference_journal_string(
                                reference=reference
                            ),
                            "volume": self.__get_reference_volume_string(
                                reference=reference
                            ),
                            "number": self.__get_reference_number_string(
                                reference=reference
                            ),
                            "pages": self.__get_reference_page_string(
                                reference=reference
                            ),
                        }
                    elif "book" == ENTRYTYPE:
                        ref_rec = {
                            "ID": self.__get_reference_bibliography_id(
                                reference=reference
                            ),
                            "ENTRYTYPE": ENTRYTYPE,
                            "tei_id": self.__get_reference_bibliography_tei_id(
                                reference=reference
                            ),
                            "author": self.__get_reference_author_string(
                                reference=reference
                            ),
                            "title": self.__get_reference_title_string(
                                reference=reference
                            ),
                            "year": self.__get_reference_year_string(
                                reference=reference
                            ),
                        }
                    elif "misc" == ENTRYTYPE:
                        ref_rec = {
                            "ID": self.__get_reference_bibliography_id(
                                reference=reference
                            ),
                            "ENTRYTYPE": ENTRYTYPE,
                            "tei_id": self.__get_reference_bibliography_tei_id(
                                reference=reference
                            ),
                            "author": self.__get_reference_author_string(
                                reference=reference
                            ),
                            "title": self.__get_reference_title_string(
                                reference=reference
                            ),
                        }
                except etree.XMLSyntaxError:
                    continue

                ref_rec = {k: v for k, v in ref_rec.items() if v is not None}
                # print(ref_rec)
                tei_bib_db.append(ref_rec)

        return tei_bib_db

    def get_citations_per_section(self) -> dict:
        section_citations = {}
        sections = self.root.iter(self.ns["tei"] + "head")
        for section in sections:
            section_name = section.text
            if section_name is None:
                continue
            citation_nodes = section.getparent().iter(self.ns["tei"] + "ref")
            citations = [
                x.get("target", "NA").replace("#", "")
                for x in citation_nodes
                if "bibr" == x.get("type", "NA")
            ]
            citations = list(filter(lambda a: a != "NA", citations))
            if len(citations) > 0:
                section_citations[section_name.lower()] = citations
        return section_citations

    def mark_references(self, *, records):

        tei_records = self.get_bibliography()
        for record in tei_records:
            if "title" not in record:
                continue

            max_sim = 0.9
            max_sim_record = {}
            for local_record in records:
                if local_record["status"] not in [
                    colrev.record.RecordState.rev_included,
                    colrev.record.RecordState.rev_synthesized,
                ]:
                    continue
                rec_sim = colrev.record.Record.get_record_similarity(
                    RECORD_A=colrev.record.Record(data=record),
                    RECORD_B=colrev.record.Record(data=local_record),
                )
                if rec_sim > max_sim:
                    max_sim_record = local_record
                    max_sim = rec_sim
            if len(max_sim_record) == 0:
                continue

            # Record found: mark in tei
            bibliography = self.root.find(".//" + self.ns["tei"] + "listBibl")
            # mark reference in bibliography
            for ref in bibliography:
                if ref.get(self.ns["w3"] + "id") == record["tei_id"]:
                    ref.set("ID", max_sim_record["ID"])
            # mark reference in in-text citations
            for reference in self.root.iter(self.ns["tei"] + "ref"):
                if "target" in reference.keys():
                    if reference.get("target") == f"#{record['tei_id']}":
                        reference.set("ID", max_sim_record["ID"])

            # if settings file available: dedupe_io match agains records

        if self.tei_path:
            tree = etree.ElementTree(self.root)
            tree.write(str(self.tei_path), pretty_print=True, encoding="utf-8")

        return self.root


if __name__ == "__main__":
    pass