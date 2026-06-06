from app.services.preset_screens import (
    PRESET_SCREENS,
    _effective_preset_filters,
    _matches_preset_filters,
    get_preset_chart_symbols,
)


def _leaders_screen():
    return next(
        screen
        for screen in PRESET_SCREENS
        if screen["id"] == "leaders_in_leading_groups"
    )


def test_leaders_in_leading_groups_preset_filters_for_v1_contract():
    screen = _leaders_screen()

    matching = {
        "symbol": "LEAD",
        "ibd_group_rank": 40,
        "rs_rating": 80,
        "composite_score": 64.23,
        "volume": 1_500_000,
    }

    assert screen["name"] == "Leaders in Leading Groups"
    assert screen["sort_by"] == "composite_score"
    assert screen["sort_order"] == "desc"
    assert screen["apply_default_filters"] is True
    assert "compositeScore" not in screen["filters"]
    assert "minVolume" not in screen["filters"]
    assert _matches_preset_filters(matching, screen["filters"]) is True
    assert _matches_preset_filters(
        {**matching, "ibd_group_rank": 41},
        screen["filters"],
    ) is False
    assert _matches_preset_filters(
        {**matching, "rs_rating": 79},
        screen["filters"],
    ) is False


def test_leaders_effective_filters_inherit_market_defaults():
    screen = _leaders_screen()

    filters = _effective_preset_filters(screen, {"minVolume": 1_300_000})

    assert filters == {
        "minVolume": 1_300_000,
        "ibdGroupRank": {"min": None, "max": 40},
        "rsRating": {"min": 80, "max": None},
    }


def test_preset_chart_symbols_apply_inherited_market_defaults():
    screen = _leaders_screen()
    rows = [
        {
            "symbol": "LIQUID",
            "ibd_group_rank": 10,
            "rs_rating": 90,
            "volume": 2_000_000,
            "composite_score": 64.0,
        },
        {
            "symbol": "THIN",
            "ibd_group_rank": 5,
            "rs_rating": 99,
            "volume": 900_000,
            "composite_score": 99.0,
        },
    ]

    assert get_preset_chart_symbols(
        rows,
        presets=[screen],
        top_n=5,
        default_filters={"minVolume": 1_300_000},
    ) == {"LIQUID"}


def test_noop_scalar_and_range_filters_match_like_frontend():
    row = {"symbol": "ROW", "volume": None, "composite_score": None}

    assert _matches_preset_filters(row, {"minVolume": None}) is True
    assert _matches_preset_filters(
        row,
        {"compositeScore": {"min": None, "max": None}},
    ) is True
