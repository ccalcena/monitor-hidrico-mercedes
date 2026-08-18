"""
fetch_dmh.py — Monitor Hidrico Resiliencia Urbana Franja Costera de Asuncion
Scrappea DMH-DINAC usando Playwright (navegador real) para bypassear bloqueos 403
y genera docs/index.html actualizado
"""

import os, re, sys
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup



SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
OUTPUT       = os.path.join(SCRIPT_DIR, "..", "docs", "index.html")
SHP_PATH     = os.path.join(SCRIPT_DIR, "..", "data", "PLANO_PROYECTO.shp")
SHP_CHA      = os.path.join(SCRIPT_DIR, "..", "data", "CHA_fase_I.shp")
SHP_PARQUE   = os.path.join(SCRIPT_DIR, "..", "data", "parque_caballero.shp")
DMH_URL    = "https://www.meteorologia.gov.py/nivel-rio/indexconvencional.php"
ASUNCION_CODE = "2000086218"
ASUNCION_HIST_URL = "https://www.meteorologia.gov.py/nivel-rio/vermas_convencional.php?code=" + ASUNCION_CODE + "&page={}"

UMBRAL_VERDE    = 3.20
UMBRAL_AMARILLO = 3.50
UMBRAL_ROJO     = 4.00

ESTACIONES = [
    "Bahía Negra","Fuerte Olimpo","Isla Margarita","Vallemi",
    "Concepción","Rosario","Puerto Antequera","Villeta",
    "Asunción","Ita Enramada","Humaitá","Alberdi","Pilar"
]

COORDS = {
    "Bahía Negra":      (-20.22,-58.16),
    "Fuerte Olimpo":    (-21.04,-57.87),
    "Isla Margarita":   (-21.95,-57.94),
    "Vallemi":          (-22.54,-57.97),
    "Concepción":       (-23.41,-57.43),
    "Rosario":          (-24.45,-57.22),
    "Puerto Antequera": (-24.08,-57.07),
    "Villeta":          (-25.51,-57.56),
    "Asunción":         (-25.28,-57.63),
    "Ita Enramada":     (-25.43,-57.60),
    "Humaitá":          (-27.06,-58.52),
    "Alberdi":          (-26.18,-58.13),
    "Pilar":            (-26.86,-58.30),
}

def read_shapefile(shp_path, label="shapefile"):
    """Lee cualquier shapefile UTM 21S y devuelve lista de polígonos en WGS84."""
    try:
        import shapefile
        from pyproj import Transformer
        shp = shapefile.Reader(shp_path)
        transformer = Transformer.from_crs('EPSG:32721', 'EPSG:4326', always_xy=True)
        polygons = []
        for shaperec in shp.shapeRecords():
            pts = shaperec.shape.points
            parts = list(shaperec.shape.parts) + [len(pts)]
            for i in range(len(parts) - 1):
                ring = pts[parts[i]:parts[i+1]]
                coords = []
                for x, y in ring:
                    lng, lat = transformer.transform(x, y)
                    coords.append([round(lat, 7), round(lng, 7)])
                if coords:
                    polygons.append(coords)
        print(f"  {label}: {len(polygons)} polígono(s) leído(s)")
        return polygons
    except Exception as e:
        print(f"  WARN {label}: {e}")
        return []

def read_project_polygon():
    pts = read_shapefile(SHP_PATH, "PLANO_PROYECTO")
    if pts:
        return pts[0]
    return [[-25.2726697,-57.6126065],[-25.2730239,-57.6128906],
            [-25.2739879,-57.6135111],[-25.2742305,-57.6140602],
            [-25.2743007,-57.6142820],[-25.2743323,-57.6145004],
            [-25.2742658,-57.6147440],[-25.2741944,-57.6149574],
            [-25.2739569,-57.6147823],[-25.2738742,-57.6149190],
            [-25.2718199,-57.6134290],[-25.2719121,-57.6132752],
            [-25.2724166,-57.6124474],[-25.2726697,-57.6126065]]

def read_cha():
    return read_shapefile(SHP_CHA, "CHA_fase_I")

def read_parque():
    return read_shapefile(SHP_PARQUE, "parque_caballero")

# ── Tiempo ────────────────────────────────────────────────────────
def now_py():
    return datetime.now(timezone(timedelta(hours=-4)))

