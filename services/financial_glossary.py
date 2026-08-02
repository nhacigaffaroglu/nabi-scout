from __future__ import annotations

from typing import Any, Dict, Optional


GLOSSARY: Dict[str, Dict[str, Any]] = {
    "roic": {
        "title": "ROIC — Yatırılan Sermayenin Getirisi",
        "simple": (
            "Şirketin kullandığı parayı ne kadar verimli biçimde "
            "kazanca dönüştürdüğünü gösterir."
        ),
        "why": (
            "Uzun vadede servet üreten şirketler, aynı sermayeyle "
            "rakiplerinden daha fazla faaliyet kârı yaratabilir."
        ),
        "good_range": {
            "weak": "5% altı",
            "average": "5%–15%",
            "good": "15%–25%",
            "excellent": "25% üzeri",
        },
        "better": "higher",
        "caution": (
            "Bankalar ve finans şirketlerinde klasik ROIC karşılaştırması "
            "yanıltıcı olabilir."
        ),
        "analogy": (
            "100 TL'lik makineye yatırım yapan iki şirketten biri yılda "
            "5 TL, diğeri 25 TL kazanıyorsa ikinci şirket sermayeyi daha "
            "verimli kullanıyordur."
        ),
    },
    "roe": {
        "title": "ROE — Özsermaye Getirisi",
        "simple": (
            "Ortakların şirkete koyduğu paranın ne kadar kazanç "
            "ürettiğini gösterir."
        ),
        "why": (
            "Şirketin hissedar sermayesini verimli kullanıp kullanmadığını "
            "anlamaya yardımcı olur."
        ),
        "good_range": {
            "weak": "8% altı",
            "average": "8%–15%",
            "good": "15%–25%",
            "excellent": "25% üzeri",
        },
        "better": "higher",
        "caution": "Yüksek borç, ROE'yi yapay biçimde yükseltebilir.",
        "analogy": (
            "Bir işletmeye koyduğun 100 TL'nin yılda kaç TL net kâr "
            "ürettiğini anlatır."
        ),
    },
    "revenue_cagr_3y": {
        "title": "3 Yıllık Gelir CAGR — Bileşik Gelir Büyümesi",
        "simple": (
            "Şirket satışlarının son üç yılda yıllık ortalama ne hızda "
            "büyüdüğünü gösterir."
        ),
        "why": (
            "Tek bir iyi yıl yerine büyümenin sürekliliğini ölçer."
        ),
        "good_range": {
            "weak": "0% altı",
            "average": "0%–8%",
            "good": "8%–15%",
            "excellent": "15% üzeri",
        },
        "better": "higher",
        "caution": (
            "Çok yüksek büyüme küçük şirketlerde daha kolaydır; sektör ve "
            "şirket büyüklüğüyle birlikte değerlendirilmelidir."
        ),
        "analogy": (
            "Bir dükkânın cirosunun üç yıl boyunca her yıl ortalama ne "
            "kadar arttığını gösterir."
        ),
    },
    "eps_cagr_3y": {
        "title": "3 Yıllık EPS CAGR — Hisse Başına Kâr Büyümesi",
        "simple": (
            "Her bir hissenin temsil ettiği kârın son üç yıldaki yıllık "
            "ortalama büyümesidir."
        ),
        "why": (
            "Gelir artarken hissedar başına düşen kârın da büyüyüp "
            "büyümediğini gösterir."
        ),
        "good_range": {
            "weak": "0% altı",
            "average": "0%–10%",
            "good": "10%–20%",
            "excellent": "20% üzeri",
        },
        "better": "higher",
        "caution": (
            "Hisse geri alımı EPS'yi artırabilir; büyümenin yalnızca "
            "operasyonlardan gelip gelmediği kontrol edilmelidir."
        ),
        "analogy": (
            "Pastanın tamamı değil, sahip olduğun her dilime düşen payın "
            "ne kadar büyüdüğünü anlatır."
        ),
    },
    "fcf_cagr_3y": {
        "title": "3 Yıllık FCF CAGR — Serbest Nakit Akışı Büyümesi",
        "simple": (
            "Şirketin tüm zorunlu yatırımlardan sonra elinde kalan nakdin "
            "üç yıllık büyüme hızıdır."
        ),
        "why": (
            "Muhasebe kârından farklı olarak borç ödeme, temettü, geri alım "
            "ve yeni yatırım için gerçekten kullanılabilecek parayı ölçer."
        ),
        "good_range": {
            "weak": "0% altı",
            "average": "0%–8%",
            "good": "8%–15%",
            "excellent": "15% üzeri",
        },
        "better": "higher",
        "caution": (
            "Büyük yatırım dönemlerinde geçici olarak negatif olabilir."
        ),
        "analogy": (
            "Maaştan kira, fatura ve zorunlu giderler çıktıktan sonra "
            "elinde kalan para gibidir."
        ),
    },
    "free_cash_flow_margin": {
        "title": "FCF Marjı — Serbest Nakit Akışı Marjı",
        "simple": (
            "Her 100 birim satışın kaç biriminin serbest nakit olarak "
            "kaldığını gösterir."
        ),
        "why": (
            "Şirketin satışlarını gerçek nakde dönüştürme kalitesini ölçer."
        ),
        "good_range": {
            "weak": "0% altı",
            "average": "0%–10%",
            "good": "10%–20%",
            "excellent": "20% üzeri",
        },
        "better": "higher",
        "caution": "Sermaye yoğun sektörlerde doğal olarak daha düşük olabilir.",
        "analogy": (
            "100 TL satıştan tüm zorunlu harcamalar sonrası kaç TL kaldığıdır."
        ),
    },
    "debt_to_equity": {
        "title": "Borç / Özsermaye",
        "simple": (
            "Şirketin borcunun, ortakların koyduğu sermayeye oranını gösterir."
        ),
        "why": (
            "Finansal riskin ve şirketin borca ne kadar bağımlı olduğunun "
            "temel göstergelerinden biridir."
        ),
        "good_range": {
            "excellent": "0,5 altı",
            "good": "0,5–1,0",
            "average": "1,0–2,0",
            "weak": "2,0 üzeri",
        },
        "better": "lower",
        "caution": (
            "Bankalar ve finans şirketleri borçla çalıştığı için sektör "
            "karşılaştırması zorunludur."
        ),
        "analogy": (
            "Bir evin ne kadarının kendi paranla, ne kadarının krediyle "
            "alındığını gösterir."
        ),
    },
    "interest_coverage": {
        "title": "Faiz Karşılama Oranı",
        "simple": (
            "Şirketin faaliyet kârının faiz giderini kaç kez ödeyebildiğini "
            "gösterir."
        ),
        "why": (
            "Borçların şirketi zorlayıp zorlamadığını anlamaya yardımcı olur."
        ),
        "good_range": {
            "weak": "2x altı",
            "average": "2x–5x",
            "good": "5x–10x",
            "excellent": "10x üzeri",
        },
        "better": "higher",
        "caution": "Döngüsel sektörlerde iyi yıllardaki oran yanıltıcı olabilir.",
        "analogy": (
            "Aylık gelirinin kredi faizini kaç kez karşılayabildiği gibidir."
        ),
    },
    "pe_ratio": {
        "title": "F/K — Fiyat / Kazanç Oranı",
        "simple": (
            "Hissenin yıllık kârının kaç katından işlem gördüğünü gösterir."
        ),
        "why": (
            "Piyasanın şirketin mevcut kârına ne kadar fiyat biçtiğini "
            "anlamaya yardım eder."
        ),
        "good_range": {
            "excellent": "Tek başına sabit bir iyi değer yok",
            "good": "Sektör ve büyümeye göre değerlendirilir",
            "average": "Tarihsel ortalamayla karşılaştırılır",
            "weak": "Negatif kârda anlamlı değildir",
        },
        "better": "context",
        "caution": (
            "Düşük F/K her zaman ucuzluk, yüksek F/K her zaman pahalılık "
            "anlamına gelmez."
        ),
        "analogy": (
            "Bir dükkânı, bugünkü yıllık kazancının kaç katına satın aldığını "
            "gösterir."
        ),
    },
    "ev_to_ebit": {
        "title": "EV/EBIT — Şirket Değeri / Faaliyet Kârı",
        "simple": (
            "Şirketin borç ve nakdi de dikkate alınmış toplam değerinin, "
            "faaliyet kârına oranıdır."
        ),
        "why": (
            "Sermaye yapıları farklı şirketleri F/K'ya göre daha sağlıklı "
            "karşılaştırabilir."
        ),
        "good_range": {
            "excellent": "8 altı",
            "good": "8–12",
            "average": "12–18",
            "weak": "18 üzeri",
        },
        "better": "lower",
        "caution": (
            "EBIT negatifse oran ekonomik olarak anlamlı değildir."
        ),
        "analogy": (
            "İşletmenin tamamına ödediğin bedelin, yıllık faaliyet kazancının "
            "kaç katı olduğunu gösterir."
        ),
    },
    "peg_ratio_calculated": {
        "title": "PEG — F/K'nın Büyümeye Göre Düzeltilmiş Hâli",
        "simple": (
            "F/K oranını şirketin kâr büyüme hızına böler."
        ),
        "why": (
            "Yüksek büyüyen bir şirketin yüksek F/K'sının makul olup "
            "olmadığını değerlendirmeye yardım eder."
        ),
        "good_range": {
            "excellent": "1 altı",
            "good": "1–1,5",
            "average": "1,5–2",
            "weak": "2 üzeri",
        },
        "better": "lower",
        "caution": (
            "Büyüme negatif veya sürdürülemezse PEG anlamsızlaşır."
        ),
        "analogy": (
            "Bir ürünün fiyatını yalnızca bugünkü kalitesine değil, gelişme "
            "hızına göre de değerlendirmek gibidir."
        ),
    },
    "price_to_fcf": {
        "title": "Fiyat / Serbest Nakit Akışı",
        "simple": (
            "Şirket değerinin ürettiği serbest nakdin kaç katı olduğunu gösterir."
        ),
        "why": (
            "Muhasebe kârı yerine şirketin gerçek nakit üretimine göre "
            "değerlemeyi sağlar."
        ),
        "good_range": {
            "excellent": "12 altı",
            "good": "12–20",
            "average": "20–30",
            "weak": "30 üzeri",
        },
        "better": "lower",
        "caution": "FCF negatifse oran anlamlı değildir.",
        "analogy": (
            "Bir işletmenin fiyatının, sahibine kalan yıllık nakdin kaç katı "
            "olduğunu gösterir."
        ),
    },
    "data_completeness": {
        "title": "Veri Tamlığı",
        "simple": (
            "Scout'un puanlama için ihtiyaç duyduğu verilerin yüzde kaçına "
            "ulaşabildiğini gösterir."
        ),
        "why": (
            "Az veriyle oluşan yüksek puanlara gereğinden fazla güvenilmesini "
            "engeller."
        ),
        "good_range": {
            "weak": "50% altı",
            "average": "50%–70%",
            "good": "70%–85%",
            "excellent": "85% üzeri",
        },
        "better": "higher",
        "caution": (
            "Veri tamlığının yüksek olması şirketin iyi olduğu anlamına gelmez; "
            "yalnızca değerlendirmenin daha güvenilir olduğunu gösterir."
        ),
        "analogy": (
            "Bir doktorun teşhis için gerekli testlerin ne kadarına sahip "
            "olduğunu gösterir."
        ),
    },
}


