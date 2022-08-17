#! /usr/bin/env python
import random

import zope.interface
from dacite import from_dict

import colrev.process
import colrev.record


@zope.interface.implementer(colrev.process.PrescreenEndpoint)
class CustomPrescreen:
    def __init__(self, *, PRESCREEN, SETTINGS):
        self.SETTINGS = from_dict(
            data_class=colrev.process.DefaultSettings, data=SETTINGS
        )

    def run_prescreen(slef, PRESCREEN, records: dict, split: list) -> dict:

        for record in records.values():
            if random.random() < 0.5:
                record.update(
                    colrev_status=colrev.record.RecordState.rev_prescreen_included
                )
            else:
                record.update(
                    colrev_status=colrev.record.RecordState.rev_prescreen_excluded
                )

        PRESCREEN.REVIEW_MANAGER.REVIEW_DATASET.save_records_dict(records=records)
        PRESCREEN.REVIEW_MANAGER.REVIEW_DATASET.add_record_changes()
        PRESCREEN.REVIEW_MANAGER.create_commit(
            msg="Pre-screen (random)",
            manual_author=False,
            script_call="colrev prescreen",
        )

        # Alternatively (does not change the records argument   )
        # presscreen_data = PRESCREEN.get_data()
        # for record in prescreen_data["items"]:
        #   PRESCREEN_RECORD = PrescreenRecord(data=record)
        #   PRESCREEN_RECORD.prescreen(REVIEW_MANAGER=PRESCREEN.REVIEW_MANAGER,
        #                               prescreen_inclusion=True/False)

        return records