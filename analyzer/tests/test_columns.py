"""Tests for ColumnInfo and its helpers."""

import dataclasses

import pytest

from pare.columns import (
    ColumnInfo,
    columns_from_dicts,
    columns_of_service,
    group_by_service,
    name_to_index,
    services,
    validate_columns,
)

# A small realistic case: frontend calls cartservice, three metrics each.
COLUMNS = [
    ColumnInfo("frontend_latency", "frontend", "latency"),
    ColumnInfo("frontend_cpu", "frontend", "cpu"),
    ColumnInfo("cartservice_mem", "cartservice", "mem"),
    ColumnInfo("cartservice_latency", "cartservice", "latency"),
]


def test_column_info_holds_the_three_fields():
    column = ColumnInfo("cartservice_mem", "cartservice", "mem")
    assert column.name == "cartservice_mem"
    assert column.service == "cartservice"
    assert column.metric == "mem"


def test_column_info_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        COLUMNS[0].service = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    "args",
    [
        ("", "svc", "cpu"),
        ("name", "", "cpu"),
        ("name", "svc", ""),
        ("   ", "svc", "cpu"),
    ],
)
def test_column_info_rejects_empty_fields(args):
    with pytest.raises(ValueError):
        ColumnInfo(*args)


def test_the_mapping_is_taken_as_given_and_never_parsed_from_the_name():
    """The central rule from docs/05 section 2.

    A column name that looks nothing like its service and metric must be stored
    exactly as supplied. If anything ever starts splitting names, this fails.
    """
    odd = ColumnInfo("col_17", "payment-service", "memory_working_set_bytes")
    assert odd.service == "payment-service"
    assert odd.metric == "memory_working_set_bytes"
    assert services([odd]) == ["payment-service"]


# --- validation -------------------------------------------------------------


def test_validate_accepts_a_good_list():
    validate_columns(COLUMNS)  # must not raise


def test_validate_rejects_duplicate_names():
    duplicated = [*COLUMNS, ColumnInfo("frontend_cpu", "frontend", "cpu")]
    with pytest.raises(ValueError, match="duplicate column names"):
        validate_columns(duplicated)


def test_validate_rejects_an_empty_list():
    with pytest.raises(ValueError, match="empty"):
        validate_columns([])


def test_two_services_may_share_a_metric_name():
    """Only full column names must be unique; frontend and cartservice both
    having a latency metric is normal and must be allowed."""
    validate_columns(
        [
            ColumnInfo("frontend_latency", "frontend", "latency"),
            ColumnInfo("cartservice_latency", "cartservice", "latency"),
        ]
    )


# --- helpers ----------------------------------------------------------------


def test_services_are_unique_and_keep_their_first_appearance_order():
    assert services(COLUMNS) == ["frontend", "cartservice"]


def test_group_by_service():
    grouped = group_by_service(COLUMNS)
    assert list(grouped) == ["frontend", "cartservice"]
    assert [c.name for c in grouped["frontend"]] == ["frontend_latency", "frontend_cpu"]
    assert [c.name for c in grouped["cartservice"]] == ["cartservice_mem", "cartservice_latency"]


def test_columns_of_service():
    assert [c.metric for c in columns_of_service(COLUMNS, "cartservice")] == ["mem", "latency"]
    assert columns_of_service(COLUMNS, "emailservice") == []


def test_name_to_index_matches_the_order_of_the_values_array():
    assert name_to_index(COLUMNS) == {
        "frontend_latency": 0,
        "frontend_cpu": 1,
        "cartservice_mem": 2,
        "cartservice_latency": 3,
    }


# --- the JSON form ----------------------------------------------------------


def test_from_dict_and_to_dict_round_trip():
    data = {"name": "cartservice_mem", "service": "cartservice", "metric": "mem"}
    assert ColumnInfo.from_dict(data).to_dict() == data


def test_from_dict_reports_what_is_missing():
    with pytest.raises(ValueError, match="missing"):
        ColumnInfo.from_dict({"name": "a", "service": "b"})


def test_columns_from_dicts_validates_the_whole_list():
    items = [c.to_dict() for c in COLUMNS]
    assert columns_from_dicts(items) == COLUMNS

    with pytest.raises(ValueError, match="duplicate"):
        columns_from_dicts(items + [items[0]])
