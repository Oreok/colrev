#! /usr/bin/env python
import csv
import os
import pkgutil
import typing
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import zope.interface
from dacite import from_dict

import colrev.exceptions as colrev_exceptions
import colrev.process
import colrev.record


@dataclass
class ScopePrescreenEndpointSettings:
    name: str
    TimeScopeFrom: typing.Optional[int]
    TimeScopeTo: typing.Optional[int]
    LanguageScope: typing.Optional[list]
    ExcludeComplementaryMaterials: typing.Optional[bool]
    OutletInclusionScope: typing.Optional[dict]
    OutletExclusionScope: typing.Optional[dict]
    ENTRYTYPEScope: typing.Optional[list]


@zope.interface.implementer(colrev.process.PrescreenEndpoint)
class ScopePrescreenEndpoint:

    title_complementary_materials_keywords = [
        "about our authors",
        "editorial board",
        "author index",
        "contents",
        "index of authors",
        "list of reviewers",
        "issue information",
        "call for papers",
        "acknowledgments",
        "back matter",
        "front matter",
        "volume information",
        "research spotlights",
        "acknowledgment of reviewers",
    ]

    def __init__(self, *, PRESCREEN, SETTINGS):
        if "TimeScopeFrom" in SETTINGS:
            assert SETTINGS["TimeScopeFrom"] > 1900
        if "TimeScopeFrom" in SETTINGS:
            assert SETTINGS["TimeScopeFrom"] < 2100
        if "TimeScopeTo" in SETTINGS:
            assert SETTINGS["TimeScopeTo"] > 1900
        if "TimeScopeTo" in SETTINGS:
            assert SETTINGS["TimeScopeTo"] < 2100
        # TODO : validate values (assert, e.g., LanguageScope)

        self.SETTINGS = from_dict(
            data_class=ScopePrescreenEndpointSettings, data=SETTINGS
        )

    def run_prescreen(self, PRESCREEN, records: dict, split: list) -> dict:
        def load_predatory_journals_beal() -> dict:

            predatory_journals = {}

            filedata = pkgutil.get_data(
                __name__, "../template/predatory_journals_beall.csv"
            )
            if filedata:
                for pj in filedata.decode("utf-8").splitlines():
                    predatory_journals[pj.lower()] = pj.lower()

            return predatory_journals

        predatory_journals_beal = load_predatory_journals_beal()

        saved_args = locals()
        PAD = 50
        for record in records.values():
            if record["colrev_status"] != colrev.record.RecordState.md_processed:
                continue

            # Note : LanguageScope is covered in prep
            # because dedupe cannot handle merges between languages

            if self.SETTINGS.ENTRYTYPEScope:
                if record["ENTRYTYPE"] not in self.SETTINGS.ENTRYTYPEScope:
                    colrev.record.Record(data=record).prescreen_exclude(
                        reason="not in ENTRYTYPEScope"
                    )

            if self.SETTINGS.OutletExclusionScope:
                if "values" in self.SETTINGS.OutletExclusionScope:
                    for r in self.SETTINGS.OutletExclusionScope["values"]:
                        for key, value in r.items():
                            if key in record and record.get(key, "") == value:
                                colrev.record.Record(data=record).prescreen_exclude(
                                    reason="in OutletExclusionScope"
                                )
                if "list" in self.SETTINGS.OutletExclusionScope:
                    for r in self.SETTINGS.OutletExclusionScope["list"]:
                        for key, value in r.items():
                            if "resource" == key and "predatory_journals_beal" == value:
                                if "journal" in record:
                                    if (
                                        record["journal"].lower()
                                        in predatory_journals_beal
                                    ):
                                        colrev.record.Record(
                                            data=record
                                        ).prescreen_exclude(
                                            reason="predatory_journals_beal"
                                        )

            if self.SETTINGS.TimeScopeFrom:
                if int(record.get("year", 0)) < self.SETTINGS.TimeScopeFrom:
                    colrev.record.Record(data=record).prescreen_exclude(
                        reason="not in TimeScopeFrom "
                        f"(>{self.SETTINGS.TimeScopeFrom})"
                    )

            if self.SETTINGS.TimeScopeTo:
                if int(record.get("year", 5000)) > self.SETTINGS.TimeScopeTo:
                    colrev.record.Record(data=record).prescreen_exclude(
                        reason="not in TimeScopeTo " f"(<{self.SETTINGS.TimeScopeTo})"
                    )

            if self.SETTINGS.OutletInclusionScope:
                in_outlet_scope = False
                if "values" in self.SETTINGS.OutletInclusionScope:
                    for r in self.SETTINGS.OutletInclusionScope["values"]:
                        for key, value in r.items():
                            if key in record and record.get(key, "") == value:
                                in_outlet_scope = True
                if not in_outlet_scope:
                    colrev.record.Record(data=record).prescreen_exclude(
                        reason="not in OutletInclusionScope"
                    )

            # TODO : discuss whether we should move this to the prep scripts
            if self.SETTINGS.ExcludeComplementaryMaterials:
                if self.SETTINGS.ExcludeComplementaryMaterials:
                    if "title" in record:
                        # TODO : extend/test the following
                        if (
                            record["title"].lower()
                            in self.title_complementary_materials_keywords
                        ):
                            colrev.record.Record(data=record).prescreen_exclude(
                                reason="complementary material"
                            )

            if (
                record["colrev_status"]
                == colrev.record.RecordState.rev_prescreen_excluded
            ):
                PRESCREEN.REVIEW_MANAGER.report_logger.info(
                    f' {record["ID"]}'.ljust(PAD, " ")
                    + "Prescreen excluded (automatically)"
                )

        PRESCREEN.REVIEW_MANAGER.REVIEW_DATASET.save_records_dict(records=records)
        PRESCREEN.REVIEW_MANAGER.REVIEW_DATASET.add_record_changes()
        PRESCREEN.REVIEW_MANAGER.create_commit(
            msg="Pre-screen (scope)",
            manual_author=False,
            script_call="colrev prescreen",
            saved_args=saved_args,
        )
        return records


