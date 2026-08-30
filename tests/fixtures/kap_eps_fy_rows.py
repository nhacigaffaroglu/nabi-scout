"""Captured KAP FY EPS typed-dimension shapes. Not live issuer authority."""

from __future__ import annotations


def _wrap(body: str, *, fy: bool = True) -> str:
    if fy:
        current = "Cari Dönem 01.01.2025 - 31.12.2025"
        prior = "Önceki Dönem 01.01.2024 - 31.12.2024"
        bs_current = "Cari Dönem<br>31.12.2025"
        bs_prior = "Önceki Dönem<br>31.12.2024"
        year = "2025"
        period = "4"
    else:
        current = "Cari Dönem 01.01.2026 - 30.06.2026"
        prior = "Önceki Dönem 01.01.2025 - 30.06.2025"
        bs_current = "Cari Dönem<br>30.06.2026"
        bs_prior = "Önceki Dönem<br>31.12.2025"
        year = "2026"
        period = "2"
    return f"""
<html>
  <div>Gönderim Tarihi:24.02.2026 18:27:36</div>
  <div>Yıl:{year}</div>
  <div>Periyot:{period}</div>
  <table class="financial-header-table">
    <tr><td>Sunum Para Birimi</td><td>1.000 TL</td></tr>
    <tr><td>Finansal Tablo Niteliği</td><td>Konsolide</td></tr>
  </table>
  <table class="financial-table">
    <tr>
      <td class="context-header">{bs_current}</td>
      <td class="context-header">{bs_prior}</td>
    </tr>
    <tr class="data-input-row">
      <td class="taxonomy-field-name-cell">
        <div class="gwt-Label taxonomy-field-name">ifrs-full_Equity|</div>
      </td>
      <td class="taxonomy-field-title">
        <div class="gwt-Label multi-language-content content-tr">Özkaynaklar</div>
      </td>
      <td class="taxonomy-context-value">80.000.000</td>
      <td class="taxonomy-context-value">70.000.000</td>
    </tr>
  </table>
  <table class="financial-table">
    <tr>
      <td class="context-header">{current}</td>
      <td class="context-header">{prior}</td>
    </tr>
    <tr class="data-input-row">
      <td class="taxonomy-field-name-cell">
        <div class="gwt-Label taxonomy-field-name">ifrs-full_Revenue|</div>
      </td>
      <td class="taxonomy-field-title">
        <div class="gwt-Label multi-language-content content-tr">Hasılat</div>
      </td>
      <td class="taxonomy-context-value">120.000.000</td>
      <td class="taxonomy-context-value">100.000.000</td>
    </tr>
    {body}
  </table>
</html>
"""


def _concept_row(concept: str, label: str) -> str:
    return f"""
    <tr class="typed-dimension-row">
      <td class="taxonomy-field-name-cell">
        <div class="gwt-Label taxonomy-field-name">{concept}|http://www.xbrl.org/2003/role/terseLabel</div>
      </td>
      <td class="taxonomy-field-title">
        <div class="gwt-Label multi-language-content content-tr">{label}</div>
      </td>
    </tr>
    """


def _typed_row(caption: str, current: str, prior: str, footnote: str = "") -> str:
    return f"""
    <tr class="new-type-row">
      <td class="bordered-cell">
        <div class="taxonomy-label-field typed-dimension-field-caption">{caption}</div>
      </td>
      <td class="taxonomy-footnote-cell"><div class="taxonomy-footnote-value">{footnote}</div></td>
      <td class="taxonomy-context-value">{current}</td>
      <td class="taxonomy-context-value">{prior}</td>
    </tr>
    """


def asels_unresolved_eps_html() -> str:
    return _wrap(
        _concept_row(
            "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations",
            "Sürdürülen Faaliyetlerden Pay Başına Kazanç (Zarar)",
        )
        + _typed_row(
            "Sürdürülen Faaliyetlerden Pay Başına Kazanç (Zarar)",
            "656,79000000",
            "439,14000000",
        )
        + _concept_row(
            "ifrs-full_DilutedEarningsLossPerShareFromContinuingOperations",
            "Sürdürülen Faaliyetlerden Sulandırılmış Pay Başına Kazanç (Zarar)",
        )
        + _typed_row(
            "Sürdürülen Faaliyetlerden Sulandırılmış Pay Başına Kazanç (Zarar)",
            "656,79000000",
            "439,14000000",
        )
    )


