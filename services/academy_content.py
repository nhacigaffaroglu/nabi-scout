from __future__ import annotations

from typing import Any, Dict, Optional


METRICS: Dict[str, Dict[str, Any]] = {
    "roic": {
        "title": "ROIC — Yatırılan Sermayenin Getirisi",
        "short": "Şirketin kullandığı sermayeyi ne kadar verimli kazanca çevirdiğini gösterir.",
        "why": "Uzun vadeli kaliteli şirketler genellikle sermayelerini rakiplerinden daha verimli kullanır.",
        "why_you_care": (
            "Şirket aynı sermayeyle daha fazla kazanç üretebiliyorsa, "
            "büyümek için sürekli dışarıdan para bulmak zorunda kalmaz."
        ),
        "simple": (
            "Şirketin elindeki parayı iyi kullanıp kullanmadığını anlatır. "
            "Yüksek olması genellikle iyidir."
        ),
        "ranges": [
            ("Zayıf", "5% altı"),
            ("Orta", "5%–15%"),
            ("Güçlü", "15%–25%"),
            ("Çok güçlü", "25% üzeri"),
        ],
        "higher_is_better": True,
        "warning": "Bankalar ve finans şirketlerinde klasik ROIC karşılaştırması yanıltıcı olabilir.",
    },
    "revenue_cagr_3y": {
        "title": "3 Yıllık Gelir CAGR",
        "short": "Şirket satışlarının son üç yıldaki yıllık ortalama büyüme hızıdır.",
        "why": "Tek bir iyi yıl yerine büyümenin sürekliliğini gösterir.",
        "why_you_care": (
            "Gelir düzenli büyüyorsa şirketin ürün veya hizmetlerine olan talep "
            "uzun vadede daha sağlam olabilir."
        ),
        "simple": "Şirketin satışları her yıl ortalama ne kadar büyüyor, onu gösterir.",
        "ranges": [
            ("Zayıf", "0% altı"),
            ("Orta", "0%–8%"),
            ("Güçlü", "8%–15%"),
            ("Çok güçlü", "15% üzeri"),
        ],
        "higher_is_better": True,
        "warning": "Çok küçük şirketlerde yüksek büyüme daha kolay olabilir.",
    },
    "eps_cagr_3y": {
        "title": "3 Yıllık EPS CAGR",
        "short": "Hisse başına düşen kârın üç yıllık yıllık ortalama büyümesidir.",
        "why": "Şirket büyürken hissedar başına düşen kârın da büyüyüp büyümediğini gösterir.",
        "why_you_care": (
            "Toplam kâr artarken hisse sayısı da artıyorsa sana düşen pay büyümeyebilir. "
            "EPS bunu ayırt etmeye yardımcı olur."
        ),
        "simple": "Sahip olduğun her hisseye düşen kârın büyüme hızıdır.",
        "ranges": [
            ("Zayıf", "0% altı"),
            ("Orta", "0%–10%"),
            ("Güçlü", "10%–20%"),
            ("Çok güçlü", "20% üzeri"),
        ],
        "higher_is_better": True,
        "warning": "Hisse geri alımları EPS'yi operasyonel büyüme olmadan da artırabilir.",
    },
    "fcf_cagr_3y": {
        "title": "3 Yıllık Serbest Nakit Akışı Büyümesi",
        "short": "Şirketin zorunlu yatırımlar sonrası elinde kalan nakdin büyüme hızıdır.",
        "why": "Muhasebe kârından farklı olarak gerçekten kullanılabilir nakdi gösterir.",
        "why_you_care": (
            "Borç ödeme, temettü, geri alım ve yeni yatırım için şirketin gerçekten "
            "ne kadar para ürettiğini anlamanı sağlar."
        ),
        "simple": "Şirketin cebinde kalan gerçek paranın büyüme hızıdır.",
        "ranges": [
            ("Zayıf", "0% altı"),
            ("Orta", "0%–8%"),
            ("Güçlü", "8%–15%"),
            ("Çok güçlü", "15% üzeri"),
        ],
        "higher_is_better": True,
        "warning": "Büyük yatırım dönemlerinde geçici olarak zayıf olabilir.",
    },
    "free_cash_flow_margin": {
        "title": "FCF Marjı",
        "short": "Her 100 birim satıştan kaç birimin serbest nakit olarak kaldığını gösterir.",
        "why": "Satışların gerçek nakde dönüşme kalitesini ölçer.",
        "why_you_care": (
            "Şirket çok satış yapıyor olabilir; önemli olan bu satışlardan kasada ne kadar para kaldığıdır."
        ),
        "simple": "100 TL satıştan şirketin cebinde kaç TL kaldığını gösterir.",
        "ranges": [
            ("Zayıf", "0% altı"),
            ("Orta", "0%–10%"),
            ("Güçlü", "10%–20%"),
            ("Çok güçlü", "20% üzeri"),
        ],
        "higher_is_better": True,
        "warning": "Sermaye yoğun sektörlerde doğal olarak daha düşük olabilir.",
    },
    "debt_to_equity": {
        "title": "Borç / Özsermaye",
        "short": "Şirketin borcunun ortakların koyduğu sermayeye oranıdır.",
        "why": "Şirketin borca ne kadar bağımlı olduğunu gösterir.",
        "why_you_care": (
            "Yüksek borç, faizler arttığında veya satışlar düştüğünde şirketi zorlayabilir."
        ),
        "simple": "Şirket büyümeyi kendi parasıyla mı, borçla mı finanse ediyor, onu gösterir.",
        "ranges": [
            ("Çok iyi", "0,5 altı"),
            ("İyi", "0,5–1,0"),
            ("Orta", "1,0–2,0"),
            ("Zayıf", "2,0 üzeri"),
        ],
        "higher_is_better": False,
        "warning": "Bankalar ve finans şirketleri için sektör karşılaştırması gerekir.",
    },
    "interest_coverage": {
        "title": "Faiz Karşılama Oranı",
        "short": "Şirketin faaliyet kârının faiz giderini kaç kez karşılayabildiğini gösterir.",
        "why": "Borçların şirketi ne kadar zorladığını anlamaya yardım eder.",
        "why_you_care": (
            "Oran düşükse şirket faiz ödemelerinde zorlanabilir ve büyüme yatırımlarını kısmak zorunda kalabilir."
        ),
        "simple": "Şirketin kazancı, faiz borcunu kaç kez ödeyebiliyor?",
        "ranges": [
            ("Zayıf", "2x altı"),
            ("Orta", "2x–5x"),
            ("Güçlü", "5x–10x"),
            ("Çok güçlü", "10x üzeri"),
        ],
        "higher_is_better": True,
        "warning": "Döngüsel şirketlerde iyi yıllardaki oran yanıltıcı olabilir.",
    },
    "pe_ratio": {
        "title": "F/K — Fiyat / Kazanç",
        "short": "Hissenin yıllık kârının kaç katından işlem gördüğünü gösterir.",
        "why": "Piyasanın şirketin bugünkü kârına ne kadar fiyat biçtiğini anlatır.",
        "why_you_care": (
            "Kaliteli bir şirketi çok pahalı almak, uzun vadeli getiriyi azaltabilir."
        ),
        "simple": "Şirketi bugünkü kârının kaç katına satın aldığını gösterir.",
        "ranges": [
            ("Not", "Tek başına sabit iyi değer yoktur"),
            ("Karşılaştır", "Sektör ve tarihsel ortalama"),
        ],
        "higher_is_better": None,
        "warning": "Düşük F/K her zaman ucuzluk, yüksek F/K her zaman pahalılık değildir.",
    },
    "ev_to_ebit": {
        "title": "EV/EBIT",
        "short": "Şirketin borç ve nakit dahil toplam değerinin faaliyet kârına oranıdır.",
        "why": "Borç yapıları farklı şirketleri karşılaştırmada F/K'dan daha sağlıklı olabilir.",
        "why_you_care": (
            "Şirketin faaliyetlerinden ürettiği kâra göre ne kadar pahalı olduğunu anlamanı sağlar."
        ),
        "simple": "Şirketin tamamına ödediğin bedelin yıllık faaliyet kârının kaç katı olduğunu gösterir.",
        "ranges": [
            ("Çok iyi", "8 altı"),
            ("İyi", "8–12"),
            ("Orta", "12–18"),
            ("Pahalı", "18 üzeri"),
        ],
        "higher_is_better": False,
        "warning": "EBIT negatifse oran anlamlı değildir.",
    },
    "peg_ratio_calculated": {
        "title": "PEG",
        "short": "F/K oranını şirketin kâr büyüme hızına göre düzeltir.",
        "why": "Yüksek büyüyen şirketlerin yüksek F/K'sının makul olup olmadığını anlamaya yardım eder.",
        "why_you_care": (
            "Sadece ucuzluğu değil, ödediğin fiyat karşılığında aldığın büyümeyi de ölçer."
        ),
        "simple": "Şirketin fiyatını büyüme hızına göre değerlendirir.",
        "ranges": [
            ("Çok iyi", "1 altı"),
            ("İyi", "1–1,5"),
            ("Orta", "1,5–2"),
            ("Pahalı", "2 üzeri"),
        ],
        "higher_is_better": False,
        "warning": "Büyüme negatif veya sürdürülemezse PEG anlamsızdır.",
    },
    "price_to_fcf": {
        "title": "Fiyat / Serbest Nakit Akışı",
        "short": "Şirket değerinin ürettiği gerçek serbest nakdin kaç katı olduğunu gösterir.",
        "why": "Muhasebe kârı yerine gerçek nakit üretimine göre değerleme sağlar.",
        "why_you_care": (
            "Şirket kârlı görünse bile nakit üretmiyorsa fiyat pahalı olabilir."
        ),
        "simple": "Şirketin fiyatının cebinde kalan gerçek paranın kaç katı olduğunu gösterir.",
        "ranges": [
            ("Çok iyi", "12 altı"),
            ("İyi", "12–20"),
            ("Orta", "20–30"),
            ("Pahalı", "30 üzeri"),
        ],
        "higher_is_better": False,
        "warning": "Serbest nakit akışı negatifse oran anlamlı değildir.",
    },
    "data_completeness": {
        "title": "Veri Tamlığı",
        "short": "Scout'un analiz için ihtiyaç duyduğu verilerin yüzde kaçına ulaştığını gösterir.",
        "why": "Az veriyle oluşan sonuçlara gereğinden fazla güvenilmesini engeller.",
        "why_you_care": (
            "Puan yüksek olsa bile veri eksikse kararın güvenilirliği düşük olabilir."
        ),
        "simple": "Scout'un şirket hakkında ne kadar bilgiye sahip olduğunu gösterir.",
        "ranges": [
            ("Zayıf", "50% altı"),
            ("Orta", "50%–70%"),
            ("İyi", "70%–85%"),
            ("Çok iyi", "85% üzeri"),
        ],
        "higher_is_better": True,
        "warning": "Yüksek veri tamlığı şirketin iyi olduğu anlamına gelmez.",
    },
}


