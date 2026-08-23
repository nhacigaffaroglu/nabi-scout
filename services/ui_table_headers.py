"""Turkish display labels for user-facing tables. DB columns stay English."""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

COLUMN_LABELS_TR: dict[str, str] = {
    "symbol": "Sembol",
    "company_name": "Şirket",
    "asset_type": "Varlık Türü",
    "market": "Piyasa",
    "current_price": "Güncel Fiyat",
    "fair_value": "Adil Değer",
    "discount_to_fair_value": "Adil Değere İskonto",
    "nabi_score": "NABI Score",
    "decision": "Karar",
    "decision_label": "Karar",
    "participation_status": "Katılım Durumu",
    "research_status": "Araştırma Durumu",
    "pipeline_stage": "Aşama",
    "currency": "Para Birimi",
    "country": "Ülke",
    "sector_theme": "Sektör / Tema",
    "data_completeness": "Veri Tamlığı",
    "data_source": "Veri Kaynağı",
    "cik": "CIK",
    "universe_name": "Evren",
    "is_etf": "ETF",
    "is_selected": "Seçili",
    "rank": "Sıra",
    "started_at": "Başlangıç",
    "finished_at": "Bitiş",
    "completed_at": "Bitiş",
    "status": "Durum",
    "created_at": "Oluşturma",
    "updated_at": "Güncelleme",
    "institution": "Kurum",
    "quantity": "Adet",
    "market_value": "Piyasa Değeri",
    "weight_pct": "Portföy Payı",
    "cost_basis": "Maliyet",
    "unrealized_pl": "K/Z",
    "pl_pct": "K/Z %",
    "error_message": "Hata",
    "total_symbols": "Toplam Sembol",
    "selected_symbols": "Seçilen Sembol",
    "cik_coverage": "CIK Kapsamı",
}


def label_for_column(column: str) -> str:
    key = str(column or "").strip()
    return COLUMN_LABELS_TR.get(key, key)


def relabel_columns(columns: Iterable[str]) -> list[str]:
    return [label_for_column(column) for column in columns]


def relabel_mapping(row: Mapping[str, object]) -> dict[str, object]:
    return {label_for_column(key): value for key, value in row.items()}


def apply_display_headers(frame, *, columns: Sequence[str] | None = None):
    """Rename DataFrame columns for display. Leaves the source mapping intact."""
    visible = list(columns) if columns is not None else list(frame.columns)
    renamed = frame[visible].rename(columns={column: label_for_column(column) for column in visible})
    return renamed
