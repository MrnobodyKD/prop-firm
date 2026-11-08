# Admin Settings Cleanup Report — 2026-11-08

## Files changed for this task

- `templates/admin/base.html` — removed Rulebook, Email Center/Analytics, moderator management/activity, and FAQ links from desktop and mobile navigation; kept the existing mobile Settings link.
- `templates/admin/settings.html` — created the missing Settings page with six permission-gated navigation cards and the copied Marketplace Control card, with a Settings return target.
- `admin_routes/admin_engagement.py` — passed `SiteSettings.get_settings()` to the existing Settings route.
- `admin_routes/admin_challenges.py` — accepted a safe `/admin/` `next` path after a marketplace toggle, otherwise returning to the dashboard.
- `admin_routes/__init__.py` — added the pending manual-claims count to dashboard context.
- `templates/admin/admin_dashboard.html` — added the linked Pending Manual Claims stat card.
- `auth.py` — attempted verification email delivery after registration commit; failures are swallowed and the session is rolled back without undoing the committed user.
- `templates/user/base.html` — added the persistent unverified-email banner above page content.
- `templates/user/settings.html` — added verification status/actions and the Change Password form.

## Verification

- Python compilation passed for all changed Python files using `venv\Scripts\python.exe -m py_compile`.
- Jinja parsing passed for all five changed/created templates using the Flask Jinja environment.
- `git diff --check` passed for the task's tracked files.
- Sidebar link inspection confirmed the six moved labels are absent from `templates/admin/base.html`; retained links including Manual Claims and Settings remain in desktop/mobile navigation. The mobile Settings link was already present, so its existing styling was preserved.
- Source inspection confirmed purchase lockdown checks already cover the buy route GET/POST, manual payment, crypto start through `_purchase_guard`, and legacy Cashfree order creation.
- Runtime Flask route and end-to-end checks against the disposable database did not produce a completed results summary in the available test run. Direct URL rendering, moderator filtering, marketplace toggle behavior, registration email-failure handling, verification UI transitions, and password changes therefore remain unverified at runtime.
- Real email delivery was not verified.

## Working tree note

The repository had extensive pre-existing changes and deletions before this task, including changes in several of the same Python files. They were preserved. No commit, push, or merge was performed. The task-specific disposable database file was removed; no `.env`, project database, or `instance/` files were modified by this task.
