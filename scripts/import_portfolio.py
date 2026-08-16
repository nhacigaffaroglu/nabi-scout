#!/usr/bin/env python3
"""Import portfolio holdings from CSV into Wealth Core.

Expected CSV columns (header required):

    symbol,quantity,average_cost,currency

Example:

    symbol,quantity,average_cost,currency
    AAPL,10,150.25,USD
    MSFT,5,380.00,USD

The script is idempotent: existing positions with matching quantity are skipped.
Conflicting quantities are never overwritten silently.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.portfolio_import_service import import_portfolio_rows
from services.supabase_admin_client import (
    SupabaseAdminClientError,
    apply_local_secrets_to_env,
    create_admin_supabase_client,
)
from services.wealth_contract import WealthValidationError
from services.wealth_core_service import WealthCoreService


REQUIRED_COLUMNS = ("symbol", "quantity", "average_cost", "currency")


def _parse_rows(path: Path) -> List[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV başlık satırı gerekli.")
        missing = [col for col in REQUIRED_COLUMNS if col not in reader.fieldnames]
        if missing:
            raise ValueError(f"Eksik sütunlar: {', '.join(missing)}")
        rows = []
        for index, row in enumerate(reader, start=2):
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                raise ValueError(f"Satır {index}: symbol boş olamaz.")
            try:
                quantity = float(row["quantity"])
                average_cost = float(row["average_cost"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Satır {index}: quantity/average_cost geçersiz.") from exc
            if quantity <= 0 or average_cost < 0:
                raise ValueError(f"Satır {index}: quantity > 0 ve average_cost >= 0 olmalı.")
            currency = str(row.get("currency") or "USD").strip().upper()
            rows.append(
                {
                    "symbol": symbol,
                    "quantity": quantity,
                    "average_cost": average_cost,
                    "currency": currency,
                }
            )
        return rows


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import portfolio CSV into Wealth Core.")
    parser.add_argument("csv_path", type=Path, help="Path to portfolio CSV file")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report without writing transactions",
    )
    args = parser.parse_args(argv)

    if not args.csv_path.is_file():
        print(f"CSV bulunamadı: {args.csv_path}", file=sys.stderr)
        return 1

    try:
        rows = _parse_rows(args.csv_path)
    except ValueError as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    apply_local_secrets_to_env()
    try:
        client, user_id = create_admin_supabase_client()
    except SupabaseAdminClientError as exc:
        print(f"Supabase oturumu açılamadı: {exc}", file=sys.stderr)
        return 1

    wealth = WealthCoreService(client, user_id)
    wealth.ensure_default_portfolio()

    try:
        summary = import_portfolio_rows(wealth, rows, dry_run=args.dry_run)
    except (WealthValidationError, ValueError) as exc:
        print(f"İçe aktarma hatası: {exc}", file=sys.stderr)
        return 1

    mode = "DRY-RUN" if args.dry_run else "IMPORT"
    print(f"{mode} tamamlandı")
    print(f"  İçe aktarılan: {summary['imported']}")
    print(f"  Atlanan: {summary['skipped']}")
    for warning in summary["warnings"]:
        print(f"  Uyarı: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
