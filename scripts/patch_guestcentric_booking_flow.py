"""
One-time patch: rebuild the GuestCentric CRS booking flow config in the DB.

Fixes applied
─────────────
1. check_availability responseMapping
   - rates: $.rates[*].name (wrong — no name field)  →  $.rates[*].rate_plan_name
   - added room_rates: $.room_rates  (full room+rate combinations for downstream)

2. Missing sync_number_of_adults node
   - GuestCentric book_reservation body requires {{number_of_adults}}
   - Flow only collected {{adults}}; this SET_VARIABLE bridges the two

3. Missing collect_rate node
   - Flow went collect_room → confirm_room_rate, skipping rate selection
   - rate_plan_code was never collected from the caller
   - Added node + rewired: collect_room → collect_rate → confirm_room_rate

4. confirm_room_rate queryParamOverrides
   - Added explicit room_type_code/rate_plan_code overrides so the filtered
     re-check always passes the selected codes as query params

5. Date normalization instructions
   - Added YYYY-MM-DD format instructions to collect_checkin / collect_checkout

6. onError messages on all API nodes

Usage
─────
    python scripts/patch_guestcentric_booking_flow.py
"""

import json
import os
import sys
import copy
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "botelier", "backend"))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TOOL_ID = "01ae4110-2916-477b-97d3-5f98e86dd471"


