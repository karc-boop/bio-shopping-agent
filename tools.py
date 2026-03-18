"""Tool definitions and implementations for the bio shopping agent."""

import json
from typing import Optional
from mock_data import PRODUCTS
from db import get_lab_profile, get_order_history, create_draft_order, get_grant_budgets

# ── Tool schemas (passed to Claude) ──────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "search_products",
        "description": (
            "Search the bio materials catalog by keyword, application, or material type. "
            "Returns matching products from multiple suppliers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keyword, e.g. 'Matrigel', 'BSA western blot', 'collagen 3D culture'",
                },
                "application": {
                    "type": "string",
                    "description": "Filter by application, e.g. 'organoids', 'western blot', 'cell culture'",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "compare_products",
        "description": (
            "Compare two or more products side-by-side on price, supplier, specs, "
            "shipping requirements, and lead time. Pass product IDs from search results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of product IDs to compare, e.g. ['P001', 'P002']",
                },
            },
            "required": ["product_ids"],
        },
    },
    {
        "name": "get_lab_memory",
        "description": (
            "Retrieve the lab's profile (PI name, institution, available grant codes) "
            "and past order history. Use this to personalise recommendations and "
            "suggest grant codes for new orders."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "create_draft_order",
        "description": (
            "Create a draft purchase order for a specific product. "
            "This does NOT place the order — it creates a draft for the researcher to review and approve."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "Product ID from search results",
                },
                "quantity": {
                    "type": "integer",
                    "description": "Number of units to order",
                },
                "grant_code": {
                    "type": "string",
                    "description": "Grant / budget code to charge this purchase to",
                },
                "notes": {
                    "type": "string",
                    "description": "Any special instructions or notes for the order",
                },
            },
            "required": ["product_id", "quantity"],
        },
    },
]


# ── Tool implementations ──────────────────────────────────────────────────────

def search_products(query: str, application: Optional[str] = None) -> str:
    query_lower = query.lower()
    app_lower = application.lower() if application else None

    results = []
    for p in PRODUCTS:
        name_match = query_lower in p["name"].lower() or query_lower in p["description"].lower()
        app_match = (
            not app_lower
            or any(app_lower in a.lower() for a in p["applications"])
        )
        if name_match and app_match:
            results.append({
                "id": p["id"],
                "name": p["name"],
                "supplier": p["supplier"],
                "catalog_number": p["catalog_number"],
                "price_usd": p["price_usd"],
                "unit": p["unit"],
                "lead_time_days": p["lead_time_days"],
                "requires_cold_chain": p["requires_cold_chain"],
                "in_stock": p["in_stock"],
                "applications": p["applications"],
            })

    if not results:
        return json.dumps({"results": [], "message": "No products found matching your query."})
    return json.dumps({"results": results, "total": len(results)})


def compare_products(product_ids: list[str]) -> str:
    found = [p for p in PRODUCTS if p["id"] in product_ids]
    if not found:
        return json.dumps({"error": "No products found for the given IDs."})

    comparison = []
    for p in found:
        comparison.append({
            "id": p["id"],
            "name": p["name"],
            "supplier": p["supplier"],
            "catalog_number": p["catalog_number"],
            "price_usd": p["price_usd"],
            "unit": p["unit"],
            "grade": p["grade"],
            "storage": p["storage"],
            "shipping": p["shipping"],
            "lead_time_days": p["lead_time_days"],
            "requires_cold_chain": p["requires_cold_chain"],
            "in_stock": p["in_stock"],
            "applications": p["applications"],
            # Scientific Score fields
            "scientific_score": p.get("scientific_score"),
            "citation_count": p.get("citation_count"),
            "reproducibility_flag": p.get("reproducibility_flag", False),
            "community_note": p.get("community_note"),
        })

    # Highlight best-value and highest-scoring options
    best_score = max(comparison, key=lambda x: x["scientific_score"] or 0)
    cheapest = min(comparison, key=lambda x: x["price_usd"])
    for item in comparison:
        item["is_highest_scientific_score"] = item["id"] == best_score["id"]
        item["is_lowest_price"] = item["id"] == cheapest["id"]

    return json.dumps({"comparison": comparison})


def get_lab_memory_tool() -> str:
    profile = get_lab_profile()
    history = get_order_history()
    budgets = get_grant_budgets()
    return json.dumps({
        "lab_profile": profile,
        "grant_budgets": budgets,
        "recent_orders": history[:5],
    })


def create_draft_order_tool(
    product_id: str,
    quantity: int,
    grant_code: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    product = next((p for p in PRODUCTS if p["id"] == product_id), None)
    if not product:
        return json.dumps({"error": f"Product {product_id} not found."})

    total = product["price_usd"] * quantity

    # Budget check: warn if grant has insufficient remaining funds
    budget_warning = None
    if grant_code:
        budgets = get_grant_budgets()
        budget = next((b for b in budgets if b["grant_code"] == grant_code), None)
        if budget is None:
            budget_warning = f"Grant code '{grant_code}' not found in lab's registered grants."
        elif total > budget["remaining_usd"]:
            budget_warning = (
                f"Insufficient budget: {grant_code} has ${budget['remaining_usd']:.2f} remaining "
                f"but this order totals ${total:.2f}. "
                f"Consider splitting across grants or reducing quantity."
            )

    draft = create_draft_order(
        product_id=product_id,
        product_name=product["name"],
        supplier=product["supplier"],
        catalog_number=product["catalog_number"],
        quantity=quantity,
        unit_price_usd=product["price_usd"],
        grant_code=grant_code,
        notes=notes,
    )

    result = {
        "draft_order": draft,
        "message": (
            f"Draft order #{draft['id']} created for ${total:.2f}. "
            "Please review and confirm to place the order."
        ),
    }
    if budget_warning:
        result["budget_warning"] = budget_warning
    return json.dumps(result)


# ── Dispatcher ────────────────────────────────────────────────────────────────

def execute_tool(name: str, inputs: dict) -> str:
    if name == "search_products":
        return search_products(**inputs)
    elif name == "compare_products":
        return compare_products(**inputs)
    elif name == "get_lab_memory":
        return get_lab_memory_tool()
    elif name == "create_draft_order":
        return create_draft_order_tool(**inputs)
    else:
        return json.dumps({"error": f"Unknown tool: {name}"})
