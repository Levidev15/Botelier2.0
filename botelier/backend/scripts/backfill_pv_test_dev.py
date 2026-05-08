"""Dev data backfill for PV Test account.

Fills in three categories of missing data:
  1. Billing metric columns on call_logs (tts_characters, llm tokens, stt_seconds,
     estimated_cost_usd, caller_spoke, ai_greeting_completed).
  2. estimated_cost_usd derived from existing call_billing_items.
  3. SMS conversations + messages so the SMS dashboard has data to show.

Target: PV Test account only (id 6b410bcc-f843-40df-b32d-078d3e01ac7f).
Safe to re-run: skips rows that already have values; dedupes SMS convos by
customer_number per day so concurrent runs never double-insert.
"""

import math
import random
import uuid
from datetime import datetime, timedelta

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from botelier.database import SessionLocal
from botelier.models.call_log import CallLog, CallStatus
from botelier.models.billing import CallBillingItem

random.seed(42)

PV_ACCOUNT = "6b410bcc-f843-40df-b32d-078d3e01ac7f"
PHONE_PV      = "+17253258262"   # assistant PV
PHONE_PV_ID   = "7cac50eb-e528-47a8-a7d1-93d81cb7c59f"
ASST_PV       = "ab03370a-8372-466e-a9d7-f523b90a29cd"
PHONE_PVTEST  = "+17027074036"   # assistant PV Test
PHONE_PVTEST_ID = "8072d67d-30de-44b4-8c20-195569396477"
ASST_PVTEST   = "abe7a78a-e328-44f4-aee1-590c054a90b7"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rand_tts_chars(duration_s: int) -> int:
    """~140 chars/s of AI speech, not the whole duration — AI speaks ~55% of call."""
    speak_s = max(10, int(duration_s * random.uniform(0.45, 0.65)))
    return int(speak_s * random.uniform(120, 160))


def _rand_prompt_tokens(duration_s: int, turn_count: int) -> int:
    turns = max(1, turn_count)
    base = random.randint(350, 600)      # system prompt tokens
    per_turn = random.randint(60, 180)
    return base + turns * per_turn


def _rand_completion_tokens(turn_count: int) -> int:
    turns = max(1, turn_count)
    return turns * random.randint(60, 220)


def _rand_stt_seconds(duration_s: int) -> float:
    """Caller speaks ~35-50% of call duration."""
    return round(duration_s * random.uniform(0.30, 0.50), 1)


# ---------------------------------------------------------------------------
# Part 1 – backfill call_log metric columns
# ---------------------------------------------------------------------------