def bimas_tam_tl_eps_html() -> str:
    return _wrap(
        _concept_row(
            "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations",
            "Sürdürülen Faaliyetlerden Pay Başına Kazanç (Zarar)",
        )
        + _typed_row(
            "Sürdürülen Faaliyetler Pay Başına Kazanç (Tam TL)",
            "31,12000000",
            "40,77000000",
            "26",
        )
        + _concept_row(
            "ifrs-full_DilutedEarningsLossPerShareFromContinuingOperations",
            "Sürdürülen Faaliyetlerden Sulandırılmış Pay Başına Kazanç (Zarar)",
        )
    )


def tuprs_one_kr_eps_html() -> str:
    return _wrap(
        _concept_row(
            "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations",
            "Sürdürülen Faaliyetlerden Pay Başına Kazanç (Zarar)",
        )
        + _typed_row(
            "Nominal değeri 1 kr. olan pay başına kazanç (zarar) (kr.)",
            "15,32000000",
            "12,44000000",
            "27",
        )
    )


def hundred_shares_of_one_kr_html() -> str:
    return _wrap(
        _concept_row(
            "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations",
            "Sürdürülen Faaliyetlerden Pay Başına Kazanç (Zarar)",
        )
        + _typed_row(
            "Nominal değeri 1 Kr olan 100 adet pay başına kazanç (TRY)",
            "6,56000000",
            "4,39000000",
        )
    )


def diluted_preferred_html() -> str:
    return _wrap(
        _concept_row(
            "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations",
            "Sürdürülen Faaliyetlerden Pay Başına Kazanç (Zarar)",
        )
        + _typed_row("Pay başına kazanç (Tam TL)", "10,00000000", "8,00000000")
        + _concept_row(
            "ifrs-full_DilutedEarningsLossPerShareFromContinuingOperations",
            "Sürdürülen Faaliyetlerden Sulandırılmış Pay Başına Kazanç (Zarar)",
        )
        + _typed_row("Sulandırılmış pay başına kazanç (Tam TL)", "9,50000000", "7,50000000")
    )


def ytd_eps_html() -> str:
    return _wrap(
        _concept_row(
            "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations",
            "Sürdürülen Faaliyetlerden Pay Başına Kazanç (Zarar)",
        )
        + _typed_row("Sürdürülen Faaliyetler Pay Başına Kazanç (Tam TL)", "4,00000000", "3,00000000"),
        fy=False,
    )


def official_nested_empty_parent_eps_html() -> str:
    """Live KAP shape: nested title <tr> plus empty parent value cells."""
    return _wrap(
        """
    <tr class="typed-dimension-row with-plus-row data-input-row">
      <td class="taxonomy-field-name-cell">
        <div class="gwt-Label taxonomy-field-name">ifrs-full_BasicEarningsLossPerShareFromContinuingOperations|http://www.xbrl.org/2003/role/terseLabel</div>
      </td>
      <td class="taxonomy-nondimensional-context-cell"></td>
      <td class="taxonomy-field-title">
        <table class="taxonomy-title-panel">
          <tr>
            <td>
              <div class="gwt-Label multi-language-content content-tr typed-dimension-field-label">
                Sürdürülen Faaliyetlerden Pay Başına Kazanç (Zarar)
              </div>
            </td>
          </tr>
        </table>
      </td>
      <td class="taxonomy-footnote-cell"><div class="taxonomy-footnote-value"></div></td>
      <td class="taxonomy-context-value"><div class="typed-dimension-field-value"></div></td>
      <td class="taxonomy-context-value"><div class="typed-dimension-field-value"></div></td>
    </tr>
    <tr class="new-type-row">
      <td></td>
      <td></td>
      <td class="bordered-cell">
        <div class="taxonomy-label-field typed-dimension-field-caption">Sürdürülen Faaliyetler Pay Başına Kazanç (Tam TL)</div>
      </td>
      <td class="taxonomy-footnote-cell"><div class="taxonomy-footnote-value">26</div></td>
      <td class="taxonomy-context-value"><div class="taxonomy-label-field align-right-important">31,12000000</div></td>
      <td class="taxonomy-context-value"><div class="taxonomy-label-field align-right-important">40,77000000</div></td>
    </tr>
        """
    )


def tuprs_headers_only_html() -> str:
    return _wrap(
        _concept_row(
            "ifrs-full_BasicEarningsLossPerShareFromContinuingOperations",
            "Sürdürülen Faaliyetlerden Pay Başına Kazanç (Zarar)",
        )
        + _concept_row(
            "ifrs-full_DilutedEarningsLossPerShareFromContinuingOperations",
            "Sürdürülen Faaliyetlerden Sulandırılmış Pay Başına Kazanç (Zarar)",
        )
    )