# ── Scraping con Playwright ───────────────────────────────────────
def scrape_playwright():
    from playwright.sync_api import sync_playwright
    print("  Iniciando navegador Playwright...")
    html = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            locale="es-PY",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        # Visitar primero la home para conseguir cookies
        page.goto("https://www.meteorologia.gov.py/", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        # Ahora la página de niveles
        page.goto(DMH_URL, timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(2000)
        html = page.content()
        browser.close()
    print(f"  HTML obtenido: {len(html)} chars")
    return html

# ── Fallback: requests ────────────────────────────────────────────
def scrape_requests():
    import requests, urllib3
    urllib3.disable_warnings()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-PY,es;q=0.9",
        "Referer": "https://www.meteorologia.gov.py/",
    }
    for verify in [True, False]:
        try:
            r = requests.get(DMH_URL, headers=headers, timeout=30, verify=verify)
            r.raise_for_status()
            if len(r.text) > 500:
                print(f"  requests OK: {len(r.text)} chars (verify={verify})")
                return r.text
        except Exception as e:
            print(f"  requests WARN (verify={verify}): {e}")
    return None

# ── Parser ────────────────────────────────────────────────────────
def parse(html):
    soup = BeautifulSoup(html, "lxml")
    stations = {}
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 4:
                continue
            loc = cells[0].strip()
            if not loc or loc.lower() in ("localidad","estacion","estación",""):
                continue
            try:
                def num(s):
                    m = re.search(r"([-\d.]+)", s)
                    return float(m.group(1)) if m else None
                def intnum(s):
                    m = re.search(r"([+-]?\d+)", s)
                    return int(m.group(1)) if m else None
                nivel = num(cells[2]) if len(cells) > 2 else None
                var   = intnum(cells[3]) if len(cells) > 3 else None
                maxh  = num(cells[5]) if len(cells) > 5 else None
                if nivel is not None:
                    stations[loc] = {
                        "nivel": nivel, "var": var, "max": maxh,
                        "pct": round(nivel/maxh*100,1) if maxh and maxh > 0 else None
                    }
            except:
                continue
    return stations

def scrape_historial_asuncion(n_paginas=6):
    """Trae el histórico diario de nivel de Asunción (serie completa DMH), paginado."""
    import requests, urllib3
    urllib3.disable_warnings()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "es-PY,es;q=0.9",
        "Referer": "https://www.meteorologia.gov.py/",
    }
    registros = []
    for pagina in range(1, n_paginas + 1):
        url = ASUNCION_HIST_URL.format(pagina)
        try:
            r = requests.get(url, headers=headers, timeout=20, verify=False)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            for table in soup.find_all("table"):
                for row in table.find_all("tr"):
                    cells = [td.get_text(strip=True) for td in row.find_all("td")]
                    if len(cells) < 2:
                        continue
                    fecha, nv = cells[0].strip(), cells[1].strip()
                    if not re.match(r"\d{2}-\d{2}-\d{4}", fecha):
                        continue
                    m = re.search(r"([-\d.]+)", nv)
                    if m:
                        registros.append({"fecha": fecha, "nivel": float(m.group(1))})
        except Exception as e:
            print(f"  WARN historial Asunción pág {pagina}: {e}")
            break
    registros.reverse()  # más antiguo primero
    print(f"  Histórico Asunción: {len(registros)} registros")
    return registros

def get_stations():
    # Try Playwright first, then fallback to requests
    html = None
    try:
        html = scrape_playwright()
    except Exception as e:
        print(f"  Playwright error: {e}")

    if not html:
        print("  Intentando con requests...")
        html = scrape_requests()

    if not html:
        print("  No se pudo obtener datos de DMH-DINAC")
        return {}

    stations = parse(html)
    print(f"  {len(stations)} estaciones parseadas")
    return stations

# ── Lógica de evaluación ──────────────────────────────────────────
def semaforo(nivel):
    if nivel is None: return "#888", "SIN DATO"
    if nivel >= UMBRAL_ROJO:     return "#c62828", "⛔ BACKWATER ACTIVO — ALERTA ROJA"
    if nivel >= UMBRAL_AMARILLO: return "#d84315", "⚠️ PRESIÓN BACKWATER — ALERTA NARANJA"
    if nivel >= UMBRAL_VERDE:    return "#f57f17", "🟡 VIGILANCIA — ALERTA AMARILLA"
    return "#0f7a5c", "✅ DRENAJE LIBRE — SIN ALERTA"

def evaluar(st):
    alertas, nivel_alerta = [], "verde"
    def g(n): return st.get(n, {})

    bn = g("Bahía Negra")
    if (bn.get("var") or 0) > 0 and bn.get("nivel"):
        alertas.append(f"🔴 <strong>Bahía Negra sigue subiendo</strong> ({bn['nivel']:.2f} m, +{bn['var']} cm hoy). La onda aún no se ha liberado hacia el sur.")
        nivel_alerta = "rojo"

    val = g("Vallemi")
    if (val.get("var") or 0) > 0 and val.get("nivel"):
        alertas.append(f"⚡ <strong>Vallemi girando a positivo</strong> ({val['nivel']:.2f} m, +{val['var']} cm) — frente de onda en tránsito. Asunción responderá en 5–8 días.")
        if nivel_alerta == "verde": nivel_alerta = "naranja"

    con = g("Concepción")
    if (con.get("var") or 0) > 0 and con.get("nivel"):
        alertas.append(f"🟠 <strong>Concepción subiendo</strong> ({con['nivel']:.2f} m, +{con['var']} cm) — onda a 2–3 días de Asunción.")
        nivel_alerta = "rojo"

    asu = g("Asunción")
    if asu.get("nivel"):
        _, txt = semaforo(asu["nivel"])
        alertas.append(f"📍 <strong>Asunción hoy: {asu['nivel']:.2f} m</strong> — {txt}.")
        if asu["nivel"] >= UMBRAL_ROJO: nivel_alerta = "rojo"
        elif asu["nivel"] >= UMBRAL_AMARILLO and nivel_alerta != "rojo": nivel_alerta = "amarillo"

    if not alertas:
        alertas.append("✅ Sin señales de alerta activa. Todos los indicadores dentro de rangos normales.")
    return alertas, nivel_alerta