@zope.interface.implementer(colrev.process.PrescreenEndpoint)
class CoLRevCLIPrescreenEndpoint:
    def __init__(self, *, PRESCREEN, SETTINGS):
        self.SETTINGS = from_dict(
            data_class=colrev.process.DefaultSettings, data=SETTINGS
        )

    def run_prescreen(self, PRESCREEN, records: dict, split: list) -> dict:

        if not split:
            split = []

        prescreen_data = PRESCREEN.get_data()
        if len(split) > 0:
            stat_len = len(split)
        else:
            stat_len = prescreen_data["nr_tasks"]

        i, quit_pressed = 0, False

        if "" == PRESCREEN.REVIEW_MANAGER.settings.prescreen.explanation:
            PRESCREEN.REVIEW_MANAGER.settings.prescreen.explanation = input(
                "Provide a short explanation of the prescreen "
                "(which papers should be included?):"
            )
            PRESCREEN.REVIEW_MANAGER.save_settings()

        print("\n\nIn the prescreen, the following process is followed:\n")
        print("   " + PRESCREEN.REVIEW_MANAGER.settings.prescreen.explanation)

        PRESCREEN.REVIEW_MANAGER.logger.info("Start prescreen")

        if 0 == stat_len:
            PRESCREEN.REVIEW_MANAGER.logger.info("No records to prescreen")

        for record in prescreen_data["items"]:
            if len(split) > 0:
                if record["ID"] not in split:
                    continue

            PRESCREEN_RECORD = colrev.record.PrescreenRecord(data=record)

            print("\n\n")
            print(PRESCREEN_RECORD)

            ret, inclusion_decision_str = "NA", "NA"
            i += 1
            while ret not in ["y", "n", "s", "q"]:
                ret = input(
                    f"({i}/{stat_len}) Include this record "
                    "[enter y,n,q,s for yes,no,quit,skip]? "
                )
                if "q" == ret:
                    quit_pressed = True
                elif "s" == ret:
                    continue
                else:
                    inclusion_decision_str = ret.replace("y", "yes").replace("n", "no")

            if quit_pressed:
                PRESCREEN.REVIEW_MANAGER.logger.info("Stop prescreen")
                break

            inclusion_decision = "yes" == inclusion_decision_str
            PRESCREEN_RECORD.prescreen(
                REVIEW_MANAGER=PRESCREEN.REVIEW_MANAGER,
                prescreen_inclusion=inclusion_decision,
                PAD=prescreen_data["PAD"],
            )

        records = PRESCREEN.REVIEW_MANAGER.REVIEW_DATASET.load_records_dict()
        PRESCREEN.REVIEW_MANAGER.REVIEW_DATASET.save_records_dict(records=records)
        PRESCREEN.REVIEW_MANAGER.REVIEW_DATASET.add_record_changes()

        if i < stat_len:  # if records remain for pre-screening
            if "y" != input("Create commit (y/n)?"):
                return records

        PRESCREEN.REVIEW_MANAGER.create_commit(
            msg="Pre-screening (manual)", manual_author=True, saved_args=None
        )
        return records


