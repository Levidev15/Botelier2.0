"""
flow_ai.py — AI Flow Builder assistant endpoint.

POST /api/tools/{tool_id}/flow/ai-assist
Accepts the current flow state + a natural language message and returns
either an explanation or a validated flow patch (nodes/edges/variables to add).
"""

import json
import os
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.middleware import check_account_permission, get_current_user
from ..database import get_db
from ..models import User
from ..models.tool import Tool
from ..models.tool import ToolType as DBToolType
from ..models.tool_set import ToolSet

router = APIRouter(prefix="/api/tools", tags=["flow_ai"])

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

VALID_NODE_TYPES = {
    "initial", "message", "collect_slot", "collect_form",
    "api_request", "condition", "router", "confirmation",
    "set_variable", "save_record", "transfer", "end",
    "option_picker",
}

NODE_SCHEMA_TEXT = """
NODE TYPES (13 usable types):
• initial — Greeting node. Fields: name, systemPrompt (global AI persona), greeting (what AI says first), waitForResponse (bool). Only one per flow.
• message — Speak a message. Fields: name, message (text, supports {{variable}}), waitForResponse (bool).
• collect_slot — Ask for one piece of info. Fields: name, slot.variableKey (bare name), slot.prompt, slot.type (text|date|number|phone|email|time|choice), slot.retryPrompt, slot.maxRetries (int).
• collect_form — Ask for multiple fields in sequence. Fields: name, introMessage, slots (array of {id, order, variableKey, prompt, type, retryPrompt, maxRetries}).
• api_request — Make an HTTP call. Fields: name, api.method (GET|POST|PUT|PATCH|DELETE), api.url (supports {{variable}}), api.headers (object), api.bodyTemplate (JSON string with {{variable}}), api.responseMapping (object: varName → "$.json.path"), api.timeout (int seconds), api.retryCount (int).
• condition — Branch on a variable's value. Fields: name, condition.variable (bare name, no braces), condition.operator (equals|not_equals|contains|greater_than|less_than|is_empty|is_not_empty), condition.value. Edges: sourceHandle "true" → true branch; sourceHandle "false" → false branch.
• router — Route to one of several nodes based on a variable's value. Fields: name, router.variable (bare name), router.options (array of {id, value, label}).
• confirmation — Read back collected info and ask caller to confirm. Fields: name, confirmation.summaryTemplate (text with {{variable}}), confirmation.confirmPrompt, confirmation.editPrompt, confirmation.variablesToConfirm (array of bare names), confirmation.allowEdit (bool).
• set_variable — Set a variable programmatically. Fields: name, setVariable.variableKey (bare name), setVariable.valueType (static|template|expression), setVariable.value.
• save_record — Save a structured CRM/PMS record. Fields: name, saveRecord.recordTypeId, saveRecord.recordTypeName, saveRecord.mapping (object: field → "{{variable}}"), saveRecord.status.
• transfer — Transfer the call. Fields: name, transfer.phoneNumber (supports {{variable}}), transfer.preTransferMessage, transfer.warmTransfer (bool).
• end — End the call. Fields: name, closingMessage.
• option_picker — Let the caller pick exactly one item from a list an earlier api_request already produced (e.g. choosing one room rate from several options), and bind chosen fields to variables in one atomic step. Fields: name, optionPicker.sourceVariable (bare name of the array variable), optionPicker.labelPath (dot-path to the item's spoken-label field, e.g. "name"), optionPicker.prompt (what to ask the caller), optionPicker.retryPrompt, optionPicker.maxRetries (int), optionPicker.writes (array of {variableKey (bare name), path (dot-path into the chosen item, e.g. "rate.code")}). Edges: sourceHandle "selected" → after a valid pick; sourceHandle "fallback" → optional, after repeated failed attempts.

VARIABLES: Declared separately. Referenced as {{varName}} in text/template fields, or as bare varName in condition.variable, router.variable, slot.variableKey, setVariable.variableKey, confirmation.variablesToConfirm.
VARIABLE TYPES: text, number, date, phone, email, time, choice.
"""

