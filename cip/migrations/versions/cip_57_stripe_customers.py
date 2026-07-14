# foundry: kind=migration domain=client-intelligence-platform
"""cip_57: ps_stripe_customers. Every Stripe fact gets a home.

Tim, 2026-07-13: "make sure all the new info you found in stripe matches to a field with
description in DB, and everything is correct."

WE WERE THROWING MOST OF STRIPE AWAY
------------------------------------
The ingest called /v1/customers, read metadata.brandId and email, and dropped the rest — 5,754
customers, two fields kept, everything else discarded on every run. There was no customers
table at all. What we were binning:

  metadata.intCustomerType  Every registered brand is 'PARENT_BRAND' (5,278 of them). The 476
                            without it are EXACTLY the 474 that also have no brandId. So the
                            "unnameable" cohort is not a set of brands we failed to match — it
                            is a structurally different class of record, created outside
                            Wayward's brand-onboarding flow. That is a fact about how the row
                            was made, and it was invisible to us.

  metadata.auth0id          A second identity key, on 100% of registered brands. Never captured.

  description               THE BIG ONE. For 5,112 customers it is a redundant copy of brandId.
                            But for customers whose metadata.brandId is NULL, the brand UUID is
                            sitting in description instead — Wayward wrote the id to the wrong
                            field. 337 of the 474 orphans carry a UUID there, and 224 of those
                            are brands our master had never heard of. That is ~71% of the
                            unnameable money recovered from Wayward's OWN data, with no
                            inference of any kind.

  delinquent / balance      Is this customer behind on payments, and by how much. This is the
                            billed-vs-collected signal, straight from the source, and we were
                            deriving it the long way round from invoice sums.

  created                   When the customer record actually began.

  address                   Populated on only 2% of customers. Recording that explicitly,
                            because it means Stripe's address is NOT a usable country source and
                            nobody should waste a day discovering that again.

ONE SELLER, MANY BRANDS
-----------------------
99 descriptions are shared by more than one customer (up to 4). "Gorillaz LLC (BLS BLUES)" and
"Gorillaz LLC (livho)" are two customer records, two brand ids, one seller. The grain here is
therefore STRIPE CUSTOMER, not brand — a brand may be billed through more than one customer
record, and any join that assumes 1:1 will silently fan out.

NEW PROVENANCE TIER
-------------------
'stripe_description' joins the brand_id_source ladder from cip_56. It IS Wayward's own record —
they wrote that UUID — but into an unlabelled free-text field rather than the structured one, so
it ranks just below stripe_metadata and above anything we infer ourselves.

Revision ID: cip_57_stripe_customers
Revises: cip_56_brand_id_provenance
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "cip_57_stripe_customers"
down_revision: str | Sequence[str] | None = "cip_56_brand_id_provenance"
branch_labels = None
depends_on = None

_READ_ROLES = ("cip_query_reader", "cip_metabase_project_silk", "cip_twenty_project_silk")

_SOURCES = (
    "stripe_metadata",
    "stripe_description",   # NEW in cip_57
    "stripe_email_match",
    "slack_feed_email",
    "payment_report",
    "name_match",
)

_COLUMN_DOCS = {
    "stripe_customer_id": (
        "Stripe's customer id (cus_...). THE GRAIN of this table. A brand can be billed through "
        "MORE THAN ONE customer record (99 sellers have several; 'Gorillaz LLC (BLS BLUES)' and "
        "'Gorillaz LLC (livho)' are two rows, one seller), so never assume customer:brand is 1:1 "
        "— a join that does will silently fan out and double-count."
    ),
    "wayward_brand_id": (
        "The brand this customer bills for. Taken from metadata.brandId where Wayward set it, "
        "and OTHERWISE from the description field, where Wayward wrote the same UUID into "
        "unstructured text (337 of the 474 customers with no metadata.brandId have it there). "
        "Always read brand_id_source alongside this."
    ),
    "brand_id_source": (
        "HOW we know this customer's brand. stripe_metadata (structured, Wayward-set) > "
        "stripe_description (Wayward's own UUID, but written to a free-text field) > "
        "stripe_email_match > name_match (inferred — never let it drive money unreviewed). "
        "NULL only when wayward_brand_id is NULL."
    ),
    "auth0_id": (
        "metadata.auth0id — the brand's Auth0 identity, present on 100% of registered brands. "
        "A second exact join key into Wayward's own systems, which we had never captured."
    ),
    "customer_type": (
        "metadata.intCustomerType. 'PARENT_BRAND' for every brand registered through Wayward's "
        "onboarding flow (5,278). NULL for the 474 that were not — and those are EXACTLY the "
        "customers missing metadata.brandId. So a NULL here does not mean 'unknown brand', it "
        "means 'this record was not created by the brand-onboarding flow', which is a different "
        "and more useful fact."
    ),
    "email": "Customer email as Stripe holds it. Used to resolve brand identity where metadata is absent.",
    "customer_name": "Stripe's display name for the customer. Often, but not always, the brand name.",
    "description_raw": (
        "Stripe's free-text description, kept VERBATIM. For 5,112 customers it merely repeats "
        "brandId; for 337 orphans it is the ONLY place the brand id exists; for the rest it is "
        "prose ('Fluencer Fruit Customer'). Kept raw so that whatever Wayward starts putting "
        "here next is not lost before we notice it."
    ),
    "delinquent": (
        "Stripe's own flag: this customer is behind on payments. The billed-but-not-collected "
        "signal at its source (367 customers), rather than inferred by summing invoices."
    ),
    "balance": (
        "Stripe account balance in the customer's currency. Positive = the customer OWES; "
        "negative = credit sits on the account. Not the same as unpaid invoices."
    ),
    "currency": "Billing currency. Populated on only ~35% of customers; NULL means Stripe never set one.",
    "address_country": (
        "Country from Stripe's address. Populated on roughly 2% of customers — so it is NOT a "
        "usable source of brand nationality. Recorded explicitly so nobody rediscovers that the "
        "hard way."
    ),
    "phone": "Customer phone. Populated on well under 1%.",
    "preferred_locales": "Stripe's language preference. Effectively never set (1 customer).",
    "created_at_stripe": (
        "When the Stripe customer record was created. The closest thing Stripe has to a start "
        "date — note it is when BILLING began, not when the brand was onboarded or first sold."
    ),
    "livemode": "False would mean a Stripe test-mode record. Guards against test data reaching money.",
    "tenant_id": "Tenant scope (D-026). Project Silk.",
    "ingested_at": "When this row was last written by the connector.",
}


def upgrade() -> None:
    allowed = ", ".join(f"'{s}'" for s in _SOURCES)

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ps_stripe_customers (
            stripe_customer_id  TEXT PRIMARY KEY,
            tenant_id           UUID NOT NULL,
            wayward_brand_id    UUID REFERENCES ps_brands (wayward_brand_id),
            brand_id_source     TEXT,
            auth0_id            TEXT,
            customer_type       TEXT,
            email               TEXT,
            customer_name       TEXT,
            description_raw     TEXT,
            delinquent          BOOLEAN,
            balance             NUMERIC(14,2),
            currency            TEXT,
            address_country     TEXT,
            phone               TEXT,
            preferred_locales   TEXT,
            created_at_stripe   TIMESTAMPTZ,
            livemode            BOOLEAN,
            ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        f"""
        ALTER TABLE ps_stripe_customers
            ADD CONSTRAINT ck_ps_stripe_customers_brand_id_source CHECK (
                (wayward_brand_id IS NULL     AND brand_id_source IS NULL)
             OR (wayward_brand_id IS NOT NULL AND brand_id_source IN ({allowed}))
            )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ps_stripe_customers_brand "
        "ON ps_stripe_customers (tenant_id, wayward_brand_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ps_stripe_customers_email "
        "ON ps_stripe_customers (tenant_id, lower(email))"
    )

    op.execute(
        "COMMENT ON TABLE ps_stripe_customers IS "
        "'Every Stripe customer, at CUSTOMER grain (not brand — one brand can bill through "
        "several customer records). Previously we called /v1/customers, kept brandId and email, "
        "and threw the rest away on every run. The discarded fields turned out to carry the "
        "brand id for 337 customers we had written off as unnameable, a second identity key "
        "(auth0id), the flag that separates registered brands from non-onboarded records "
        "(intCustomerType), and delinquency straight from the source.'"
    )
    for col, doc in _COLUMN_DOCS.items():
        op.execute(
            f"COMMENT ON COLUMN ps_stripe_customers.{col} IS '{doc.replace(chr(39), chr(39) * 2)}'"
        )

    # brand_id_source now admits stripe_description, on every table that carries it.
    for tbl in ("ps_stripe_invoices", "ps_stripe_invoice_lines", "cip_clients"):
        op.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS ck_{tbl}_brand_id_source")
        op.execute(
            f"""
            ALTER TABLE {tbl} ADD CONSTRAINT ck_{tbl}_brand_id_source CHECK (
                (wayward_brand_id IS NULL     AND brand_id_source IS NULL)
             OR (wayward_brand_id IS NOT NULL AND brand_id_source IN ({allowed}))
            )
            """
        )

    op.execute("ALTER TABLE ps_stripe_customers ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY ps_stripe_customers_tenant ON ps_stripe_customers
            USING (tenant_id = current_setting('app.current_tenant', true)::uuid)
        """
    )
    for r in _READ_ROLES:
        op.execute(f"GRANT SELECT ON ps_stripe_customers TO {r}")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ps_stripe_customers")
    allowed = ", ".join(f"'{s}'" for s in _SOURCES if s != "stripe_description")
    for tbl in ("ps_stripe_invoices", "ps_stripe_invoice_lines", "cip_clients"):
        op.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS ck_{tbl}_brand_id_source")
        op.execute(
            f"""
            ALTER TABLE {tbl} ADD CONSTRAINT ck_{tbl}_brand_id_source CHECK (
                (wayward_brand_id IS NULL     AND brand_id_source IS NULL)
             OR (wayward_brand_id IS NOT NULL AND brand_id_source IN ({allowed}))
            )
            """
        )
