from tools import TOOL_DEFINITIONS, TOOL_REGISTRY

def test_tools_registered():
    expected = {
        "sales_summary",
        "top_products",
        "low_stock",
        "store_comparison",
        "period_sales_detail",
    }
    assert set(TOOL_REGISTRY) == expected
    assert {item["function"]["name"] for item in TOOL_DEFINITIONS} == expected


def test_period_sales_detail_definition_supports_dates_and_stores():
    definition = next(
        item["function"]
        for item in TOOL_DEFINITIONS
        if item["function"]["name"] == "period_sales_detail"
    )
    properties = definition["parameters"]["properties"]
    assert {"start_date", "end_date", "store_name"} <= set(properties)


def test_agent_tools_are_read_only():
    assert not any(
        any(prefix in name for prefix in ("create_", "update_", "delete_", "set_"))
        for name in TOOL_REGISTRY
    )
