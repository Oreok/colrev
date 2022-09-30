#! /usr/bin/env python
"""Curated metadata project"""
from dataclasses import dataclass
from pathlib import Path

import zope.interface
from dacite import from_dict
from dataclasses_jsonschema import JsonSchemaMixin

import colrev.env.package_manager
import colrev.env.utils
import colrev.ops.built_in.database_connectors
import colrev.ops.search
import colrev.record

# pylint: disable=too-few-public-methods
# pylint: disable=duplicate-code


@zope.interface.implementer(
    colrev.env.package_manager.ReviewTypePackageEndpointInterface
)
@dataclass
class CuratedMasterdata(JsonSchemaMixin):

    settings_class = colrev.env.package_manager.DefaultSettings

    def __init__(
        self, *, operation: colrev.operation.CheckOperation, settings: dict
    ) -> None:
        self.settings = from_dict(data_class=self.settings_class, data=settings)
        self.review_manager = operation.review_manager

    def __str__(self) -> str:
        return "curated masterdata repository"

    def initialize(
        self, settings: colrev.settings.Settings
    ) -> colrev.settings.Settings:

        # replace readme
        colrev.env.utils.retrieve_package_file(
            template_file=Path("template/review_type/curated_masterdata/readme.md"),
            target=Path("readme.md"),
        )
        if self.review_manager.settings.project.curation_url:
            colrev.env.utils.inplace_change(
                filename=Path("readme.md"),
                old_string="{{url}}",
                new_string=self.review_manager.settings.project.curation_url,
            )
        crossref_source = colrev.settings.SearchSource(
            endpoint="crossref",
            filename=Path("data/search/CROSSREF.bib"),
            search_type=colrev.settings.SearchType["DB"],
            source_identifier="https://api.crossref.org/works/{{doi}}",
            search_parameters={},
            load_conversion_package_endpoint={"endpoint": "colrev_built_in.bibtex"},
            comment="",
        )
        settings.sources.insert(0, crossref_source)
        settings.search.retrieve_forthcoming = False

        # TODO : exclude complementary materials in prep scripts
        # TODO : exclude get_masterdata_from_citeas etc. from prep
        settings.prep.prep_man_package_endpoints = [
            {"endpoint": "colrev_built_in.prep_man_curation_jupyter"},
            {"endpoint": "colrev_built_in.export_man_prep"},
        ]
        settings.prescreen.explanation = (
            "All records are automatically prescreen included."
        )

        settings.screen.explanation = (
            "All records are automatically included in the screen."
        )

        settings.project.curated_masterdata = True
        settings.prescreen.prescreen_package_endpoints = [
            {
                "endpoint": "colrev_built_in.scope_prescreen",
                "ExcludeComplementaryMaterials": True,
            },
            {"endpoint": "colrev_built_in.conditional_prescreen"},
        ]
        settings.screen.screen_package_endpoints = [
            {"endpoint": "colrev_built_in.conditional_screen"}
        ]
        settings.pdf_get.pdf_get_package_endpoints = []
        # TODO : Deactivate languages, ...
        #  exclusion and add a complementary exclusion built-in script

        settings.dedupe.dedupe_package_endpoints = [
            {
                "endpoint": "colrev_built_in.curation_full_outlet_dedupe",
                "selected_source": "data/search/CROSSREF.bib",
            },
            {
                "endpoint": "colrev_built_in.curation_full_outlet_dedupe",
                "selected_source": "data/search/pdfs.bib",
            },
            {"endpoint": "colrev_built_in.curation_missing_dedupe"},
        ]

        # curated repo: automatically prescreen/screen-include papers
        # (no data endpoint -> automatically rev_synthesized)

        return settings


if __name__ == "__main__":
    pass