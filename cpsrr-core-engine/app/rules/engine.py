from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
import json
from decimal import Decimal
from typing import Tuple, List, Optional, Union

from app.models import (
    User, VehiclePermit, ParkingZone, ParkingSlot,
    RuleConfig, ReservationRegister, ViolationLog, AuditLog
)


@dataclass
class FailureReason:
    """
    Standardized rejection diagnostic structure.
    Used by Engine 2 multi-rule verification to provide explainable feedback.
    """
    category: str
    code: str
    message: str
    guidance: str

    def to_dict(self) -> dict:
        return asdict(self)


class VerificationVerdict(dict):
    """
    Standardized verdict container supporting dictionary indexing, attribute access,
    and tuple unpacking (is_approved, reasons) = verdict.
    """
    def __init__(self, is_approved: bool, reasons: list, timestamp: Optional[datetime] = None):
        reasons_dicts = [r.to_dict() if hasattr(r, 'to_dict') else r for r in reasons]
        super().__init__(
            is_approved=is_approved,
            approved=is_approved,
            reasons=reasons_dicts,
            reason_list=reasons_dicts,
            timestamp=timestamp.isoformat() if timestamp else None
        )
        self.is_approved = is_approved
        self.approved = is_approved
        self.reasons = reasons_dicts
        self.reason_list = reasons_dicts
        self.raw_reasons = reasons

    def __iter__(self):
        return iter((self.is_approved, self.raw_reasons))


