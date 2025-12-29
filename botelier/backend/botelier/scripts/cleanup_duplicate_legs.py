"""
Cleanup script to remove duplicate transfer legs from call logs.

This script fixes historical call logs that have multiple transfer legs
to the same destination due to a bug where record_transfer() was called
multiple times for the same transfer.

Run with: python -m botelier.scripts.cleanup_duplicate_legs

Options:
    --dry-run    Preview changes without modifying database (default)
    --execute    Actually perform the cleanup
"""

import sys
import argparse
from datetime import datetime
from sqlalchemy import text, func
from sqlalchemy.orm import Session
from loguru import logger

from botelier.database import SessionLocal
from botelier.models.call_log import CallLeg, CallLog, LegType


def find_duplicate_groups(db: Session) -> list:
    """
    Find all duplicate transfer leg groups.
    
    Returns list of dicts with:
    - call_log_id, leg_type, participant
    - count of duplicates
    - list of leg IDs in the group
    """
    query = text("""
        WITH duplicate_groups AS (
            SELECT 
                call_log_id,
                leg_type,
                participant,
                COUNT(*) as leg_count,
                array_agg(id ORDER BY COALESCE(started_at, created_at), leg_number, id) as leg_ids,
                array_agg(duration_seconds ORDER BY COALESCE(started_at, created_at), leg_number, id) as durations,
                MIN(started_at) as first_started,
                MAX(ended_at) as last_ended,
                MAX(duration_seconds) as max_duration
            FROM call_legs
            WHERE leg_type IN ('transfer_external', 'transfer_sip')
            GROUP BY call_log_id, leg_type, participant
            HAVING COUNT(*) > 1
        )
        SELECT 
            dg.*,
            cl.call_sid
        FROM duplicate_groups dg
        JOIN call_logs cl ON cl.id = dg.call_log_id
        ORDER BY cl.started_at DESC
    """)
    
    result = db.execute(query)
    groups = []
    for row in result:
        groups.append({
            "call_log_id": str(row.call_log_id),
            "call_sid": row.call_sid,
            "leg_type": row.leg_type,
            "participant": row.participant,
            "leg_count": row.leg_count,
            "leg_ids": [str(lid) for lid in row.leg_ids],
            "durations": row.durations,
            "first_started": row.first_started,
            "last_ended": row.last_ended,
            "max_duration": row.max_duration or 0
        })
    
    return groups


def cleanup_duplicates(db: Session, groups: list, dry_run: bool = True) -> dict:
    """
    Clean up duplicate transfer legs.
    
    For each group:
    1. Keep the first leg (survivor)
    2. Update survivor with best timing data (max duration, proper timestamps)
    3. Delete all other legs in the group
    4. Renumber remaining legs to be sequential
    """
    stats = {
        "groups_processed": 0,
        "legs_deleted": 0,
        "legs_updated": 0,
        "calls_renumbered": 0,
        "errors": []
    }
    
    for group in groups:
        try:
            survivor_id = group["leg_ids"][0]
            duplicate_ids = group["leg_ids"][1:]
            
            if not dry_run:
                survivor = db.query(CallLeg).filter(CallLeg.id == survivor_id).first()
                if survivor:
                    if group["max_duration"] and group["max_duration"] > (survivor.duration_seconds or 0):
                        survivor.duration_seconds = group["max_duration"]
                    if group["first_started"] and (not survivor.started_at or group["first_started"] < survivor.started_at):
                        survivor.started_at = group["first_started"]
                    if group["last_ended"] and (not survivor.ended_at or group["last_ended"] > survivor.ended_at):
                        survivor.ended_at = group["last_ended"]
                    stats["legs_updated"] += 1
                
                deleted = db.query(CallLeg).filter(CallLeg.id.in_(duplicate_ids)).delete(synchronize_session=False)
                stats["legs_deleted"] += deleted
            else:
                stats["legs_deleted"] += len(duplicate_ids)
                stats["legs_updated"] += 1
            
            stats["groups_processed"] += 1
            
            logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Processed call {group['call_sid']}: "
                       f"kept leg {survivor_id[:8]}..., deleted {len(duplicate_ids)} duplicates")
            
        except Exception as e:
            stats["errors"].append(f"Error processing group {group['call_log_id']}: {e}")
            logger.error(f"Error processing group: {e}")
    
    if not dry_run and stats["groups_processed"] > 0:
        db.commit()
        logger.info("Committed duplicate cleanup")
    
    return stats


