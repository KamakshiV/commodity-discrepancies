"""Tests for Scenario 2 attribute-mismatch change document research."""

import pandas as pd

from app.services.change_document_research import research_vbep_changes_for_vbeln


def test_vbep_change_join_with_objectclas_alias():
    cdhdr = pd.DataFrame(
        [
            {
                "OBJECTID": "00051000401",
                "CHANGENR": "0002942764",
                "OBJECTCLAS": "VERKBELEG",
            }
        ]
    )
    cdpos = pd.DataFrame(
        [
            {
                "CHANGENR": "0002942764",
                "OBJECTID": "00051000401",
                "OBJECTCLAS": "VERKBELEG",
                "TABNAME": "VBEP",
                "FNAME": "BMENG",
                "VALUE_OLD": "10",
                "VALUE_NEW": "20",
            },
            {
                "CHANGENR": "0002942764",
                "OBJECTID": "00051000401",
                "OBJECTCLAS": "VERKBELEG",
                "TABNAME": "VBAP",
                "FNAME": "KWMENG",
                "VALUE_OLD": "1",
                "VALUE_NEW": "2",
            },
        ]
    )

    changes = research_vbep_changes_for_vbeln("51000401", cdhdr, cdpos, posnr="000010")

    assert len(changes) == 1
    ch = changes[0]
    assert ch["CHANGENR"] == "0002942764"
    assert ch["OBJECTID"] == "00051000401"
    assert ch["OBJECTCLASS"] == "VERKBELEG"
    assert ch["TABNAME"] == "VBEP"
    assert ch["FNAME"] == "BMENG"
    assert ch["VALUE_OLD"] == "10"
    assert ch["VALUE_NEW"] == "20"
    assert ch["POSNR"] == "000010"


def test_no_match_when_vbeln_not_in_cdhdr():
    cdhdr = pd.DataFrame([{"OBJECTID": "999", "CHANGENR": "1", "OBJECTCLASS": "VERKBELEG"}])
    cdpos = pd.DataFrame(
        [
            {
                "CHANGENR": "1",
                "OBJECTID": "999",
                "OBJECTCLASS": "VERKBELEG",
                "TABNAME": "VBEP",
                "FNAME": "X",
                "VALUE_OLD": "",
                "VALUE_NEW": "",
            }
        ]
    )
    assert research_vbep_changes_for_vbeln("51000401", cdhdr, cdpos) == []
