"""
Binderim Marketplace Bot
========================
- PC (PriceCharting) fiyatı altındaki ilanları tarar
- Yeni ilanlar Telegram'a anlık bildirim gönderir
- Daha önce bildirilmiş ilanları tekrar bildirmez
- Her 2 saatte bir çalışır

Gereksinimler:
  pip install playwright beautifulsoup4 requests
  playwright install chromium

Kullanım:
  python binderim_bot.py
"""

import json
import os
import time
import hashlib
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# ─── Ayarlar ──────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN  = "8989163707:AAHEaZqB_oRPpx_XpkaTM2VDxelgKWYXU8I"
TELEGRAM_CHATID = "7400523147"

TARAMA_ARALIGI_SAAT = 2
SAYFA_BASINA_ILAN   = 100
TOPLAM_SAYFA        = 5
GECIKME_SANIYE      = 2
GORULMUS_DOSYA      = "gorulmus_ilanlar.json"

OYUNLAR = {
    1: "Pokémon TCG",
    2: "One Piece TCG",
}

# ─── Telegram Bildirim ────────────────────────────────────────────────────────

def telegram_gonder(mesaj: str):
    """Telegram'a mesaj gönderir."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHATID,
            "text": mesaj,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        r = requests.post(url, data=data, timeout=10)
        if not r.ok:
            print(f"  ⚠️  Telegram hata: {r.text}")
    except Exception as e:
        print(f"  ⚠️  Telegram gönderilemedi: {e}")


def ilan_telegram_mesaji(ilan: dict) -> str:
    """İlan için Telegram mesajı oluşturur."""
    onaylı = " ✅ <b>Onaylı Satıcı</b>" if ilan.get("onaylı") else ""
    fark = abs(ilan['fark_yuzde'])
    dil = ilan.get('dil', '')
    kondisyon = ilan.get('kondisyon', '')

    mesaj = (
        f"🔥 <b>YENİ FIRSAT — {ilan['oyun']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🃏 <b>{ilan['kart_adi']}</b>\n"
        f"💰 Fiyat: <b>₺{ilan['fiyat']:,.0f}</b>\n"
        f"📊 Adil Fiyat: ₺{ilan['adil_fiyat']:,.0f}  (-%{fark:.1f})\n"
        f"🏷 Kondisyon: {kondisyon} {dil}\n"
        f"👤 Satıcı: {ilan['satici']}{onaylı}\n"
        f"🔗 <a href=\"{ilan['kart_url']}\">İlana Git</a>"
    )
    return mesaj


# ─── Yardımcı Fonksiyonlar ────────────────────────────────────────────────────

def ilan_id_olustur(ilan: dict) -> str:
    ham = f"{ilan['kart_adi']}|{ilan['satici']}|{ilan['fiyat']}|{ilan['kondisyon']}|{ilan['dil']}"
    return hashlib.md5(ham.encode()).hexdigest()


def gorulmus_yukle() -> set:
    if os.path.exists(GORULMUS_DOSYA):
        with open(GORULMUS_DOSYA, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def gorulmus_kaydet(gorulmus: set):
    with open(GORULMUS_DOSYA, "w", encoding="utf-8") as f:
        json.dump(list(gorulmus), f, ensure_ascii=False, indent=2)


def fiyat_parse(fiyat_str: str) -> float:
    try:
        temiz = fiyat_str.replace("₺", "").replace(".", "").replace(",", ".").strip()
        return float(temiz)
    except Exception:
        return 0.0


def yuzde_parse(yuzde_str: str) -> float:
    try:
        temiz = yuzde_str.replace("−", "-").replace("+", "").replace("%", "").replace(",", ".").strip()
        return float(temiz)
    except Exception:
        return 0.0


# ─── Scraping ─────────────────────────────────────────────────────────────────

def sayfa_cek(page, oyun_id: int, sayfa_no: int) -> str:
    url = (
        f"https://binderim.com/Marketplace"
        f"?gameId={oyun_id}"
        f"&sort=price-asc"
        f"&pageSize={SAYFA_BASINA_ILAN}"
        f"&page={sayfa_no}"
        f"&viewMode=grid"
    )
    page.goto(url, wait_until="networkidle", timeout=45000)
    time.sleep(GECIKME_SANIYE)
    return page.content()


def ilanlar_parse(html: str, oyun_adi: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    ilanlar = []
    kart_linkleri = soup.find_all("a", href=lambda h: h and "/Card/Detail/" in h)
    islenmiş_kartlar = set()

    for link in kart_linkleri:
        try:
            container = link.find_parent("div", recursive=False)
            if not container:
                container = link.parent

            kart_adi = link.get_text(strip=True)
            if not kart_adi or kart_adi in islenmiş_kartlar:
                continue
            islenmiş_kartlar.add(kart_adi)

            kart_url = "https://binderim.com" + link["href"]

            buyuk_container = container
            for _ in range(5):
                parent = buyuk_container.find_parent("div")
                if parent:
                    buyuk_container = parent
                    if "₺" in buyuk_container.get_text():
                        break

            tam_metin = buyuk_container.get_text(separator="\n").strip()
            satirlar = [s.strip() for s in tam_metin.split("\n") if s.strip()]

            firsat_mi = any("fırsat" in s.lower() for s in satirlar)
            if not firsat_mi:
                continue

            fiyat = 0.0
            adil_fiyat = 0.0
            fark_yuzde = 0.0
            satici = ""
            kondisyon = ""
            dil = ""

            for satir in satirlar:
                if "₺" in satir and "Adil fiyat" not in satir and fiyat == 0.0:
                    fiyat = fiyat_parse(satir.replace("başl.", "").strip())

                if "Adil fiyat ₺" in satir:
                    parcalar = satir.replace("Adil fiyat", "").strip().split()
                    if parcalar:
                        adil_fiyat = fiyat_parse(parcalar[0])

                if (satir.startswith("−") or satir.startswith("+")) and "%" in satir:
                    fark_yuzde = yuzde_parse(satir)

                if satir in ["NM", "LP", "MP", "HP", "M"]:
                    kondisyon = satir

                if satir in ["EN", "JP", "CN"]:
                    dil = satir

            onaylı_elem = buyuk_container.find(string=lambda t: t and "Onaylı" in t)
            for sc in buyuk_container.find_all("span"):
                txt = sc.get_text(strip=True)
                if txt and len(txt) > 2 and "₺" not in txt and txt not in ["NM","LP","EN","JP","CN","Onaylı","Yeni","Fırsat"]:
                    satici = txt
                    break

            if fiyat > 0 and adil_fiyat > 0:
                ilanlar.append({
                    "oyun": oyun_adi,
                    "kart_adi": kart_adi,
                    "kart_url": kart_url,
                    "fiyat": fiyat,
                    "adil_fiyat": adil_fiyat,
                    "fark_yuzde": fark_yuzde,
                    "satici": satici,
                    "kondisyon": kondisyon,
                    "dil": dil,
                    "onaylı": bool(onaylı_elem),
                })

        except Exception:
            continue

    return ilanlar


# ─── Terminal Çıktısı ─────────────────────────────────────────────────────────

RENK = {
    "reset":   "\033[0m",
    "yesil":   "\033[92m",
    "sari":    "\033[93m",
    "mavi":    "\033[94m",
    "cyan":    "\033[96m",
    "bold":    "\033[1m",
}

def bildirim_yazdir(ilan: dict):
    R = RENK
    fark = abs(ilan['fark_yuzde'])
    onaylı_txt = f" {R['cyan']}✓ Onaylı{R['reset']}" if ilan.get("onaylı") else ""
    print(f"\n{'─'*60}")
    print(f"  {R['yesil']}{R['bold']}[YENİ FIRSAT]{R['reset']}  {R['bold']}{ilan['kart_adi']}{R['reset']}  [{ilan['oyun']}]")
    print(f"  Fiyat     : {R['bold']}₺{ilan['fiyat']:,.0f}{R['reset']}")
    print(f"  Adil Fiyat: ₺{ilan['adil_fiyat']:,.0f}  ({R['yesil']}-%{fark:.1f}{R['reset']})")
    print(f"  Kondisyon : {ilan.get('kondisyon','')} {ilan.get('dil','')}")
    print(f"  Satıcı    : {ilan['satici']}{onaylı_txt}")
    print(f"  Link      : {R['mavi']}{ilan['kart_url']}{R['reset']}")
    print(f"{'─'*60}")


def ozet_yazdir(yeni: int, toplam: int, sure: float):
    R = RENK
    zaman = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    print(f"\n{'═'*60}")
    print(f"  {R['bold']}Tarama Tamamlandı{R['reset']}  —  {zaman}")
    print(f"  Toplam fırsat ilan : {toplam}")
    print(f"  Yeni bildirilen    : {R['yesil']}{R['bold']}{yeni}{R['reset']}")
    print(f"  Süre               : {sure:.1f}s")
    print(f"  Sonraki tarama     : {TARAMA_ARALIGI_SAAT} saat sonra")
    print(f"{'═'*60}\n")


# ─── Ana Tarama ───────────────────────────────────────────────────────────────

def tara(page) -> tuple[int, int]:
    gorulmus = gorulmus_yukle()
    yeni_ilanlar = []
    tum_ilanlar = []

    for oyun_id, oyun_adi in OYUNLAR.items():
        print(f"\n  📦 {oyun_adi} taranıyor...", end="", flush=True)
        for sayfa_no in range(1, TOPLAM_SAYFA + 1):
            try:
                html = sayfa_cek(page, oyun_id, sayfa_no)
                ilanlar = ilanlar_parse(html, oyun_adi)
                tum_ilanlar.extend(ilanlar)
                if not ilanlar:
                    break
                print(f" {sayfa_no}✓", end="", flush=True)
            except Exception as e:
                print(f"\n  ⚠️  Sayfa {sayfa_no} hatası: {e}")
                break
        print()

    for ilan in tum_ilanlar:
        ilan_id = ilan_id_olustur(ilan)
        if ilan_id not in gorulmus:
            yeni_ilanlar.append((ilan_id, ilan))

    if yeni_ilanlar:
        print(f"\n  🔔 {len(yeni_ilanlar)} yeni fırsat!\n")
        for ilan_id, ilan in yeni_ilanlar:
            bildirim_yazdir(ilan)
            telegram_gonder(ilan_telegram_mesaji(ilan))
            gorulmus.add(ilan_id)
            time.sleep(0.3)  # Telegram rate limit önleme
    else:
        print("\n  ✓ Yeni PC altı ilan yok.")

    gorulmus_kaydet(gorulmus)
    return len(yeni_ilanlar), len(tum_ilanlar)


# ─── Ana Döngü ────────────────────────────────────────────────────────────────

def main():
    R = RENK
    print(f"\n{R['bold']}{'█'*60}{R['reset']}")
    print(f"  {R['cyan']}{R['bold']}Binderim Fırsat Botu{R['reset']}")
    print(f"  PC altı ilanlar Telegram'a bildirilir")
    print(f"  Her {TARAMA_ARALIGI_SAAT} saatte bir tarar  |  Çıkmak: Ctrl+C")
    print(f"{R['bold']}{'█'*60}{R['reset']}\n")

    # Başlangıç test mesajı
    telegram_gonder("🤖 <b>Binderim Fırsat Botu başlatıldı!</b>\nPC altı yeni ilanlar buraya bildirilecek.")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        tarama_sayisi = 0

        try:
            while True:
                tarama_sayisi += 1
                baslangic = time.time()
                zaman = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                print(f"{'─'*60}")
                print(f"  🔍 Tarama #{tarama_sayisi}  —  {zaman}")

                try:
                    yeni, toplam = tara(page)
                except Exception as e:
                    print(f"\n  ❌ Tarama hatası: {e}")
                    yeni, toplam = 0, 0

                ozet_yazdir(yeni, toplam, time.time() - baslangic)
                print(f"  💤 {TARAMA_ARALIGI_SAAT} saat bekleniyor...\n")
                time.sleep(TARAMA_ARALIGI_SAAT * 3600)

        except KeyboardInterrupt:
            print(f"\n\n  {R['sari']}Bot durduruldu.{R['reset']}\n")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
