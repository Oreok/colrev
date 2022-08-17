#!/usr/bin/env python3
import typing
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Note : to avoid performance issues on startup (ReviewManager, parsing settings)
# the settings dataclasses should be in one file (13s compared to 0.3s)

# https://stackoverflow.com/questions/66807878/pretty-print-dataclasses-prettier

# Project


class IDPpattern(Enum):
    first_author_year = "FIRST_AUTHOR_YEAR"
    three_authors_year = "THREE_AUTHORS_YEAR"

    @classmethod
    def get_options(cls):
        # pylint: disable=no-member
        return cls._member_names_


class ReviewType(Enum):
    curated_masterdata = "curated_masterdata"
    realtime = "realtime"
    literature_review = "literature_review"
    narrative_review = "narrative_review"
    descriptive_review = "descriptive_review"
    scoping_review = "scoping_review"
    critical_review = "critical_review"
    theoretical_review = "theoretical_review"
    conceptual_review = "conceptual_review"
    qualitative_systematic_review = "qualitative_systematic_review"
    meta_analysis = "meta_analysis"
    scientometric = "scientometric"
    peer_review = "peer_review"

    @classmethod
    def get_options(cls):
        return cls._member_names_

    def __str__(self):
        return (
            f"{self.name.replace('_', ' ').replace('meta analysis', 'meta-analysis')}"
        )


@dataclass
class Author:
    name: str
    initials: str
    email: str
    orcid: typing.Optional[str]
    contributions: typing.Optional[list]
    affiliations: typing.Optional[list]
    funding: typing.Optional[list]
    identifiers: typing.Optional[list]


@dataclass
class Protocol:
    url: str


@dataclass
class ProjectConfiguration:
    title: str
    authors: typing.List[Author]
    keywords: typing.List[str]
    # status ? (development/published?)
    protocol: typing.Optional[Protocol]
    # publication: ... (reference, link, ....)
    review_type: ReviewType
    id_pattern: IDPpattern
    share_stat_req: str
    delay_automated_processing: bool
    curation_url: typing.Optional[str]
    curated_masterdata: bool
    curated_fields: typing.List[str]
    colrev_version: str

    def __str__(self):
        # TODO : add more
        return f"Review ({self.review_type})"


# Search


class SearchType(Enum):
    DB = "DB"
    TOC = "TOC"
    BACKWARD_SEARCH = "BACKWARD_SEARCH"
    FORWARD_SEARCH = "FORWARD_SEARCH"
    PDFS = "PDFS"
    OTHER = "OTHER"

    @classmethod
    def get_options(cls):
        return cls._member_names_

    def __str__(self):
        return f"{self.name}"


@dataclass
class SearchSource:
    filename: Path
    search_type: SearchType
    source_name: str
    source_identifier: str
    search_parameters: str
    search_script: dict
    conversion_script: dict
    source_prep_scripts: list
    comment: typing.Optional[str]

    def __str__(self):
        source_prep_scripts_string = ",".join(
            s["endpoint"] for s in self.source_prep_scripts
        )
        return (
            f"{self.source_name} (type: {self.search_type}, "
            + f"filename: {self.filename})\n"
            + f"   source identifier:   {self.source_identifier}\n"
            + f"   search parameters:   {self.search_parameters}\n"
            + f"   search_script:       {self.search_script.get('endpoint', '')}\n"
            + f"   conversion_script:   {self.conversion_script['endpoint']}\n"
            + f"   source_prep_script:  {source_prep_scripts_string}\n"
            + f"   comment:             {self.comment}"
        )


# @dataclass
# class SearchSources:

#     sources: typing.List[SearchSource]

#     def __str__(self):
#         return " - " + "\n - ".join([str(s) for s in self.sources])


@dataclass
class SearchConfiguration:
    retrieve_forthcoming: bool

    def __str__(self):
        return f" - retrieve_forthcoming: {self.retrieve_forthcoming}"


# Load


@dataclass
class LoadConfiguration:
    def __str__(self):
        return " - TODO"


# Prep


