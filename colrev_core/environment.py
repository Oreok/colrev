#! /usr/bin/env python
import binascii
import hashlib
import logging
import os
import re
import time
import typing
import unicodedata
from pathlib import Path

import docker
from bibtexparser.bparser import BibTexParser
from bibtexparser.customization import convert_to_unicode
from git.exc import InvalidGitRepositoryError
from lxml.etree import SerialisationError
from nameparser import HumanName
from opensearchpy import NotFoundError
from opensearchpy import OpenSearch
from thefuzz import fuzz
from tqdm import tqdm

from colrev_core.process import CheckProcess
from colrev_core.process import RecordState
from colrev_core.tei import TEI
from colrev_core.tei import TEI_Exception


class EnvironmentManager:

    colrev_path = Path.home().joinpath("colrev")
    registry = "registry.yaml"

    paths = {"REGISTRY": colrev_path.joinpath(registry)}

    os_db = "opensearchproject/opensearch-dashboards:1.3.0"

    docker_images = {
        "lfoppiano/grobid": "lfoppiano/grobid:0.7.0",
        "pandoc/ubuntu-latex": "pandoc/ubuntu-latex:2.14",
        "jbarlow83/ocrmypdf": "jbarlow83/ocrmypdf:v13.3.0",
        "zotero/translation-server": "zotero/translation-server:2.0.4",
        "opensearchproject/opensearch": "opensearchproject/opensearch:1.3.0",
        "opensearchproject/opensearch-dashboards": os_db,
    }

    def __init__(self):
        self.local_registry = self.load_local_registry()

    @classmethod
    def load_local_registry(cls) -> list:
        from yaml import safe_load
        import pandas as pd

        local_registry_path = EnvironmentManager.paths["REGISTRY"]
        local_registry = []
        if local_registry_path.is_file():
            with open(local_registry_path) as f:
                local_registry_df = pd.json_normalize(safe_load(f))
                local_registry = local_registry_df.to_dict("records")

        return local_registry

    @classmethod
    def save_local_registry(cls, updated_registry: list) -> None:
        import pandas as pd
        import json
        import yaml

        local_registry_path = cls.paths["REGISTRY"]

        updated_registry_df = pd.DataFrame(updated_registry)
        orderedCols = [
            "filename",
            "source_name",
            "source_url",
        ]
        for x in [x for x in updated_registry_df.columns if x not in orderedCols]:
            orderedCols.append(x)
        updated_registry_df = updated_registry_df.reindex(columns=orderedCols)

        local_registry_path.parents[0].mkdir(parents=True, exist_ok=True)
        with open(local_registry_path, "w") as f:
            yaml.dump(
                json.loads(
                    updated_registry_df.to_json(orient="records", default_handler=str)
                ),
                f,
                default_flow_style=False,
                sort_keys=False,
            )
        return

    @classmethod
    def register_repo(cls, path_to_register: Path) -> None:
        import git

        local_registry = cls.load_local_registry()
        registered_paths = [x["source_url"] for x in local_registry]

        if registered_paths != []:
            if str(path_to_register) in registered_paths:
                print(f"Warning: Path already registered: {path_to_register}")
                return
        else:
            print(f"Creating {cls.paths['REGISTRY']}")

        new_record = {
            "filename": path_to_register.stem,
            "source_name": path_to_register.stem,
            "source_url": path_to_register,
        }
        git_repo = git.Repo(path_to_register)
        for remote in git_repo.remotes:
            if remote.url:
                new_record["source_link"] = remote.url
        local_registry.append(new_record)
        cls.save_local_registry(local_registry)
        print(f"Registered path ({path_to_register})")
        return

    @classmethod
    def get_name_mail_from_global_git_config(cls) -> list:
        import git

        ggit_conf_path = Path.home() / Path(".gitconfig")
        global_conf_details = []
        if ggit_conf_path.is_file():
            glob_git_conf = git.GitConfigParser([str(ggit_conf_path)], read_only=True)
            global_conf_details = [
                glob_git_conf.get("user", "name"),
                glob_git_conf.get("user", "email"),
            ]
        return global_conf_details

    @classmethod
    def build_docker_images(cls) -> None:

        client = docker.from_env()

        repo_tags = [image.tags for image in client.images.list()]
        repo_tags = [tag[0][: tag[0].find(":")] for tag in repo_tags if tag]

        if "lfoppiano/grobid" not in repo_tags:
            print("Pulling grobid Docker image...")
            client.images.pull(cls.docker_images["lfoppiano/grobid"])
        if "pandoc/ubuntu-latex" not in repo_tags:
            print("Pulling pandoc/ubuntu-latex image...")
            client.images.pull(cls.docker_images["pandoc/ubuntu-latex"])
        if "jbarlow83/ocrmypdf" not in repo_tags:
            print("Pulling jbarlow83/ocrmypdf image...")
            client.images.pull(cls.docker_images["jbarlow83/ocrmypdf"])
        if "zotero/translation-server" not in repo_tags:
            print("Pulling zotero/translation-server image...")
            client.images.pull(cls.docker_images["zotero/translation-server"])

        return

    @classmethod
    def check_git_installed(cls) -> None:
        import subprocess
        from colrev_core.review_manager import MissingDependencyError

        try:
            null = open("/dev/null", "w")
            subprocess.Popen("git", stdout=null, stderr=null)
            null.close()
        except OSError:
            pass
            raise MissingDependencyError("git")
        return

    @classmethod
    def check_docker_installed(cls) -> None:
        import subprocess
        from colrev_core.review_manager import MissingDependencyError

        try:
            null = open("/dev/null", "w")
            subprocess.Popen("docker", stdout=null, stderr=null)
            null.close()
        except OSError:
            pass
            raise MissingDependencyError("docker")
        return

    def get_environment_details(self) -> dict:
        from colrev_core.environment import LocalIndex
        from colrev_core.review_manager import ReviewManager

        from git.exc import NoSuchPathError
        from git.exc import InvalidGitRepositoryError
        from opensearchpy import NotFoundError

        LOCAL_INDEX = LocalIndex()

        environment_details = {}

        size = 0
        last_modified = "NOT_INITIATED"
        status = ""

        def get_last_modified() -> str:
            import os
            import datetime

            list_of_files = LOCAL_INDEX.opensearch_index.glob(
                "**/*"
            )  # * means all if need specific format then *.csv
            latest_file = max(list_of_files, key=os.path.getmtime)
            last_mod = datetime.datetime.fromtimestamp(latest_file.lstat().st_mtime)
            return last_mod.strftime("%Y-%m-%d %H:%M")

        try:
            size = LOCAL_INDEX.os.cat.count(
                index=LOCAL_INDEX.RECORD_INDEX, params={"format": "json"}
            )[0]["count"]
            last_modified = get_last_modified()
            status = "up"
        except (NotFoundError, IndexError):
            status = "down"
            pass

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
                cp_REVIEW_MANAGER = ReviewManager(path_str=repo["source_url"])
                CHECK_PROCESS = CheckProcess(cp_REVIEW_MANAGER)
                repo_stat = CHECK_PROCESS.REVIEW_MANAGER.get_status()
                repo["size"] = repo_stat["status"]["overall"]["md_processed"]
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
                pass

        environment_details["local_repos"] = {
            "repos": repos,
            "broken_links": broken_links,
        }
        return environment_details

    @classmethod
    def get_curated_outlets(cls) -> list:
        curated_outlets: typing.List[str] = []
        for source_url in [
            x["source_url"]
            for x in EnvironmentManager.load_local_registry()
            if "colrev/curated_metadata/" in x["source_url"]
        ]:
            with open(f"{source_url}/readme.md") as f:
                first_line = f.readline()
            curated_outlets.append(first_line.lstrip("# ").replace("\n", ""))

            with open(f"{source_url}/references.bib") as r:
                outlets = []
                for line in r.readlines():

                    if "journal" == line.lstrip()[:7]:
                        journal = line[line.find("{") + 1 : line.rfind("}")]
                        outlets.append(journal)
                    if "booktitle" == line.lstrip()[:9]:
                        booktitle = line[line.find("{") + 1 : line.rfind("}")]
                        outlets.append(booktitle)

                if len(set(outlets)) != 1:
                    raise CuratedOutletNotUnique(
                        "Error: Duplicate outlets in curated_metadata of "
                        f"{source_url} : {','.join(list(set(outlets)))}"
                    )
        return curated_outlets


