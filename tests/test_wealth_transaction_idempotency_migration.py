import unittest
from pathlib import Path


MIGRATION = Path(
    "database/migration_wealth_transaction_idempotency.sql"
)


class WealthTransactionIdempotencyMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8")

    def test_migration_file_exists(self):
        self.assertTrue(MIGRATION.exists())

    def test_adds_idempotency_key_column(self):
        self.assertIn(
            "add column if not exists idempotency_key text",
            self.sql.lower(),
        )

    def test_blank_idempotency_key_is_rejected(self):
        sql = self.sql.lower()

        self.assertIn(
            "wealth_transactions_idempotency_key_not_blank",
            sql,
        )
        self.assertIn(
            "length(btrim(idempotency_key)) > 0",
            sql,
        )

    def test_null_idempotency_key_remains_allowed(self):
        sql = self.sql.lower()

        self.assertIn(
            "idempotency_key is null",
            sql,
        )

    def test_unique_index_is_scoped_to_user_and_key(self):
        sql = self.sql.lower()

        self.assertIn(
            "wealth_transactions_user_idempotency_uidx",
            sql,
        )
        self.assertIn(
            "on public.wealth_transactions (user_id, idempotency_key)",
            sql,
        )

    def test_unique_index_excludes_null_keys(self):
        sql = self.sql.lower()

        self.assertIn(
            "where idempotency_key is not null",
            sql,
        )

    def test_migration_is_additive(self):
        sql = self.sql.lower()

        self.assertIn(
            "alter table public.wealth_transactions",
            sql,
        )
        self.assertNotIn(
            "drop table public.wealth_transactions",
            sql,
        )
        self.assertNotIn(
            "drop column idempotency_key",
            sql,
        )

    def test_migration_does_not_modify_transaction_type_constraint(self):
        sql = self.sql.lower()

        self.assertNotIn(
            "txn_type",
            sql.replace("idempotency_key", ""),
        )


if __name__ == "__main__":
    unittest.main()
