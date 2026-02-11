import base64
import httpx
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger
from sqlalchemy.orm import Session

from botelier.models.integration import AccountIntegration, IntegrationType, IntegrationStatus
from botelier.models.queue_report import QueuePerformanceReport


ZOOM_TOKEN_URL = "https://zoom.us/oauth/token"
ZOOM_API_BASE = "https://api.zoom.us/v2"


async def _get_zoom_access_token(connection: AccountIntegration, db: Session) -> Optional[str]:
    if connection.get_access_token() and not connection.is_token_expired():
        return connection.get_access_token()

    creds = connection.get_credentials()
    client_id = creds.get("client_id", "")
    client_secret = creds.get("client_secret", "")
    account_id = creds.get("account_id", "")

    if not all([client_id, client_secret, account_id]):
        logger.error("Missing Zoom credentials")
        return None

    auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            ZOOM_TOKEN_URL,
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "account_credentials",
                "account_id": account_id,
            },
        )

        if resp.status_code != 200:
            logger.error(f"Zoom token error: {resp.status_code} - {resp.text}")
            connection.status = IntegrationStatus.ERROR
            connection.last_error = f"Token error: {resp.status_code}"
            db.commit()
            return None

        token_data = resp.json()
        access_token = token_data.get("access_token", "")
        expires_in = token_data.get("expires_in", 3600)

        connection.set_access_token(access_token)
        connection.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 60)
        connection.status = IntegrationStatus.CONNECTED
        connection.last_error = None
        db.commit()

        return access_token


async def _zoom_api_get(token: str, path: str, params: dict = None) -> Optional[dict]:
    url = f"{ZOOM_API_BASE}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        if resp.status_code == 200:
            return resp.json()
        logger.error(f"Zoom API error: {resp.status_code} - {resp.text[:200]}")
        return None


async def fetch_queue_list(connection: AccountIntegration, db: Session) -> list[dict]:
    token = await _get_zoom_access_token(connection, db)
    if not token:
        return []

    data = await _zoom_api_get(token, "/contact_center/queues")
    if not data:
        return []
    return data.get("queues", [])


async def fetch_queue_performance(
    connection: AccountIntegration,
    db: Session,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
) -> list[QueuePerformanceReport]:
    token = await _get_zoom_access_token(connection, db)
    if not token:
        return []

    if not to_dt:
        to_dt = datetime.utcnow()
    if not from_dt:
        from_dt = to_dt - timedelta(hours=1)

    from_str = from_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    to_str = to_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    queues_data = await _zoom_api_get(token, "/contact_center/queues")
    if not queues_data:
        return []

    queues = queues_data.get("queues", [])
    reports = []

    for q in queues:
        queue_id = q.get("queue_id") or q.get("id", "")
        queue_name = q.get("name", "Unknown Queue")

        metrics = await _zoom_api_get(
            token,
            f"/contact_center/analytics/historical/queues/{queue_id}/metrics",
            params={"from": from_str, "to": to_str},
        )

        if not metrics:
            continue

        m = metrics if isinstance(metrics, dict) else {}

        total = _safe_int(m.get("total_calls", m.get("total_engagements", 0)))
        answered = _safe_int(m.get("calls_answered", m.get("answered", 0)))
        abandoned = _safe_int(m.get("calls_abandoned", m.get("abandoned", 0)))
        transferred = _safe_int(m.get("total_transferred", m.get("transferred", 0)))
        overflowed = _safe_int(m.get("overflowed", 0))

        avg_wait = _safe_float(m.get("avg_wait_time", m.get("average_wait_time", 0)))
        max_wait = _safe_float(m.get("max_wait_time", m.get("maximum_wait_time", 0)))
        avg_handle = _safe_float(m.get("avg_handle_time", m.get("average_handle_time", 0)))
        avg_talk = _safe_float(m.get("avg_talk_time", m.get("average_talk_time", 0)))
        avg_hold = _safe_float(m.get("avg_hold_time", m.get("average_hold_time", 0)))
        avg_wrap = _safe_float(m.get("avg_wrap_time", m.get("average_wrap_up_time", 0)))

        sl = _safe_float(m.get("service_level", 0))
        abandon_rate = (abandoned / total * 100) if total > 0 else 0.0
        answer_rate = (answered / total * 100) if total > 0 else 0.0

        report = QueuePerformanceReport(
            account_id=connection.account_id,
            integration_connection_id=connection.id,
            queue_id=queue_id,
            queue_name=queue_name,
            report_period_start=from_dt,
            report_period_end=to_dt,
            total_calls=total,
            calls_answered=answered,
            calls_abandoned=abandoned,
            calls_transferred=transferred,
            calls_overflowed=overflowed,
            avg_wait_time_seconds=avg_wait,
            max_wait_time_seconds=max_wait,
            avg_handle_time_seconds=avg_handle,
            avg_talk_time_seconds=avg_talk,
            avg_hold_time_seconds=avg_hold,
            avg_wrap_time_seconds=avg_wrap,
            service_level_pct=sl,
            abandon_rate_pct=abandon_rate,
            answer_rate_pct=answer_rate,
            raw_data=m,
            fetched_at=datetime.utcnow(),
        )
        db.add(report)
        reports.append(report)

    if reports:
        connection.last_sync_at = datetime.utcnow()
        db.commit()
        logger.info(f"Fetched {len(reports)} queue reports for connection {connection.id}")

    return reports


async def run_hourly_report_fetch(db: Session):
    connections = (
        db.query(AccountIntegration)
        .join(IntegrationType)
        .filter(
            IntegrationType.slug == "zoom-contact-center",
            AccountIntegration.status == IntegrationStatus.CONNECTED,
        )
        .all()
    )

    logger.info(f"Running hourly Zoom CC report fetch for {len(connections)} connections")

    for conn in connections:
        try:
            await fetch_queue_performance(conn, db)
        except Exception as e:
            logger.error(f"Error fetching reports for connection {conn.id}: {e}")
            conn.last_error = str(e)
            db.commit()


def _safe_int(val) -> int:
    try:
        return int(val) if val else 0
    except (ValueError, TypeError):
        return 0


def _safe_float(val) -> float:
    try:
        return float(val) if val else 0.0
    except (ValueError, TypeError):
        return 0.0