@zope.interface.implementer(colrev.process.PrescreenEndpoint)
class ASReviewPrescreenEndpoint:

    endpoint_path = Path("prescreen/asreview")
    export_filepath = endpoint_path / Path("records_to_screen.csv")

    def __init__(self, *, PRESCREEN, SETTINGS):
        self.SETTINGS = from_dict(
            data_class=colrev.process.DefaultSettings, data=SETTINGS
        )

        try:
            import asreview  # noqa: F401

            _ = asreview
        except (ImportError, ModuleNotFoundError) as e:
            raise colrev_exceptions.MissingDependencyError(
                "Dependency asreview not found. "
                "Please install it\n  pip install asreview"
            ) from e

    def export_for_asreview(self, PRESCREEN, records, split) -> None:

        self.endpoint_path.mkdir(exist_ok=True, parents=True)

        PRESCREEN.REVIEW_MANAGER.logger.info("Export: asreview")

        # TODO : tbd. whether the selection is necessary
        records = [
            r
            for ID, r in records.items()
            if r["colrev_status"] in [colrev.record.RecordState.md_processed]
        ]
        # Casting to string (in particular the RecordState Enum)
        records = [
            {
                k: str(v)
                for k, v in r.items()
                if k
                not in [
                    "colrev_origin",
                    "colrev_status",
                    "colrev_masterdata_provenance",
                    "colrev_id",
                    "colrev_data_provenance",
                ]
            }
            for r in records
        ]

        to_screen_df = pd.DataFrame.from_dict(records)
        to_screen_df.to_csv(self.export_filepath, quoting=csv.QUOTE_NONNUMERIC)

    def import_from_asreview(self, PRESCREEN, records):
        def get_last_modified(input_paths) -> Path:

            latest_file = max(input_paths, key=os.path.getmtime)
            return Path(latest_file)

        available_files = [
            str(x)
            for x in self.endpoint_path.glob("**/*")
            if "records_to_screen" not in str(x) and x.suffix in [".csv"]
        ]
        if 0 == len(available_files):
            return

        asreview_project_file = get_last_modified(available_files)

        print(f"Loading prescreen results from {asreview_project_file}")

        # TODO : get asreview (python package) version / Docker asreview version
        # If both are available (and if they differ), the user will have to select
        # the one that was actually used

        # TODO : if the included column is not set, no decision has been recorded
        # The idea of asreview is that they could be set to "excluded" automatically
        # We would probably want to do that in a separate commit

        if asreview_project_file.suffix == ".asreview":  # "Export project" in asreview

            print(
                "the project export seems to have changed. we now need to parse"
                "the results.sql file..."
            )
            return
            # import zipfile
            # with zipfile.ZipFile(asreview_project_file, "r") as zip_ref:
            #     zip_ref.extractall(self.endpoint_path)
            # os.remove(asreview_project_file)

            # PRESCREEN.REVIEW_MANAGER.REVIEW_DATASET.\
            # add_changes(path=str(self.endpoint_path))
            # csv_dir = self.endpoint_path / Path("data")
            # csv_path = next(csv_dir.glob("*.csv"))
            # to_import = pd.read_csv(csv_path)

            # labels_json_path = self.endpoint_path / Path("labeled.json")
            # with open(labels_json_path) as json_str:
            #     label_data = json.loads(json_str.read())
            # label_df = pd.DataFrame(label_data, columns=["row_num", "included"])
            # label_df.reset_index(drop=True)
            # label_df.set_index("row_num", inplace=True)

            # to_import = pd.merge(to_import, label_df,
            #  left_index=True, right_index=True)

            # for index, row in to_import.iterrows():
            #     PRESCREEN_RECORD = PrescreenRecord(data=records[row["ID"]])
            #     if 1 == row["included"]:
            #       PRESCREEN_RECORD.prescreen(
            #          REVIEW_MANAGER=PRESCREEN.REVIEW_MANAGER,
            #          prescreen_inclusion=True,
            #       )
            #     if 0 == row["included"]:
            #        PRESCREEN_RECORD.prescreen(
            #            REVIEW_MANAGER=PRESCREEN.REVIEW_MANAGER,
            #            prescreen_inclusion=False,
            #        )
            # result_json_path = self.endpoint_path / Path("result.json")
            # with open(result_json_path) as json_str:
            #     json_data = json.loads(json_str.read())

            # saved_args = {
            #     "version": json_data["version"],
            #     "software_version": json_data["software_version"],
            # }
            # PRESCREEN.REVIEW_MANAGER.report_logger.info(
            #     "asreview settings: "
            # f"\n{PRESCREEN.REVIEW_MANAGER.pp.pformat(json_data['settings'])}"
            # )

        if asreview_project_file.suffix == ".csv":  # "Export results" in asreview
            to_import = pd.read_csv(asreview_project_file)
            for _, row in to_import.iterrows():
                PRESCREEN_RECORD = colrev.record.PrescreenRecord(
                    data=records[row["ID"]]
                )
                if "1" == str(row["included"]):
                    PRESCREEN_RECORD.prescreen(
                        REVIEW_MANAGER=PRESCREEN.REVIEW_MANAGER,
                        prescreen_inclusion=True,
                    )
                elif "0" == str(row["included"]):
                    PRESCREEN_RECORD.prescreen(
                        REVIEW_MANAGER=PRESCREEN.REVIEW_MANAGER,
                        prescreen_inclusion=False,
                    )
                else:
                    print(f'not prescreened: {row["ID"]}')

        # TODO: add version
        saved_args = {"software": "asreview"}

        PRESCREEN.REVIEW_MANAGER.create_commit(
            msg="Pre-screening (manual, with asreview)",
            manual_author=True,
            script_call="colrev prescreen",
            saved_args=saved_args,
        )

        return

    def run_prescreen(self, PRESCREEN, records: dict, split: list) -> dict:

        # there may be an optional setting to change the endpoint_path

        endpoint_path_empty = not any(Path(self.endpoint_path).iterdir())

        # Note : we always update/overwrite the to_screen csv
        self.export_for_asreview(PRESCREEN, records, split)

        if endpoint_path_empty:
            start_screen_selected = True
        else:
            start_screen_selected = "y" == input("Start prescreen [y,n]?")

        if start_screen_selected:

            # Note : the Docker image throws errors for Linux machines
            # The pip package is recommended anyway.

            print(
                "\n  To start the prescreen, create a project and import"
                f" the following csv file: \n\n     {self.export_filepath}"
            )
            print(
                "\n\n  Once completed, export the results as a csv file and"
                f" save in {self.endpoint_path}"
            )
            input("\n  Press Enter to start and ctrl+c to stop ...")
            print("\n\n  ASReview will open shortly.")

            # TODO : if not available: ask to "pip install asreview"
            from asreview.entry_points import LABEntryPoint

            try:
                ASREVIEW = LABEntryPoint()
                ASREVIEW.execute(argv={})
            except KeyboardInterrupt:
                print("\n\n\nCompleted prescreen. ")

        if "y" == input("Import prescreen from asreview [y,n]?"):
            self.import_from_asreview(PRESCREEN, records)

            if PRESCREEN.REVIEW_MANAGER.REVIEW_DATASET.has_changes():
                if "y" == input("create commit [y,n]?"):
                    PRESCREEN.REVIEW_MANAGER.create_commit(
                        msg="Pre-screen (spreadsheets)",
                        manual_author=True,
                        script_call="colrev prescreen",
                    )

        return records