# ── Construcción del HTML ─────────────────────────────────────────
def build_rows(st):
    rows = ""
    for nombre in ESTACIONES:
        s = st.get(nombre, {})
        nivel = s.get("nivel"); var = s.get("var"); maxh = s.get("max"); pct = s.get("pct")
        nv = f"{nivel:.2f} m" if nivel is not None else "—"
        mv = f"{maxh:.2f} m" if maxh else "—"
        pv = f"{pct}%" if pct else "—"
        if var is not None and var > 1:
            tc="#c62828"; tt=f"+{var} cm ↑"; bdg='<span class="bdg b-r">SUBIENDO</span>'
        elif var is not None and var < -1:
            tc="#0f7a5c"; tt=f"{var} cm ↓"; bdg='<span class="bdg b-g">BAJANDO</span>'
        else:
            tc="#888"; tt=f"{var:+d} cm" if var is not None else "—"; bdg='<span class="bdg b-a">ESTABLE</span>'
        rc  = "ref" if nombre=="Asunción" else ("warn" if nombre=="Vallemi" and (var or 0)>0 else ("hi" if nombre=="Bahía Negra" and (var or 0)>0 else ""))
        lbl = "⭐ Asunción" if nombre=="Asunción" else ("⚡ Vallemi" if nombre=="Vallemi" else nombre)
        rows += f'<tr class="{rc}"><td>{lbl}</td><td class="mono"><strong>{nv}</strong></td><td style="color:{tc};font-weight:700">{tt}</td><td class="mono">{mv}</td><td>{pv}</td><td>{bdg}</td></tr>\n'
    return rows

def build_waves(st):
    def bar(nombre, color, extra=""):
        s     = st.get(nombre, {})
        nivel = s.get("nivel", 0) or 0
        maxh  = s.get("max", 10) or 10
        pct   = min(int(nivel/maxh*100), 100)
        var   = s.get("var", 0) or 0
        tend  = f"+{var} cm" if var>0 else (f"{var} cm" if var<0 else "estable")
        lbl   = f"{nombre} {extra}".strip()
        return f'<div class="wb"><div class="wl">{lbl}</div><div class="wt"><div class="wf" style="width:{pct}%;background:{color};">{nivel:.2f} m</div></div><div class="wv-val" style="color:{color};">{tend}</div></div>\n'
    w  = bar("Bahía Negra",    "#c62828")
    w += bar("Fuerte Olimpo",  "#d84315")
    w += bar("Isla Margarita", "#f57f17")
    w += bar("Vallemi",        "#c9a227", "⚡")
    w += bar("Concepción",     "#1f9d78")
    w += bar("Asunción",       "#0f7a5c", "⭐")
    return w

def build_stations_js(st):
    lines = []
    for nombre, (lat, lng) in COORDS.items():
        s     = st.get(nombre, {})
        nivel = f"{s['nivel']:.2f} m" if s.get("nivel") is not None else "—"
        var   = s.get("var", 0) or 0
        tend  = f"+{var} cm" if var>0 else (f"{var} cm" if var<0 else "estable")
        key   = "true" if nombre in ("Vallemi","Asunción") else "false"
        lines.append(f'  {{ name:"{nombre}", lat:{lat}, lng:{lng}, nivel:"{nivel}", tend:"{tend}", key:{key} }}')
    return "[\n" + ",\n".join(lines) + "\n]"

BANNER = {
    "verde":   ("#e6f6f0","#0a3d2e","#0f7a5c"),
    "amarillo":("#fffde7","#7f3800","#f9a825"),
    "naranja": ("#fff3e0","#7f3800","#d84315"),
    "rojo":    ("#fff0f0","#7f1d1d","#c62828"),
}