SYSTEM_PROMPT = f"""You are a Botelier AI Flow Builder. Botelier is a voice AI platform for hotels — flows define what the AI says and does during phone calls with guests.

Help users build and modify voice AI flows. Be concise, practical, and hotel-industry aware.

{NODE_SCHEMA_TEXT}

RESPONSE FORMAT — always return valid JSON with exactly one of these shapes:

For explanations (no canvas changes — use for "what does X do", "why won't this publish", general questions):
{{"type": "explanation", "text": "Your clear explanation here."}}

For adding nodes to the canvas:
{{"type": "patch", "text": "One-sentence summary of what you're adding.", "patch": {{"nodes": [...], "edges": [...], "variables": [...]}}}}

PATCH NODE FORMAT:
{{"id": "n1", "type": "<node_type>", "position": {{"x": 400, "y": 300}}, "data": {{...type-specific fields...}}}}

PATCH EDGE FORMAT:
{{"id": "e1", "source": "n1", "target": "n2"}}
For condition nodes: add "sourceHandle": "true" for the true branch, "sourceHandle": "false" for the false branch.

PATCH VARIABLE FORMAT:
{{"key": "var_name", "type": "text", "description": "What it holds", "required": true}}

POSITIONING: Space nodes ~220px apart vertically. If adding to an existing flow, place new nodes below the last existing node (highest y + 220 per new node). x=400 for the main column.

RULES:
1. Add nodes only — never modify or delete existing ones.
2. Always declare variables referenced by new nodes.
3. Include edges between NEW nodes only. Do not create edges to existing nodes (the user connects those manually).
4. If the flow already has an initial node, don't add another.
5. For gathering multiple fields, prefer collect_form over multiple collect_slots.
6. If the request is ambiguous, pick a reasonable approach and note it in "text".

EXAMPLES:

User: "Add a step to collect guest name and room number"
{{"type":"patch","text":"Adding a form node to collect guest name and room number.","patch":{{"nodes":[{{"id":"n1","type":"collect_form","position":{{"x":400,"y":400}},"data":{{"name":"Guest Details","introMessage":"I'll need a couple of details.","slots":[{{"id":"s1","order":1,"variableKey":"guest_name","prompt":"What's your name?","type":"text","retryPrompt":"Could you repeat that?","maxRetries":3}},{{"id":"s2","order":2,"variableKey":"room_number","prompt":"And your room number?","type":"text","retryPrompt":"Sorry, your room number?","maxRetries":3}}]}}}}],"edges":[],"variables":[{{"key":"guest_name","type":"text","description":"Guest full name","required":true}},{{"key":"room_number","type":"text","description":"Guest room number","required":true}}]}}}}

User: "Add a condition that checks if room_available equals yes, with a message on the true branch"
{{"type":"patch","text":"Adding a condition node and a true-branch message for room availability.","patch":{{"nodes":[{{"id":"n1","type":"condition","position":{{"x":400,"y":400}},"data":{{"name":"Is Room Available","condition":{{"variable":"room_available","operator":"equals","value":"yes"}}}}}},{{"id":"n2","type":"message","position":{{"x":250,"y":620}},"data":{{"name":"Room Available","message":"Great news, a room is available for your dates!","waitForResponse":true}}}}],"edges":[{{"id":"e1","source":"n1","target":"n2","sourceHandle":"true"}}],"variables":[{{"key":"room_available","type":"text","description":"Whether a room is available","required":false}}]}}}}

User: "What does the Router node do?"
{{"type":"explanation","text":"The Router node branches the flow to different paths based on a variable's exact value. You set a variable to route on, then define options (each with a value and label). The flow engine looks at the variable's current value and follows the matching edge. It's useful when a caller might want one of several services — e.g., routing on 'request_type' to Restaurant, Spa, or Housekeeping paths."}}
"""


