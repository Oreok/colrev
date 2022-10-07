#!/usr/bin/env python3
"""Functionality for data/records.bib and git repository."""
from __future__ import annotations

import io
import itertools
import os
import re
import string
import time
import typing
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING

import git
import pybtex.errors
from git.exc import GitCommandError
from git.exc import InvalidGitRepositoryError
from pybtex.database import Person
from pybtex.database.input import bibtex

import colrev.env.utils
import colrev.exceptions as colrev_exceptions
import colrev.operation
import colrev.record
import colrev.settings

if TYPE_CHECKING:
    import colrev.review_manager

# pylint: disable=too-many-public-methods


class Dataset:
    """The CoLRev dataset (records and their history in git)"""

    RECORDS_FILE_RELATIVE = Path("data/records.bib")
    records_file: Path
    __git_repo: git.Repo

    def __init__(self, *, review_manager: colrev.review_manager.ReviewManager) -> None:

        self.review_manager = review_manager
        self.records_file = review_manager.path / self.RECORDS_FILE_RELATIVE

        try:
            self.__git_repo = git.Repo(self.review_manager.path)
        except InvalidGitRepositoryError as exc:
            msg = "Not a CoLRev/git repository. Run\n    colrev init"
            raise colrev_exceptions.RepoSetupError(msg) from exc

    def get_origin_state_dict(self, *, file_object: io.StringIO = None) -> dict:
        """Get the origin_state_dict (to determine state transitions efficiently)

        {'30_example_records.bib/Staehr2010': <RecordState.pdf_not_available: 10>,}
        """

        current_origin_states_dict = {}
        if self.records_file.is_file():
            for record_header_item in self.__read_record_header_items(
                file_object=file_object
            ):
                for origin in record_header_item["colrev_origin"]:
                    current_origin_states_dict[origin] = record_header_item[
                        "colrev_status"
                    ]
        return current_origin_states_dict

    def get_committed_origin_state_dict(self) -> dict:
        """Get the committed origin_state_dict"""

        filecontents = self.__get_last_records_filecontents()
        committed_origin_state_dict = self.get_origin_state_dict(
            file_object=io.StringIO(filecontents.decode("utf-8"))
        )
        return committed_origin_state_dict

    def get_nr_in_bib(self, *, file_path: Path) -> int:
        """Returns number of records in the bib file"""
        number_in_bib = 0
        with open(file_path, encoding="utf8") as file:
            line = file.readline()
            while line:
                if "@" in line[:3]:
                    if "@comment" not in line[:10].lower():
                        number_in_bib += 1
                line = file.readline()
        return number_in_bib

    def load_from_git_history(self) -> typing.Iterator[dict]:
        """Returns an iterator of the records_dict based on git history"""
        revlist = (
            (
                commit.hexsha,
                (commit.tree / str(self.RECORDS_FILE_RELATIVE)).data_stream.read(),
            )
            for commit in self.__git_repo.iter_commits(
                paths=str(self.RECORDS_FILE_RELATIVE)
            )
        )
        parser = bibtex.Parser()

        for _, filecontents in list(revlist):
            bib_data = parser.parse_string(filecontents.decode("utf-8"))
            records_dict = self.parse_records_dict(records_dict=bib_data.entries)
            yield records_dict

    def get_changed_records(self, *, target_commit: str) -> typing.List[dict]:
        """Get the records that changed in a selected commit"""

        revlist = (
            (
                commit.hexsha,
                (commit.tree / str(self.RECORDS_FILE_RELATIVE)).data_stream.read(),
            )
            for commit in self.__git_repo.iter_commits(
                paths=str(self.RECORDS_FILE_RELATIVE)
            )
        )
        found = False
        for commit, filecontents in list(revlist):
            if found:  # load the records_file_relative in the following commit
                prior_records_dict = self.review_manager.dataset.load_records_dict(
                    load_str=filecontents.decode("utf-8")
                )
                break
            if commit == target_commit:
                records_dict = self.review_manager.dataset.load_records_dict(
                    load_str=filecontents.decode("utf-8")
                )
                found = True

        # determine which records have been changed (prepared or merged)
        # in the target_commit
        for record in records_dict.values():
            prior_record = [
                rec for id, rec in prior_records_dict.items() if id == record["ID"]
            ][0]
            # Note: the following is an exact comparison of all fields
            if record != prior_record:
                record.update(changed_in_target_commit="True")

        return list(records_dict.values())

    @classmethod
    def __load_field_dict(cls, *, value: str, field: str) -> dict:
        # pylint: disable=too-many-branches

        return_dict = {}
        if "colrev_masterdata_provenance" == field:
            if "CURATED" == value[:7]:
                if value.count(";") == 0:
                    value += ";;"  # Note : temporary fix (old format)
                if value.count(";") == 1:
                    value += ";"  # Note : temporary fix (old format)

                if ":" in value:
                    source = value[value.find(":") + 1 : value[:-1].rfind(";")]
                else:
                    source = ""
                return_dict["CURATED"] = {
                    "source": source,
                    "note": "",
                }

            elif "" != value:
                for item in (value + " ").split("; "):
                    if "" == item:
                        continue
                    item += ";"  # removed by split
                    key_source = item[: item[:-1].rfind(";")]
                    if ":" in key_source:
                        note = item[item[:-1].rfind(";") + 1 : -1]
                        key, source = key_source.split(":", 1)
                        return_dict[key] = {
                            "source": source,
                            "note": note,
                        }
                    else:
                        print(f"problem with masterdata_provenance_item {item}")

        elif "colrev_data_provenance" == field:
            if "" != value:
                # Note : pybtex replaces \n upon load
                for item in (value + " ").split("; "):
                    if "" == item:
                        continue
                    item += ";"  # removed by split
                    key_source = item[: item[:-1].rfind(";")]
                    note = item[item[:-1].rfind(";") + 1 : -1]
                    if ":" in key_source:
                        key, source = key_source.split(":", 1)
                        return_dict[key] = {
                            "source": source,
                            "note": note,
                        }
                    else:
                        print(f"problem with data_provenance_item {item}")

        else:
            print(f"error loading dict_field: {key}")

        return return_dict

    @classmethod
    def parse_records_dict(cls, *, records_dict: dict) -> dict:
        """Parse a records_dict from pybtex to colrev standard"""

        def format_name(person: Person) -> str:
            def join(name_list: list) -> str:
                return " ".join([name for name in name_list if name])

            first = person.get_part_as_text("first")
            middle = person.get_part_as_text("middle")
            prelast = person.get_part_as_text("prelast")
            last = person.get_part_as_text("last")
            lineage = person.get_part_as_text("lineage")
            name_string = ""
            if last:
                name_string += join([prelast, last])
            if lineage:
                name_string += f", {lineage}"
            if first or middle:
                name_string += ", "
                name_string += join([first, middle])
            return name_string

        # Need to concatenate fields and persons dicts
        # but pybtex is still the most efficient solution.
        records_dict = {
            k: {
                **{"ID": k},
                **{"ENTRYTYPE": v.type},
                **dict(
                    {
                        # Cast status to Enum
                        k: colrev.record.RecordState[v] if ("colrev_status" == k)
                        # DOIs are case insensitive -> use upper case.
                        else v.upper() if ("doi" == k)
                        # Note : the following two lines are a temporary fix
                        # to converg colrev_origins to list items
                        else [el.rstrip().lstrip() for el in v.split(";") if "" != el]
                        if k == "colrev_origin"
                        else [el.rstrip() for el in (v + " ").split("; ") if "" != el]
                        if k in colrev.record.Record.list_fields_keys
                        else Dataset.__load_field_dict(value=v, field=k)
                        if k in colrev.record.Record.dict_fields_keys
                        else v
                        for k, v in v.fields.items()
                    }
                ),
                **dict(
                    {
                        k: " and ".join(format_name(person) for person in persons)
                        for k, persons in v.persons.items()
                    }
                ),
            }
            for k, v in records_dict.items()
        }

        return records_dict

    def __read_record_header_items(self, *, file_object: typing.TextIO = None) -> list:
        # Note : more than 10x faster than the pybtex part of load_records_dict()

        def parse_k_v(current_key_value_pair_str: str) -> tuple:
            if " = " in current_key_value_pair_str:
                key, value = current_key_value_pair_str.split(" = ", 1)
            else:
                key = "ID"
                value = current_key_value_pair_str.split("{")[1]

            key = key.lstrip().rstrip()
            value = value.lstrip().rstrip().lstrip("{").rstrip("},")
            if "colrev_origin" == key:
                value_list = value.replace("\n", "").replace(" ", "").split(";")
                value_list = [x for x in value_list if x]
                return key, value_list
            if "colrev_status" == key:
                return key, colrev.record.RecordState[value]
            return key, value

        # pylint: disable=consider-using-with
        if file_object is None:
            file_object = open(self.records_file, encoding="utf-8")

        # Fields required
        default = {
            "ID": "NA",
            "colrev_origin": "NA",
            "colrev_status": "NA",
            "screening_criteria": "NA",
            "file": "NA",
            "colrev_masterdata_provenance": "NA",
        }
        number_required_header_items = len(default)

        record_header_item = default.copy()
        current_header_item_count = 0
        current_key_value_pair_str = ""
        record_header_items = []
        while True:
            line = file_object.readline()
            if not line:
                break
            if line[:1] == "%" or line == "\n":
                continue

            if current_header_item_count > number_required_header_items or "}" == line:
                record_header_items.append(record_header_item)
                record_header_item = default.copy()
                current_header_item_count = 0
                continue

            if "@" in line[:2] and not "NA" == record_header_item["ID"]:
                record_header_items.append(record_header_item)
                record_header_item = default.copy()
                current_header_item_count = 0

            current_key_value_pair_str += line
            if "}," in line or "@" in line[:2]:
                key, value = parse_k_v(current_key_value_pair_str)
                current_key_value_pair_str = ""
                if key in record_header_item:
                    current_header_item_count += 1
                    record_header_item[key] = value
        if "NA" != record_header_item["colrev_origin"]:
            record_header_items.append(record_header_item)
        return record_header_items

    def load_records_dict(
        self, *, load_str: str = None, header_only: bool = False
    ) -> dict:
        """Load the records

        - requires review_manager.notify(...)

        header_only:

        {"Staehr2010": {'ID': 'Staehr2010',
        'colrev_origin': ['30_example_records.bib/Staehr2010'],
        'colrev_status': <RecordState.md_imported: 2>,
        'screening_criteria': 'NA',
        'file': 'NA',
        'colrev_masterdata_provenance': 'CURATED:https://github.com/...;;'}},
        }
        """

        pybtex.errors.set_strict_mode(False)

        if self.review_manager.notified_next_operation is None:
            raise colrev_exceptions.ReviewManagerNotNofiedError()

        if header_only:
            # TODO : parse Path / screening_criteria / colrev_masterdata_provenance

            record_header_list = (
                self.__read_record_header_items() if self.records_file.is_file() else []
            )
            record_header_dict = {r["ID"]: r for r in record_header_list}
            return record_header_dict

        parser = bibtex.Parser()

        if load_str:
            bib_data = parser.parse_string(load_str)
            records_dict = self.parse_records_dict(records_dict=bib_data.entries)

        elif self.records_file.is_file():
            bib_data = parser.parse_file(self.records_file)
            records_dict = self.parse_records_dict(records_dict=bib_data.entries)
        else:
            records_dict = {}

        return records_dict

    def parse_bibtex_str(self, *, recs_dict_in: dict) -> str:
        """Parse a records_dict to a BiBTex string"""

        # Note: we need a deepcopy because the parsing modifies dicts
        recs_dict = deepcopy(recs_dict_in)

        def format_field(field: str, value: str) -> str:
            padd = " " * max(0, 28 - len(field))
            return f",\n   {field} {padd} = {{{value}}}"

        bibtex_str = ""

        first = True
        for record_id, record_dict in recs_dict.items():
            if not first:
                bibtex_str += "\n"
            first = False

            bibtex_str += f"@{record_dict['ENTRYTYPE']}{{{record_id}"

            if "language" in record_dict:
                # convert to ISO 639-3
                # TODO : other languages/more systematically
                # (see database_connectors) > in record.py?
                if "en" == record_dict["language"]:
                    record_dict["language"] = record_dict["language"].replace(
                        "en", "eng"
                    )

                if len(record_dict["language"]) != 3:
                    self.review_manager.logger.warn(
                        "language (%s) of %s not in ISO 639-3 format",
                        record_dict["language"],
                        record_dict["ID"],
                    )

            field_order = [
                "colrev_origin",  # must be in second line
                "colrev_status",
                "colrev_masterdata_provenance",
                "colrev_data_provenance",
                "colrev_id",
                "colrev_pdf_id",
                "screening_criteria",
                "file",  # Note : do not change this order (parsers rely on it)
                "prescreen_exclusion",
                "doi",
                "grobid-version",
                "dblp_key",
                "sem_scholar_id",
                "wos_accession_number",
                "author",
                "booktitle",
                "journal",
                "title",
                "year",
                "volume",
                "number",
                "pages",
                "editor",
            ]

            record = colrev.record.Record(data=record_dict)
            record_dict = record.get_data(stringify=True)

            for ordered_field in field_order:
                if ordered_field in record_dict:
                    if "" == record_dict[ordered_field]:
                        continue
                    bibtex_str += format_field(
                        ordered_field, record_dict[ordered_field]
                    )

            for key, value in record_dict.items():
                if key in field_order + ["ID", "ENTRYTYPE"]:
                    continue

                bibtex_str += format_field(key, value)

            bibtex_str += ",\n}\n"

        return bibtex_str

    def save_records_dict_to_file(self, *, records: dict, save_path: Path) -> None:
        """Save the records dict to specifified file"""
        # Note : this classmethod function can be called by CoLRev scripts
        # operating outside a CoLRev repo (e.g., sync)

        bibtex_str = self.parse_bibtex_str(recs_dict_in=records)

        with open(save_path, "w", encoding="utf-8") as out:
            out.write(bibtex_str + "\n")

    def __save_record_list_by_id(
        self, *, records: dict, append_new: bool = False
    ) -> None:
        # Note : currently no use case for append_new=True??

        parsed = self.parse_bibtex_str(recs_dict_in=records)
        record_list = [
            {
                "ID": item[item.find("{") + 1 : item.find(",")],
                "record": "@" + item + "\n",
            }
            for item in parsed.split("\n@")
        ]
        # Correct the first item
        record_list[0]["record"] = "@" + record_list[0]["record"][2:]

        current_id_str = "NOTSET"
        if self.records_file.is_file():
            with open(self.records_file, "r+b") as file:
                seekpos = file.tell()
                line = file.readline()
                while line:
                    if b"@" in line[:3]:
                        current_id = line[line.find(b"{") + 1 : line.rfind(b",")]
                        current_id_str = current_id.decode("utf-8")
                    if current_id_str in [x["ID"] for x in record_list]:
                        replacement = [x["record"] for x in record_list][0]
                        record_list = [
                            x for x in record_list if x["ID"] != current_id_str
                        ]
                        line = file.readline()
                        while (
                            b"@" not in line[:3] and line
                        ):  # replace: drop the current record
                            line = file.readline()
                        remaining = line + file.read()
                        file.seek(seekpos)
                        file.write(replacement.encode("utf-8"))
                        seekpos = file.tell()
                        file.flush()
                        os.fsync(file)
                        file.write(remaining)
                        file.truncate()  # if the replacement is shorter...
                        file.seek(seekpos)

                    seekpos = file.tell()
                    line = file.readline()

        if len(record_list) > 0:
            if append_new:
                with open(self.records_file, "a", encoding="utf8") as m_refs:
                    for item in record_list:
                        m_refs.write(item["record"])
            else:
                self.review_manager.report_logger.error(
                    "records not written to file: " f'{[x["ID"] for x in record_list]}'
                )

        self.add_record_changes()

    def save_records_dict(self, *, records: dict, partial: bool = False) -> None:
        """Save the records dict in RECORDS_FILE"""

        if partial:
            self.__save_record_list_by_id(records=records)
            return
        self.save_records_dict_to_file(records=records, save_path=self.records_file)

    def read_next_record(self, *, conditions: list = None) -> typing.Iterator[dict]:
        """Read records (Iterator) based on condition"""

        # Note : matches conditions connected with 'OR'
        record_dict = self.load_records_dict()

        records = []
        for _, record in record_dict.items():
            if conditions is not None:
                for condition in conditions:
                    for key, value in condition.items():
                        if str(value) == str(record[key]):
                            records.append(record)
            else:
                records.append(record)
        yield from records

    def format_records_file(self) -> bool:
        """Format the records file"""

        records = self.load_records_dict()
        for record_dict in records.values():
            if "colrev_status" not in record_dict:
                print(f'Error: no status field in record ({record_dict["ID"]})')
                continue

            record = colrev.record.PrepRecord(data=record_dict)
            if record_dict["colrev_status"] in [
                colrev.record.RecordState.md_needs_manual_preparation,
            ]:
                record.update_masterdata_provenance(
                    unprepared_record=record, review_manager=self.review_manager
                )
                record.update_metadata_status(review_manager=self.review_manager)

            if record_dict["colrev_status"] == colrev.record.RecordState.pdf_prepared:
                record.reset_pdf_provenance_notes()

        self.save_records_dict(records=records)
        changed = self.RECORDS_FILE_RELATIVE in [
            r.a_path for r in self.__git_repo.index.diff(None)
        ]
        return changed

    # ID creation, update and lookup ---------------------------------------

    def reprocess_id(self, *, paper_ids: str) -> None:
        """Remove an ID (set of IDs) from the bib_db (for reprocessing)"""

        saved_args = locals()
        if "all" == paper_ids:
            # self.review_manager.logger.info("Removing/reprocessing all records")
            os.remove(self.records_file)
            self.__git_repo.index.remove(
                [str(self.RECORDS_FILE_RELATIVE)],
                working_tree=True,
            )
        else:
            records = self.load_records_dict()
            records = {
                ID: record
                for ID, record in records.items()
                if ID not in paper_ids.split(",")
            }
            self.save_records_dict(records=records)
            self.add_record_changes()

        self.review_manager.create_commit(msg="Reprocess", saved_args=saved_args)

    def __create_temp_id(
        self, *, local_index: colrev.env.local_index.LocalIndex, record_dict: dict
    ) -> str:

        try:

            retrieved_record = local_index.retrieve(record_dict=record_dict)
            temp_id = retrieved_record["ID"]

        except colrev_exceptions.RecordNotInIndexException:

            if "" != record_dict.get("author", record_dict.get("editor", "")):
                authors_string = record_dict.get(
                    "author", record_dict.get("editor", "Anonymous")
                )
                authors = colrev.record.PrepRecord.format_author_field(
                    input_string=authors_string
                ).split(" and ")
            else:
                authors = ["Anonymous"]

            # Use family names
            for author in authors:
                if "," in author:
                    author = author.split(",", maxsplit=1)[0]
                else:
                    author = author.split(" ", maxsplit=1)[0]

            id_pattern = self.review_manager.settings.project.id_pattern
            if colrev.settings.IDPattern.first_author_year == id_pattern:
                temp_id = (
                    f'{author.replace(" ", "")}{str(record_dict.get("year", "NoYear"))}'
                )
            elif colrev.settings.IDPattern.three_authors_year == id_pattern:
                temp_id = ""
                indices = len(authors)
                if len(authors) > 3:
                    indices = 3
                for ind in range(0, indices):
                    temp_id = temp_id + f'{authors[ind].split(",")[0].replace(" ", "")}'
                if len(authors) > 3:
                    temp_id = temp_id + "EtAl"
                temp_id = temp_id + str(record_dict.get("year", "NoYear"))

            if temp_id.isupper():
                temp_id = temp_id.capitalize()
            # Replace special characters
            # (because IDs may be used as file names)
            temp_id = colrev.env.utils.remove_accents(input_str=temp_id)
            temp_id = re.sub(r"\(.*\)", "", temp_id)
            temp_id = re.sub("[^0-9a-zA-Z]+", "", temp_id)

        return temp_id

    def __update_temp_id_based_on_id_blacklist(
        self,
        *,
        record_in_bib_db: bool,
        record_dict: dict,
        temp_id: str,
        id_blacklist: list,
    ) -> str:
        if record_in_bib_db:
            # allow IDs to remain the same.
            other_ids = id_blacklist
            # Note: only remove it once. It needs to change when there are
            # other records with the same ID
            if record_dict["ID"] in other_ids:
                other_ids.remove(record_dict["ID"])
        else:
            # ID can remain the same, but it has to change
            # if it is already in bib_db
            other_ids = id_blacklist

        order = 0
        letters = list(string.ascii_lowercase)
        next_unique_id = temp_id
        appends: list = []
        while next_unique_id.lower() in [i.lower() for i in other_ids]:
            if len(appends) == 0:
                order += 1
                appends = list(itertools.product(letters, repeat=order))
            next_unique_id = temp_id + "".join(list(appends.pop(0)))
        temp_id = next_unique_id
        return temp_id

    def propagated_id(self, *, record_id: str) -> bool:
        """Check whether an ID is propagated (i.e., its record's status is beyond md_processed)"""

        for record in self.load_records_dict(header_only=True):
            if record["ID"] == record_id:
                if record[
                    "colrev_status"
                ] in colrev.record.RecordState.get_post_x_states(
                    state=colrev.record.RecordState.md_processed
                ):
                    return True

        return False

    def __generate_id_blacklist(
        self,
        *,
        local_index: colrev.env.local_index.LocalIndex,
        record_dict: dict,
        id_blacklist: list = None,
        record_in_bib_db: bool = False,
    ) -> str:
        """Generate a blacklist to avoid setting duplicate IDs"""

        # Only change IDs that are before md_processed
        if record_dict["colrev_status"] in colrev.record.RecordState.get_post_x_states(
            state=colrev.record.RecordState.md_processed
        ):
            raise colrev_exceptions.PropagatedIDChange([record_dict["ID"]])
        # Alternatively, we could change IDs except for those
        # that have been propagated to the
        # screen or data will not be replaced
        # (this would break the chain of evidence)

        temp_id = self.__create_temp_id(
            local_index=local_index, record_dict=record_dict
        )

        if id_blacklist:
            temp_id = self.__update_temp_id_based_on_id_blacklist(
                record_in_bib_db=record_in_bib_db,
                record_dict=record_dict,
                temp_id=temp_id,
                id_blacklist=id_blacklist,
            )

        return temp_id

    def set_ids(self, *, records: dict = None, selected_ids: list = None) -> dict:
        """Set the IDs of records according to predefined formats or
        according to the LocalIndex"""
        # pylint: disable=redefined-outer-name

        local_index = self.review_manager.get_local_index()

        if records is None:
            records = {}

        if len(records) == 0:
            records = self.load_records_dict()

        id_list = list(records.keys())

        for record_id in list(records.keys()):
            record_dict = records[record_id]
            record = colrev.record.Record(data=record_dict)
            if record.masterdata_is_curated():
                continue
            self.review_manager.logger.debug(f"Set ID for {record_id}")
            if selected_ids is not None:
                if record_id not in selected_ids:
                    continue
            elif record_dict["colrev_status"] not in [
                colrev.record.RecordState.md_imported,
                colrev.record.RecordState.md_prepared,
            ]:
                continue

            old_id = record_id
            new_id = self.__generate_id_blacklist(
                local_index=local_index,
                record_dict=record_dict,
                id_blacklist=id_list,
                record_in_bib_db=True,
            )

            id_list.append(new_id)
            if old_id != new_id:
                # We need to insert the a new element into records
                # to make sure that the IDs are actually saved
                record_dict.update(ID=new_id)
                records[new_id] = record_dict
                del records[old_id]
                self.review_manager.report_logger.info(f"set_ids({old_id}) to {new_id}")
                if old_id in id_list:
                    id_list.remove(old_id)

        self.save_records_dict(records=records)
        self.add_record_changes()

        return records

    def get_next_id(self, *, bib_file: Path) -> int:
        """Get the next ID (incrementing counter)"""
        ids = []
        if bib_file.is_file():
            with open(bib_file, encoding="utf8") as file:
                line = file.readline()
                while line:
                    if "@" in line[:3]:
                        current_id = line[line.find("{") + 1 : line.rfind(",")]
                        ids.append(current_id)
                    line = file.readline()
        max_id = max([int(cid) for cid in ids if cid.isdigit()] + [0]) + 1
        return max_id

    # GIT operations -----------------------------------------------

    def get_repo(self) -> git.Repo:
        """Get the git repository object (requires review_manager.notify(...))"""

        if self.review_manager.notified_next_operation is None:
            raise colrev_exceptions.ReviewManagerNotNofiedError()
        return self.__git_repo

    def has_changes(self) -> bool:
        """Check whether the git repository has changes"""
        # Extension : allow for optional path (check changes for that file)
        return self.__git_repo.is_dirty()

    def add_changes(self, *, path: Path) -> None:
        """Add changed file to git"""

        while (self.review_manager.path / Path(".git/index.lock")).is_file():
            time.sleep(0.5)
            print("Waiting for previous git operation to complete")

        self.__git_repo.index.add([str(path)])

    def get_untracked_files(self) -> list:
        """Get the files that are untracked by git"""

        return self.__git_repo.untracked_files

    def __get_last_records_filecontents(self) -> bytes:
        revlist = (
            (
                commit.hexsha,
                (commit.tree / str(self.RECORDS_FILE_RELATIVE)).data_stream.read(),
            )
            for commit in self.__git_repo.iter_commits(
                paths=str(self.RECORDS_FILE_RELATIVE)
            )
        )
        filecontents = list(revlist)[0][1]
        return filecontents

    def records_changed(self) -> bool:
        """Check whether the records were changed"""
        main_recs_changed = str(self.RECORDS_FILE_RELATIVE) in [
            item.a_path for item in self.__git_repo.index.diff(None)
        ] + [x.a_path for x in self.__git_repo.head.commit.diff()]

        try:
            self.__get_last_records_filecontents()
        except IndexError:
            main_recs_changed = False
        return main_recs_changed

    def remove_file_from_git(self, *, path: str) -> None:
        """Remove a file from git"""
        self.__git_repo.index.remove([path], working_tree=True)

    def create_commit(
        self, *, msg: str, author: git.Actor, committer: git.Actor, hook_skipping: bool
    ) -> None:
        """Create a commit"""
        self.__git_repo.index.commit(
            msg,
            author=author,
            committer=committer,
            skip_hooks=hook_skipping,
        )

    def records_file_in_history(self) -> bool:
        """Check whether the records file is in the git history"""
        return self.file_in_history(filepath=self.RECORDS_FILE_RELATIVE)

    def file_in_history(self, *, filepath: Path) -> bool:
        """Check whether a file is in the git history"""
        return str(filepath) in [
            o.path for o in self.__git_repo.head.commit.tree.traverse()
        ]

    def get_commit_message(self, *, commit_nr: int) -> str:
        """Get the commit message for commit #"""
        master = self.__git_repo.head.reference
        assert commit_nr == 0  # extension : implement other cases
        if commit_nr == 0:
            cmsg = master.commit.message
        return cmsg

    def add_record_changes(self) -> None:
        """Add changes in records to git"""
        while (self.review_manager.path / Path(".git/index.lock")).is_file():
            time.sleep(0.5)
            print("Waiting for previous git operation to complete")
        self.__git_repo.index.add([str(self.RECORDS_FILE_RELATIVE)])

    def add_setting_changes(self) -> None:
        """Add changes in settings to git"""
        while (self.review_manager.path / Path(".git/index.lock")).is_file():
            time.sleep(0.5)
            print("Waiting for previous git operation to complete")

        self.__git_repo.index.add([str(self.review_manager.SETTINGS_RELATIVE)])

    def has_untracked_search_records(self) -> bool:
        """Check whether there are untracked search records"""
        search_dir = str(self.review_manager.SEARCHDIR_RELATIVE) + "/"
        untracked_files = self.get_untracked_files()
        return any(search_dir in untracked_file for untracked_file in untracked_files)

    def reset_log_if_no_changes(self) -> None:
        """Reset the report log file if there are not changes"""
        if not self.__git_repo.is_dirty():
            self.review_manager.reset_report_logger()

    def get_last_commit_sha(self) -> str:
        """Get the last commit sha"""
        return str(self.__git_repo.head.commit.hexsha)

    def get_tree_hash(self) -> str:
        """Get the current tree hash"""
        tree_hash = self.__git_repo.git.execute(["git", "write-tree"])
        return str(tree_hash)

    def __get_remote_commit_differences(self) -> list:
        origin = self.__git_repo.remotes.origin
        if origin.exists():
            try:
                origin.fetch()
            except GitCommandError:
                return [-1, -1]

        nr_commits_behind, nr_commits_ahead = -1, -1
        if self.__git_repo.active_branch.tracking_branch() is not None:
            branch_name = str(self.__git_repo.active_branch)
            tracking_branch_name = str(self.__git_repo.active_branch.tracking_branch())
            self.review_manager.logger.debug(f"{branch_name} - {tracking_branch_name}")

            behind_operation = branch_name + ".." + tracking_branch_name
            commits_behind = self.__git_repo.iter_commits(behind_operation)
            nr_commits_behind = sum(1 for c in commits_behind)

            ahead_operation = tracking_branch_name + ".." + branch_name
            commits_ahead = self.__git_repo.iter_commits(ahead_operation)
            nr_commits_ahead = sum(1 for c in commits_ahead)

        return [nr_commits_behind, nr_commits_ahead]

    def behind_remote(self) -> bool:
        """Check whether the repository is behind the remote"""
        nr_commits_behind = 0
        connected_remote = 0 != len(self.__git_repo.remotes)
        if connected_remote:
            origin = self.__git_repo.remotes.origin
            if origin.exists():
                (
                    nr_commits_behind,
                    _,
                ) = self.__get_remote_commit_differences()
        if nr_commits_behind > 0:
            return True
        return False

    def remote_ahead(self) -> bool:
        """Check whether the remote is ahead"""
        connected_remote = 0 != len(self.__git_repo.remotes)
        if connected_remote:
            origin = self.__git_repo.remotes.origin
            if origin.exists():
                (
                    _,
                    nr_commits_ahead,
                ) = self.__get_remote_commit_differences()
        if nr_commits_ahead > 0:
            return True
        return False

    def pull_if_repo_clean(self) -> None:
        """Pull project if repository is clean"""
        if not self.__git_repo.is_dirty():
            origin = self.__git_repo.remotes.origin
            origin.pull()


if __name__ == "__main__":
    pass