def get_metric(key: str) -> Optional[Dict[str, Any]]:
    return GLOSSARY.get(key)


def interpret_value(
    key: str,
    value: Optional[float],
) -> str:
    if value is None:
        return "Bu şirket için yeterli veri bulunamadı."

    metric = GLOSSARY.get(key)
    if not metric:
        return "Bu metrik için otomatik yorum bulunmuyor."

    if key == "roic":
        if value >= 25:
            return "Olağanüstü sermaye verimliliği."
        if value >= 15:
            return "Güçlü sermaye verimliliği."
        if value >= 5:
            return "Orta düzey sermaye verimliliği."
        return "Zayıf sermaye verimliliği."

    if key in {"revenue_cagr_3y", "eps_cagr_3y", "fcf_cagr_3y"}:
        if value >= 15:
            return "Güçlü ve dikkat çekici büyüme."
        if value >= 8:
            return "Sağlıklı büyüme."
        if value >= 0:
            return "Sınırlı büyüme."
        return "Küçülme veya negatif trend."

    if key == "debt_to_equity":
        if value <= 0.5:
            return "Borçluluk çok kontrollü."
        if value <= 1:
            return "Borçluluk makul."
        if value <= 2:
            return "Borçluluk izlenmeli."
        return "Borçluluk yüksek."

    if key == "interest_coverage":
        if value >= 10:
            return "Faiz yükünü çok rahat karşılıyor."
        if value >= 5:
            return "Faiz karşılama güçlü."
        if value >= 2:
            return "Faiz yükü izlenmeli."
        return "Faiz ödeme kapasitesi zayıf."

    if key in {"ev_to_ebit", "price_to_fcf"}:
        if value <= 0:
            return "Negatif kâr veya nakit nedeniyle oran anlamlı değil."
        if value < 12:
            return "Değerleme görece makul."
        if value < 20:
            return "Değerleme orta seviyede."
        return "Değerleme yüksek olabilir."

    if key == "peg_ratio_calculated":
        if value <= 0:
            return "Negatif veya anlamsız büyüme nedeniyle yorumlanamaz."
        if value < 1:
            return "Büyümeye göre cazip değerleme."
        if value < 1.5:
            return "Büyümeye göre makul değerleme."
        if value < 2:
            return "Büyümeye göre yüksekçe değerleme."
        return "Büyümeye göre pahalı olabilir."

    if key == "data_completeness":
        if value >= 85:
            return "Analizin veri güveni yüksek."
        if value >= 70:
            return "Analizin veri güveni iyi."
        if value >= 50:
            return "Analiz ek doğrulama gerektiriyor."
        return "Bu puana güvenmek için veri yetersiz."

    return "Değer sektör ve şirket geçmişiyle birlikte yorumlanmalıdır."
