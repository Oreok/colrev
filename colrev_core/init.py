#! /usr/bin/env python
import logging
from pathlib import Path

import git

from colrev_core.settings import ReviewType


class Initializer:
    def __init__(
        self,
        *,
        project_name: str,
        SHARE_STAT_REQ: str,
        type: str,
        url: str = "NA",
        example: bool = False,
        local_index_repo: bool = False,
    ) -> None:

        saved_args = locals()

        if project_name is not None:
            self.project_name = project_name
        else:
            self.project_name = str(Path.cwd().name)
        assert SHARE_STAT_REQ in ["NONE", "PROCESSED", "SCREENED", "COMPLETED"]
        assert not (example and local_index_repo)
        assert type in ReviewType._member_names_

        self.SHARE_STAT_REQ = SHARE_STAT_REQ
        self.review_type = type
        self.url = url

        self.__require_empty_directory()
        print("Setup files")
        self.__setup_files()
        print("Setup git")
        self.__setup_git()
        print("Create commit")
        if example:
            self.__create_example_repo()
        self.__create_commit(saved_args=saved_args)
        if not example:
            print("Register repo")
            self.__register_repo()
        if local_index_repo:
            self.__create_local_index()

    def __register_repo(self) -> None:
        from colrev_core.environment import EnvironmentManager

        EnvironmentManager.register_repo(path_to_register=Path.cwd())
        return

    def __create_commit(self, *, saved_args: dict) -> None:
        from colrev_core.review_manager import ReviewManager

        self.REVIEW_MANAGER = ReviewManager()

        self.REVIEW_MANAGER.report_logger.info("Initialize review repository")
        self.REVIEW_MANAGER.report_logger.info(
            "Set project title:".ljust(30, " ") + f"{self.project_name}"
        )
        self.REVIEW_MANAGER.report_logger.info(
            "Set SHARE_STAT_REQ:".ljust(30, " ") + f"{self.SHARE_STAT_REQ}"
        )
        del saved_args["local_index_repo"]
        self.REVIEW_MANAGER.create_commit(
            msg="Initial commit", manual_author=True, saved_args=saved_args
        )
        return

    def __setup_files(self) -> None:
        from colrev_core.environment import EnvironmentManager
        import pkgutil
        import json

        # Note: parse instead of copy to avoid format changes
        filedata = pkgutil.get_data(__name__, "template/settings.json")
        if filedata:
            settings = json.loads(filedata.decode("utf-8"))
            with open("settings.json", "w", encoding="utf8") as file:
                json.dump(settings, file, indent=4)

        Path("search").mkdir()
        Path("pdfs").mkdir()

        files_to_retrieve = [
            [Path("template/readme.md"), Path("readme.md")],
            [Path("template/.pre-commit-config.yaml"), Path(".pre-commit-config.yaml")],
            [Path("template/.markdownlint.yaml"), Path(".markdownlint.yaml")],
            [Path("template/.gitattributes"), Path(".gitattributes")],
            [
                Path("template/docker-compose.yml"),
                Path.home() / Path("colrev/docker-compose.yml"),
            ],
        ]
        for rp, p in files_to_retrieve:
            self.__retrieve_package_file(template_file=rp, target=p)

        with open("settings.json") as f:
            settings = json.load(f)

        settings["project"]["review_type"] = self.review_type
        # Principle: adapt values provided by the default settings.json
        # instead of creating a new settings.json

        if self.review_type not in ["curated_masterdata"]:
            settings["data"]["data_format"] = [
                {
                    "endpoint": "MANUSCRIPT",
                    "paper_endpoint_version": "1.0",
                    "word_template": "APA-7.docx",
                    "csl_style": "apa.csl",
                }
            ]

        if "literature_review" == self.review_type:
            pass

        elif "narrative_review" == self.review_type:
            pass

        elif "descriptive_review" == self.review_type:
            settings["data"]["data_format"].append(
                {"endpoint": "PRISMA", "prisma_data_endpoint_version": "1.0"}
            )

        elif "scoping_review" == self.review_type:
            settings["data"]["data_format"].append(
                {"endpoint": "PRISMA", "prisma_data_endpoint_version": "1.0"}
            )

        elif "critical_review" == self.review_type:
            settings["data"]["data_format"].append(
                {"endpoint": "PRISMA", "prisma_data_endpoint_version": "1.0"}
            )

        elif "theoretical_review" == self.review_type:
            pass

        elif "conceptual_review" == self.review_type:
            pass

        elif "qualitative_systematic_review" == self.review_type:
            settings["data"]["data_format"].append(
                {
                    "endpoint": "STRUCTURED",
                    "structured_data_endpoint_version": "1.0",
                    "fields": [],
                }
            )
            settings["data"]["data_format"].append(
                {"endpoint": "PrismaDiagram", "prisma_data_endpoint_version": "1.0"}
            )

        elif "meta_analysis" == self.review_type:
            settings["data"]["data_format"].append(
                {
                    "endpoint": "STRUCTURED",
                    "structured_data_endpoint_version": "1.0",
                    "fields": [],
                }
            )
            settings["data"]["data_format"].append(
                {"endpoint": "PRISMA", "prisma_data_endpoint_version": "1.0"}
            )

        elif "realtime" == self.review_type:
            settings["project"]["delay_automated_processing"] = False
            settings["prep"]["prep_rounds"] = [
                {
                    "name": "high_confidence",
                    "similarity": 0.95,
                    "scripts": [
                        "load_fixes",
                        "remove_urls_with_500_errors",
                        "remove_broken_IDs",
                        "global_ids_consistency_check",
                        "prep_curated",
                        "format",
                        "resolve_crossrefs",
                        "get_doi_from_urls",
                        "get_masterdata_from_doi",
                        "get_masterdata_from_crossref",
                        "get_masterdata_from_dblp",
                        "get_masterdata_from_open_library",
                        "get_year_from_vol_iss_jour_crossref",
                        "get_record_from_local_index",
                        "remove_nicknames",
                        "format_minor",
                        "drop_fields",
                    ],
                }
            ]

        elif "curated_masterdata" == self.review_type:
            # replace readme
            self.__retrieve_package_file(
                template_file=Path("template/review_type/curated_masterdata/readme.md"),
                target=Path("readme.md"),
            )
            if self.url:
                self.__inplace_change(
                    filename=Path("readme.md"),
                    old_string="{{url}}",
                    new_string=self.url,
                )

            settings["project"]["curated_masterdata"] = True
            settings["prescreen"]["scripts"] = [{"endpoint": "conditional_prescreen"}]
            settings["screen"]["scripts"] = [{"endpoint": "conditional_screen"}]
            settings["pdf_get"]["scripts"] = []

        with open("settings.json", "w") as outfile:
            json.dump(settings, outfile, indent=4)

        if "review" in self.project_name.lower():
            self.__inplace_change(
                filename=Path("readme.md"),
                old_string="{{project_title}}",
                new_string=self.project_name.rstrip(" "),
            )
        else:
            r_type_suffix = self.review_type.replace("_", " ").replace(
                "meta analysis", "meta-analysis"
            )
            self.__inplace_change(
                filename=Path("readme.md"),
                old_string="{{project_title}}",
                new_string=self.project_name.rstrip(" ") + f": A {r_type_suffix}",
            )

        global_git_vars = EnvironmentManager.get_name_mail_from_global_git_config()
        if 2 != len(global_git_vars):
            logging.error("Global git variables (user name and email) not available.")
            return

        # Note: need to write the .gitignore because file would otherwise be
        # ignored in the template directory.
        f = open(".gitignore", "w", encoding="utf8")
        f.write(
            "*.bib.sav\n"
            + "missing_pdf_files.csv\n"
            + "manual_cleansing_statistics.csv\n"
            + "data.csv\n"
            + "venv\n"
            + ".references_learned_settings\n"
            + ".corrections\n"
            + ".ipynb_checkpoints/\n"
            + "pdfs\n"
            + "requests_cache.sqlite\n"
            + "__pycache__"
        )
        f.close()
        return

    def __setup_git(self) -> None:
        from subprocess import check_call
        from subprocess import DEVNULL
        from subprocess import STDOUT
        from subprocess import CalledProcessError

        from colrev_core.environment import EnvironmentManager

        git_repo = git.Repo.init()

        # To check if git actors are set
        EnvironmentManager.get_name_mail_from_global_git_config()

        logging.info("Install latest pre-commmit hooks")
        scripts_to_call = [
            ["pre-commit", "install"],
            ["pre-commit", "install", "--hook-type", "prepare-commit-msg"],
            ["pre-commit", "install", "--hook-type", "pre-push"],
            ["pre-commit", "autoupdate"],
            ["daff", "git", "csv"],
        ]
        for script_to_call in scripts_to_call:
            try:
                print(" ".join(script_to_call) + "...")
                check_call(script_to_call, stdout=DEVNULL, stderr=STDOUT)
            except CalledProcessError:
                if "" == " ".join(script_to_call):
                    print(
                        f"{' '.join(script_to_call)} did not succeed "
                        "(Internet connection could not be available)"
                    )
                else:
                    print(f"Failed: {' '.join(script_to_call)}")
                pass
        git_repo.index.add(
            [
                "readme.md",
                ".pre-commit-config.yaml",
                ".gitattributes",
                ".gitignore",
                "settings.json",
                ".markdownlint.yaml",
            ]
        )
        return

    def __require_empty_directory(self):

        cur_content = [str(x) for x in Path.cwd().glob("**/*")]

        if "venv" in cur_content:
            cur_content.remove("venv")
            # Note: we can use paths directly when initiating the project
        if "report.log" in cur_content:
            cur_content.remove("report.log")

        if 0 != len(cur_content):
            raise NonEmptyDirectoryError()

    def __inplace_change(
        self, *, filename: Path, old_string: str, new_string: str
    ) -> None:
        with open(filename, encoding="utf8") as f:
            s = f.read()
            if old_string not in s:
                logging.info(f'"{old_string}" not found in {filename}.')
                return
        with open(filename, "w", encoding="utf8") as f:
            s = s.replace(old_string, new_string)
            f.write(s)
        return

    def __retrieve_package_file(self, *, template_file: Path, target: Path) -> None:
        import pkgutil

        filedata = pkgutil.get_data(__name__, str(template_file))
        if filedata:
            with open(target, "w", encoding="utf8") as file:
                file.write(filedata.decode("utf-8"))
        return

    def __create_example_repo(self) -> None:
        """The example repository is intended to provide an initial illustration
        of CoLRev. It focuses on a quick overview of the process and does
        not cover advanced features or special cases."""

        print("Include 30_example_records.bib")
        self.__retrieve_package_file(
            template_file=Path("template/example/30_example_records.bib"),
            target=Path("search/30_example_records.bib"),
        )

        git_repo = git.Repo.init()
        git_repo.index.add(["search/30_example_records.bib"])

        return

    def __create_local_index(self) -> None:
        from colrev_core.environment import LocalIndex
        import os

        self.REVIEW_MANAGER.report_logger.handlers = []

        local_index_path = LocalIndex.local_environment_path / Path("local_index")
        curdir = Path.cwd()
        if not local_index_path.is_dir():
            local_index_path.mkdir(parents=True, exist_ok=True)
            os.chdir(local_index_path)
            Initializer(
                project_name="local_index",
                SHARE_STAT_REQ="PROCESSED",
                type="curated_masterdata",
                local_index_repo=True,
            )
            print("Created local_index repository")

        os.chdir(curdir)
        return


class NonEmptyDirectoryError(Exception):
    def __init__(self):
        self.message = "please change to an empty directory to initialize a project"
        super().__init__(self.message)


if __name__ == "__main__":
    pass
