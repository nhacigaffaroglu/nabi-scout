from services.turkiye_fund_evidence_extract import mandate_uygun_tokens_present


def test_kira_sertifikalari_alone_does_not_make_pack_reusable():
    excerpts = (
        "Yabancı borsa yatırım fonlarının, kıymetli madenlerin ve "
        "döviz cinsi kira sertifikalarının dahil edilmesi mümkündür.",
    )
    assert mandate_uygun_tokens_present(excerpts) is False


def test_kira_sertifikalari_with_katilim_context_is_reusable():
    excerpts = (
        "Fon portföyü katılım ilkelerine uygun olarak yönetilir ve "
        "kira sertifikaları içerebilir.",
    )
    assert mandate_uygun_tokens_present(excerpts) is True


def test_explicit_faizsiz_finans_wording_is_reusable():
    excerpts = (
        "Fon portföyü faizsiz finans ilkelerine uygun şekilde yönetilir.",
    )
    assert mandate_uygun_tokens_present(excerpts) is True