@zope.interface.implementer(colrev.process.PrescreenEndpoint)
class ConditionalPrescreenEndpoint:
    def __init__(self, *, PRESCREEN, SETTINGS):
        self.SETTINGS = from_dict(
            data_class=colrev.process.DefaultSettings, data=SETTINGS
        )

    def run_prescreen(self, PRESCREEN, records: dict, split: list) -> dict:
        # TODO : conditions as a settings/parameter
        saved_args = locals()
        saved_args["include_all"] = ""
        PAD = 50
        for record in records.values():
            if record["colrev_status"] != colrev.record.RecordState.md_processed:
                continue
            PRESCREEN.REVIEW_MANAGER.report_logger.info(
                f' {record["ID"]}'.ljust(PAD, " ")
                + "Included in prescreen (automatically)"
            )
            record.update(
                colrev_status=colrev.record.RecordState.rev_prescreen_included
            )

        PRESCREEN.REVIEW_MANAGER.REVIEW_DATASET.save_records_dict(records=records)
        PRESCREEN.REVIEW_MANAGER.REVIEW_DATASET.add_record_changes()
        PRESCREEN.REVIEW_MANAGER.create_commit(
            msg="Pre-screen (include_all)",
            manual_author=False,
            script_call="colrev prescreen",
            saved_args=saved_args,
        )
        return records