def apply(dry_run: bool = False) -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")

    engine = create_engine(db_url)
    db = sessionmaker(bind=engine)()

    try:
        row = db.execute(
            text("SELECT config FROM tools WHERE id = :id"), {"id": TOOL_ID}
        ).fetchone()
        if not row:
            raise RuntimeError(f"Tool {TOOL_ID} not found")

        config = copy.deepcopy(
            row[0] if isinstance(row[0], dict) else json.loads(row[0])
        )
        nodes = config["nodes"]
        edges = config["edges"]

        # ── 1. check_availability: fix responseMapping ────────────────────────
        ca = next(n for n in nodes if n["id"] == "check_availability")
        ca["data"]["api"]["responseMapping"] = {
            "available_rooms": "$.rooms[*].name",
            "rates":           "$.rates[*].rate_plan_name",
            "room_rates":      "$.room_rates",
        }
        ca["data"]["api"]["autoMappingSource"] = {
            "available_rooms": "$.rooms[*].name",
            "rates":           "$.rates[*].rate_plan_name",
            "room_rates":      "$.room_rates",
        }
        ca["data"]["api"].setdefault(
            "onError",
            "I wasn't able to retrieve available rooms right now. "
            "Would you like to try different check-in or check-out dates?",
        )
        ca["data"]["instructions"] = (
            "After this node completes, present the available room types clearly by name, "
            "then present the available rate plans. Ask the caller to choose one of each. "
            "If no rooms are available or this call fails, apologise and ask if they would "
            "like to try different dates — do NOT transfer the call."
        )
        print("✓ check_availability updated")

        # ── 2. Date instructions ──────────────────────────────────────────────
        for nid, note in [
            ("collect_checkin",
             "Once the caller provides the date, store it in YYYY-MM-DD format "
             "(e.g. 2025-12-15). The date must be today or a future date."),
            ("collect_checkout",
             "Once the caller provides the date, store it in YYYY-MM-DD format "
             "(e.g. 2025-12-18). The date must be after the check-in date."),
        ]:
            n = next((x for x in nodes if x["id"] == nid), None)
            if n:
                n["data"]["slot"]["instructions"] = note
                print(f"✓ {nid} YYYY-MM-DD instructions added")

        # ── 3. onError on remaining API nodes ─────────────────────────────────
        on_errors = {
            "confirm_room_rate":
                "I wasn't able to confirm that room and rate combination. "
                "Please choose a different room type or rate plan.",
            "check_cancellation_policy":
                "I had a technical issue retrieving the cancellation policy. "
                "I will proceed and note the policy should be confirmed.",
            "create_booking":
                "I'm sorry, there was a problem submitting your reservation. "
                "Could you confirm your details are correct and I will try once more?",
        }
        for nid, msg in on_errors.items():
            n = next((x for x in nodes if x["id"] == nid), None)
            if n:
                n["data"]["api"].setdefault("onError", msg)
                print(f"✓ {nid} onError set")

        # ── 4. confirm_room_rate: explicit queryParamOverrides ────────────────
        crm = next((n for n in nodes if n["id"] == "confirm_room_rate"), None)
        if crm:
            crm["data"]["api"]["queryParamOverrides"] = {
                "room_type_code": "{{room_type_code}}",
                "rate_plan_code": "{{rate_plan_code}}",
            }
            print("✓ confirm_room_rate queryParamOverrides set")

        # ── 5. sync_number_of_adults (idempotent) ─────────────────────────────
        existing_ids = {n["id"] for n in nodes}
        if "sync_number_of_adults" not in existing_ids:
            nodes.append({
                "id": "sync_number_of_adults",
                "type": "set_variable",
                "position": {"x": 750, "y": 750},
                "data": {
                    "name": "Sync Adults for Booking",
                    "setVariable": {
                        "variableKey": "number_of_adults",
                        "valueType": "template",
                        "value": "{{adults}}",
                    },
                },
            })
            edges[:] = [
                e for e in edges
                if not (
                    e["source"] == "node_1783660424526_1"
                    and e["target"] == "check_availability"
                )
            ]
            edges.append({"id": "e3b", "source": "node_1783660424526_1",
                          "target": "sync_number_of_adults"})
            edges.append({"id": "e4",  "source": "sync_number_of_adults",
                          "target": "check_availability"})
            print("✓ sync_number_of_adults added + edges rewired")

        # ── 6. collect_rate (idempotent) ──────────────────────────────────────
        existing_ids = {n["id"] for n in nodes}
        if "collect_rate" not in existing_ids:
            nodes.append({
                "id": "collect_rate",
                "type": "collect_slot",
                "position": {"x": 750, "y": 1050},
                "data": {
                    "name": "Rate Plan Selection",
                    "slot": {
                        "variableKey": "rate_plan_code",
                        "prompt": (
                            "And which rate plan would you like? "
                            "The available plans are: {{rates}}. "
                            "I will record the exact rate plan code for your selection."
                        ),
                        "type": "text",
                        "retryPrompt": "Could you repeat which rate plan you'd like?",
                        "maxRetries": 3,
                    },
                },
            })
            edges[:] = [
                e for e in edges
                if not (
                    e["source"] == "collect_room"
                    and e["target"] == "confirm_room_rate"
                )
            ]
            edges.append({"id": "e6",  "source": "collect_room",
                          "target": "collect_rate"})
            edges.append({"id": "e6b", "source": "collect_rate",
                          "target": "confirm_room_rate"})
            print("✓ collect_rate added + edges rewired")

        # ── collect_room / collect_rate prompt cleanup ────────────────────────
        for nid, prompt in [
            ("collect_room",
             "Which room type would you prefer? The available options are: "
             "{{available_rooms}}. I will record the exact room type code for "
             "your selection."),
            ("collect_rate",
             "And which rate plan would you like? The available plans are: "
             "{{rates}}. I will record the exact rate plan code for your selection."),
        ]:
            n = next((x for x in nodes if x["id"] == nid), None)
            if n:
                n["data"]["slot"]["prompt"] = prompt
                print(f"✓ {nid} prompt cleaned up")

        # ── Write back ────────────────────────────────────────────────────────
        config["nodes"] = nodes
        config["edges"] = edges
        config_json = json.dumps(config)

        if dry_run:
            print("\n[DRY RUN] No changes written.")
            return

        db.execute(
            text("UPDATE tools SET config = CAST(:cfg AS json), updated_at = NOW() "
                 "WHERE id = :id"),
            {"cfg": config_json, "id": TOOL_ID},
        )

        latest = db.execute(
            text("SELECT version_number FROM flow_versions WHERE tool_id = :tid "
                 "ORDER BY version_number DESC LIMIT 1"),
            {"tid": TOOL_ID},
        ).fetchone()
        next_v = (latest[0] + 1) if latest else 1

        db.execute(
            text("""
                INSERT INTO flow_versions
                    (id, tool_id, version_number, status, flow_config, created_at, published_at)
                VALUES (:id, :tid, :vnum, 'PUBLISHED', CAST(:cfg AS jsonb), NOW(), NOW())
            """),
            {"id": str(uuid.uuid4()), "tid": TOOL_ID, "vnum": next_v, "cfg": config_json},
        )
        db.commit()
        print(f"\n✅ tools.config updated, flow_versions v{next_v} PUBLISHED created.")

    except Exception as exc:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    apply(dry_run=dry)
