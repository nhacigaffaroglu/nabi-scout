from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from services.fmp_client import FMPError, normalize_fmp_error_class


OPERATION_LABELS_TR: Dict[str, str] = {
    "profile": "Şirket profili",
    "income_quarterly": "Çeyreklik gelir tablosu",
    "balance_quarterly": "Çeyreklik bilanço",
    "cashflow_quarterly": "Çeyreklik nakit akışı",
    "ratios_ttm": "TTM oranları",
    "key_metrics_ttm": "TTM temel metrikler",
    "ratios_history": "Tarihsel oranlar",
    "key_metrics_history": "Tarihsel temel metrikler",
    "stock_peers": "Rakip listesi",
    "stock_news": "Hisse haberleri",
    "earnings_surprises": "Kazanç sürprizleri",
    "earnings_calendar": "Kazanç takvimi",
    "historical_price_eod_light": "Tarihsel fiyat verisi",
}


FAILURE_CATEGORY_MESSAGES_TR: Dict[str, str] = {
    "AUTH": "Kimlik doğrulama hatası.",
    "PLAN_RESTRICTED": "Mevcut abonelik planında bu uç nokta kullanılamıyor.",
    "RATE_LIMIT": "Sağlayıcı hız sınırına takıldı.",
    "NOT_FOUND": "Sağlayıcı kaydı bulunamadı.",
    "BAD_REQUEST": "Geçersiz istek.",
    "PROVIDER_ERROR": "Sağlayıcı geçici veya bilinmeyen hata döndürdü.",
    "NETWORK": "Ağ veya zaman aşımı hatası.",
    "PARSE": "Sağlayıcı yanıtı çözümlenemedi.",
    "EMPTY_DATA": "Sağlayıcı boş yanıt döndürdü.",
}


@dataclass(frozen=True)
class ProviderDiagnostic:
    provider: str
    operation: str
    failure_category: str
    user_message_tr: str
    http_status: Optional[int] = None
    retryable: bool = False
    endpoint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "provider": self.provider,
            "operation": self.operation,
            "failure_category": self.failure_category,
            "user_message_tr": self.user_message_tr,
            "retryable": self.retryable,
        }
        if self.http_status is not None:
            payload["http_status"] = self.http_status
        if self.endpoint:
            payload["endpoint"] = self.endpoint
        return payload


def _operation_label(operation: str) -> str:
    if operation in OPERATION_LABELS_TR:
        return OPERATION_LABELS_TR[operation]
    if operation.startswith("peer_ratios_ttm:"):
        peer = operation.split(":", 1)[1]
        return f"Rakip TTM oranları ({peer})"
    return operation.replace("_", " ")


def _category_message(category: str) -> str:
    return FAILURE_CATEGORY_MESSAGES_TR.get(category, "Sağlayıcı hatası.")


def _is_retryable(category: str) -> bool:
    return category in {"RATE_LIMIT", "PROVIDER_ERROR", "NETWORK"}


def diagnostic_from_fmp_error(operation: str, exc: FMPError) -> ProviderDiagnostic:
    category = normalize_fmp_error_class(exc.error_class)
    operation_label = _operation_label(operation)
    category_message = _category_message(category)
    return ProviderDiagnostic(
        provider="fmp",
        operation=operation,
        failure_category=category,
        user_message_tr=f"{operation_label}: {category_message}",
        http_status=exc.status_code,
        retryable=_is_retryable(category),
        endpoint=exc.endpoint,
    )


def diagnostic_from_failure_token(failure: str) -> Optional[ProviderDiagnostic]:
    if failure.startswith("earnings_calendar:foreign_symbol_rows:"):
        count = failure.rsplit(":", 1)[-1]
        return ProviderDiagnostic(
            provider="fmp",
            operation="earnings_calendar",
            failure_category="SYMBOL_MISMATCH",
            user_message_tr=(
                f"Kazanç takvimi yanıtı {count} yabancı sembol satırı içeriyordu; "
                "filtrelendi."
            ),
            retryable=False,
            endpoint="earnings-calendar",
        )
    if ":" not in failure:
        return None
    operation, error_class = failure.split(":", 1)
    category = normalize_fmp_error_class(error_class)
    return ProviderDiagnostic(
        provider="fmp",
        operation=operation,
        failure_category=category,
        user_message_tr=f"{_operation_label(operation)}: {_category_message(category)}",
        retryable=_is_retryable(category),
    )


def build_provider_diagnostics(
    failures: Iterable[str],
    *,
    recorded: Optional[Iterable[ProviderDiagnostic]] = None,
) -> Tuple[ProviderDiagnostic, ...]:
    items: List[ProviderDiagnostic] = []
    seen: set[Tuple[str, str, str]] = set()
    for diagnostic in recorded or ():
        key = (diagnostic.provider, diagnostic.operation, diagnostic.failure_category)
        if key in seen:
            continue
        seen.add(key)
        items.append(diagnostic)
    for failure in failures:
        diagnostic = diagnostic_from_failure_token(failure)
        if diagnostic is None:
            continue
        key = (diagnostic.provider, diagnostic.operation, diagnostic.failure_category)
        if key in seen:
            continue
        seen.add(key)
        items.append(diagnostic)
    return tuple(items)


def format_provider_limitation_tr(diagnostic: ProviderDiagnostic) -> str:
    return diagnostic.user_message_tr


def format_fmp_exception_limitation(operation: str, exc: Exception) -> str:
    if isinstance(exc, FMPError):
        return diagnostic_from_fmp_error(operation, exc).user_message_tr
    return f"{_operation_label(operation)}: {exc.__class__.__name__}"
