import urllib.request
import json
import sqlite3
import csv
import os
import sys
import ssl
from datetime import datetime, timedelta
import statistics

# ------------------------------------------------------------
# 1. YAHOO FINANCE API'DEN VERİ ÇEKME (GÜVENLİ)
# ------------------------------------------------------------
def fetch_data(symbol, range_str='6mo'):
    """
    Yahoo Finance API'den günlük kapanış fiyatlarını çeker.
    Hata olursa ayrıntılı mesaj verir ve programı sonlandırır.
    """
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range_str}&interval=1d'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    try:
        # SSL hatalarını yok saymak için (bazı sistemlerde sertifika sorunu olabilir)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
            data = json.loads(response.read().decode())

        if 'chart' not in data or 'result' not in data['chart'] or not data['chart']['result']:
            raise ValueError("Yanıt beklenen yapıda değil.")

        chart = data['chart']['result'][0]
        if 'timestamp' not in chart or 'indicators' not in chart:
            raise ValueError("Yanıtta timestamp veya indicators eksik.")

        timestamps = chart['timestamp']
        quote = chart['indicators']['quote'][0]
        closes = quote.get('close', [])

        if not timestamps or not closes:
            raise ValueError("Fiyat verisi boş.")

        result = {}
        for ts, close in zip(timestamps, closes):
            if close is not None:
                date = datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d')
                result[date] = close

        if not result:
            raise ValueError(f"{symbol} için geçerli fiyat bulunamadı.")
        return result

    except urllib.error.HTTPError as e:
        print(f"HTTP Hatası ({symbol}): {e.code} - {e.reason}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Bağlantı Hatası ({symbol}): {e.reason}")
        sys.exit(1)
    except Exception as e:
        print(f"Beklenmeyen hata ({symbol}): {e}")
        sys.exit(1)


def fill_missing_dates(data_dict, start_date, end_date):
    """
    Belirtilen aralıktaki her gün için fiyat sağlar.
    Eksik günlerde önceki günün fiyatını kullanır.
    İlk gün verisi yoksa, ilk mevcut fiyat geriye doğru doldurulur.
    """
    # Tüm günleri oluştur
    all_dates = []
    current = start_date
    while current <= end_date:
        all_dates.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)

    # Önce ilk mevcut tarihi bul
    first_available = None
    for date in all_dates:
        if date in data_dict:
            first_available = data_dict[date]
            break

    if first_available is None:
        # Hiç veri yoksa hata
        raise ValueError("Veri setinde hiç fiyat bulunamadı.")

    filled = {}
    last_value = first_available  # Başlangıç için ilk değeri kullan
    for date in all_dates:
        if date in data_dict:
            last_value = data_dict[date]
        # Eğer tarih, ilk mevcut tarihten önceyse ve elimizde değer varsa onu kullan
        # (yukarıda last_value zaten ilk değerle başladı)
        filled[date] = last_value

    return filled


