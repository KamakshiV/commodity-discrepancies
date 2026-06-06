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
    assert changes[0]["TABNAME"] == "VBEP"
    assert changes[0]["FNAME"] == "BMENG"


def test_three_key_join_preferred_over_two_key_pool():
    cdhdr = pd.DataFrame(
        [
            {
                "OBJECTID": "51000401",
                "CHANGENR": "0002942764",
                "OBJECTCLAS": "VERKBELEG",
            }
        ]
    )
    cdpos = pd.DataFrame(
        [
            {
                "CHANGENR": "0002942764",
                "OBJECTID": "51000401",
                "OBJECTCLAS": "VERKBELEG",
                "TABNAME": "VBEP",
                "FNAME": "LGORT",
                "VALUE_OLD": "FINV",
                "VALUE_NEW": "INTR",
            },
            {
                "CHANGENR": "0002942764",
                "OBJECTID": "9999999999",
                "OBJECTCLAS": "VERKBELEG",
                "TABNAME": "VBEP",
                "FNAME": "LGORT",
                "VALUE_OLD": "X",
                "VALUE_NEW": "Y",
            },
        ]
    )

    changes = research_vbep_changes_for_vbeln("51000401", cdhdr, cdpos)
    assert len(changes) == 1
    assert changes[0]["VALUE_NEW"] == "INTR"
    assert changes[0]["CDPOS_OBJECTID"] == "51000401"


def test_cdpos_objectid_may_differ_from_cdhdr_vbeln():
    """Real extracts: CDHDR.OBJECTID=VBELN, CDPOS.OBJECTID=internal id, same CHANGENR."""
    cdhdr = pd.DataFrame(
        [
            {
                "OBJECTID": "51000401",
                "CHANGENR": "0002942753",
                "OBJECTCLAS": "VERKBELEG",
            }
        ]
    )
    cdpos = pd.DataFrame(
        [
            {
                "CHANGENR": "0002942753",
                "OBJECTID": "1200000058",
                "OBJECTCLAS": "VERKBELEG",
                "TABNAME": "VBEP",
                "FNAME": "LGORT",
                "VALUE_OLD": "FINV",
                "VALUE_NEW": "INTR",
            },
            {
                "CHANGENR": "0002942753",
                "OBJECTID": "1200000058",
                "OBJECTCLAS": "VERKBELEG",
                "TABNAME": "VBAP",
                "FNAME": "OIC_ADESTN",
                "VALUE_OLD": "",
                "VALUE_NEW": "CAOEDM101",
            },
        ]
    )

    changes = research_vbep_changes_for_vbeln("51000401", cdhdr, cdpos)
    assert len(changes) == 1
    assert changes[0]["TABNAME"] == "VBEP"
    assert changes[0]["FNAME"] == "LGORT"
    assert changes[0]["VALUE_NEW"] == "INTR"
    assert changes[0]["CDHDR_OBJECTID"] == "51000401"
    assert changes[0]["CDPOS_OBJECTID"] == "1200000058"


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


def test_vbep_lgort_change_via_cmm_internal_doc_bridge():
    """CDHDR uses internal OBJECTID; CDPOS LGORT must be on TABNAME=VBEP."""
    cdhdr = pd.DataFrame(
        [
            {
                "OBJECTID": "1700007919",
                "CHANGENR": "0003395261",
                "OBJECTCLAS": "VERKBELEG",
            }
        ]
    )
    cdpos = pd.DataFrame(
        [
            {
                "CHANGENR": "0003395261",
                "OBJECTID": "1700007919",
                "OBJECTCLAS": "VERKBELEG",
                "TABNAME": "VBEP",
                "TABKEY": "0831700007919000010",
                "FNAME": "LGORT",
                "VALUE_OLD": "INTR",
                "VALUE_NEW": "500",
            }
        ]
    )
    cmm = pd.DataFrame(
        [
            {
                "DOCUMENT_CHAR10": "1700007919",
                "DOCUMENT_ITEM": "000010",
                "ROOT_DOC": "0052004067",
                "LGORT": "500",
            },
            {
                "DOCUMENT_CHAR10": "0052004067",
                "DOCUMENT_ITEM": "000010",
                "ROOT_DOC": "0052004067",
                "LGORT": "500",
            },
        ]
    )
    cmm_row = cmm.iloc[1]

    changes = research_vbep_changes_for_vbeln(
        "0052004067",
        cdhdr,
        cdpos,
        posnr="000010",
        cmm=cmm,
        cmm_row=cmm_row,
        mandt="083",
    )

    assert len(changes) == 1
    assert changes[0]["TABNAME"] == "VBEP"
    assert changes[0]["FNAME"] == "LGORT"
    assert changes[0]["VALUE_NEW"] == "500"