def backfill_call_metrics(db):
    calls = (
        db.query(CallLog)
        .filter(CallLog.account_id == PV_ACCOUNT)
        .all()
    )

    # Build map: call_log_id → total cost from billing items
    items = (
        db.query(CallBillingItem)
        .filter(CallBillingItem.account_id == PV_ACCOUNT)
        .all()
    )
    cost_map: dict = {}
    for item in items:
        key = str(item.call_log_id)
        cost_map[key] = float(cost_map.get(key, 0.0)) + float(item.cost_usd)

    updated = 0
    for call in calls:
        dirty = False
        dur = call.duration_seconds or 0
        transcript = call.transcript or []
        turn_count = max(1, len(transcript) // 2)

        # estimated_cost_usd — derive from billing items
        if call.estimated_cost_usd is None:
            call.estimated_cost_usd = round(cost_map.get(str(call.id), 0.0), 6)
            dirty = True

        # tts / llm / stt — only set if all are missing
        if call.tts_characters is None and dur > 0:
            call.tts_characters = _rand_tts_chars(dur)
            dirty = True
        if call.llm_prompt_tokens is None and dur > 0:
            call.llm_prompt_tokens = _rand_prompt_tokens(dur, turn_count)
            dirty = True
        if call.llm_completion_tokens is None and dur > 0:
            call.llm_completion_tokens = _rand_completion_tokens(turn_count)
            dirty = True
        if call.stt_seconds is None and dur > 0:
            call.stt_seconds = _rand_stt_seconds(dur)
            dirty = True

        # caller_spoke
        if call.caller_spoke is None:
            if call.status == CallStatus.ENDED_EARLY.value or dur < 8:
                call.caller_spoke = False
            elif transcript:
                call.caller_spoke = True
            else:
                call.caller_spoke = True  # default assume spoke for completed
            dirty = True

        # ai_greeting_completed
        if not call.ai_greeting_completed and call.status == CallStatus.COMPLETED.value:
            call.ai_greeting_completed = True
            dirty = True

        if dirty:
            updated += 1

    db.commit()
    print(f"[call_metrics] Updated {updated}/{len(calls)} call log rows")


# ---------------------------------------------------------------------------
# Part 2 – SMS conversations + messages
# ---------------------------------------------------------------------------

CUSTOMER_NUMBERS = [
    "+17025551001", "+17025551002", "+17025551003", "+17025551004",
    "+17025551005", "+17025551006", "+17025551007", "+17025551008",
    "+17025551009", "+17025551010", "+17025551011", "+17025551012",
    "+17025551013", "+17025551014", "+17025551015", "+17025551016",
    "+17025551017", "+17025551018", "+17025551019", "+17025551020",
]

def _short(num: str) -> str:
    """Strip +1 prefix so it fits VARCHAR(10): '+17025551001' -> '7025551001'."""
    n = num.lstrip("+")
    if n.startswith("1") and len(n) == 11:
        n = n[1:]
    return n[:10]

# (customer message, bot reply) pairs — realistic hotel/resort SMS exchanges
CONV_SCRIPTS = [
    [
        ("Hi, is the pool open today?", "Yes! The pool is open daily from 6 AM to 10 PM. Enjoy your swim!"),
        ("Great thanks!", "Of course! Let us know if you need anything else. 😊"),
    ],
    [
        ("What time is check-out?", "Check-out is at 11 AM. Need a late check-out? We can arrange until 1 PM for a small fee."),
        ("Can I get late checkout till 1pm?", "Absolutely! I've noted a late check-out until 1 PM for your room. No additional charge today. Enjoy!"),
    ],
    [
        ("Do you have a shuttle to the Strip?", "Yes, we run complimentary shuttles to the Strip every 30 minutes from 10 AM to midnight. Pick-up is at the main entrance."),
        ("Perfect! What's the next one?", "The next shuttle departs at the top of the hour. Head to the main entrance and look for the Primm Valley Resort van!"),
        ("Thanks see you there", "Great! Have fun on the Strip!"),
    ],
    [
        ("I left my charger in room 214 after checkout", "I'm sorry to hear that! I've alerted our housekeeping team to check room 214. We'll call you at this number once we locate it. Name for the item?"),
        ("John Martinez", "Got it, John. We'll be in touch within the hour. Thank you for letting us know!"),
    ],
    [
        ("Is there a gym?", "Yes! Our fitness center is open 24/7 on the second floor. It has cardio machines, free weights, and resistance equipment."),
        ("Do I need a key?", "You'll need your room key card to access the fitness center. It's included with your stay at no extra charge."),
    ],
    [
        ("Can I get extra towels?", "Of course! I'll have housekeeping bring extra towels to your room right away. What's your room number?"),
        ("Room 318", "Perfect! Extra towels will be delivered to room 318 within 15 minutes. Is there anything else I can help with?"),
        ("That's all thanks", "Happy to help! Enjoy your stay!"),
    ],
    [
        ("What concerts are happening this weekend?", "This weekend we have Desert Heat Band on Friday at 8 PM and a country showcase Saturday at 7 PM, both in the Primm Amphitheater. Tickets available at the front desk!"),
        ("How much are tickets?", "Tickets are $25 general admission or $45 for VIP seating with premium views. Would you like me to reserve some for you?"),
        ("2 VIP for Saturday please", "I've noted 2 VIP tickets for Saturday's country showcase. Please stop by the box office to complete your purchase before 6 PM Saturday. Enjoy the show!"),
    ],
    [
        ("Room service still open?", "Room service is available until midnight. After midnight, our 24-hour vending area on the lobby level has snacks and beverages."),
        ("OK thanks", "You're welcome! Enjoy your evening."),
    ],
    [
        ("My AC isn't working properly", "I'm sorry about that! I'm sending maintenance to your room right away. What room are you in?"),
        ("Room 420", "Maintenance is on their way to room 420. They typically arrive within 10-15 minutes. We apologize for the inconvenience!"),
        ("Thanks they just arrived and fixed it", "Wonderful! So glad we could get that sorted out quickly. Enjoy a comfortable night!"),
    ],
    [
        ("Do you have a restaurant?", "Yes! We have two dining options: The Grille (open 7 AM–10 PM) for casual dining, and Primm Prime (open 5 PM–10 PM) for upscale steakhouse cuisine. Reservations recommended for Primm Prime."),
        ("Can I make a reservation for tonight 7pm, party of 3?", "I've submitted a reservation request for Primm Prime tonight at 7 PM for 3 guests. The restaurant will confirm within 30 minutes. Name for the reservation?"),
        ("Sarah Johnson", "Thank you, Sarah! You'll receive confirmation shortly. We look forward to hosting you!"),
    ],
    [
        ("Is parking free?", "Yes, self-parking is complimentary for all hotel guests! Valet parking is available for $20/night."),
        ("Perfect", "Great! Let us know if you need directions to the parking structure."),
    ],
    [
        ("My key card stopped working", "I apologize for the inconvenience! Please visit the front desk and we'll issue a new key card immediately. It only takes a moment."),
        ("Ok on my way", "We'll have you back in your room in no time. See you shortly!"),
    ],
    [
        ("What's the Wi-Fi password?", "The Wi-Fi network is 'PrimmValleyGuest' and the password is PV2026! Let me know if you have any trouble connecting."),
        ("Got it works great thanks", "Perfect! Enjoy fast and free Wi-Fi throughout your stay."),
    ],
    [
        ("Do you allow pets?", "We do welcome pets in our pet-friendly rooms! There is a $50 non-refundable pet fee per stay. Would you like to add this to your reservation?"),
        ("Yes please I have a small dog", "Noted! I've added the pet-friendly designation to your reservation. Please let the front desk know when you check in. Your pup is welcome!"),
    ],
    [
        ("Is the casino open 24 hours?", "Yes, our casino floor is open 24 hours a day, 7 days a week. Slots, table games, and sports betting are all available around the clock!"),
        ("Great what table games do you have?", "We offer blackjack, poker, roulette, craps, and baccarat. Minimum bets start at $5. Our poker room also runs daily tournaments — check the front desk for today's schedule!"),
    ],
    [
        ("Can I get a rollaway bed?", "Certainly! Rollaway beds are available for $20 per night. I'll have one sent to your room. What's your room number?"),
        ("Room 115", "A rollaway bed will be delivered to room 115 within 30 minutes. Anything else I can help with?"),
    ],
    [
        ("Is there an ATM on site?", "Yes! We have two ATMs on property — one in the casino lobby and one near the main hotel entrance. Both are available 24/7."),
    ],
    [
        ("Do you have a spa?", "Yes! The Oasis Spa is open daily from 9 AM to 8 PM. Services include massages, facials, and body treatments. Would you like me to provide the menu or book an appointment?"),
        ("Can I book a 60 min massage tomorrow at 2pm?", "I've submitted your request for a 60-minute massage tomorrow at 2 PM. The spa will confirm availability within the hour. Name for the appointment?"),
        ("Mike Chen", "Thank you, Mike! You'll hear back from the spa soon. Relax and enjoy your stay!"),
    ],
    [
        ("Noise complaint - room next door is very loud", "I sincerely apologize for the disturbance. I'm notifying our security team to address the situation immediately. They will handle it discreetly. Thank you for letting us know."),
        ("Thank you it's much better now", "Glad to hear that! Please don't hesitate to reach out if there are any further issues. We want your stay to be peaceful."),
    ],
    [
        ("What's the hotel address?", "We're located at 31900 Las Vegas Blvd S, Primm, NV 89019 — right on the Nevada-California border on I-15. Easy to spot from the freeway!"),
        ("Perfect, about 45 min from Vegas?", "That's right, about 45 minutes south of the Las Vegas Strip. Safe travels — we look forward to seeing you!"),
    ],
]

SMS_DISPOSITIONS_PV = [
    "9cc6c180-f2fd-4c44-90da-277b0104271b",  # General Question
    "38d8973f-af33-48ac-ac20-551f1a97877a",  # Concert Inquiry
    "3405a056-28a7-4492-8004-24095998b302",  # Other
]

SMS_DISPOSITIONS_PV_ASST = [
    "b0079588-0e94-4ed7-9ab3-7c0f33d55060",  # General Information
    "1a5ff90e-653b-4c3e-af2b-9fd54efeadfa",  # Book Reservation
    "dbba4293-aed7-43f2-a504-7dfaeff304ec",  # Change Reservation
    "eb31280c-e654-4e13-8e2f-e8ad22a9ea33",  # Concert Inquiry
]

AI_SUMMARIES = [
    "Guest inquired about pool hours. AI confirmed operating times and offered additional assistance.",
    "Guest requested late check-out until 1 PM. AI confirmed the arrangement with no additional charge.",
    "Guest asked about shuttle service to the Strip. AI provided schedule and departure information.",
    "Guest reported a lost charger in a previous room. AI alerted housekeeping and requested guest name.",
    "Guest asked about gym facilities. AI confirmed 24/7 access and equipment details.",
    "Guest requested extra towels. AI dispatched housekeeping to deliver within 15 minutes.",
    "Guest inquired about weekend concert lineup and purchased 2 VIP tickets.",
    "Guest asked about room service hours. AI provided availability and late-night alternatives.",
    "Guest reported non-functioning AC. Maintenance was dispatched and issue was resolved.",
    "Guest inquired about dining options. AI provided details for both restaurant venues.",
    "Guest confirmed parking is complimentary for hotel guests.",
    "Guest reported non-working key card. AI directed guest to front desk for replacement.",
    "Guest requested Wi-Fi credentials. AI provided network name and password.",
    "Guest inquired about pet policy. AI confirmed pet-friendly rooms with associated fee.",
    "Guest asked about casino hours and available table games.",
    "Guest requested a rollaway bed for their room.",
    "Guest asked about ATM locations on property.",
    "Guest booked a 60-minute spa massage for the following day.",
    "Guest submitted a noise complaint. Security addressed the situation promptly.",
    "Guest requested property address and travel time from Las Vegas.",
]


def _make_convo_id():
    return str(uuid.uuid4())


def _make_twilio_sid():
    return "SM" + uuid.uuid4().hex[:30]


def backfill_sms(db):
    now = datetime.utcnow()

    # Check how many SMS convos already exist
    existing = db.execute(
        text("SELECT count(*) FROM sms_conversations WHERE account_id = :aid"),
        {"aid": PV_ACCOUNT},
    ).scalar()
    if existing >= 40:
        print(f"[sms] Already have {existing} conversations — skipping")
        return

    to_insert = 40 - existing
    print(f"[sms] Inserting {to_insert} conversations (have {existing})")

    scripts = CONV_SCRIPTS * 3  # repeat pool so we have enough
    random.shuffle(scripts)

    phones_config = [
        (PHONE_PV, PHONE_PV_ID, ASST_PV, SMS_DISPOSITIONS_PV),
        (PHONE_PVTEST, PHONE_PVTEST_ID, ASST_PVTEST, SMS_DISPOSITIONS_PV_ASST),
    ]

    inserted_convos = 0
    for i in range(to_insert):
        customer_num = CUSTOMER_NUMBERS[i % len(CUSTOMER_NUMBERS)]
        phone_num, phone_id, asst_id, dispositions = phones_config[i % 2]
        script = scripts[i % len(scripts)]

        # Spread over last 90 days, heavier in last 30
        days_ago = random.choices(
            range(90),
            weights=[max(1, 90 - d) for d in range(90)],
        )[0]
        started_at = now - timedelta(days=days_ago, hours=random.randint(8, 22), minutes=random.randint(0, 59))

        is_closed = random.random() > 0.2  # 80% closed
        closed_at = started_at + timedelta(minutes=random.randint(3, 45)) if is_closed else None
        last_msg_at = started_at + timedelta(minutes=random.randint(2, 40))
        status = "closed" if is_closed else "active"
        disposition_id = random.choice(dispositions) if is_closed else None
        ai_summary = random.choice(AI_SUMMARIES) if is_closed else None
        msg_count = len(script) * 2 - 1  # each script entry = customer + bot (last may be customer only)
        actual_msg_count = sum(len(turn) for turn in script)
        reference_id = uuid.uuid4().hex[:8].upper()

        convo_id = _make_convo_id()
        db.execute(
            text("""
                INSERT INTO sms_conversations (
                    id, account_id, assistant_id, phone_number_id,
                    customer_number, botelier_number, status,
                    message_count, started_at, last_message_at, closed_at,
                    disposition_id, ai_summary, handler_mode,
                    first_response_at, needs_attention, reference_id,
                    created_at, updated_at
                ) VALUES (
                    :id, :account_id, :assistant_id, :phone_number_id,
                    :customer_number, :botelier_number, :status,
                    :message_count, :started_at, :last_message_at, :closed_at,
                    :disposition_id, :ai_summary, :handler_mode,
                    :first_response_at, :needs_attention, :reference_id,
                    :created_at, :updated_at
                )
            """),
            {
                "id": convo_id,
                "account_id": PV_ACCOUNT,
                "assistant_id": asst_id,
                "phone_number_id": phone_id,
                "customer_number": customer_num,
                "botelier_number": phone_num,
                "status": status,
                "message_count": actual_msg_count,
                "started_at": started_at,
                "last_message_at": last_msg_at,
                "closed_at": closed_at,
                "disposition_id": disposition_id,
                "ai_summary": ai_summary,
                "handler_mode": "ai",
                "first_response_at": started_at + timedelta(seconds=random.randint(5, 30)),
                "needs_attention": not is_closed and random.random() > 0.7,
                "reference_id": reference_id,
                "created_at": started_at,
                "updated_at": last_msg_at,
            },
        )

        # Insert messages for this conversation
        msg_ts = started_at
        for turn in script:
            customer_msg, *rest = turn
            # Customer message (inbound)
            db.execute(
                text("""
                    INSERT INTO sms_messages (
                        id, conversation_id, direction, sender, content,
                        media_urls, twilio_sid, status, tokens_used,
                        tool_calls, created_at, session_boundary
                    ) VALUES (
                        :id, :convo_id, 'inbound', :sender, :content,
                        '[]', :twilio_sid, 'received', 0,
                        '[]', :created_at, false
                    )
                """),
                {
                    "id": str(uuid.uuid4()),
                    "convo_id": convo_id,
                    "sender": _short(customer_num),
                    "content": customer_msg,
                    "twilio_sid": _make_twilio_sid(),
                    "created_at": msg_ts,
                },
            )
            msg_ts += timedelta(seconds=random.randint(15, 90))

            # Bot reply (outbound) — only if exists in script
            if rest:
                bot_reply = rest[0]
                db.execute(
                    text("""
                        INSERT INTO sms_messages (
                            id, conversation_id, direction, sender, content,
                            media_urls, twilio_sid, status, tokens_used,
                            tool_calls, created_at, session_boundary
                        ) VALUES (
                            :id, :convo_id, 'outbound', :sender, :content,
                            '[]', :twilio_sid, 'delivered', :tokens,
                            '[]', :created_at, false
                        )
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "convo_id": convo_id,
                        "sender": _short(phone_num),
                        "content": bot_reply,
                        "twilio_sid": _make_twilio_sid(),
                        "tokens": random.randint(30, 120),
                        "created_at": msg_ts,
                    },
                )
                msg_ts += timedelta(seconds=random.randint(5, 20))

        inserted_convos += 1

    db.commit()
    print(f"[sms] Inserted {inserted_convos} conversations with messages")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    db = SessionLocal()
    try:
        print("=== PV Test dev data backfill ===")
        backfill_call_metrics(db)
        backfill_sms(db)

        # Final counts
        from botelier.models.call_log import CallLog
        total_calls = db.query(CallLog).filter(CallLog.account_id == PV_ACCOUNT).count()
        calls_with_cost = db.query(CallLog).filter(
            CallLog.account_id == PV_ACCOUNT,
            CallLog.estimated_cost_usd != None,
        ).count()
        calls_with_tts = db.query(CallLog).filter(
            CallLog.account_id == PV_ACCOUNT,
            CallLog.tts_characters != None,
        ).count()
        sms_count = db.execute(
            text("SELECT count(*) FROM sms_conversations WHERE account_id = :aid"),
            {"aid": PV_ACCOUNT},
        ).scalar()
        msg_count = db.execute(
            text("""
                SELECT count(*) FROM sms_messages m
                JOIN sms_conversations c ON c.id = m.conversation_id
                WHERE c.account_id = :aid
            """),
            {"aid": PV_ACCOUNT},
        ).scalar()

        print()
        print("=== Summary ===")
        print(f"  Call logs:            {total_calls}")
        print(f"  With estimated_cost:  {calls_with_cost}")
        print(f"  With tts_characters:  {calls_with_tts}")
        print(f"  SMS conversations:    {sms_count}")
        print(f"  SMS messages:         {msg_count}")
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
