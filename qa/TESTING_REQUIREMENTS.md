# AutomataGrid: Testing Requirements (Architecture v1.8.0)

This document establishes the technical standards for time-series data and cross-timezone stability within the AutomataGrid engine. All developers and QA agents must adhere to these requirements during feature development and verification.

## 1. Datetime Architecture Standards

### 1.1 Model Standard: Aware-Only
All `DateTime` columns in SQLAlchemy models MUST use the `AwareDateTime` TypeDecorator (defined in `models.py`). This ensures:
- UTC offsets are re-attached to datetimes when retrieved from SQLite.
- All stored time data is normalized to UTC.

**Requirement**: Verify every new model column during QA code reviews.

### 1.2 Comparison Protocol
All system-time comparisons (e.g., TTL checks, expiry windows, cooldowns) must be performed using **offset-aware UTC objects**.

**Standard**: Use `datetime.now(timezone.utc)` for all "current time" calculations.
**Prohibited**: Never use `datetime.now()` or `datetime.utcnow()` for database-backed comparisons.

## 2. Verification Protocol for Datetime Fixes

### 2.1 Regression Testing
Every architectural shift concerning time must be verified using the `qa/repro_datetime_snag.py` (or equivalent) to ensure legacy naive data does not crash the engine during a `TypeError` comparison.

### 2.2 timezone info Verification
Automated tests should explicitly verify the presence of `tzinfo` on records retrieved from the database.

Example Verification:
```python
assert record.breached_at.tzinfo is not None, "Database record returned naive datetime"
```

## 3. Grid Hack Loop (Task 039)
The Grid Hack Loop requires a mandatory **300-second TTL window** for both Discovery (PROBE) and Breach (HACK) records. This window must be verified using the normalized aware-UTC comparisons.
