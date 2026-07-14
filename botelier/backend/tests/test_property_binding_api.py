"""Per-property binding API tests (Task #327 follow-through).

The isolation *enforcement* is covered by ``test_property_isolation.py``. These
tests cover the operator-facing side the reviewer flagged as missing: there must
be a real API path to actually *assign* ``property_id`` to a phone number, an
assistant, and an integration connection — and those bindings must (a) reject
cross-account/cross-property assignment and (b) actually drive channel behavior
(session property resolution + fail-closed integration scoping).

These are DB-backed (like ``test_call_logs_export_tz.py``): a throwaway account
is created, every row is tagged with its account_id, and teardown deletes
unconditionally so the suite runs against the live dev DB without touching real
data. Permission checks are bypassed (they are exercised elsewhere); the point
here is the binding + validation logic.
"""

import os
import uuid
from unittest.mock import MagicMock, patch

import pytest

if not os.environ.get("DATABASE_URL"):
    raise RuntimeError(
        "test_property_binding_api requires DATABASE_URL to be set. "
        "These tests guard the per-property binding APIs and must not be "
        "silently skipped — point DATABASE_URL at a test or dev database."
    )

from fastapi import HTTPException

from botelier.api import assistants as assistants_api
from botelier.api import integrations as integrations_api
from botelier.api import phone_numbers as phone_numbers_api
from botelier.database import SessionLocal
from botelier.models.account import Account, AccountStatus, SubscriptionTier
from botelier.models.assistant import Assistant
from botelier.models.integration import (
    AccountIntegration,
    IntegrationStatus,
    IntegrationType,
)
from botelier.models.phone_number import PhoneNumber
from botelier.models.property import Property
from botelier.services.integration_client import IntegrationClient
from botelier.services.property_scope import (
    property_belongs_to_account,
    resolve_session_property_id,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_account(db, tag) -> Account:
    suffix = uuid.uuid4().hex[:12]
    acct = Account(
        name=f"{tag}-{suffix}",
        slug=f"{tag}-{suffix}",
        email=f"{tag}-{suffix}@example.invalid",
        status=AccountStatus.ACTIVE,
        subscription_tier=SubscriptionTier.FREE,
    )
    db.add(acct)
    db.flush()
    return acct


def _make_property(db, account_id, name) -> Property:
    prop = Property(account_id=account_id, name=name)
    db.add(prop)
    db.flush()
    return prop


@pytest.fixture()
def env():
    """A main account with two properties + a separate account with its own."""
    db = SessionLocal()
    main = _make_account(db, "bind-main")
    other = _make_account(db, "bind-other")
    prop_a = _make_property(db, main.id, "Hotel A")
    prop_b = _make_property(db, main.id, "Hotel B")
    other_prop = _make_property(db, other.id, "Other Hotel")

    itype = IntegrationType(
        slug=f"bind-test-{uuid.uuid4().hex[:8]}",
        name="Binding Test Integration",
        provider="test",
        auth_type="none",
    )
    db.add(itype)
    db.flush()
    db.commit()

    ns = MagicMock()
    ns.db = db
    ns.main_id = str(main.id)
    ns.other_id = str(other.id)
    ns.prop_a = str(prop_a.id)
    ns.prop_b = str(prop_b.id)
    ns.other_prop = str(other_prop.id)
    ns.itype_id = str(itype.id)
    ns.user = MagicMock()

    try:
        with (
            patch.object(assistants_api, "check_account_permission"),
            patch.object(phone_numbers_api, "check_account_permission"),
            patch.object(integrations_api, "_assert_account_access"),
        ):
            yield ns
    finally:
        for model in (AccountIntegration, PhoneNumber, Assistant):
            db.query(model).filter(
                model.account_id.in_([main.id, other.id])
            ).delete(synchronize_session=False)
        db.query(Property).filter(
            Property.account_id.in_([main.id, other.id])
        ).delete(synchronize_session=False)
        db.query(IntegrationType).filter(IntegrationType.id == itype.id).delete()
        db.query(Account).filter(Account.id.in_([main.id, other.id])).delete(
            synchronize_session=False
        )
        db.commit()
        db.close()


def _phone(db, account_id, number) -> PhoneNumber:
    ph = PhoneNumber(
        account_id=account_id,
        phone_number=number,
        country_code="US",
        twilio_sid=f"PN{uuid.uuid4().hex}",
    )
    db.add(ph)
    db.commit()
    db.refresh(ph)
    return ph


def _integration(db, account_id, itype_id) -> AccountIntegration:
    integ = AccountIntegration(
        account_id=account_id,
        integration_type_id=itype_id,
        connection_name="conn",
        status=IntegrationStatus.CONNECTED,
    )
    db.add(integ)
    db.commit()
    db.refresh(integ)
    return integ


# ── Assistant binding ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_assistant_binds_property(env):
    data = assistants_api.AssistantCreate(
        account_id=env.main_id, property_id=env.prop_a, name="A1"
    )
    result = await assistants_api.create_assistant(data=data, db=env.db, user=env.user)
    assert result["property_id"] == env.prop_a


@pytest.mark.asyncio
async def test_create_assistant_rejects_cross_account_property(env):
    data = assistants_api.AssistantCreate(
        account_id=env.main_id, property_id=env.other_prop, name="A2"
    )
    with pytest.raises(HTTPException) as exc:
        await assistants_api.create_assistant(data=data, db=env.db, user=env.user)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_update_assistant_sets_and_clears_property(env):
    created = await assistants_api.create_assistant(
        data=assistants_api.AssistantCreate(account_id=env.main_id, name="A3"),
        db=env.db,
        user=env.user,
    )
    aid = created["id"]

    set_b = await assistants_api.update_assistant(
        assistant_id=aid,
        data=assistants_api.AssistantUpdate(property_id=env.prop_b),
        db=env.db,
        user=env.user,
    )
    assert set_b["property_id"] == env.prop_b

    cleared = await assistants_api.update_assistant(
        assistant_id=aid,
        data=assistants_api.AssistantUpdate(property_id=None),
        db=env.db,
        user=env.user,
    )
    assert cleared["property_id"] is None


@pytest.mark.asyncio
async def test_update_assistant_rejects_cross_account_property(env):
    created = await assistants_api.create_assistant(
        data=assistants_api.AssistantCreate(account_id=env.main_id, name="A4"),
        db=env.db,
        user=env.user,
    )
    with pytest.raises(HTTPException) as exc:
        await assistants_api.update_assistant(
            assistant_id=created["id"],
            data=assistants_api.AssistantUpdate(property_id=env.other_prop),
            db=env.db,
            user=env.user,
        )
    assert exc.value.status_code == 400


# ── Phone-number binding ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_phone_property_sets_and_clears(env):
    ph = _phone(env.db, env.main_id, f"+1555{uuid.uuid4().int % 10000000:07d}")

    bound = await phone_numbers_api.assign_to_property(
        phone_number_id=str(ph.id),
        request=phone_numbers_api.AssignPropertyRequest(property_id=env.prop_a),
        db=env.db,
        user=env.user,
    )
    assert bound["property_id"] == env.prop_a

    cleared = await phone_numbers_api.assign_to_property(
        phone_number_id=str(ph.id),
        request=phone_numbers_api.AssignPropertyRequest(property_id=None),
        db=env.db,
        user=env.user,
    )
    assert cleared["property_id"] is None


@pytest.mark.asyncio
async def test_assign_phone_property_rejects_cross_account(env):
    ph = _phone(env.db, env.main_id, f"+1555{uuid.uuid4().int % 10000000:07d}")
    with pytest.raises(HTTPException) as exc:
        await phone_numbers_api.assign_to_property(
            phone_number_id=str(ph.id),
            request=phone_numbers_api.AssignPropertyRequest(property_id=env.other_prop),
            db=env.db,
            user=env.user,
        )
    assert exc.value.status_code == 400


# ── Integration binding ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_integration_rejects_cross_account_property(env):
    """Cross-account property is rejected before any credential/auth work."""
    with pytest.raises(HTTPException) as exc:
        await integrations_api.connect_integration(
            account_id=env.main_id,
            request=integrations_api.ConnectIntegrationRequest(
                integration_type_id=env.itype_id,
                credentials={},
                property_id=env.other_prop,
            ),
            current_user=env.user,
            db=env.db,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_update_integration_property_sets_and_rejects_cross_account(env):
    integ = _integration(env.db, env.main_id, env.itype_id)

    bound = await integrations_api.update_integration_property(
        account_id=env.main_id,
        integration_id=str(integ.id),
        request=integrations_api.UpdateIntegrationPropertyRequest(property_id=env.prop_a),
        current_user=env.user,
        db=env.db,
    )
    assert bound.property_id == env.prop_a

    with pytest.raises(HTTPException) as exc:
        await integrations_api.update_integration_property(
            account_id=env.main_id,
            integration_id=str(integ.id),
            request=integrations_api.UpdateIntegrationPropertyRequest(
                property_id=env.other_prop
            ),
            current_user=env.user,
            db=env.db,
        )
    assert exc.value.status_code == 400


# ── property_belongs_to_account helper ────────────────────────────────────────


def test_property_belongs_to_account_helper(env):
    assert property_belongs_to_account(env.db, env.main_id, env.prop_a) is True
    # A property from another account must never validate for this account.
    assert property_belongs_to_account(env.db, env.main_id, env.other_prop) is False
    # A nonexistent property id must fail closed.
    assert (
        property_belongs_to_account(env.db, env.main_id, str(uuid.uuid4())) is False
    )


# ── End-to-end: a configured binding drives channel behavior ──────────────────


@pytest.mark.asyncio
async def test_configured_binding_drives_session_and_integration_scope(env):
    """Bind via API -> resolve at session start -> fail-closed at runtime.

    Proves the binding is not cosmetic: the dialed number's property wins
    resolution, and IntegrationClient then refuses another property's data.
    """
    number = f"+1555{uuid.uuid4().int % 10000000:07d}"
    ph = _phone(env.db, env.main_id, number)

    # Bind the number to Hotel A and an assistant to Hotel B via the real APIs.
    await phone_numbers_api.assign_to_property(
        phone_number_id=str(ph.id),
        request=phone_numbers_api.AssignPropertyRequest(property_id=env.prop_a),
        db=env.db,
        user=env.user,
    )
    created = await assistants_api.create_assistant(
        data=assistants_api.AssistantCreate(
            account_id=env.main_id, property_id=env.prop_b, name="voice"
        ),
        db=env.db,
        user=env.user,
    )
    assistant = env.db.query(Assistant).filter(Assistant.id == created["id"]).first()

    # Dialed-number property wins over the assistant's property.
    resolved = resolve_session_property_id(number, assistant, env.db)
    assert resolved == env.prop_a

    # That resolved property now gates integration access, fail-closed.
    client = IntegrationClient(
        account_id=env.main_id, db=MagicMock(), property_id=resolved
    )
    allowed_same = MagicMock(property_id=env.prop_a)
    allowed_global = MagicMock(property_id=None)
    denied_other = MagicMock(property_id=env.prop_b)
    assert client._is_property_allowed(allowed_same) is True
    assert client._is_property_allowed(allowed_global) is True
    assert client._is_property_allowed(denied_other) is False