class LocalIndex:

    global_keys = ["doi", "dblp_key", "colrev_pdf_id", "url"]
    max_len_sha256 = 2 ** 256

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

    def __init__(self):

        self.os = OpenSearch("http://localhost:9200")

        self.opensearch_index.mkdir(exist_ok=True, parents=True)
        self.start_opensearch_docker()
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
                pass

        return

    def start_opensearch_docker(self) -> None:
        import requests

        os_image = EnvironmentManager.docker_images["opensearchproject/opensearch"]
        client = docker.from_env()
        if not any(
            "opensearch" in container.name for container in client.containers.list()
        ):
            try:
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
                pass

        available = False
        try:
            self.os.get(index=self.RECORD_INDEX, id="test")
        except requests.exceptions.RequestException:
            pass
        except NotFoundError:
            available = True
            pass

        if not available:
            print("Waiting until LocalIndex is available")
            for i in tqdm(range(0, 20)):
                try:
                    self.os.get(index=self.RECORD_INDEX, id="test")
                    break
                except requests.exceptions.RequestException:
                    time.sleep(3)
                    pass
                except NotFoundError:
                    pass
                    break
        return

    def check_opensearch_docker_available(self) -> None:
        # If not available after 120s: raise error
        self.os.info()
        return

    def __robust_append(self, input_string: str, to_append: str) -> str:
        input_string = str(input_string)
        to_append = (
            str(to_append).replace("\n", " ").rstrip().lstrip().replace("–", " ")
        )
        to_append = re.sub(r"[\.\:“”’]", "", to_append)
        to_append = re.sub(r"\s+", " ", to_append)
        to_append = to_append.lower()
        input_string = input_string + "|" + to_append
        return input_string

    def __rmdiacritics(self, char):
        """
        Return the base character of char, by "removing" any
        diacritics like accents or curls and strokes and the like.
        """
        try:
            desc = unicodedata.name(char)
            cutoff = desc.find(" WITH ")
            if cutoff != -1:
                desc = desc[:cutoff]
                char = unicodedata.lookup(desc)
        except (KeyError, ValueError):
            pass  # removing "WITH ..." produced an invalid name
        return char

    def __remove_accents(self, input_str: str) -> str:
        nfkd_form = unicodedata.normalize("NFKD", input_str)
        wo_ac = [
            self.__rmdiacritics(c) for c in nfkd_form if not unicodedata.combining(c)
        ]
        wo_ac_str = "".join(wo_ac)
        return wo_ac_str

    def __get_container_title(self, record: dict) -> str:

        # if multiple container titles are available, they are concatenated
        container_title = ""

        # school as the container title for theses
        if "school" in record:
            container_title += record["school"]
        # for technical reports
        if "institution" in record:
            container_title += record["institution"]
        if "series" in record:
            container_title += record["series"]
        if "booktitle" in record:
            container_title += record["booktitle"]
        if "journal" in record:
            container_title += record["journal"]

        if "url" in record and not any(
            x in record for x in ["journal", "series", "booktitle"]
        ):
            container_title += record["url"]

        return container_title

    def __format_author_field(self, input_string: str) -> str:
        input_string = input_string.replace("\n", " ")
        names = (
            self.__remove_accents(input_string).replace("; ", " and ").split(" and ")
        )
        author_list = []
        for name in names:
            parsed_name = HumanName(name)
            # Note: do not set parsed_name.string_format as a global constant
            # to preserve consistent creation of identifiers
            parsed_name.string_format = "{last}, {first} {middle}"
            if len(parsed_name.middle) > 0:
                parsed_name.middle = parsed_name.middle[:1]
            if len(parsed_name.first) > 0:
                parsed_name.first = parsed_name.first[:1]
            if len(parsed_name.nickname) > 0:
                parsed_name.nickname = ""

            if "," not in str(parsed_name):
                author_list.append(str(parsed_name))
                continue
            author_list.append(str(parsed_name))
        return " and ".join(author_list)

    def get_colrev_id(self, record: dict) -> str:

        # Including the version of the identifier prevents cases
        # in which almost all identifiers are identical
        # (and very few identifiers change)
        # when updating the identifier function function
        # (this may look like an anomaly and be hard to identify)
        srep = "v0.1"
        author = record.get("author", "")
        srep = self.__robust_append(srep, record.get("ENTRYTYPE", "NA").lower())
        srep = self.__robust_append(srep, self.__format_author_field(author))
        srep = self.__robust_append(srep, record.get("year", ""))
        title_str = re.sub("[^0-9a-zA-Z]+", " ", record.get("title", ""))
        srep = self.__robust_append(srep, title_str)
        srep = self.__robust_append(srep, self.__get_container_title(record))
        srep = self.__robust_append(srep, record.get("volume", ""))
        srep = self.__robust_append(srep, record.get("number", ""))
        pages = record.get("pages", "")
        srep = self.__robust_append(srep, pages)

        return srep

    def __get_record_hash(self, record: dict) -> str:
        string_to_hash = self.get_colrev_id(record)
        return hashlib.sha256(string_to_hash.encode("utf-8")).hexdigest()

    def __increment_hash(self, hash: str) -> str:

        plaintext = binascii.unhexlify(hash)
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

    def __get_tei_index_file(self, hash: str) -> Path:
        return self.teiind_path / Path(f"{hash[:2]}/{hash[2:]}.tei.xml")

    def __store_record(self, hash: str, record: dict) -> None:

        if "file" in record:
            try:
                tei_path = self.__get_tei_index_file(hash)
                tei_path.parents[0].mkdir(exist_ok=True, parents=True)
                if Path(record["file"]).is_file():
                    TEI_INSTANCE = TEI(
                        pdf_path=Path(record["file"]),
                        tei_path=tei_path,
                        notify_state_transition_process=False,
                    )
                    record["fulltext"] = TEI_INSTANCE.get_tei_str()
            except (TEI_Exception, AttributeError, SerialisationError):
                pass

        self.os.index(index=self.RECORD_INDEX, id=hash, body=record)

        return

    def __retrieve_toc_index(self, toc_key: str) -> list:

        toc_item_response = self.os.get(index=self.TOC_INDEX, id=toc_key)
        toc_item = toc_item_response["_source"]

        return toc_item

    def __amend_record(self, hash: str, record: dict) -> None:

        try:
            saved_record_response = self.os.get(index=self.RECORD_INDEX, id=hash)
            saved_record = saved_record_response["_source"]

            # amend saved record
            for k, v in record.items():
                # Note : the record from the first repository should take precedence)
                if k in saved_record:
                    continue
                saved_record[k] = v

            if "file" in record and "fulltext" not in saved_record:
                try:
                    tei_path = self.__get_tei_index_file(hash)
                    tei_path.parents[0].mkdir(exist_ok=True, parents=True)
                    if Path(record["file"]).is_file():
                        TEI_INSTANCE = TEI(
                            pdf_path=Path(record["file"]),
                            tei_path=tei_path,
                            notify_state_transition_process=False,
                        )
                        saved_record["fulltext"] = TEI_INSTANCE.get_tei_str()
                except (TEI_Exception, AttributeError, SerialisationError):
                    pass

            self.os.update(index=self.RECORD_INDEX, id=hash, body={"doc": saved_record})
        except NotFoundError:
            pass
        return

    def __record_index(self, record: dict) -> None:
        # Casting to string (in particular the RecordState Enum)
        record = {k: str(v) for k, v in record.items()}
        if record.get("year", "NA").isdigit():
            record["year"] = int(record["year"])
        elif "year" in record:
            del record["year"]

        record["colrev_id"] = self.get_colrev_id(record)

        hash = self.__get_record_hash(record)

        try:
            # check if the record is already indexed (based on d)
            retrieved_record = self.retrieve(record)

            # if the string_representations are not identical: add to d_index
            if not self.get_colrev_id(retrieved_record) == record["colrev_id"]:
                # Note: we need the colrev_id of the retrieved_record
                # (may be different from record)
                self.__amend_record(self.__get_record_hash(retrieved_record), record)
                return
        except RecordNotInIndexException:
            pass

        while True:
            if not self.os.exists(index=self.RECORD_INDEX, id=hash):
                self.__store_record(hash, record)
                break
            else:
                saved_record_response = self.os.get(index=self.RECORD_INDEX, id=hash)
                saved_record = saved_record_response["_source"]
                if saved_record["colrev_id"] == record["colrev_id"]:
                    # ok - no collision, update the record
                    # Note : do not update (the record from the first repository
                    # should take precedence - reset the index to update)
                    self.__amend_record(hash, record)
                    break
                else:
                    # to handle the collision:
                    print(f"Collision: {hash}")
                    print(record["colrev_id"])
                    print(saved_record["colrev_id"])
                    print(saved_record)
                    hash = self.__increment_hash(hash)
                    # Note: alsoKnownAs field should be covered
                    # in the previous try/except block

        return

    def __get_toc_key(self, record: dict) -> str:
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

    def __toc_index(self, record) -> None:

        if record.get("ENTRYTYPE", "") in ["article", "inproceedings"]:
            # Note : records are md_prepared, i.e., complete

            toc_key = self.__get_toc_key(record)
            if "NA" == toc_key:
                return

            # print(toc_key)
            record["colrev_id"] = self.get_colrev_id(record)

            if not self.os.exists(index=self.TOC_INDEX, id=toc_key):
                toc_item = {
                    "toc_key": toc_key,
                    "string_representations": [record["colrev_id"]],
                }
                self.os.index(index=self.TOC_INDEX, id=toc_key, body=toc_item)
            else:
                toc_item_response = self.os.get(index=self.TOC_INDEX, id=toc_key)
                toc_item = toc_item_response["_source"]
                if toc_item["toc_key"] == toc_key:
                    # ok - no collision, update the record
                    # Note : do not update (the record from the first repository
                    #  should take precedence - reset the index to update)
                    if record["colrev_id"] not in toc_item["string_representations"]:
                        toc_item["string_representations"].append(  # type: ignore
                            record["colrev_id"]
                        )
                        self.os.update(
                            index=self.TOC_INDEX, id=toc_key, body={"doc": toc_item}
                        )

        return

    def __append_j_variation(
        self, j_variations: list, origin_record: dict, record: dict
    ) -> list:

        if "journal" not in origin_record or "journal" not in record:
            return j_variations
        else:
            if origin_record["journal"] != record["journal"]:
                j_variations.append([origin_record["journal"], record["journal"]])

        return j_variations

    def __append_if_duplicate_repr(
        self, non_identical_representations: list, origin_record: dict, record: dict
    ) -> list:

        required_fields = [
            k
            for k, v in record.items()
            if k
            in [
                "author",
                "title",
                "year",
                "journal",
                "volume",
                "number",
                "pages",
                "booktitle",
            ]
        ]

        if all(required_field in origin_record for required_field in required_fields):
            orig_repr = self.get_colrev_id(origin_record)
            main_repr = self.get_colrev_id(record)
            if orig_repr != main_repr:
                non_identical_representations.append([orig_repr, main_repr])

        return non_identical_representations

    def __update_alsoKnownAs(self, alsoKnownAs_Instances: list) -> None:

        alsoKnownAs_Instances = [
            list(x) for x in {tuple(x) for x in alsoKnownAs_Instances}
        ]

        for (
            alsoKnownAs_colrev_id,
            main_colrev_id,
        ) in alsoKnownAs_Instances:

            try:
                hash = hashlib.sha256(main_colrev_id.encode("utf-8")).hexdigest()
                while True:
                    if self.os.exists(index=self.RECORD_INDEX, id=hash):
                        # Note : this should happen rarely/never
                        # but we have to make sure that the while loop breaks
                        break
                    else:
                        response = self.os.get(index=self.RECORD_INDEX, id=hash)
                        saved_record = response["_source"]
                        saved_original_string_repr = saved_record["colrev_id"]

                        if saved_original_string_repr == main_colrev_id:
                            # ok - no collision
                            if alsoKnownAs_colrev_id not in saved_record.get(
                                "alsoKnownAs", []
                            ):
                                if "alsoKnownAs" in saved_record:
                                    saved_record["alsoKnownAs"].append(
                                        alsoKnownAs_colrev_id
                                    )
                                else:
                                    saved_record["alsoKnownAs"] = [
                                        alsoKnownAs_colrev_id
                                    ]
                                self.os.update(
                                    index=self.RECORD_INDEX,
                                    id=hash,
                                    body={"doc": saved_record},
                                )
                            break
                        else:
                            print(f"Collision: {hash}")
                            hash = self.__increment_hash(hash)
            except NotFoundError:
                pass

        return

    def __alsoKnownAs_index(self, records: typing.List[dict]) -> None:

        try:
            search_path = Path(records[0]["source_url"] + "/search/")
        except IndexError:
            pass
            return

        print(f"Update alsoKnownAs fields for {search_path.parent}")

        # Note : records are at least md_processed.
        duplicate_repr_list = []
        for record in records:
            for orig in record["origin"].split(";"):
                duplicate_repr_list.append(
                    {
                        "origin_source": orig.split("/")[0],
                        "origin_id": orig.split("/")[1],
                        "record": record,
                    }
                )

        if len(duplicate_repr_list) == 0:
            return

        origin_sources = list({x["origin_source"] for x in duplicate_repr_list})
        alsoKnownAsInstances: typing.List[list] = []
        j_variations: typing.List[list] = []
        for origin_source in origin_sources:
            os_fp = search_path / Path(origin_source)
            if not os_fp.is_file():
                print(f"source not found {os_fp}")
            else:
                with open(os_fp) as target_db:
                    bib_db = BibTexParser(
                        customization=convert_to_unicode,
                        ignore_nonstandard_types=False,
                        common_strings=True,
                    ).parse_file(target_db, partial=True)

                    origin_source_records = bib_db.entries
                for duplicate_repr in duplicate_repr_list:
                    if duplicate_repr["origin_source"] != origin_source:
                        continue

                    record = duplicate_repr["record"]
                    origin_record_list = [
                        x
                        for x in origin_source_records
                        if x["ID"] == duplicate_repr["origin_id"]
                    ]
                    if len(origin_record_list) != 1:
                        continue
                    origin_record = origin_record_list[0]
                    alsoKnownAsInstances = self.__append_if_duplicate_repr(
                        alsoKnownAsInstances, origin_record, record
                    )
                    j_variations = self.__append_j_variation(
                        j_variations, origin_record, record
                    )

        # 2. add alsoKnownAs to index
        self.__update_alsoKnownAs(alsoKnownAsInstances)

        return

    def __retrieve_record_from_d_index(self, record: dict) -> dict:

        string_representation_record = self.get_colrev_id(record)

        try:
            # match_phrase := exact match
            resp = self.os.search(
                index=self.RECORD_INDEX,
                body={
                    "query": {
                        "match_phrase": {"alsoKnownAs": string_representation_record}
                    }
                },
            )
            retrieved_record = resp["hits"]["hits"][0]["_source"]

        except (IndexError, NotFoundError):
            pass
            raise RecordNotInIndexException

        if retrieved_record["ENTRYTYPE"] != record["ENTRYTYPE"]:
            raise RecordNotInIndexException

        return self.prep_record_for_return(retrieved_record)

    def __retrieve_from_record_index(self, record: dict) -> dict:
        retrieved_record = self.__retrieve_based_on_colrev_id(
            self.get_colrev_id(record)
        )
        if retrieved_record["ENTRYTYPE"] != record["ENTRYTYPE"]:
            raise RecordNotInIndexException
        return retrieved_record

    def __retrieve_based_on_colrev_id(self, colrev_id: str) -> dict:

        hash = hashlib.sha256(colrev_id.encode("utf-8")).hexdigest()

        while True:  # Note : while breaks with NotFoundError
            res = self.os.get(index=self.RECORD_INDEX, id=hash)
            retrieved_record = res["_source"]
            if self.get_colrev_id(retrieved_record) == colrev_id:
                break
            else:
                # Collision
                hash = self.__increment_hash(hash)

        return retrieved_record

    def prep_record_for_return(self, record: dict, include_file: bool = False) -> dict:
        from colrev_core.process import RecordState

        # Casting to string (in particular the RecordState Enum)
        record = {k: str(v) for k, v in record.items()}

        # del retrieved_record['source_url']

        # Note: record['file'] should be an absolute path by definition
        # when stored in the LocalIndex
        if "file" in record:
            if not Path(record["file"]).is_file():
                del record["file"]

        if "manual_non_duplicate" in record:
            del record["manual_non_duplicate"]
        if "manual_duplicate" in record:
            del record["manual_duplicate"]
        if "alsoKnownAs" in record:
            del record["alsoKnownAs"]
        if "fulltext" in record:
            del record["fulltext"]
        if "tei_file" in record:
            del record["tei_file"]
        if "colrev_id" in record:
            del record["colrev_id"]

        if not include_file:
            if "file" in record:
                del record["file"]
            if "colref_pdf_id" in record:
                del record["colref_pdf_id"]

        record["status"] = RecordState.md_prepared

        return record

    def duplicate_outlets(self) -> bool:
        import collections

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

    def index_records(self) -> None:
        # import shutil
        from colrev_core.review_manager import ReviewManager

        print("Start LocalIndex")

        if self.duplicate_outlets():
            return

        print(f"Reset {self.RECORD_INDEX} and {self.TOC_INDEX}")
        # if self.teiind_path.is_dir():
        #     shutil.rmtree(self.teiind_path)

        self.opensearch_index.mkdir(exist_ok=True, parents=True)
        if self.RECORD_INDEX in self.os.indices.get_alias().keys():
            self.os.indices.delete(index=self.RECORD_INDEX, ignore=[400, 404])
        if self.TOC_INDEX in self.os.indices.get_alias().keys():
            self.os.indices.delete(index=self.TOC_INDEX, ignore=[400, 404])
        self.os.indices.create(index=self.RECORD_INDEX)
        self.os.indices.create(index=self.TOC_INDEX)

        for source_url in [
            x["source_url"] for x in EnvironmentManager.load_local_registry()
        ]:

            try:
                if not Path(source_url).is_dir():
                    print(f"Warning {source_url} not a directory")
                    continue
                os.chdir(source_url)
                print(f"Index records from {source_url}")

                # get ReviewManager for project (after chdir)
                REVIEW_MANAGER = ReviewManager(path_str=str(source_url))
                CHECK_PROCESS = CheckProcess(REVIEW_MANAGER)

                if not CHECK_PROCESS.REVIEW_MANAGER.paths["MAIN_REFERENCES"].is_file():
                    continue

                records = CHECK_PROCESS.REVIEW_MANAGER.REVIEW_DATASET.load_records()
                records = [
                    r
                    for r in records
                    if r["status"]
                    not in [
                        RecordState.md_retrieved,
                        RecordState.md_imported,
                        RecordState.md_prepared,
                        RecordState.md_needs_manual_preparation,
                    ]
                ]

                for record in tqdm(records):
                    record["source_url"] = source_url
                    if "excl_criteria" in record:
                        del record["excl_criteria"]
                    # Note: if the colrev_pdf_id has not been checked,
                    # we cannot use it for retrieval or preparation.
                    if record["status"] not in [
                        RecordState.pdf_prepared,
                        RecordState.rev_excluded,
                        RecordState.rev_included,
                        RecordState.rev_synthesized,
                    ]:
                        if "colrev_pdf_id" in record:
                            del record["colrev_pdf_id"]

                    # To fix pdf_hash fields that should have been renamed
                    if "pdf_hash" in record:
                        record["colref_pdf_id"] = "cpid1:" + record["pdf_hash"]
                        del record["pdf_hash"]

                    if "pdf_prep_hints" in record:
                        del record["pdf_prep_hints"]
                    if "pdf_processed" in record:
                        del record["pdf_processed"]

                    # Note : file paths should be absolute when added to the LocalIndex
                    if "file" in record:
                        pdf_path = source_url / Path(record["file"])
                        if pdf_path.is_file:
                            record["file"] = str(pdf_path)
                        else:
                            del record["file"]

                    del record["status"]

                    self.__record_index(record)

                    # Note : only use curated journal metadata for TOC indices
                    # otherwise, TOCs will be incomplete and affect retrieval
                    if "colrev/curated_metadata" in source_url:
                        self.__toc_index(record)

                self.__alsoKnownAs_index(records)
            except InvalidGitRepositoryError:
                print(f"InvalidGitRepositoryError: {source_url}")
                pass

        # for annotator in self.annotators_path.glob("*/annotate.py"):
        #     print(f"Load {annotator}")
        #     import imp

        #     annotator_module = imp.load_source("annotator_module", str(annotator))
        #     annotate = getattr(annotator_module, "annotate")
        #     annotate(self)
        # Note : es.update can use functions applied to each record (for the update)

        return

    def retrieve_from_toc(
        self, record: dict, similarity_threshold: float, include_file=False
    ) -> dict:
        toc_key = self.__get_toc_key(record)

        # 1. get TOC
        toc_items = []
        if self.os.exists(index=self.TOC_INDEX, id=toc_key):
            res = self.__retrieve_toc_index(toc_key)
            toc_items = res["string_representations"]  # type: ignore

        # 2. get most similar record
        if len(toc_items) > 0:
            record["colrev_id"] = self.get_colrev_id(record)
            sim_list = []
            for toc_records_colrev_id in toc_items:
                # Note : using a simpler similarity measure
                # because the publication outlet parameters are already identical
                sv = fuzz.ratio(record["colrev_id"], toc_records_colrev_id) / 100
                sim_list.append(sv)

            if max(sim_list) > similarity_threshold:
                toc_records_colrev_id = toc_items[sim_list.index(max(sim_list))]
                hash = hashlib.sha256(toc_records_colrev_id.encode("utf-8")).hexdigest()
                res = self.os.get(index=self.RECORD_INDEX, id=str(hash))
                record = res["_source"]  # type: ignore
                return self.prep_record_for_return(record, include_file)

        raise RecordNotInIndexException()
        return record

    def get_from_index_exact_match(self, index_name, key, value) -> dict:
        resp = self.os.search(
            index=index_name, body={"query": {"match_phrase": {key: value}}}
        )
        res = resp["hits"]["hits"][0]["_source"]
        return res

    def retrieve(self, record: dict, include_file: bool = False) -> dict:
        """
        Convenience function to retrieve the indexed record metadata
        based on another record
        """

        retrieved_record: typing.Dict = dict()

        # 1. Try the record index

        if not retrieved_record:
            try:
                retrieved_record = self.__retrieve_from_record_index(record)

            except (NotFoundError, RecordNotInIndexException):
                pass

        if retrieved_record:
            return self.prep_record_for_return(retrieved_record, include_file)

        # 2. Try using global-ids
        if not retrieved_record:
            for k, v in record.items():
                if k not in self.global_keys or "ID" == k:
                    continue
                try:
                    retrieved_record = self.get_from_index_exact_match(
                        self.RECORD_INDEX, k, v
                    )
                    break
                except (IndexError, NotFoundError):
                    pass

        if retrieved_record:
            return self.prep_record_for_return(retrieved_record, include_file)

        # 3. Try alsoKnownAs
        if not retrieved_record:
            try:
                retrieved_record = self.__retrieve_record_from_d_index(record)
            except FileNotFoundError:
                pass

        if not retrieved_record:
            raise RecordNotInIndexException(record.get("ID", "no-key"))

        return self.prep_record_for_return(retrieved_record, include_file)

    def set_source_url_link(self, record: dict) -> dict:
        if "source_url" in record:
            for local_repo in EnvironmentManager.load_local_registry():
                if local_repo["source_url"] == record["source_url"]:
                    if "source_link" in local_repo:
                        record["source_url"] = local_repo["source_link"]

        return record

    def set_source_path(self, record: dict) -> dict:
        if "source_url" in record:
            for local_repo in EnvironmentManager.load_local_registry():
                if local_repo["source_link"] == record["source_url"]:
                    record["source_url"] = local_repo["source_url"]

        return record

    def is_duplicate(self, record1_colrev_id: str, record2_colrev_id: str) -> str:
        """Convenience function to check whether two records are a duplicate"""

        if record1_colrev_id == record2_colrev_id:
            return "yes"

        # Note : the retrieve(record) also checks the d_index, i.e.,
        # if the IDs and source_urls are identical,
        # record1 and record2 have been mapped to the same record
        # if record1 and record2 in index (and same source_url): return 'no'
        try:
            r1_index = self.__retrieve_based_on_colrev_id(record1_colrev_id)
            r2_index = self.__retrieve_based_on_colrev_id(record2_colrev_id)
            if r1_index["source_url"] == r2_index["source_url"]:
                if r1_index["ID"] == r2_index["ID"]:
                    return "yes"
                else:
                    return "no"

            # Note : We know that records are not duplicates when they are
            # part of curated_metadata repositories and their IDs are not identical
            # For the same journal, only deduplicated records are indexed
            # We make sure that journals are only indexed once
            if (
                "colrev/curated_metadata" in r1_index["source_url"]
                and "colrev/curated_metadata" in r2_index["source_url"]
            ):
                if r1_index["colrev_id"] != r2_index["colrev_id"]:
                    return "no"

        except (RecordNotInIndexException, NotFoundError):
            pass
            return "unknown"

        return "unknown"

    def analyze(self, threshold: float = 0.95) -> None:

        # TODO : update analyze() functionality based on es index
        # import pandas as pd

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

        #     with open(r_file) as f:
        #         while True:
        #             line = f.readline()
        #             if not line:
        #                 break
        #             if "colrev_pdf_id" in line[:9]:
        #                 val = line[line.find("{") + 1 : line.rfind("}")]
        #                 colrev_pdf_ids.append(val)

        # import collections

        # colrev_pdf_ids_dupes = [
        #     item for item, count in
        #       collections.Counter(colrev_pdf_ids).items() if count > 1
        # ]

        # with open("non-unique-cpids.txt", "w") as o:
        #     o.write("\n".join(colrev_pdf_ids_dupes))
        # print("Export non-unique-cpids.txt")
        return