def parse_datetime(val: Union[datetime, str]) -> Optional[datetime]:
    """Parse various datetime representations into Python timezone-aware UTC datetime object."""
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    if not val:
        return None
    val_str = str(val).strip()
    try:
        dt = datetime.fromisoformat(val_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(val_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def get_monotonic_campus_time() -> datetime:
    """Returns current system UTC time representing campus reference clock."""
    return datetime.now(timezone.utc)


def evaluate_reservation_request(db_session, request_data: dict, acting_user: Union[User, dict, None] = None) -> Tuple[bool, List[FailureReason]]:
    """
    Engine 2: Non-Short-Circuiting Multi-Rule Verification Algorithm (SRS Section 6.4)

    Evaluates ALL declarative business rules against incoming reservation requests without
    halting on first failure. Aggregates all failure reasons into a comprehensive ReasonList
    for explainable diagnostic feedback, then writes an immutable AuditLog entry.

    Parameters:
        db_session: Active SQLAlchemy database session.
        request_data: Dict containing user_id, permit_id, slot_id, start_time, end_time, client_ip.
        acting_user: User object or dict representing the user initiating the action.

    Returns:
        Tuple[bool, List[FailureReason]]: (is_approved, reason_list)
    """
    reasons: List[FailureReason] = []
    current_time = get_monotonic_campus_time()

    # Normalize acting user information
    acting_user_id = None
    acting_user_role = "STUDENT"

    if isinstance(acting_user, User):
        acting_user_id = acting_user.user_id
        acting_user_role = acting_user.role
    elif isinstance(acting_user, dict):
        acting_user_id = acting_user.get("user_id")
        acting_user_role = acting_user.get("role", "STUDENT")
    elif request_data.get("user_id"):
        acting_user_id = int(request_data.get("user_id"))
        user_in_db = db_session.get(User, acting_user_id)
        if user_in_db:
            acting_user_role = user_in_db.role

    client_ip = request_data.get("client_ip") or "127.0.0.1"

    # Step 1: Dynamic Rule Configuration Ingestion (Theme 1 Core: Zero Magic Numbers)
    active_rules_records = db_session.query(RuleConfig).filter(
        RuleConfig.is_active == 1,
        RuleConfig.role_applicability.in_(["ALL", acting_user_role.upper()])
    ).all()

    rule_map = {}
    for rule in active_rules_records:
        rule_map[rule.rule_key] = rule.cast_value()

    # Parse requested time interval
    req_start_time = parse_datetime(request_data.get("start_time"))
    req_end_time = parse_datetime(request_data.get("end_time"))
    req_permit_id = request_data.get("permit_id")
    req_slot_id = request_data.get("slot_id")

    # Time parsing defensive check
    if not req_start_time or not req_end_time:
        reasons.append(FailureReason(
            category="TIME_VALIDATION",
            code="ERR_INVALID_DATETIME_FORMAT",
            message="Start time or end time format is invalid.",
            guidance="Provide dates in ISO format (YYYY-MM-DD HH:MM:SS)."
        ))

    # RULE 1: User Account Operational Status
    user_record = db_session.get(User, acting_user_id) if acting_user_id else None
    if user_record is None or user_record.is_active != 1:
        reasons.append(FailureReason(
            category="USER_ACTIVE_CHECK",
            code="ERR_USER_ACCOUNT_SUSPENDED",
            message="User account is suspended, inactive, or not registered.",
            guidance="Contact campus security administration to restore user account status."
        ))

    # RULE 2: Vehicle Permit Standing & Expiry
    permit = db_session.get(VehiclePermit, req_permit_id) if req_permit_id else None
    if permit is None:
        reasons.append(FailureReason(
            category="PERMIT_EXISTS",
            code="ERR_PERMIT_NOT_FOUND",
            message="Vehicle permit does not exist in register.",
            guidance="Ensure vehicle is registered and permit ID is valid."
        ))
    else:
        if acting_user_id and permit.user_id != acting_user_id:
            reasons.append(FailureReason(
                category="PERMIT_OWNER",
                code="ERR_PERMIT_OWNERSHIP_MISMATCH",
                message="Cannot reserve using a permit registered to another user.",
                guidance="Select a vehicle permit registered under your institutional USN/Employee code."
            ))
        if permit.permit_status != "ACTIVE":
            reasons.append(FailureReason(
                category="PERMIT_ACTIVE",
                code="ERR_PERMIT_INACTIVE",
                message=f"Vehicle permit is marked '{permit.permit_status}'.",
                guidance="Renew or clear permit status at the campus parking desk."
            ))
        if req_end_time and permit.valid_until:
            p_valid_until = permit.valid_until
            if p_valid_until.tzinfo is None:
                p_valid_until = p_valid_until.replace(tzinfo=timezone.utc)
            else:
                p_valid_until = p_valid_until.astimezone(timezone.utc)
            if p_valid_until < req_end_time:
                reasons.append(FailureReason(
                    category="PERMIT_EXPIRY",
                    code="ERR_PERMIT_EXPIRED",
                    message="Permit expires prior to requested reservation end time.",
                    guidance="Renew vehicle permit validity or choose an earlier reservation window."
                ))

    # RULE 3: Slot Existence, Zone Status & Maintenance
    slot = db_session.get(ParkingSlot, req_slot_id) if req_slot_id else None
    if slot is None:
        reasons.append(FailureReason(
            category="SLOT_EXISTS",
            code="ERR_SLOT_NOT_FOUND",
            message="Requested parking slot does not exist.",
            guidance="Select a valid slot from the live slot catalog."
        ))
    else:
        zone = slot.zone
        if zone is None or zone.is_active != 1:
            reasons.append(FailureReason(
                category="ZONE_ACTIVE",
                code="ERR_ZONE_INACTIVE",
                message="Selected parking zone is closed for campus maintenance.",
                guidance="Please choose a slot in an active parking sector."
            ))
        if slot.operational_status == "MAINTENANCE":
            reasons.append(FailureReason(
                category="SLOT_MAINTENANCE",
                code="ERR_SLOT_MAINTENANCE",
                message="Physical slot is barricaded for repair or maintenance.",
                guidance="Select another parking slot that is operational."
            ))

        # RULE 4: Zone Role Authorization
        enforce_roles = rule_map.get("ENFORCE_ZONE_ROLES", True)
        if enforce_roles and zone:
            allowed_roles = [r.strip().upper() for r in (zone.allowed_roles or "").split(",") if r.strip()]
            if acting_user_role.upper() not in allowed_roles:
                reasons.append(FailureReason(
                    category="ZONE_ROLE",
                    code="ERR_UNAUTHORIZED_ZONE_ROLE",
                    message=f"Role '{acting_user_role}' is not permitted in {zone.zone_name} ({zone.zone_code}).",
                    guidance=f"Eligible roles for this zone are: {', '.join(allowed_roles)}."
                ))

        # RULE 5: Vehicle Category Matching Slot
        if permit is not None and permit.vehicle_type != slot.vehicle_type:
            reasons.append(FailureReason(
                category="VEHICLE_MATCH",
                code="ERR_VEHICLE_SLOT_TYPE_MISMATCH",
                message=f"Vehicle category '{permit.vehicle_type}' does not match bay specification '{slot.vehicle_type}'.",
                guidance=f"Select a parking bay designated for {permit.vehicle_type}."
            ))

    # RULE 6: Outstanding Fines & Active Violation Strikes
    if acting_user_id:
        max_allowed_fine = float(rule_map.get("MAX_ALLOWED_UNPAID_FINE", 0.00))
        unpaid_fines = db_session.query(ViolationLog).filter(
            ViolationLog.user_id == acting_user_id,
            ViolationLog.is_paid == 0
        ).all()
        total_dues = sum(float(v.fine_amount) for v in unpaid_fines)
        if total_dues > max_allowed_fine:
            reasons.append(FailureReason(
                category="OUTSTANDING_FINES",
                code="ERR_OUTSTANDING_FINES_BLOCKED",
                message=f"Account has INR {total_dues:.2f} in unpaid parking fines.",
                guidance="Clear outstanding violation penalties at security cashier before booking."
            ))

    # RULE 7 & RULE 8: Temporal Boundaries (Advance Window & Duration)
    if req_start_time and req_end_time:
        if req_end_time <= req_start_time:
            reasons.append(FailureReason(
                category="TIME_WINDOW",
                code="ERR_INVALID_TIME_INTERVAL",
                message="Reservation end time must be strictly after start time.",
                guidance="Ensure the end time is scheduled after the start time."
            ))
        else:
            # Advance booking window
            max_adv_hours = int(rule_map.get("MAX_ADVANCE_BOOKING_HOURS", 48))
            advance_cutoff = current_time + timedelta(hours=max_adv_hours)
            if req_start_time > advance_cutoff:
                reasons.append(FailureReason(
                    category="ADVANCE_WINDOW",
                    code="ERR_EXCEEDS_MAX_ADVANCE",
                    message=f"Cannot book more than {max_adv_hours} hours in advance.",
                    guidance=f"Select a reservation start time within the next {max_adv_hours} hours."
                ))

            # Maximum reservation duration per role
            dur_mins = (req_end_time - req_start_time).total_seconds() / 60.0
            role_dur_key = f"MAX_RESERVATION_DURATION_MINUTES_{acting_user_role.upper()}"
            max_dur_mins = int(rule_map.get(role_dur_key, rule_map.get("MAX_RESERVATION_DURATION_MINUTES", 240)))
            if dur_mins > max_dur_mins:
                reasons.append(FailureReason(
                    category="MAX_DURATION",
                    code="ERR_MAX_DURATION_EXCEEDED",
                    message=f"Duration ({dur_mins/60.0:.1f}h) exceeds permitted limit ({max_dur_mins/60.0:.1f}h) for role {acting_user_role}.",
                    guidance=f"Maximum allowed reservation duration for your role is {int(max_dur_mins)} minutes."
                ))

    # RULE 9: Daily Booking Quota per User
    # Quota is unlimited by default unless ENABLE_DAILY_QUOTA is explicitly enabled and max_quota is between 1 and 9998
    if acting_user_id and req_start_time:
        enable_quota = rule_map.get("ENABLE_DAILY_QUOTA", False) in (True, 1, "1", "true", "True")
        role_quota_key = f"MAX_DAILY_RESERVATIONS_{acting_user_role.upper()}"
        quota_val = rule_map.get(role_quota_key, rule_map.get("MAX_DAILY_RESERVATIONS", 9999))
        try:
            max_quota = int(quota_val) if quota_val is not None else 9999
        except (ValueError, TypeError):
            max_quota = 9999

        if enable_quota and 0 < max_quota < 9999:
            start_of_day = datetime(req_start_time.year, req_start_time.month, req_start_time.day, 0, 0, 0, tzinfo=timezone.utc)
            end_of_day = datetime(req_start_time.year, req_start_time.month, req_start_time.day, 23, 59, 59, tzinfo=timezone.utc)

            daily_count = db_session.query(ReservationRegister).filter(
                ReservationRegister.user_id == acting_user_id,
                ReservationRegister.start_time >= start_of_day,
                ReservationRegister.start_time <= end_of_day,
                ReservationRegister.reservation_status.in_(["RESERVED", "OCCUPIED"])
            ).count()

            if daily_count >= max_quota:
                booking_date_str = req_start_time.strftime("%Y-%m-%d")
                reasons.append(FailureReason(
                    category="DAILY_QUOTA",
                    code="ERR_DAILY_QUOTA_EXCEEDED",
                    message=f"Daily reservation quota ({max_quota}) already reached for {booking_date_str}.",
                    guidance="Users are restricted by role daily limits. Release an existing reservation or choose another date."
                ))

    # RULE 10: Temporal Overlap Mutual Exclusion: !(S_new < E_exist and E_new > S_exist)
    if req_slot_id and req_start_time and req_end_time:
        conflicts = db_session.query(ReservationRegister).filter(
            ReservationRegister.slot_id == req_slot_id,
            ReservationRegister.reservation_status.in_(["RESERVED", "OCCUPIED"]),
            ReservationRegister.start_time < req_end_time,
            ReservationRegister.end_time > req_start_time
        ).all()

        if conflicts:
            conflict_res = conflicts[0]
            start_str = conflict_res.start_time.strftime("%H:%M")
            end_str = conflict_res.end_time.strftime("%H:%M")
            reasons.append(FailureReason(
                category="SLOT_OVERLAP",
                code="ERR_SLOT_TEMPORAL_CONFLICT",
                message=f"Slot is already reserved by another booking ({conflict_res.reservation_code}) between {start_str} and {end_str}.",
                guidance="Select an alternative vacant parking bay or adjust the reservation time window."
            ))

    # Step 5: Consolidated Verdict Determination & Append-Only Audit Logging
    is_approved = (len(reasons) == 0)
    verdict = "SUCCESS" if is_approved else "BLOCKED"

    reason_list_serialized = json.dumps([r.to_dict() for r in reasons])

    audit_entry = AuditLog(
        timestamp=current_time,
        acting_user_id=acting_user_id,
        ip_address=client_ip,
        action_type="RESERVATION_EVALUATION",
        target_table="reservation_register",
        record_id=None,
        old_state_json=None,
        new_state_json=json.dumps({
            "slot_id": req_slot_id,
            "permit_id": req_permit_id,
            "start_time": req_start_time.isoformat() if req_start_time else None,
            "end_time": req_end_time.isoformat() if req_end_time else None,
            "is_approved": is_approved
        }),
        reason_list_json=reason_list_serialized,
        verdict=verdict
    )

    try:
        db_session.add(audit_entry)
        db_session.flush()
    except Exception as e:
        # If audit write fails, do not silently ignore
        db_session.rollback()
        raise e

    return VerificationVerdict(is_approved, reasons, current_time)