def get_metric(key: str) -> Optional[Dict[str, Any]]:
    return METRICS.get(key)


def interpret_metric(
    key: str,
    value: Optional[float],
) -> Dict[str, str]:
    if value is None:
        return {
            "label": "Veri yok",
            "tone": "neutral",
            "comment": "Bu şirket için yeterli veri bulunamadı.",
        }

    if key == "roic":
        if value >= 25:
            return {"label": "Çok güçlü", "tone": "positive", "comment": "Şirket sermayesini olağanüstü verimli kullanıyor."}
        if value >= 15:
            return {"label": "Güçlü", "tone": "positive", "comment": "Sermaye verimliliği uzun vadeli kalite açısından olumlu."}
        if value >= 5:
            return {"label": "Orta", "tone": "neutral", "comment": "Sermaye verimliliği orta seviyede."}
        return {"label": "Zayıf", "tone": "negative", "comment": "Şirket sermayesinden yeterli getiri üretemiyor."}

    if key in {"revenue_cagr_3y", "eps_cagr_3y", "fcf_cagr_3y"}:
        if value >= 15:
            return {"label": "Çok güçlü", "tone": "positive", "comment": "Büyüme dikkat çekici ve güçlü."}
        if value >= 8:
            return {"label": "Güçlü", "tone": "positive", "comment": "Büyüme sağlıklı seviyede."}
        if value >= 0:
            return {"label": "Sınırlı", "tone": "neutral", "comment": "Büyüme pozitif ancak güçlü değil."}
        return {"label": "Negatif", "tone": "negative", "comment": "Şirket küçülüyor veya ilgili metrik geriliyor."}

    if key == "free_cash_flow_margin":
        if value >= 20:
            return {"label": "Çok güçlü", "tone": "positive", "comment": "Satışlar çok güçlü biçimde nakde dönüşüyor."}
        if value >= 10:
            return {"label": "Güçlü", "tone": "positive", "comment": "Nakit üretim kalitesi iyi."}
        if value >= 0:
            return {"label": "Sınırlı", "tone": "neutral", "comment": "Nakit üretimi pozitif ancak sınırlı."}
        return {"label": "Negatif", "tone": "negative", "comment": "Şirket serbest nakit üretmiyor."}

    if key == "debt_to_equity":
        if value <= 0.5:
            return {"label": "Çok iyi", "tone": "positive", "comment": "Borçluluk çok kontrollü."}
        if value <= 1:
            return {"label": "İyi", "tone": "positive", "comment": "Borç seviyesi makul."}
        if value <= 2:
            return {"label": "İzlenmeli", "tone": "neutral", "comment": "Borçluluk orta seviyede."}
        return {"label": "Yüksek", "tone": "negative", "comment": "Borç şirket için önemli risk oluşturabilir."}

    if key == "interest_coverage":
        if value >= 10:
            return {"label": "Çok güçlü", "tone": "positive", "comment": "Faiz yükünü çok rahat karşılıyor."}
        if value >= 5:
            return {"label": "Güçlü", "tone": "positive", "comment": "Faiz ödeme kapasitesi iyi."}
        if value >= 2:
            return {"label": "İzlenmeli", "tone": "neutral", "comment": "Faiz yükü dikkatle izlenmeli."}
        return {"label": "Zayıf", "tone": "negative", "comment": "Faiz ödeme kapasitesi yetersiz olabilir."}

    if key == "ev_to_ebit":
        if value <= 0:
            return {"label": "Anlamsız", "tone": "neutral", "comment": "Negatif faaliyet kârı nedeniyle oran yorumlanamaz."}
        if value < 8:
            return {"label": "Cazip", "tone": "positive", "comment": "Faaliyet kârına göre değerleme düşük."}
        if value < 12:
            return {"label": "Makul", "tone": "positive", "comment": "Değerleme makul aralıkta."}
        if value < 18:
            return {"label": "Orta", "tone": "neutral", "comment": "Değerleme ne ucuz ne aşırı pahalı."}
        return {"label": "Yüksek", "tone": "negative", "comment": "Faaliyet kârına göre değerleme pahalı olabilir."}

    if key == "peg_ratio_calculated":
        if value <= 0:
            return {"label": "Anlamsız", "tone": "neutral", "comment": "Negatif büyüme nedeniyle oran yorumlanamaz."}
        if value < 1:
            return {"label": "Cazip", "tone": "positive", "comment": "Büyümeye göre değerleme cazip."}
        if value < 1.5:
            return {"label": "Makul", "tone": "positive", "comment": "Büyümeye göre değerleme makul."}
        if value < 2:
            return {"label": "Yüksekçe", "tone": "neutral", "comment": "Büyümeye göre fiyat biraz yüksek."}
        return {"label": "Pahalı", "tone": "negative", "comment": "Büyümeye göre değerleme pahalı olabilir."}

    if key == "price_to_fcf":
        if value <= 0:
            return {"label": "Anlamsız", "tone": "neutral", "comment": "Negatif serbest nakit nedeniyle oran yorumlanamaz."}
        if value < 12:
            return {"label": "Cazip", "tone": "positive", "comment": "Nakit üretimine göre değerleme düşük."}
        if value < 20:
            return {"label": "Makul", "tone": "positive", "comment": "Nakit üretimine göre değerleme makul."}
        if value < 30:
            return {"label": "Orta", "tone": "neutral", "comment": "Nakit üretimine göre değerleme yüksekçe."}
        return {"label": "Pahalı", "tone": "negative", "comment": "Nakit üretimine göre değerleme pahalı olabilir."}

    if key == "data_completeness":
        if value >= 85:
            return {"label": "Yüksek güven", "tone": "positive", "comment": "Analiz için veri kapsamı güçlü."}
        if value >= 70:
            return {"label": "İyi", "tone": "positive", "comment": "Analiz kullanılabilir veri kapsamına sahip."}
        if value >= 50:
            return {"label": "Orta", "tone": "neutral", "comment": "Ek veri doğrulaması faydalı olur."}
        return {"label": "Düşük", "tone": "negative", "comment": "Bu sonuca güvenmek için veri yetersiz."}

    return {
        "label": "Bağlama göre değerlendir",
        "tone": "neutral",
        "comment": "Sektör, şirket geçmişi ve diğer metriklerle birlikte yorumlanmalıdır.",
    }