def _get_flow_tool(db: Session, tool_id: str, account_id: str) -> Tool:
    """Fetch a FLOW tool by ID, scoped through ToolSet.account_id for multi-tenant isolation."""
    tool = (
        db.query(Tool)
        .join(ToolSet, Tool.tool_set_id == ToolSet.id)
        .filter(Tool.id == tool_id, ToolSet.account_id == account_id)
        .first()
    )
    if not tool:
        raise HTTPException(
            status_code=404,
            detail=f"Tool {tool_id} not found for this account",
        )
    if tool.tool_type != DBToolType.FLOW:
        raise HTTPException(
            status_code=422,
            detail=f"Tool {tool_id} is not a flow-type tool",
        )
    return tool


class AIHistoryMessage(BaseModel):
    role: str
    content: str


class AIAssistRequest(BaseModel):
    message: str
    history: list[AIHistoryMessage] = []
    current_flow: dict = {}
    last_validation_errors: list[str] = []


@router.post("/{tool_id}/flow/ai-assist")
async def flow_ai_assist(
    tool_id: str,
    account_id: str,
    body: AIAssistRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI flow builder: accept a natural-language request and return a patch or explanation."""
    # Verify the caller has flow-edit rights on this account, then confirm
    # the tool exists, belongs to the account, and is a FLOW-type tool.
    check_account_permission(user, account_id, "flows.edit", db)
    _get_flow_tool(db, tool_id, account_id)

    if not openai_client:
        raise HTTPException(
            status_code=503,
            detail="AI assistant is not configured (OPENAI_API_KEY missing)",
        )

    flow_ctx = _summarize_flow(body.current_flow)
    system = SYSTEM_PROMPT + (
        f"\n\nCURRENT FLOW:\n{flow_ctx}"
        if flow_ctx
        else "\n\nCurrent flow: empty canvas (no nodes yet)."
    )
    if body.last_validation_errors:
        system += "\n\nLAST VALIDATION ERRORS:\n" + "\n".join(
            f"- {e}" for e in body.last_validation_errors[:20]
        )

    messages: list[dict] = [{"role": "system", "content": system}]
    for msg in body.history[-8:]:
        if msg.role in ("user", "assistant"):
            messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": body.message})

    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
            max_tokens=2500,
            temperature=0.25,
        )
        raw = resp.choices[0].message.content or "{}"
        result: dict = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="AI returned an unparseable response")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI assistant error: {exc}")

    # Sanitize patch before returning to avoid garbage nodes reaching the canvas
    if result.get("type") == "patch" and isinstance(result.get("patch"), dict):
        result["patch"] = _sanitize_patch(result["patch"])

    result.setdefault("text", "")
    return result


def _safe_url(url: str) -> str:
    """Return only scheme+host+path from a URL, stripping userinfo and query-string credentials."""
    if not url:
        return "[url]"
    try:
        p = urlparse(url)
        # Build netloc without userinfo (drop user:password@)
        safe_netloc = p.hostname or ""
        if p.port:
            safe_netloc += f":{p.port}"
        # Drop query string and fragment — both can carry API keys/tokens
        return urlunparse((p.scheme, safe_netloc, p.path, "", "", "")) or "[url]"
    except Exception:
        return "[url]"


def _safe_node_summary(node: dict) -> str:
    """
    Return a one-line structural description of a node with all credential-bearing
    fields (API headers, bodyTemplate, phone numbers, system prompts) omitted.
    Only structural metadata that is safe to share with a third-party LLM is included.
    """
    nid = node.get("id", "?")
    ntype = node.get("type", "?")
    pos = node.get("position") or {}
    y = pos.get("y", "?")
    d = node.get("data") or {}
    name = d.get("name", "unnamed")

    extra = ""
    if ntype == "api_request":
        api = d.get("api") or {}
        # Only expose method + sanitized URL (scheme/host/path only — no userinfo,
        # no query string, no body template, no headers; all can carry credentials)
        extra = f"  method={api.get('method','?')}  url={_safe_url(api.get('url',''))}"
    elif ntype == "condition":
        cond = d.get("condition") or {}
        extra = f"  var={cond.get('variable','?')}  op={cond.get('operator','?')}"
    elif ntype in ("collect_slot",):
        slot = d.get("slot") or {}
        extra = f"  key={slot.get('variableKey','?')}  type={slot.get('type','?')}"
    elif ntype == "collect_form":
        slots = d.get("slots") or []
        keys = [s.get("variableKey", "?") for s in slots[:6]]
        extra = f"  slots=[{', '.join(keys)}]"
    elif ntype == "router":
        router = d.get("router") or {}
        extra = f"  var={router.get('variable','?')}"
    elif ntype == "set_variable":
        sv = d.get("setVariable") or {}
        extra = f"  key={sv.get('variableKey','?')}"
    elif ntype == "confirmation":
        conf = d.get("confirmation") or {}
        vtc = conf.get("variablesToConfirm") or []
        extra = f"  confirms=[{', '.join(str(v) for v in vtc[:6])}]"
    # transfer.phoneNumber, initial.systemPrompt, initial.greeting, message.message,
    # api.headers, api.bodyTemplate — all intentionally omitted.

    return f"  id={nid}  type={ntype}  name=\"{name}\"  y={y}{extra}"


def _summarize_flow(flow: dict) -> str:
    """
    Condense the flow into a safe, compact string for the system prompt context.
    Credential-bearing fields (API headers, body templates, phone numbers,
    system prompts) are explicitly excluded — only structural metadata is included.
    """
    if not flow:
        return ""
    parts: list[str] = []

    variables = flow.get("variables") or []
    if variables:
        var_strs = [
            f"{v.get('key')} ({v.get('type', 'text')})" for v in variables[:25]
        ]
        parts.append("Variables: " + ", ".join(var_strs))

    nodes = flow.get("nodes") or []
    if nodes:
        lines = [_safe_node_summary(n) for n in nodes[:30]]
        parts.append("Nodes:\n" + "\n".join(lines))

    edges = flow.get("edges") or []
    if edges:
        lines = []
        for e in edges[:30]:
            hdl = f"[{e['sourceHandle']}]" if e.get("sourceHandle") else ""
            lines.append(f"  {e.get('source','?')}{hdl} → {e.get('target','?')}")
        parts.append("Edges:\n" + "\n".join(lines))

    return "\n".join(parts)


def _sanitize_patch(patch: dict) -> dict:
    """Validate and clean the AI-generated patch before sending to the frontend."""
    out: dict = {"nodes": [], "edges": [], "variables": []}

    for n in patch.get("nodes") or []:
        if n.get("type") not in VALID_NODE_TYPES:
            continue
        pos = n.get("position") or {}
        out["nodes"].append(
            {
                "id": str(n.get("id") or f"ai_{len(out['nodes'])}"),
                "type": n["type"],
                "position": {
                    "x": int(pos.get("x") or 400),
                    "y": int(pos.get("y") or 400),
                },
                "data": n.get("data") or {"name": "New Node"},
            }
        )

    for e in patch.get("edges") or []:
        if not e.get("source") or not e.get("target"):
            continue
        edge: dict = {
            "id": str(e.get("id") or f"ai_e_{len(out['edges'])}"),
            "source": str(e["source"]),
            "target": str(e["target"]),
        }
        if e.get("sourceHandle"):
            edge["sourceHandle"] = str(e["sourceHandle"])
        if e.get("targetHandle"):
            edge["targetHandle"] = str(e["targetHandle"])
        out["edges"].append(edge)

    for v in patch.get("variables") or []:
        key = str(v.get("key") or "").strip().lower().replace(" ", "_")
        if not key:
            continue
        out["variables"].append(
            {
                "key": key,
                "type": v.get("type") or "text",
                "description": str(v.get("description") or ""),
                "required": bool(v.get("required", False)),
            }
        )

    return out