class Resources:

    curations_path = Path.home().joinpath("colrev/curated_metadata")
    annotators_path = Path.home().joinpath("colrev/annotators")

    def __init__(self):
        pass

    def install_curated_resource(self, curated_resource: str) -> bool:
        import git
        import shutil

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

        if (repo_dir / Path("references.bib")).is_file():
            EnvironmentManager.register_repo(repo_dir)
        elif (repo_dir / Path("annotate.py")).is_file():
            shutil.move(str(repo_dir), str(annotator_dir))
        elif (repo_dir / Path("readme.md")).is_file():
            text = Path(repo_dir / "readme.md").read_text()
            for line in [x for x in text.splitlines() if "colrev env --install" in x]:
                if line == curated_resource:
                    continue
                self.install_curated_resource(line.replace("colrev env --install ", ""))
        else:
            print(
                f"Error: repo does not contain a references.bib/linked repos {repo_dir}"
            )
        return True


class RecordNotInIndexException(Exception):
    def __init__(self, id: str = None):
        if id is not None:
            self.message = f"Record not in index ({id})"
        else:
            self.message = "Record not in index"
        super().__init__(self.message)


class CuratedOutletNotUnique(Exception):
    def __init__(self, msg: str = None):
        self.message = msg
        super().__init__(self.message)


if __name__ == "__main__":
    pass