def generate(st, alertas, nivel_alerta, ts, proj_coords=None, cha_coords=None, parque_coords=None, historial=None):
    asu     = st.get("Asunción", {})
    asu_v   = asu.get("nivel")
    asu_txt = f"{asu_v:.2f} m" if asu_v else "—"
    asu_vc  = asu.get("var", 0) or 0
    asu_tend= f"+{asu_vc} cm ↑" if asu_vc>0 else (f"{asu_vc} cm ↓" if asu_vc<0 else "estable")
    sc, st_txt = semaforo(asu_v)
    bb, bt, bbd = BANNER.get(nivel_alerta, BANNER["verde"])
    alertas_html = "".join(f"<div class='alerta-item'>{a}</div>\n" for a in alertas)
    rows  = build_rows(st)
    waves = build_waves(st)
    sjs   = build_stations_js(st)

    no_data_banner = ""
    if not st:
        no_data_banner = """<div style="background:#fff3cd;border:1px solid #ffc107;border-left:4px solid #ffc107;border-radius:10px;padding:12px 16px;margin-bottom:14px;font-size:12px;">
          ⚠️ <strong>No se pudieron obtener datos en esta actualización.</strong> Se muestra la última versión disponible. El sistema reintentará mañana a las 7:00 AM.
        </div>"""

    # Shapefile polygon coords for Leaflet
    if proj_coords is None:
        proj_coords = read_project_polygon()
    if cha_coords is None:
        cha_coords = read_cha()
    if parque_coords is None:
        parque_coords = read_parque()
    import json
    proj_coords_js   = json.dumps(proj_coords)
    cha_coords_js    = json.dumps(cha_coords)
    parque_coords_js = json.dumps(parque_coords)
    historial_js     = json.dumps(historial or [])

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Monitor Hídrico — Resiliencia Urbana Franja Costera Asunción</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"/>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
:root {{
  --ink:#0b1a2b;--paper:#f3f6f6;--navy:#0a1f3d;--navy-2:#123258;--navy-deep:#071628;
  --emerald:#0f5c46;--emerald-2:#0f7a5c;--emerald-light:#e6f6f0;
  --blue-light:#e8f0fb;--red:#c62828;--red-light:#fff0f0;--orange:#d84315;
  --orange-light:#fff3e0;--green:#0a3d2e;--green-light:#e6f6f0;
  --amber:#b45309;--amber-light:#fffbeb;--grey:#5b6b76;--border:#e0e6e6;
  --shadow:0 1px 2px rgba(10,31,61,.04),0 8px 24px rgba(10,31,61,.06);
  --shadow-hover:0 4px 8px rgba(10,31,61,.06),0 16px 36px rgba(10,31,61,.10);
}}
*{{box-sizing:border-box;margin:0;padding:0;}}
html{{scroll-behavior:smooth;}}
body{{font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;background:var(--paper);color:var(--ink);font-size:13px;line-height:1.6;-webkit-font-smoothing:antialiased;}}
.page{{max-width:1000px;margin:0 auto;padding:28px 18px 56px;}}
.reveal{{opacity:0;transform:translateY(18px);transition:opacity .7s cubic-bezier(.16,1,.3,1),transform .7s cubic-bezier(.16,1,.3,1);}}
.reveal.visible{{opacity:1;transform:translateY(0);}}
.hdr{{background:linear-gradient(135deg,var(--navy-deep) 0%,var(--navy) 55%,var(--emerald) 130%);color:white;border-radius:20px;padding:28px 30px 0;position:relative;overflow:hidden;box-shadow:var(--shadow);}}
.hdr::before{{content:'';position:absolute;top:-90px;right:-70px;width:320px;height:320px;border-radius:50%;background:radial-gradient(circle,rgba(255,255,255,.10),transparent 70%);}}
.hdr::after{{content:'';position:absolute;bottom:-120px;left:-60px;width:260px;height:260px;border-radius:50%;background:radial-gradient(circle,rgba(15,122,92,.28),transparent 70%);}}
.hdr-top{{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;margin-bottom:18px;position:relative;}}
.hdr-badge{{background:rgba(255,255,255,.12);backdrop-filter:blur(6px);border:1px solid rgba(255,255,255,.22);border-radius:20px;padding:5px 13px;font-size:10px;font-weight:600;letter-spacing:.8px;text-transform:uppercase;}}
.hdr h1{{font-family:'Inter',sans-serif;font-weight:800;font-size:22px;letter-spacing:-.02em;line-height:1.25;margin-bottom:6px;}}
.hdr .sub{{font-size:11.5px;opacity:.72;}}
.hdr-meta{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:rgba(255,255,255,.10);border-top:1px solid rgba(255,255,255,.14);margin-top:20px;border-radius:12px 12px 0 0;overflow:hidden;position:relative;}}
.hdr-mi{{padding:12px 15px;background:rgba(255,255,255,.05);transition:background .25s ease;}}
.hdr-mi:hover{{background:rgba(255,255,255,.09);}}
.hdr-mi .label{{font-size:9px;opacity:.6;text-transform:uppercase;letter-spacing:.6px;}}
.hdr-mi .val{{font-size:13.5px;font-weight:700;margin-top:3px;letter-spacing:-.01em;}}
.semaforo{{display:flex;align-items:stretch;background:white;border:1px solid var(--border);border-top:4px solid {sc};border-radius:0 0 16px 16px;margin-bottom:16px;overflow:hidden;box-shadow:var(--shadow);transition:box-shadow .3s ease;}}
.semaforo:hover{{box-shadow:var(--shadow-hover);}}
.semaforo-left{{background:{sc};color:white;padding:20px 24px;display:flex;flex-direction:column;justify-content:center;align-items:center;min-width:190px;position:relative;overflow:hidden;}}
.semaforo-left::after{{content:'';position:absolute;inset:0;background:radial-gradient(circle at 30% 20%,rgba(255,255,255,.18),transparent 60%);}}
.semaforo-left .nivel{{font-family:'JetBrains Mono',monospace;font-size:36px;font-weight:700;line-height:1;position:relative;}}
.semaforo-left .etiqueta{{font-size:10px;opacity:.9;text-transform:uppercase;letter-spacing:.6px;margin-top:5px;position:relative;}}
.semaforo-right{{flex:1;padding:18px 22px;}}
.semaforo-right h3{{font-size:13px;font-weight:700;margin-bottom:7px;color:var(--navy);letter-spacing:-.01em;}}
.semaforo-right .status-big{{font-size:15px;font-weight:800;color:{sc};margin-bottom:11px;}}
.semaforo-scale{{display:flex;gap:6px;flex-wrap:wrap;}}
.scale-item{{font-size:10px;padding:4px 9px;border-radius:20px;}}
.alertas-box{{background:{bb};border:1px solid {bbd};border-left:4px solid {bbd};border-radius:14px;padding:16px 20px;margin-bottom:16px;box-shadow:var(--shadow);}}
.alertas-box h4{{font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:{bt};margin-bottom:10px;}}
.alerta-item{{font-size:12px;color:var(--ink);margin-bottom:8px;line-height:1.55;padding-left:11px;border-left:2px solid {bbd};}}
.card{{background:white;border:1px solid var(--border);border-radius:16px;margin-bottom:16px;overflow:hidden;box-shadow:var(--shadow);transition:box-shadow .3s ease,transform .3s ease;}}
.card:hover{{box-shadow:var(--shadow-hover);transform:translateY(-2px);}}
.card-hdr{{padding:13px 20px;display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--border);font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.6px;}}
.num{{width:23px;height:23px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:800;color:white;flex-shrink:0;}}
.card-body{{padding:18px 20px;max-height:2000px;overflow:hidden;transition:max-height .4s ease,padding .4s ease;}}
.card-body.collapsed{{max-height:0;padding-top:0;padding-bottom:0;}}
.c1 .card-hdr{{background:var(--blue-light);color:var(--navy);}} .c1 .num{{background:var(--navy);}}
.c2 .card-hdr{{background:#eef2f2;color:var(--navy-deep);}} .c2 .num{{background:var(--navy-2);}}
.c3 .card-hdr{{background:var(--emerald-light);color:var(--emerald);}} .c3 .num{{background:var(--emerald-2);}}
.c4 .card-hdr{{background:var(--blue-light);color:var(--navy);}} .c4 .num{{background:var(--navy);}}
.wv{{background:#f8f9f8;border:1px solid var(--border);border-radius:12px;padding:16px 18px;margin-top:12px;}}
.wv-title{{font-size:11px;font-weight:700;color:var(--navy);margin-bottom:13px;}}
.wb{{display:flex;align-items:center;gap:10px;margin-bottom:9px;}}
.wl{{font-size:10px;font-weight:600;width:150px;flex-shrink:0;}}
.wt{{flex:1;background:#e4e9e8;border-radius:20px;height:22px;overflow:hidden;}}
.wf{{height:100%;border-radius:20px;display:flex;align-items:center;padding-left:9px;font-size:9px;font-weight:700;color:white;transition:width 1s cubic-bezier(.16,1,.3,1);}}
.wv-val{{font-size:10px;font-weight:700;width:65px;text-align:right;flex-shrink:0;}}
.wv-note{{font-size:9px;color:#8a9299;margin-top:9px;}}
.tbl{{width:100%;border-collapse:collapse;font-size:11.5px;}}
.tbl thead th{{background:var(--navy-deep);color:white;padding:9px 12px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.4px;}}
.tbl tbody td{{padding:8px 12px;border-bottom:1px solid #eef1f1;vertical-align:middle;}}
.tbl tbody tr{{transition:background .2s ease;}}
.tbl tbody tr:hover td{{background:#f6f9f8;}}
.tbl tbody tr.hi td{{background:#fff9f9;}}
.tbl tbody tr.ref td{{background:var(--emerald-light);font-weight:700;}}
.tbl tbody tr.warn td{{background:#fff8f0;}}
.mono{{font-family:'JetBrains Mono',monospace;font-size:11px;}}
.bdg{{display:inline-block;padding:3px 9px;border-radius:20px;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap;}}
.b-r{{background:#fee2e2;color:#7f1d1d;}} .b-o{{background:#ffedd5;color:#9a3412;}}
.b-g{{background:var(--emerald-light);color:var(--emerald);}} .b-a{{background:var(--amber-light);color:var(--amber);}}
.b-w{{background:#fef9c3;color:#713f12;}}
.rzone{{display:flex;border-radius:12px;overflow:hidden;margin-bottom:16px;height:140px;border:1px solid var(--border);}}
.rz{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:white;gap:5px;padding:10px 6px;text-align:center;transition:filter .25s ease;}}
.rz:hover{{filter:brightness(1.08);}}
.rz span{{font-size:10px;font-weight:400;opacity:.95;line-height:1.3;}}
.umbral-item{{border-radius:12px;padding:13px 15px;text-align:center;margin-bottom:9px;}}
.umbral-item .u-val{{font-family:'JetBrains Mono',monospace;font-size:18px;font-weight:700;}}
.umbral-item .u-lbl{{font-size:10px;margin-top:3px;}}
.callout{{background:var(--blue-light);border:1px solid #c3d6ee;border-left:4px solid var(--navy);border-radius:12px;padding:14px 17px;margin-top:15px;}}
.callout-title{{font-size:11px;font-weight:800;color:var(--navy);margin-bottom:6px;}}
.callout p{{font-size:11px;color:var(--ink);line-height:1.55;}}
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start;}}
.foot{{font-size:9.5px;color:var(--grey);text-align:center;margin-top:18px;padding:14px;border-top:1px solid var(--border);line-height:1.7;}}
.foot a{{color:var(--emerald);text-decoration:none;font-weight:600;}}
.foot a:hover{{color:var(--navy);text-decoration:underline;}}
@media(max-width:680px){{.hdr-meta{{grid-template-columns:1fr 1fr;}} .semaforo{{flex-direction:column;}} .semaforo-left{{min-width:unset;}} .two-col{{grid-template-columns:1fr!important;}}}}
</style>
</head>
<body>
<div class="page">

<div class="hdr reveal">
  <div class="hdr-top">
    <div>
      <h1>Monitor Hídrico Diario<br>Resiliencia Urbana de la Franja Costera de Asunción</h1>
      <div class="sub">Cuenca A° Las Mercedes · Bahía de Asunción · Datos: DMH-DINAC (meteorologia.gov.py)</div>
    </div>
    <div class="hdr-badge">🔄 Auto-actualizado</div>
  </div>
  <div class="hdr-meta">
    <div class="hdr-mi"><div class="label">Última actualización</div><div class="val">{ts}</div></div>
    <div class="hdr-mi"><div class="label">Fuente</div><div class="val">DMH – DINAC</div></div>
    <div class="hdr-mi"><div class="label">Asunción hoy</div><div class="val">{asu_txt} {asu_tend}</div></div>
    <div class="hdr-mi"><div class="label">Nivel de alerta</div><div class="val">{nivel_alerta.upper()}</div></div>
  </div>
</div>

<div class="semaforo reveal">
  <div class="semaforo-left">
    <div class="nivel">{asu_txt}</div>
    <div class="etiqueta">Río Paraguay · Asunción</div>
  </div>
  <div class="semaforo-right">
    <h3>Estado del drenaje del A° Las Mercedes</h3>
    <div class="status-big">{st_txt}</div>
    <div class="semaforo-scale">
      <div class="scale-item" style="background:#e6f6f0;color:#0a3d2e;">✅ &lt; 3.20 m — Drenaje libre</div>
      <div class="scale-item" style="background:#fff3e0;color:#d84315;">🟡 3.20–3.50 m — Vigilancia</div>
      <div class="scale-item" style="background:#ffedd5;color:#9a3412;">⚠️ 3.50–4.00 m — Presión backwater</div>
      <div class="scale-item" style="background:#fee2e2;color:#7f1d1d;">⛔ &gt; 4.00 m — Backwater activo</div>
    </div>
  </div>
</div>

{no_data_banner}

<div class="alertas-box reveal">
  <h4>📋 Evaluación del día — {ts}</h4>
  {alertas_html}
</div>

<div class="card c1 reveal">
  <div class="card-hdr"><div class="num">1</div>Propagación de la onda Norte → Sur — Río Paraguay</div>
  <div class="card-body">
    <div class="wv">
      <div class="wv-title">🔁 Estado actual — nivel relativo al máximo histórico de cada estación</div>
      {waves}
      <div class="wv-note">⬇ Dirección de flujo sur. ⚡ Vallemi = señal de avance 5–8 días antes de Asunción. ⭐ = referencia directa del proyecto.</div>
    </div>
  </div>
</div>

<div class="card c2 reveal">
  <div class="card-hdr"><div class="num">2</div>Red completa Río Paraguay — Estaciones convencionales</div>
  <div class="card-body">
    <table class="tbl">
      <thead><tr><th>Localidad</th><th>Nivel actual</th><th>Var. diaria</th><th>Máx. histórico</th><th>% del máx.</th><th>Estado</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <div style="font-size:9.5px;color:#8a9299;margin-top:9px;">⭐ referencia directa del proyecto &nbsp;|&nbsp; ⚡ señal de alerta temprana</div>
  </div>
</div>

<div class="card c4 reveal">
  <div class="card-hdr" style="cursor:pointer;justify-content:space-between;user-select:none;" onclick="toggleCard(this)"><div style="display:flex;align-items:center;gap:10px;"><div class="num">3</div>Evolución histórica — Nivel del Río Paraguay en Asunción</div><span class="chev" style="transition:transform .3s ease;font-size:13px;">▾</span></div>
  <div class="card-body">
    <canvas id="histChart" height="100"></canvas>
    <div class="wv-note">Serie diaria publicada por la DMH-DINAC para la estación Asunción. Datos oficiales, sin interpolar.</div>
  </div>
</div>

<div class="card c3 reveal">
  <div class="card-hdr"><div class="num">4</div>Umbrales de riesgo y mapa — Proyecto Resiliencia Urbana Franja Costera</div>
  <div class="card-body">
    <div class="two-col">
      <div>
        <div class="rzone">
          <div class="rz" style="background:var(--emerald-2);">Norte<br><span>Mayor cota relativa</span><br><span style="font-weight:700">RIESGO MEDIO</span></div>
          <div class="rz" style="background:#d84315;">Centro<br><span>Zona de transición</span><br><span style="font-weight:700">RIESGO MEDIO-ALTO</span></div>
          <div class="rz" style="background:#c62828;">Sur<br><span>Cota baja · Alta densidad adj.</span><br><span style="font-weight:700">RIESGO ALTO</span></div>
        </div>
        <div class="umbral-item" style="background:var(--emerald-light);">
          <div class="u-val" style="color:#0a3d2e;">&lt; 3.20 m</div>
          <div class="u-lbl" style="color:#0a3d2e;">✅ Drenaje libre — obras normales</div>
        </div>
        <div class="umbral-item" style="background:#fff3e0;">
          <div class="u-val" style="color:#d84315;">3.20 – 3.50 m</div>
          <div class="u-lbl" style="color:#d84315;">🟡 Vigilancia — suspender sector sur ante lluvia</div>
        </div>
        <div class="umbral-item" style="background:#fee2e2;">
          <div class="u-val" style="color:#c62828;">&gt; 4.00 m</div>
          <div class="u-lbl" style="color:#c62828;">⛔ Alerta roja — sector sur fuera de operación</div>
        </div>
        <div class="callout">
          <div class="callout-title">🎯 Estación clave: VALLEMI</div>
          <p>Vallemi da <strong>5–8 días de anticipación</strong>. Cuando suba 2 días consecutivos → alerta naranja. Asunción &gt; 3.20 m → amarilla. Asunción &gt; 4.00 m → roja, sector sur fuera de operación.</p>
        </div>
      </div>
      <div>
        <div style="font-size:11px;font-weight:700;color:var(--navy);margin-bottom:8px;">🗺️ Río Paraguay y zonas de riesgo del proyecto</div>
        <div id="map" style="height:420px;border-radius:12px;border:1px solid var(--border);overflow:hidden;z-index:0;"></div>
        <div style="font-size:9px;color:var(--grey);margin-top:6px;display:flex;gap:10px;flex-wrap:wrap;">
          <span>🔵 Estaciones DMH</span>
          <span style="color:var(--emerald-2);">■ Norte</span>
          <span style="color:#d84315;">■ Centro</span>
          <span style="color:#c62828;">■ Sur</span>
          <span style="color:#f9c000;">— PLANO_PROYECTO</span>
          <span style="color:#9c27b0;">■ CHA Fase I</span>
          <span style="color:#00897b;">■ Parque Caballero</span>
        </div>
      </div>
    </div>
  </div>
</div>

<div class="foot">
  Monitor automático · Fuente: <a href="https://www.meteorologia.gov.py/nivel-rio/indexconvencional.php" target="_blank">DMH-DINAC — meteorologia.gov.py</a><br>
  Referencia técnica: Monitoreo Hidrométrico A° Las Mercedes — INCLAM-HIDROCONTROL / HydroB&ck, Mayo 2022<br>
  <strong>Uso interno — Resiliencia Urbana de la Franja Costera de Asunción · Paraguay</strong>
</div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
var map = L.map('map',{{zoomControl:true,scrollWheelZoom:true}}).setView([-25.2735,-57.6137],15);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png',{{
  attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> © <a href="https://carto.com/attributions">CARTO</a>',
  subdomains:'abcd', maxZoom:19
}}).addTo(map);

var stationData = {sjs};
var blueIcon = L.divIcon({{className:'',html:'<div style="width:10px;height:10px;background:#123258;border:2px solid white;border-radius:50%;box-shadow:0 1px 4px rgba(0,0,0,.35);"></div>',iconSize:[10,10],iconAnchor:[5,5]}});
var redIcon  = L.divIcon({{className:'',html:'<div style="width:14px;height:14px;background:#c62828;border:2px solid white;border-radius:50%;box-shadow:0 1px 4px rgba(0,0,0,.45);"></div>',iconSize:[14,14],iconAnchor:[7,7]}});

stationData.forEach(function(s){{
  L.marker([s.lat,s.lng],{{icon:s.key?redIcon:blueIcon}}).addTo(map)
   .bindTooltip('<strong>'+s.name+'</strong><br>Nivel: '+s.nivel+'<br>Tendencia: '+s.tend,{{sticky:true}});
}});

L.polyline([[-19.95,-57.85],[-20.22,-58.16],[-21.04,-57.87],[-21.95,-57.94],[-22.54,-57.97],[-23.41,-57.43],[-24.45,-57.22],[-24.70,-57.35],[-25.28,-57.63],[-25.43,-57.60],[-26.18,-58.13],[-26.86,-58.30],[-27.06,-58.52]],
  {{color:'#123258',weight:3,opacity:0.75}}).addTo(map).bindTooltip('Río Paraguay',{{sticky:true}});
// ── Polígono real del proyecto (PLANO_PROYECTO.shp UTM 21S → WGS84) ──
var proyCoords = {proj_coords_js};
var proyPolygon = L.polygon(proyCoords,{{color:'#f9c000',weight:3,opacity:1,fillColor:'#f9c000',fillOpacity:0.12,dashArray:'6 4'}}).addTo(map).bindTooltip('<strong>PLANO_PROYECTO</strong><br>Resiliencia Urbana Franja Costera<br>Área: 33,304 m²',{{sticky:true}});
L.polygon([[-25.2718199,-57.6134290],[-25.2719121,-57.6132752],[-25.2724166,-57.6124474],[-25.2726697,-57.6126065],[-25.2730239,-57.6128906],[-25.2731500,-57.6134000],[-25.2722000,-57.6138000]],{{color:'#0f7a5c',weight:1.5,fillColor:'#0f7a5c',fillOpacity:0.40,dashArray:'3 3'}}).addTo(map).bindTooltip('Zona NORTE — Riesgo MEDIO',{{sticky:true}});
L.polygon([[-25.2731500,-57.6134000],[-25.2730239,-57.6128906],[-25.2735000,-57.6133000],[-25.2739879,-57.6135111],[-25.2738000,-57.6141000],[-25.2734000,-57.6143000],[-25.2731500,-57.6140000]],{{color:'#d84315',weight:1.5,fillColor:'#d84315',fillOpacity:0.40,dashArray:'3 3'}}).addTo(map).bindTooltip('Zona CENTRO — Riesgo MEDIO-ALTO',{{sticky:true}});
L.polygon([[-25.2738000,-57.6141000],[-25.2739879,-57.6135111],[-25.2742305,-57.6140602],[-25.2743007,-57.6142820],[-25.2743323,-57.6145004],[-25.2742658,-57.6147440],[-25.2741944,-57.6149574],[-25.2739569,-57.6147823],[-25.2738742,-57.6149190],[-25.2734000,-57.6143000]],{{color:'#c62828',weight:1.5,fillColor:'#c62828',fillOpacity:0.40,dashArray:'3 3'}}).addTo(map).bindTooltip('Zona SUR — Riesgo ALTO',{{sticky:true}});
map.fitBounds(proyPolygon.getBounds().pad(0.5));

// ── CHA Fase I ──────────────────────────────────────────────────────
var chaCoords = {cha_coords_js};
chaCoords.forEach(function(ring) {{
  L.polygon(ring, {{
    color:'#9c27b0', weight:2, opacity:1,
    fillColor:'#ce93d8', fillOpacity:0.30,
    dashArray:'5 3'
  }}).addTo(map).bindTooltip('<strong>CHA Fase I</strong>', {{sticky:true}});
}});

// ── Parque Caballero ─────────────────────────────────────────────────
var parqueCoords = {parque_coords_js};
parqueCoords.forEach(function(ring) {{
  L.polygon(ring, {{
    color:'#00897b', weight:2, opacity:1,
    fillColor:'#80cbc4', fillOpacity:0.30,
    dashArray:'5 3'
  }}).addTo(map).bindTooltip('<strong>Parque Caballero</strong>', {{sticky:true}});
}});

// ── Gráfico histórico Asunción ────────────────────────────────────────
var historial = {historial_js};
if (historial.length) {{
  var ctx = document.getElementById('histChart').getContext('2d');
  var grad = ctx.createLinearGradient(0,0,0,260);
  grad.addColorStop(0,'rgba(15,122,92,0.28)');
  grad.addColorStop(1,'rgba(15,122,92,0)');
  new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: historial.map(function(r){{return r.fecha;}}),
      datasets: [{{
        label: 'Nivel Asunción (m)',
        data: historial.map(function(r){{return r.nivel;}}),
        borderColor: '#0f7a5c',
        backgroundColor: grad,
        borderWidth: 2.5,
        pointRadius: 0,
        pointHoverRadius: 5,
        pointHitRadius: 12,
        tension: 0.35,
        fill: true
      }}]
    }},
    options: {{
      responsive: true,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: '#0a1f3d',
          padding: 10,
          titleFont: {{ size: 11 }},
          bodyFont: {{ size: 12, weight: '700' }},
          callbacks: {{ label: function(ctx){{ return ctx.parsed.y.toFixed(2) + ' m'; }} }}
        }}
      }},
      scales: {{
        x: {{ grid: {{ display:false }}, ticks: {{ maxTicksLimit: 8, font: {{ size: 10 }} }} }},
        y: {{ grid: {{ color:'#eef1f1' }}, ticks: {{ font: {{ size: 10 }} }} }}
      }}
    }}
  }});
}}

function toggleCard(hdr) {{
  var body = hdr.nextElementSibling;
  var chev = hdr.querySelector('.chev');
  body.classList.toggle('collapsed');
  chev.style.transform = body.classList.contains('collapsed') ? 'rotate(-90deg)' : 'rotate(0deg)';
}}

// ── Animación de entrada (fade-in escalonado al cargar) ───────────────
var revealEls = document.querySelectorAll('.reveal');
revealEls.forEach(function(el, i){{
  setTimeout(function(){{ el.classList.add('visible'); }}, 120 + i*80);
}});
</script>
</body>
</html>"""

# ── Main ──────────────────────────────────────────────────────────
def main():
    ts = now_py().strftime("%d de %B de %Y — %H:%M hs (hora Paraguay)")
    print(f"[{ts}] Iniciando monitor hídrico...")
    st = get_stations()
    alertas, nivel_alerta = evaluar(st)
    proj_coords   = read_project_polygon()
    cha_coords    = read_cha()
    parque_coords = read_parque()
    historial     = scrape_historial_asuncion()
    html = generate(st, alertas, nivel_alerta, ts, proj_coords, cha_coords, parque_coords, historial)
    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT)), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✓ Dashboard guardado ({len(html)} chars)")

if __name__ == "__main__":
    main()