@zope.interface.implementer(colrev.process.PrescreenEndpoint)
class SpreadsheetPrescreenEndpoint:
    def __init__(self, *, PRESCREEN, SETTINGS):
        self.SETTINGS = from_dict(
            data_class=colrev.process.DefaultSettings, data=SETTINGS
        )

    def export_table(
        self, PRESCREEN, records, split, export_table_format="csv"
    ) -> None:
        # TODO : add delta (records not yet in the spreadsheet)
        # instead of overwriting
        # TODO : export_table_format as a settings parameter

        PRESCREEN.REVIEW_MANAGER.logger.info("Loading records for export")

        tbl = []
        for record in records.values():

            if record["colrev_status"] not in [
                colrev.record.RecordState.md_processed,
                colrev.record.RecordState.rev_prescreen_excluded,
                colrev.record.RecordState.rev_prescreen_included,
                colrev.record.RecordState.pdf_needs_manual_retrieval,
                colrev.record.RecordState.pdf_imported,
                colrev.record.RecordState.pdf_not_available,
                colrev.record.RecordState.pdf_needs_manual_preparation,
                colrev.record.RecordState.pdf_prepared,
                colrev.record.RecordState.rev_excluded,
                colrev.record.RecordState.rev_included,
                colrev.record.RecordState.rev_synthesized,
            ]:
                continue

            if len(split) > 0:
                if record["ID"] not in split:
                    continue

            if colrev.record.RecordState.md_processed == record["colrev_status"]:
                inclusion_1 = "TODO"
            elif (
                colrev.record.RecordState.rev_prescreen_excluded
                == record["colrev_status"]
            ):
                inclusion_1 = "no"
            else:
                inclusion_1 = "yes"

            # pylint: disable=duplicate-code
            row = {
                "ID": record["ID"],
                "author": record.get("author", ""),
                "title": record.get("title", ""),
                "journal": record.get("journal", ""),
                "booktitle": record.get("booktitle", ""),
                "year": record.get("year", ""),
                "volume": record.get("volume", ""),
                "number": record.get("number", ""),
                "pages": record.get("pages", ""),
                "doi": record.get("doi", ""),
                "abstract": record.get("abstract", ""),
                "presceen_inclusion": inclusion_1,
            }
            tbl.append(row)

        if "csv" == export_table_format.lower():
            screen_df = pd.DataFrame(tbl)
            screen_df.to_csv("prescreen.csv", index=False, quoting=csv.QUOTE_ALL)
            PRESCREEN.REVIEW_MANAGER.logger.info("Created prescreen.csv")

        if "xlsx" == export_table_format.lower():
            screen_df = pd.DataFrame(tbl)
            screen_df.to_excel("prescreen.xlsx", index=False, sheet_name="screen")
            PRESCREEN.REVIEW_MANAGER.logger.info("Created prescreen.xlsx")

    def import_table(
        self, PRESCREEN, records, import_table_path="prescreen.csv"
    ) -> None:
        # pylint: disable=duplicate-code
        if not Path(import_table_path).is_file():
            PRESCREEN.REVIEW_MANAGER.logger.error(
                f"Did not find {import_table_path} - exiting."
            )
            return
        screen_df = pd.read_csv(import_table_path)
        screen_df.fillna("", inplace=True)
        screened_records = screen_df.to_dict("records")

        PRESCREEN.REVIEW_MANAGER.logger.warning("import_table not completed")

        for screened_record in screened_records:
            if screened_record.get("ID", "") in records:
                record = records[screened_record.get("ID", "")]
                if "no" == screened_record.get("inclusion_1", ""):
                    record[
                        "colrev_status"
                    ] = colrev.record.RecordState.rev_prescreen_excluded
                if "yes" == screened_record.get("inclusion_1", ""):
                    record[
                        "colrev_status"
                    ] = colrev.record.RecordState.rev_prescreen_included

        PRESCREEN.REVIEW_MANAGER.REVIEW_DATASET.save_records_dict(records=records)
        PRESCREEN.REVIEW_MANAGER.REVIEW_DATASET.add_record_changes()
        return

    def run_prescreen(self, PRESCREEN, records: dict, split: list) -> dict:

        if "y" == input("create prescreen spreadsheet [y,n]?"):
            self.export_table(PRESCREEN, records, split)

        if "y" == input("import prescreen spreadsheet [y,n]?"):
            self.import_table(PRESCREEN, records)

        if PRESCREEN.REVIEW_MANAGER.REVIEW_DATASET.has_changes():
            if "y" == input("create commit [y,n]?"):
                PRESCREEN.REVIEW_MANAGER.create_commit(
                    msg="Pre-screen (spreadsheets)",
                    manual_author=True,
                    script_call="colrev prescreen",
                )
        return records