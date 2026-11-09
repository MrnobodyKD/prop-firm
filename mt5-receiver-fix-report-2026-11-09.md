# MT5 Receiver Fix Report — 2026-11-09

## Fix status

1. **Timestamps — partially fixed, completed.** `parse_datetime()` now accepts Unix seconds, Unix milliseconds, digit-only timestamp strings, and ISO strings. Empty and invalid values retain the existing UTC-now fallback. Unit checks passed for integer and float seconds, integer milliseconds, digit-string seconds and milliseconds, ISO values with and without a timezone, a naive `datetime`, empty string, `None`, and garbage.
2. **Payload logging — partially fixed, completed.** Removed the raw-payload and cleaned-JSON prints. Added one `[SYNC]` summary line with challenge ID, balance, equity, and open/closed counts. Captured route logs contained no payload or challenge token; existing error and status logs remain.
3. **Numeric conversions — partially fixed, completed.** Balance, equity, terminal build, trade types, free margin, margin used, and received trade/order numeric values use safe conversions. A nonnumeric balance did not produce an HTTP 500.
4. **Persist new journal fields — partially fixed, completed.** `AccountSnapshot.currency` already existed with a nullable USD default. Added nullable string leverage and margin level; added swap, commission, and comment to `EATrade`; added `EAOrder` and history-order upserts. Missing/unknown optional payload fields were tolerated. The SQLite duplicate check also now treats a stored naive timestamp as UTC before the existing two-second comparison.
5. **Authentication/access/response — already fixed, verified.** The hardcoded `X-Internal-Key` check and disabled IP allowlist were left unchanged. Wrong key returned 403, bad token 401, missing token 400. Successful and old-format responses retained the existing keys; a repeated payload returned the existing duplicate response.

## Verification

- `python -m py_compile mt5_receiver.py models.py` — passed.
- Timestamp cases — all 11 passed; only empty and invalid inputs used the now fallback.
- Migration — disposable copy reported applied revision `d10000000003`; repository migration head before this work was `d10000000004`. The new `d10000000005` revision is chained after `d10000000004`. Upgrade, downgrade to `d10000000004`, and re-upgrade passed, including the app-startup case where `db.create_all()` creates `ea_order` before Alembic runs. Row counts remained unchanged for `challenge_purchase` (2), `account_snapshot` (0), `ea_trade` (0), and `challenge_template` (3). The final schema contained the expected new columns and `ea_order` table.
- Receiver — tested through the local Flask test client against the disposable copy, with the rule engine stubbed. New-format and old-format payloads, unix and ISO trade/order times, stored snapshot/trade/order fields, duplicate detection, bad balance, unknown fields, and 400/401/403 auth paths passed.
- Logs — four tested sync attempts emitted one summary line each and no raw or cleaned payload or token.
- No live server was called. Database verification and receiver tests used a temporary copy; the source database was not used by the test client.
- A migration-head inspection imported the app against its default local database; app startup created an empty `ea_order` table there. I verified the table had zero rows and the revision was still `d10000000003`, removed only that empty table, and confirmed SQLite `integrity_check` returned `ok`. No receiver sync or migration was run against that database.

## Files for this request

- `mt5_receiver.py` — timestamp parsing, safe conversions, summary logging, snapshot/trade/order persistence, and duplicate timestamp normalization.
- `models.py` — requested `AccountSnapshot` and `EATrade` fields and the `EAOrder` model. The existing unrelated `ChallengeTemplate.price` change was already in the working tree and was not changed for this task.
- `migrations/versions/d10000000005_mt5_trade_order_fields.py` — the single new migration.
- `mt5-receiver-fix-report-2026-11-09.md` — this report.

The working tree also contains unrelated modifications, deletions, and untracked files from earlier work. They were present before this request and were left untouched. The earlier untracked `d10000000004_challenge_price_float.py` migration remains unchanged.

## Deploy note

After this is pushed, run `git pull`, check `flask db current` on the server, run `flask db upgrade` without forcing a revision, then restart the service.
