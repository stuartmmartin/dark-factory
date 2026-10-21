"""SQLAdmin views: read-only by construction.

D9 (RULING, flagged for a human): the admin runs on the service's `sb_app` engine with no tenant
set, so FORCE RLS makes every list view show zero rows. Accepted for Plan 4; a tenant picker is
a follow-up. Never build the admin on `migrator_url` (it bypasses RLS).
"""

from __future__ import annotations

from sqladmin import ModelView

from ledger.infrastructure.models import AccountRow


class AccountAdmin(ModelView, model=AccountRow):
    name = "Account"
    name_plural = "Accounts"
    can_create = False
    can_edit = False
    can_delete = False
    can_export = False
    column_list = (
        AccountRow.id,
        AccountRow.tenant_id,
        AccountRow.name,
        AccountRow.currency,
        AccountRow.opened_at,
    )