# ------------------------------------------------------------
# 2. DOSYA KAYDETME FONKSİYONLARI
# ------------------------------------------------------------
def save_to_sqlite(records, db_name):
    try:
        conn = sqlite3.connect(db_name)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS altin_fiyatlari (
                        tarih TEXT PRIMARY KEY,
                        ons REAL,
                        gram REAL,
                        ceyrek REAL,
                        cumhuriyet REAL
                    )''')
        c.execute('DELETE FROM altin_fiyatlari')
        c.executemany('INSERT INTO altin_fiyatlari VALUES (?,?,?,?,?)', records)
        conn.commit()
        conn.close()
        print(f"SQLite veritabanı oluşturuldu: {db_name}")
    except Exception as e:
        print(f"SQLite kaydetme hatası: {e}")
        sys.exit(1)

def save_to_csv(records, csv_name):
    try:
        with open(csv_name, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Tarih', 'ONS', 'Gram', 'Ceyrek', 'Cumhuriyet'])
            writer.writerows(records)
        print(f"CSV dosyası oluşturuldu: {csv_name}")
    except Exception as e:
        print(f"CSV kaydetme hatası: {e}")
        sys.exit(1)

def create_html_report(records, html_name):
    try:
        tarihler = [r[0] for r in records]
        ons = [r[1] for r in records]
        gram = [r[2] for r in records]
        ceyrek = [r[3] for r in records]
        cumhuriyet = [r[4] for r in records]

        html_template = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Altın Fiyatları</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .chart-container { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .chart-box { border: 1px solid #ddd; padding: 15px; border-radius: 8px; }
        h1 { text-align: center; }
    </style>
</head>
<body>
    <h1>Son 6 Aylık Altın Fiyatları (Tam Takvim Verisi)</h1>
    <div class="chart-container">
        <div class="chart-box"><canvas id="chartGram"></canvas></div>
        <div class="chart-box"><canvas id="chartCeyrek"></canvas></div>
        <div class="chart-box"><canvas id="chartOns"></canvas></div>
        <div class="chart-box"><canvas id="chartCumhuriyet"></canvas></div>
    </div>
    <script>
        const labels = __LABELS__;
        const gramData = __GRAM__;
        const ceyrekData = __CEYREK__;
        const onsData = __ONS__;
        const cumhuriyetData = __CUMHURIYET__;

        function createChart(id, label, data, color) {
            new Chart(document.getElementById(id), {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: label,
                        data: data,
                        borderColor: color,
                        borderWidth: 2,
                        tension: 0.1
                    }]
                },
                options: {
                    responsive: true,
                    plugins: { title: { display: true, text: label } },
                    scales: {
                        x: { title: { display: true, text: 'Tarih' } },
                        y: { title: { display: true, text: 'Fiyat' } }
                    }
                }
            });
        }

        createChart('chartGram', 'Gram Altın (TL/gram)', gramData, 'blue');
        createChart('chartCeyrek', 'Çeyrek Altın (TL)', ceyrekData, 'green');
        createChart('chartOns', 'ONS Altın (USD/ons)', onsData, 'red');
        createChart('chartCumhuriyet', 'Cumhuriyet Altını (TL)', cumhuriyetData, 'purple');
    </script>
</body>
</html>"""

        html = html_template.replace('__LABELS__', json.dumps(tarihler))
        html = html.replace('__GRAM__', json.dumps(gram))
        html = html.replace('__CEYREK__', json.dumps(ceyrek))
        html = html.replace('__ONS__', json.dumps(ons))
        html = html.replace('__CUMHURIYET__', json.dumps(cumhuriyet))

        with open(html_name, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"İnteraktif grafik HTML raporu oluşturuldu: {html_name}")
    except Exception as e:
        print(f"HTML raporu oluşturma hatası: {e}")
        sys.exit(1)

def create_markdown_report(records, md_name):
    if not records:
        print("Hata: Kayıt bulunamadı, Markdown raporu oluşturulamadı.")
        return
    son = records[-1]
    tarih, ons, gram, ceyrek, cumhuriyet = son[0], son[1], son[2], son[3], son[4]

    ons_list = [r[1] for r in records]
    gram_list = [r[2] for r in records]
    ceyrek_list = [r[3] for r in records]
    cumhuriyet_list = [r[4] for r in records]

    with open(md_name, 'w', encoding='utf-8') as f:
        f.write("# Altın Fiyatları Raporu (Tam Takvim Verisi)\n\n")
        f.write(f"**Rapor Tarihi:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## Son Değerler\n\n")
        f.write(f"- **Tarih:** {tarih}\n")
        f.write(f"- **ONS:** {ons:.2f} USD/ons\n")
        f.write(f"- **Gram:** {gram:.2f} TL/gram\n")
        f.write(f"- **Çeyrek:** {ceyrek:.2f} TL\n")
        f.write(f"- **Cumhuriyet:** {cumhuriyet:.2f} TL\n\n")
        f.write("## İstatistiksel Özet (Son 6 Ay)\n\n")
        f.write("| Metrik | ONS | Gram | Çeyrek | Cumhuriyet |\n")
        f.write("|--------|-----|------|--------|------------|\n")
        f.write(f"| Ortalama | {statistics.mean(ons_list):.2f} | {statistics.mean(gram_list):.2f} | {statistics.mean(ceyrek_list):.2f} | {statistics.mean(cumhuriyet_list):.2f} |\n")
        f.write(f"| Min      | {min(ons_list):.2f} | {min(gram_list):.2f} | {min(ceyrek_list):.2f} | {min(cumhuriyet_list):.2f} |\n")
        f.write(f"| Max      | {max(ons_list):.2f} | {max(gram_list):.2f} | {max(ceyrek_list):.2f} | {max(cumhuriyet_list):.2f} |\n")
        f.write("\n")
    print(f"Markdown raporu oluşturuldu: {md_name}")

def create_text_summary(records, txt_name):
    son = records[-1]
    tarih, ons, gram, ceyrek, cumhuriyet = son[0], son[1], son[2], son[3], son[4]
    with open(txt_name, 'w', encoding='utf-8') as f:
        f.write("SON 6 AYLIK ALTIN FİYATLARI ÖZETİ (Tam Takvim Verisi)\n")
        f.write("=" * 60 + "\n")
        f.write(f"Tarih: {tarih}\n")
        f.write(f"ONS: {ons:.2f} USD\n")
        f.write(f"Gram: {gram:.2f} TL\n")
        f.write(f"Çeyrek: {ceyrek:.2f} TL\n")
        f.write(f"Cumhuriyet: {cumhuriyet:.2f} TL\n")
    print(f"Metin özeti oluşturuldu: {txt_name}")

# ------------------------------------------------------------
# 3. ANA PROGRAM
# ------------------------------------------------------------
def main():
    klasor = os.path.join(os.path.expanduser("~"), "Desktop", "Altın Fiyatları Yahoo")
    os.makedirs(klasor, exist_ok=True)
    os.chdir(klasor)
    print(f"Çalışma dizini: {klasor}")

    # Tarih aralığı (son 6 ay)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=180)
    print(f"Veri aralığı: {start_date.date()} - {end_date.date()}")

    print("Yahoo Finance API'den altın ve kur verileri indiriliyor...")
    gold_raw = fetch_data('GC=F')
    usdtry_raw = fetch_data('USDTRY=X')

    # Her iki veri setini de tüm tarihleri kapsayacak şekilde doldur
    try:
        gold_filled = fill_missing_dates(gold_raw, start_date, end_date)
        usdtry_filled = fill_missing_dates(usdtry_raw, start_date, end_date)
    except Exception as e:
        print(f"Tarih doldurma hatası: {e}")
        sys.exit(1)

    # Ortak tarihleri sıralı al (artık her gün mevcut)
    all_dates = sorted(set(gold_filled.keys()) & set(usdtry_filled.keys()))
    if not all_dates:
        print("Hata: İki veri seti arasında ortak tarih bulunamadı.")
        sys.exit(1)

    records = []
    for date in all_dates:
        ons = gold_filled[date]
        usdtry = usdtry_filled[date]
        gram = (ons / 31.1035) * usdtry
        ceyrek = gram * 1.75 * (22 / 24)
        cumhuriyet = gram * 7.2 * (22 / 24)
        records.append((date, ons, gram, ceyrek, cumhuriyet))

    print(f"Toplam {len(records)} günlük veri elde edildi (eksik günler dolduruldu).")

    # Dosya isimleri
    db_name = 'altin_fiyatlari.db'
    csv_name = 'altin_fiyatlari.csv'
    html_name = 'altin_fiyatlari_grafik.html'
    markdown_name = 'rapor.md'
    text_name = 'son_fiyatlar.txt'

    # Kaydet
    save_to_sqlite(records, db_name)
    save_to_csv(records, csv_name)
    create_html_report(records, html_name)
    create_markdown_report(records, markdown_name)
    create_text_summary(records, text_name)

    print("\nTüm dosyalar başarıyla oluşturuldu.")
    print(f"İnteraktif grafiği görmek için '{html_name}' dosyasını tarayıcıda açın.")

if __name__ == "__main__":
    main()