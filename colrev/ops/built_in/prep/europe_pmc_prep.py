#! /usr/bin/env python
"""Consolidation of metadata based on Europe PMC API as a prep operation"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import timeout_decorator
import zope.interface
from dacite import from_dict
from dataclasses_jsonschema import JsonSchemaMixin

import colrev.env.package_manager
import colrev.ops.built_in.database_connectors
import colrev.ops.search_sources
import colrev.record

if TYPE_CHECKING:
    import colrev.ops.prep

# pylint: disable=too-few-public-methods
# pylint: disable=duplicate-code


@zope.interface.implementer(colrev.env.package_manager.PrepPackageEndpointInterface)
@dataclass
class EuropePMCMetadataPrep(JsonSchemaMixin):
    """Prepares records based on Europe PCM metadata"""

    settings_class = colrev.env.package_manager.DefaultSettings

    source_correction_hint = "ask the publisher to correct the metadata"
    always_apply_changes = False

    def __init__(
        self,
        *,
        prep_operation: colrev.ops.prep.Prep,  # pylint: disable=unused-argument
        settings: dict,
    ) -> None:
        self.settings = from_dict(data_class=self.settings_class, data=settings)

    @timeout_decorator.timeout(60, use_signals=False)
    def prepare(
        self, prep_operation: colrev.ops.prep.Prep, record: colrev.record.PrepRecord
    ) -> colrev.record.Record:
        """Prepare a record based on Europe PMC metadata"""

        colrev.ops.built_in.database_connectors.EuropePMCConnector.get_masterdata_from_europe_pmc(
            prep_operation=prep_operation, record=record
        )
        return record


if __name__ == "__main__":
    pass