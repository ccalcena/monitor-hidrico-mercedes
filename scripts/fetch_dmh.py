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
    return "#2e7d32", "✅ DRENAJE LIBRE — SIN ALERTA"

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
            tc="#2e7d32"; tt=f"{var} cm ↓"; bdg='<span class="bdg b-g">BAJANDO</span>'
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
    w += bar("Vallemi",        "#f9a825", "⚡")
    w += bar("Concepción",     "#66bb6a")
    w += bar("Asunción",       "#2e7d32", "⭐")
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
    "verde":   ("#e8f5e9","#1b5e20","#2e7d32"),
    "amarillo":("#fffde7","#7f3800","#f9a825"),
    "naranja": ("#fff3e0","#7f3800","#d84315"),
    "rojo":    ("#fff0f0","#7f1d1d","#c62828"),
}

def generate(st, alertas, nivel_alerta, ts, proj_coords=None, cha_coords=None, parque_coords=None):
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
        no_data_banner = """<div style="background:#fff3cd;border:1px solid #ffc107;border-left:4px solid #ffc107;border-radius:4px;padding:12px 16px;margin-bottom:14px;font-size:12px;">
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

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Monitor Hídrico — Resiliencia Urbana Franja Costera Asunción</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"/>
<style>
:root {{
  --ink:#0d1b2a;--paper:#f4f1eb;--blue-deep:#0a2f5c;--blue:#1565c0;
  --blue-light:#e3eeff;--red:#c62828;--red-light:#fff0f0;--orange:#d84315;
  --orange-light:#fff3e0;--green:#1b5e20;--green-light:#e8f5e9;
  --amber:#b45309;--amber-light:#fffbeb;--grey:#64748b;--border:#d6d0c4;
}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'DM Sans',sans-serif;background:var(--paper);color:var(--ink);font-size:13px;line-height:1.6;}}
.page{{max-width:980px;margin:0 auto;padding:24px 18px 48px;}}
.hdr{{background:var(--blue-deep);color:white;border-radius:4px 4px 0 0;padding:24px 28px 0;position:relative;overflow:hidden;}}
.hdr::before{{content:'';position:absolute;top:-60px;right:-60px;width:240px;height:240px;border-radius:50%;background:rgba(255,255,255,.04);}}
.hdr-top{{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;margin-bottom:16px;}}
.hdr-badge{{background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.25);border-radius:20px;padding:4px 12px;font-size:10px;font-weight:600;letter-spacing:.8px;text-transform:uppercase;}}
.hdr h1{{font-family:'DM Serif Display',serif;font-size:20px;font-weight:400;line-height:1.25;margin-bottom:4px;}}
.hdr .sub{{font-size:11px;opacity:.75;}}
.hdr-meta{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:rgba(255,255,255,.1);border-top:1px solid rgba(255,255,255,.15);margin-top:18px;}}
.hdr-mi{{padding:10px 14px;background:rgba(255,255,255,.06);}}
.hdr-mi .label{{font-size:9px;opacity:.6;text-transform:uppercase;letter-spacing:.6px;}}
.hdr-mi .val{{font-size:13px;font-weight:700;margin-top:2px;}}
.semaforo{{display:flex;align-items:stretch;background:white;border:1px solid var(--border);border-top:4px solid {sc};border-radius:0 0 4px 4px;margin-bottom:14px;overflow:hidden;}}
.semaforo-left{{background:{sc};color:white;padding:18px 22px;display:flex;flex-direction:column;justify-content:center;align-items:center;min-width:180px;}}
.semaforo-left .nivel{{font-family:'JetBrains Mono',monospace;font-size:34px;font-weight:700;line-height:1;}}
.semaforo-left .etiqueta{{font-size:10px;opacity:.85;text-transform:uppercase;letter-spacing:.6px;margin-top:4px;}}
.semaforo-right{{flex:1;padding:16px 20px;}}
.semaforo-right h3{{font-size:13px;font-weight:700;margin-bottom:6px;color:var(--blue-deep);}}
.semaforo-right .status-big{{font-size:15px;font-weight:800;color:{sc};margin-bottom:10px;}}
.semaforo-scale{{display:flex;gap:6px;flex-wrap:wrap;}}
.scale-item{{font-size:10px;padding:3px 8px;border-radius:2px;}}
.alertas-box{{background:{bb};border:1px solid {bbd};border-left:4px solid {bbd};border-radius:4px;padding:14px 18px;margin-bottom:14px;}}
.alertas-box h4{{font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:{bt};margin-bottom:9px;}}
.alerta-item{{font-size:12px;color:var(--ink);margin-bottom:7px;line-height:1.5;padding-left:10px;border-left:2px solid {bbd};}}
.card{{background:white;border:1px solid var(--border);border-radius:4px;margin-bottom:14px;overflow:hidden;}}
.card-hdr{{padding:11px 18px;display:flex;align-items:center;gap:9px;border-bottom:1px solid var(--border);font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.6px;}}
.num{{width:22px;height:22px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:800;color:white;flex-shrink:0;}}
.card-body{{padding:16px 18px;}}
.c1 .card-hdr{{background:var(--blue-light);color:var(--blue-deep);}} .c1 .num{{background:var(--blue);}}
.c2 .card-hdr{{background:#f0f4f8;color:#2c3e50;}} .c2 .num{{background:#2c3e50;}}
.c3 .card-hdr{{background:var(--orange-light);color:#7f3800;}} .c3 .num{{background:var(--orange);}}
.wv{{background:#f8f7f4;border:1px solid var(--border);border-radius:4px;padding:14px 16px;margin-top:12px;}}
.wv-title{{font-size:11px;font-weight:700;color:var(--blue-deep);margin-bottom:12px;}}
.wb{{display:flex;align-items:center;gap:10px;margin-bottom:8px;}}
.wl{{font-size:10px;font-weight:600;width:150px;flex-shrink:0;}}
.wt{{flex:1;background:#e5e1d8;border-radius:2px;height:22px;overflow:hidden;}}
.wf{{height:100%;border-radius:2px;display:flex;align-items:center;padding-left:8px;font-size:9px;font-weight:700;color:white;}}
.wv-val{{font-size:10px;font-weight:700;width:65px;text-align:right;flex-shrink:0;}}
.wv-note{{font-size:9px;color:#888;margin-top:8px;}}
.tbl{{width:100%;border-collapse:collapse;font-size:11.5px;}}
.tbl thead th{{background:var(--ink);color:white;padding:8px 11px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.4px;}}
.tbl tbody td{{padding:7px 11px;border-bottom:1px solid #eee;vertical-align:middle;}}
.tbl tbody tr:hover td{{background:#f9f8f5;}}
.tbl tbody tr.hi td{{background:#fff9f9;}}
.tbl tbody tr.ref td{{background:#fffbe8;font-weight:700;}}
.tbl tbody tr.warn td{{background:#fff8f0;}}
.mono{{font-family:'JetBrains Mono',monospace;font-size:11px;}}
.bdg{{display:inline-block;padding:2px 8px;border-radius:2px;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap;}}
.b-r{{background:#fee2e2;color:#7f1d1d;}} .b-o{{background:#ffedd5;color:#9a3412;}}
.b-g{{background:#dcfce7;color:var(--green);}} .b-a{{background:var(--amber-light);color:var(--amber);}}
.b-w{{background:#fef9c3;color:#713f12;}}
.rzone{{display:flex;border-radius:3px;overflow:hidden;margin-bottom:14px;height:140px;border:1px solid var(--border);}}
.rz{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:white;gap:5px;padding:10px 6px;text-align:center;}}
.rz span{{font-size:10px;font-weight:400;opacity:.95;line-height:1.3;}}
.umbral-item{{border-radius:4px;padding:12px 14px;text-align:center;margin-bottom:8px;}}
.umbral-item .u-val{{font-family:'JetBrains Mono',monospace;font-size:18px;font-weight:700;}}
.umbral-item .u-lbl{{font-size:10px;margin-top:3px;}}
.callout{{background:var(--blue-light);border:1px solid #b6cff5;border-left:4px solid var(--blue);border-radius:3px;padding:13px 16px;margin-top:14px;}}
.callout-title{{font-size:11px;font-weight:800;color:var(--blue-deep);margin-bottom:5px;}}
.callout p{{font-size:11px;color:var(--ink);line-height:1.55;}}
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start;}}
.foot{{font-size:9.5px;color:var(--grey);text-align:center;margin-top:16px;padding:12px;border-top:1px solid var(--border);line-height:1.7;}}
@media(max-width:680px){{.hdr-meta{{grid-template-columns:1fr 1fr;}} .semaforo{{flex-direction:column;}} .semaforo-left{{min-width:unset;}} .two-col{{grid-template-columns:1fr!important;}}}}
</style>
</head>
<body>
<div class="page">

<div class="hdr">
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

<div class="semaforo">
  <div class="semaforo-left">
    <div class="nivel">{asu_txt}</div>
    <div class="etiqueta">Río Paraguay · Asunción</div>
  </div>
  <div class="semaforo-right">
    <h3>Estado del drenaje del A° Las Mercedes</h3>
    <div class="status-big">{st_txt}</div>
    <div class="semaforo-scale">
      <div class="scale-item" style="background:#e8f5e9;color:#1b5e20;">✅ &lt; 3.20 m — Drenaje libre</div>
      <div class="scale-item" style="background:#fff3e0;color:#d84315;">🟡 3.20–3.50 m — Vigilancia</div>
      <div class="scale-item" style="background:#ffedd5;color:#9a3412;">⚠️ 3.50–4.00 m — Presión backwater</div>
      <div class="scale-item" style="background:#fee2e2;color:#7f1d1d;">⛔ &gt; 4.00 m — Backwater activo</div>
    </div>
  </div>
</div>

{no_data_banner}

<div class="alertas-box">
  <h4>📋 Evaluación del día — {ts}</h4>
  {alertas_html}
</div>

<div class="card c1">
  <div class="card-hdr"><div class="num">1</div>Propagación de la onda Norte → Sur — Río Paraguay</div>
  <div class="card-body">
    <div class="wv">
      <div class="wv-title">🔁 Estado actual — nivel relativo al máximo histórico de cada estación</div>
      {waves}
      <div class="wv-note">⬇ Dirección de flujo sur. ⚡ Vallemi = señal de avance 5–8 días antes de Asunción. ⭐ = referencia directa del proyecto.</div>
    </div>
  </div>
</div>

<div class="card c2">
  <div class="card-hdr"><div class="num">2</div>Red completa Río Paraguay — Estaciones convencionales</div>
  <div class="card-body">
    <table class="tbl">
      <thead><tr><th>Localidad</th><th>Nivel actual</th><th>Var. diaria</th><th>Máx. histórico</th><th>% del máx.</th><th>Estado</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <div style="font-size:9.5px;color:#888;margin-top:8px;">⭐ referencia directa del proyecto &nbsp;|&nbsp; ⚡ señal de alerta temprana</div>
  </div>
</div>

<div class="card c3">
  <div class="card-hdr"><div class="num">3</div>Umbrales de riesgo y mapa — Proyecto Resiliencia Urbana Franja Costera</div>
  <div class="card-body">
    <div class="two-col">
      <div>
        <div class="rzone">
          <div class="rz" style="background:#2e7d32;">Norte<br><span>Mayor cota relativa</span><br><span style="font-weight:700">RIESGO MEDIO</span></div>
          <div class="rz" style="background:#d84315;">Centro<br><span>Zona de transición</span><br><span style="font-weight:700">RIESGO MEDIO-ALTO</span></div>
          <div class="rz" style="background:#c62828;">Sur<br><span>Cota baja · Alta densidad adj.</span><br><span style="font-weight:700">RIESGO ALTO</span></div>
        </div>
        <div class="umbral-item" style="background:#e8f5e9;">
          <div class="u-val" style="color:#1b5e20;">&lt; 3.20 m</div>
          <div class="u-lbl" style="color:#1b5e20;">✅ Drenaje libre — obras normales</div>
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
        <div style="font-size:11px;font-weight:700;color:var(--blue-deep);margin-bottom:8px;">🗺️ Río Paraguay y zonas de riesgo del proyecto</div>
        <div id="map" style="height:420px;border-radius:4px;border:1px solid var(--border);overflow:hidden;z-index:0;"></div>
        <div style="font-size:9px;color:var(--grey);margin-top:5px;display:flex;gap:10px;flex-wrap:wrap;">
          <span>🔵 Estaciones DMH</span>
          <span style="color:#2e7d32;">■ Norte</span>
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
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{
  attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',maxZoom:19
}}).addTo(map);

var stationData = {sjs};
var blueIcon = L.divIcon({{className:'',html:'<div style="width:10px;height:10px;background:#1565c0;border:2px solid white;border-radius:50%;box-shadow:0 1px 4px rgba(0,0,0,.4);"></div>',iconSize:[10,10],iconAnchor:[5,5]}});
var redIcon  = L.divIcon({{className:'',html:'<div style="width:14px;height:14px;background:#c62828;border:2px solid white;border-radius:50%;box-shadow:0 1px 4px rgba(0,0,0,.5);"></div>',iconSize:[14,14],iconAnchor:[7,7]}});

stationData.forEach(function(s){{
  L.marker([s.lat,s.lng],{{icon:s.key?redIcon:blueIcon}}).addTo(map)
   .bindTooltip('<strong>'+s.name+'</strong><br>Nivel: '+s.nivel+'<br>Tendencia: '+s.tend,{{sticky:true}});
}});

L.polyline([[-19.95,-57.85],[-20.22,-58.16],[-21.04,-57.87],[-21.95,-57.94],[-22.54,-57.97],[-23.41,-57.43],[-24.45,-57.22],[-24.70,-57.35],[-25.28,-57.63],[-25.43,-57.60],[-26.18,-58.13],[-26.86,-58.30],[-27.06,-58.52]],
  {{color:'#1e88e5',weight:3,opacity:0.7}}).addTo(map).bindTooltip('Río Paraguay',{{sticky:true}});
L.polygon([[-25.22,-57.67],[-25.24,-57.68],[-25.27,-57.68],[-25.29,-57.67],[-25.30,-57.65],[-25.27,-57.63],[-25.24,-57.63],[-25.22,-57.65]],
  {{color:'#1565c0',weight:1.5,fillColor:'#1e88e5',fillOpacity:0.3}}).addTo(map).bindTooltip('Bahía de Asunción',{{sticky:true}});
// ── Polígono real del proyecto (PLANO_PROYECTO.shp UTM 21S → WGS84) ──
var proyCoords = {proj_coords_js};
var proyPolygon = L.polygon(proyCoords,{{color:'#f9c000',weight:3,opacity:1,fillColor:'#f9c000',fillOpacity:0.12,dashArray:'6 4'}}).addTo(map).bindTooltip('<strong>PLANO_PROYECTO</strong><br>Resiliencia Urbana Franja Costera<br>Área: 33,304 m²',{{sticky:true}});
L.polygon([[-25.2718199,-57.6134290],[-25.2719121,-57.6132752],[-25.2724166,-57.6124474],[-25.2726697,-57.6126065],[-25.2730239,-57.6128906],[-25.2731500,-57.6134000],[-25.2722000,-57.6138000]],{{color:'#2e7d32',weight:1.5,fillColor:'#2e7d32',fillOpacity:0.40,dashArray:'3 3'}}).addTo(map).bindTooltip('Zona NORTE — Riesgo MEDIO',{{sticky:true}});
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
    html = generate(st, alertas, nivel_alerta, ts, proj_coords, cha_coords, parque_coords)
    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT)), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✓ Dashboard guardado ({len(html)} chars)")

if __name__ == "__main__":
    main()