def renumber_legs(db: Session, call_log_ids: list, dry_run: bool = True) -> int:
    """
    Renumber legs for affected calls to ensure sequential numbering.
    """
    renumbered = 0
    
    for call_log_id in call_log_ids:
        legs = db.query(CallLeg).filter(
            CallLeg.call_log_id == call_log_id
        ).order_by(CallLeg.leg_number, CallLeg.created_at).all()
        
        needs_renumber = False
        for i, leg in enumerate(legs, start=1):
            if leg.leg_number != i:
                needs_renumber = True
                break
        
        if needs_renumber:
            if not dry_run:
                for i, leg in enumerate(legs, start=1):
                    leg.leg_number = i
            renumbered += 1
            logger.debug(f"{'[DRY-RUN] ' if dry_run else ''}Renumbered legs for call {call_log_id}")
    
    if not dry_run and renumbered > 0:
        db.commit()
    
    return renumbered


def main():
    parser = argparse.ArgumentParser(description="Cleanup duplicate transfer legs from call logs")
    parser.add_argument("--execute", action="store_true", help="Actually perform cleanup (default is dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without modifying database")
    args = parser.parse_args()
    
    dry_run = not args.execute
    
    logger.info(f"{'=' * 60}")
    logger.info(f"Call Leg Duplicate Cleanup Script")
    logger.info(f"Mode: {'DRY-RUN (preview only)' if dry_run else 'EXECUTE (will modify database)'}")
    logger.info(f"{'=' * 60}")
    
    db = SessionLocal()
    
    try:
        logger.info("Finding duplicate transfer leg groups...")
        groups = find_duplicate_groups(db)
        
        if not groups:
            logger.info("No duplicate transfer legs found. Database is clean.")
            return
        
        total_duplicates = sum(g["leg_count"] - 1 for g in groups)
        logger.info(f"Found {len(groups)} calls with duplicate transfer legs ({total_duplicates} duplicates total)")
        
        logger.info("")
        logger.info("Duplicate groups preview:")
        for i, g in enumerate(groups[:10], 1):
            logger.info(f"  {i}. Call {g['call_sid']}: {g['leg_count']} legs to {g['participant']} "
                       f"(max duration: {g['max_duration']}s)")
        if len(groups) > 10:
            logger.info(f"  ... and {len(groups) - 10} more")
        
        logger.info("")
        logger.info("Processing duplicates...")
        stats = cleanup_duplicates(db, groups, dry_run=dry_run)
        
        affected_call_ids = list(set(g["call_log_id"] for g in groups))
        logger.info("Renumbering legs for affected calls...")
        renumbered = renumber_legs(db, affected_call_ids, dry_run=dry_run)
        stats["calls_renumbered"] = renumbered
        
        logger.info("")
        logger.info(f"{'=' * 60}")
        logger.info(f"Summary {'(DRY-RUN - no changes made)' if dry_run else ''}")
        logger.info(f"{'=' * 60}")
        logger.info(f"  Groups processed: {stats['groups_processed']}")
        logger.info(f"  Legs updated (survivors): {stats['legs_updated']}")
        logger.info(f"  Legs deleted: {stats['legs_deleted']}")
        logger.info(f"  Calls renumbered: {stats['calls_renumbered']}")
        
        if stats["errors"]:
            logger.warning(f"  Errors: {len(stats['errors'])}")
            for err in stats["errors"]:
                logger.warning(f"    - {err}")
        
        if dry_run:
            logger.info("")
            logger.info("To apply these changes, run with --execute flag:")
            logger.info("  python -m botelier.scripts.cleanup_duplicate_legs --execute")
        
    except Exception as e:
        logger.exception(f"Script failed: {e}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
