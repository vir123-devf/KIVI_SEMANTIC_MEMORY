"""
Hey Kivi's request handler: a bounded tool-use loop. The model decides which
tool(s) to call, sees results, and either calls another tool or answers.

Grounding rule (enforced by prompt, checked in eval): if no tool call
returned anything relevant, Hey Kivi must say so rather than invent an
answer. This is the single most safety-critical behavior in the assignment
brief ("whether it refuses to invent an answer when the history does not
contain one").
"""
import json
import time

from llm_client import call, ORCHESTRATION_MODEL
from tools import TOOL_SCHEMAS, DISPATCH
from db import new_id, now_iso, get_conn

SYSTEM = """You are Hey Kivi, a voice assistant with access to the user's \
dictation history and durable memory (facts/preferences) via tools.

Rules:
- Use tools to ground every factual claim about the user's past work or \
preferences. Never state a fact about their history without having \
retrieved it via a tool this turn.
- If your tool calls return nothing relevant, say plainly that you don't \
have that in their history. Do not guess or fill gaps.
- When asked to "remember" or "forget" something explicitly, use the \
remember/forget tools rather than just acknowledging in text.
- Keep responses short and voice-appropriate (this is spoken back to the \
user, not read as a document)."""


def handle_turn(query_text: str) -> dict:
    start = time.time()
    messages = [{"role": "user", "content": query_text}]
    tool_calls_log = []
    retrieved_memory_ids = set()
    total_in, total_out = 0, 0

    for _ in range(4):  # bounded loop: at most 4 tool round-trips per turn
        resp, latency = call(
            model=ORCHESTRATION_MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOL_SCHEMAS,
            max_tokens=1024,
        )
        total_in += resp.usage.input_tokens
        total_out += resp.usage.output_tokens

        tool_use_blocks = [b for b in resp.content if b.type == "tool_use"]
        if not tool_use_blocks:
            final_text = "".join(b.text for b in resp.content if b.type == "text")
            elapsed_ms = int((time.time() - start) * 1000)
            return _log_and_return(
                query_text, final_text, tool_calls_log, retrieved_memory_ids,
                elapsed_ms, total_in, total_out,
            )

        messages.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for block in tool_use_blocks:
            fn = DISPATCH.get(block.name)
            output = fn(**block.input) if fn else {"error": f"unknown tool {block.name}"}
            tool_calls_log.append({"name": block.name, "input": block.input, "output": output})
            for item in output.get("results", []):
                if "memory_id" in item:
                    retrieved_memory_ids.add(item["memory_id"])
                if "id" in item and block.name in ("recall_durable",):
                    retrieved_memory_ids.add(item["id"])
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(output),
            })
        messages.append({"role": "user", "content": tool_results})

    # Safety valve: loop exhausted without a final answer.
    elapsed_ms = int((time.time() - start) * 1000)
    return _log_and_return(
        query_text, "I wasn't able to complete that within the tool budget for this turn.",
        tool_calls_log, retrieved_memory_ids, elapsed_ms, total_in, total_out,
    )


def _log_and_return(query, response_text, tool_calls_log, retrieved_ids, latency_ms, in_tok, out_tok):
    reasoning = _summarize_reasoning(tool_calls_log, retrieved_ids)
    turn_id = new_id()
    conn = get_conn()
    conn.execute(
        "INSERT INTO hey_kivi_turns (id, ts, query_text, tool_calls, retrieved_memory_ids, "
        "response_text, reasoning_note, latency_ms, input_tokens, output_tokens, model_used) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (turn_id, now_iso(), query, json.dumps(tool_calls_log), json.dumps(list(retrieved_ids)),
         response_text, reasoning, latency_ms, in_tok, out_tok, ORCHESTRATION_MODEL),
    )
    conn.commit()
    conn.close()
    return {
        "turn_id": turn_id,
        "response": response_text,
        "tool_calls": tool_calls_log,
        "retrieved_memory_ids": list(retrieved_ids),
        "reasoning": reasoning,
        "latency_ms": latency_ms,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
    }


def _summarize_reasoning(tool_calls_log, retrieved_ids) -> str:
    if not tool_calls_log:
        return "No tools called; answered from the request text alone."
    names = [t["name"] for t in tool_calls_log]
    if not retrieved_ids and not any(t["output"].get("results") for t in tool_calls_log):
        return f"Called {', '.join(names)} but found nothing relevant; answered without grounding."
    return f"Called {', '.join(names)}; grounded on {len(retrieved_ids)} memory record(s)."
