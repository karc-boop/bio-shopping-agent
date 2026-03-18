"""Bio shopping agent — Claude-powered agentic loop."""

import anthropic
from tools import TOOL_DEFINITIONS, execute_tool

client = anthropic.Anthropic()

SYSTEM_PROMPT = """You are a bio materials purchasing assistant for university research labs.
Your job is to help researchers find, compare, and order biological materials with confidence.

Your workflow:
1. Understand what the researcher needs (material, intended use, quantity)
2. Use search_products to find relevant items
3. Use compare_products when multiple options exist — always interpret the Scientific Score
4. Use get_lab_memory to retrieve lab profile, grant budgets, and past orders
5. Use create_draft_order to prepare a draft for the researcher's review and approval

Scientific Score guidance (shown in compare_products results):
- Score 1.0–5.0, derived from peer-reviewed publication citation counts
- Higher score = more community validation and reproducible results in the literature
- If reproducibility_flag is true, explicitly warn the researcher about known lot-to-lot variability
- Always mention the citation_count when comparing products — it is the strongest trust signal
- Default to the highest Scientific Score option unless the researcher has a clear price constraint
  or the lower-scored product is meaningfully better suited to their specific application

Grant budget guidance (shown in get_lab_memory results):
- Always call get_lab_memory before recommending a grant code for an order
- Show the researcher their remaining balance per grant before they commit
- If create_draft_order returns a budget_warning, surface it prominently to the researcher
  and suggest alternatives (different grant code, smaller quantity)
- Never assign a grant code without confirming the researcher agrees

General rules:
- Always clarify the intended application if it affects grade or spec selection
- Flag cold chain requirements early so the researcher can plan logistics
- Never place a final order — always create a draft and ask for confirmation
- If the researcher says "confirm", "approve", or "yes" to a draft, summarise the order
  (product, quantity, total cost, grant code) and tell them the draft ID to approve via /approve
"""


def run_agent(conversation: list) -> tuple[str, list]:
    """
    Run one turn of the agent loop.

    Args:
        conversation: Full message history (list of {role, content} dicts)

    Returns:
        (assistant_text, updated_conversation)
    """
    messages = list(conversation)

    while True:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        # Append assistant turn (full content block list, preserving thinking blocks)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Extract final text response
            text = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
            return text, messages

        if response.stop_reason == "tool_use":
            # Execute all tool calls
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            # Feed results back to Claude
            messages.append({"role": "user", "content": tool_results})
            # Loop continues — Claude will process tool results

        else:
            # Unexpected stop reason
            text = next(
                (b.text for b in response.content if b.type == "text"),
                f"[Stopped: {response.stop_reason}]",
            )
            return text, messages