@dataclass
class PrepRound:
    """The scripts are either in Prepare.prep_scripts, in a custom project script
    (the script in settings.json must have the same name), or otherwise in a
    python package (locally installed)."""

    name: str
    similarity: float
    scripts: list

    def __str__(self):
        short_list = [script["endpoint"] for script in self.scripts][:3]
        if len(self.scripts) > 3:
            short_list.append("...")
        return f"{self.name} (" + ",".join(short_list) + ")"


@dataclass
class PrepConfiguration:
    fields_to_keep: typing.List[str]
    prep_rounds: typing.List[PrepRound]

    man_prep_scripts: list

    def __str__(self):
        return (
            " - prep_rounds: \n   - "
            + "\n   - ".join([str(prep_round) for prep_round in self.prep_rounds])
            + f"\n - fields_to_keep: {self.fields_to_keep}"
        )


# Dedupe


@dataclass
class DedupeConfiguration:
    same_source_merges: str  # TODO : "prevent" or "apply"
    scripts: list

    def __str__(self):
        return (
            f" - same_source_merges: {self.same_source_merges}\n"
            + " - "
            + ",".join([s["endpoint"] for s in self.scripts])
        )


# Prescreen


@dataclass
class PrescreenConfiguration:
    explanation: str
    scripts: list

    def __str__(self):
        return "Scripts: " + ",".join([s["endpoint"] for s in self.scripts])


# PDF get


@dataclass
class PDFGetConfiguration:
    pdf_path_type: str  # TODO : "symlink" or "copy"
    pdf_required_for_screen_and_synthesis: bool
    """With the pdf_required_for_screen_and_synthesis flag, the PDF retrieval
    can be specified as mandatory (true) or optional (false) for the following steps"""
    rename_pdfs: bool
    scripts: list

    man_pdf_get_scripts: list

    def __str__(self):
        return (
            f" - pdf_path_type: {self.pdf_path_type}"
            + " - "
            + ",".join([s["endpoint"] for s in self.scripts])
        )


# PDF prep


@dataclass
class PDFPrepConfiguration:
    scripts: list

    man_pdf_prep_scripts: list

    def __str__(self):
        return " - " + ",".join([s["endpoint"] for s in self.scripts])


# Screen


class ScreenCriterionType(Enum):
    inclusion_criterion = "inclusion_criterion"
    exclusion_criterion = "exclusion_criterion"

    @classmethod
    def get_options(cls):
        # pylint: disable=no-member
        return cls._member_names_

    def __str__(self):
        return self.name


@dataclass
class ScreenCriterion:
    explanation: str
    comment: typing.Optional[str]
    criterion_type: ScreenCriterionType

    def __str__(self):
        return f"{self.criterion_type} {self.explanation} ({self.explanation})"


@dataclass
class ScreenConfiguration:
    explanation: typing.Optional[str]
    criteria: typing.Dict[str, ScreenCriterion]
    scripts: list

    def __str__(self):
        return " - " + "\n - ".join([str(c) for c in self.criteria])


# Data


@dataclass
class DataConfiguration:
    scripts: list

    def __str__(self):
        return " - " + "\n- ".join([s["endpoint"] for s in self.scripts])


@dataclass
class Configuration:

    project: ProjectConfiguration
    sources: typing.List[SearchSource]
    search: SearchConfiguration
    load: LoadConfiguration
    prep: PrepConfiguration
    dedupe: DedupeConfiguration
    prescreen: PrescreenConfiguration
    pdf_get: PDFGetConfiguration
    pdf_prep: PDFPrepConfiguration
    screen: ScreenConfiguration
    data: DataConfiguration

    def __str__(self):
        return (
            str(self.project)
            + "\nSearch\n"
            + str(self.search)
            + "\nSources\n"
            + "\n- ".join([str(s) for s in self.sources])
            + "\nLoad\n"
            + str(self.load)
            + "\nPreparation\n"
            + str(self.prep)
            + "\nDedupe\n"
            + str(self.dedupe)
            + "\nPrescreen\n"
            + str(self.prescreen)
            + "\nPDF get\n"
            + str(self.pdf_get)
            + "\nPDF prep\n"
            + str(self.pdf_prep)
            + "\nScreen\n"
            + str(self.screen)
            + "\nData\n"
            + str(self.data)
        )


if __name__ == "__main__":
    pass