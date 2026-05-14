import os
import json
import requests
import pandas as pd
import urllib3
import ssl
import sys
from datetime import datetime, timedelta
from threading import Lock
from flask import Flask, render_template_string, request, jsonify, send_from_directory

app = Flask(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuración de codificación para consola
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# --- CONFIGURACIÓN DE PERSISTENCIA ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATS_FILE = os.path.join(BASE_DIR, 'stats_clics.json')
stats_lock = Lock()  # Bloqueo para evitar colisiones entre hilos

def cargar_stats():
    """Carga las estadísticas desde el disco de forma segura."""
    if not os.path.exists(STATS_FILE):
        return {}
    try:
        with open(STATS_FILE, 'r', encoding='utf-8') as f:
            contenido = f.read()
            if not contenido:
                return {}
            return json.loads(contenido)
    except Exception as e:
        print(f"[ERROR] Cargando stats: {e}")
        return {}

def guardar_stats(stats):
    """Guarda las estadísticas usando un archivo temporal (escritura atómica)."""
    try:
        temp_file = STATS_FILE + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=4)
        # Reemplazo atómico: evita archivos corruptos por cortes de ejecución
        os.replace(temp_file, STATS_FILE)
    except Exception as e:
        print(f"[ERROR] Guardando stats: {e}")

# --- CACHES ---
cache_canales = {}
cache_epg = {}

# --- ADAPTADOR SSL (Orange requiere niveles de seguridad específicos) ---
class OrangeSSLAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.set_ciphers('DEFAULT@SECLEVEL=1')
        context.check_hostname = False
        kwargs['ssl_context'] = context
        return super(OrangeSSLAdapter, self).init_poolmanager(*args, **kwargs)

def get_session():
    session = requests.Session()
    session.mount('https://', OrangeSSLAdapter())
    return session

def obtener_mapeo_canales():
    global cache_canales
    if cache_canales: return cache_canales

    url = "https://pc.orangetv.orange.es/pc/api/rtv/v1/GetChannelList?bouquet_external_id=12_PRO&model_external_id=PC&filter_unsupported_channels=true&max_pr_level=8&client=json"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    try:
        res = get_session().get(url, headers=headers, verify=False, timeout=10)
        data = res.json()
        
        canales_raw = []
        if isinstance(data, list): canales_raw = data
        elif isinstance(data, dict):
            for key in ['channels', 'channelList', 'response', 'entries']:
                if key in data and isinstance(data[key], list):
                    canales_raw = data[key]
                    break
        
        mapeo = {}
        for item in canales_raw:
            if isinstance(item, dict):
                eid = str(item.get("externalChannelId", "")).strip()
                nombre = str(item.get("name", "")).strip()
                if eid and nombre: mapeo[eid] = nombre
        
        cache_canales = mapeo
        return cache_canales
    except Exception as e:
        print(f"[ERROR] Mapeo: {e}")
        return {}

def obtener_epg_dia(date_str):
    global cache_epg
    if date_str in cache_epg: return cache_epg[date_str]

    nombres = obtener_mapeo_canales()
    #12_PRO es ESPAÑA, 1_PRO es ALEMANIA
    urls = [f"https://epg.orangetv.orange.es/epg/SmartTV_Android/12_PRO/{date_str}_8h_{i}.json?region_id=1111" for i in [1, 2, 3]]
    all_progs = []
    session = get_session()

    for url in urls:
        try:
            res = session.get(url, headers={'User-Agent': 'Mozilla/5.0'}, verify=False, timeout=10)
            for bloque in res.json():
                if isinstance(bloque, dict) and bloque.get("responseElementType") == "ProgramList":
                    eid = str(bloque.get("channelExternalId", "")).strip()
                    name = nombres.get(eid, f"Canal {eid}")
                    for p in bloque.get("programs", []):
                        all_progs.append({
                            "channel_id": eid, "canal": name,
                            "start": p["startDate"], "end": p["endDate"],
                            "inicio": datetime.fromtimestamp(p["startDate"]/1000).strftime("%H:%M"),
                            "fin": datetime.fromtimestamp(p["endDate"]/1000).strftime("%H:%M"),
                            "titulo": p["name"], "ref_id": p["referenceProgramId"], "id": p["id"]
                        })
        except: continue
    
    if not all_progs: return pd.DataFrame()
    df = pd.DataFrame(all_progs).drop_duplicates(subset=['id'])
    df['url_play'] = df.apply(lambda x: f"https://orangetv.orange.es/ply?extChId={x['channel_id']}&prgId={x['id']}&prgExtId={x['ref_id']}&rp=0&type=U7D", axis=1)
    df['url_live'] = df.apply(lambda x: f"https://orangetv.orange.es/lcn?extChId={x['channel_id']}&type=live", axis=1)
    cache_epg[date_str] = df
    return df

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es" class="dark">
<head>
    <meta charset="UTF-8">
    <title>AZ's ORANGETV EPG v0.2</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background-color: #020617; color: #f1f5f9; }
        #loading-overlay {
            display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0, 0, 0, 0.95); z-index: 9999; backdrop-filter: blur(10px);
            flex-direction: column; justify-content: center; align-items: center;
        }
        .spinner {
            border: 4px solid rgba(255, 255, 255, 0.1); width: 60px; height: 60px;
            border-radius: 50%; border-left-color: #f97316; animation: spin 0.8s ease-in-out infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .scrollbar-hide::-webkit-scrollbar { display: none; }
    </style>
</head>
<body class="p-4 sm:p-10">
    <div id="loading-overlay">
        <div class="spinner"></div>
        <p class="mt-4 text-orange-500 font-black tracking-widest animate-pulse">SINCRONIZANDO EPG...</p>
    </div>

    <div class="max-w-7xl mx-auto">
        <header class="flex justify-between items-center mb-6">
            <h1 class="text-4xl font-black text-orange-500 tracking-tighter italic">AZ's ORANGE<span class="text-white">TV</span></h1>
            <div class="text-right text-xs text-slate-500 font-mono italic">updated at {{ now_time }}</div>
        </header>

        {% if top_canales %}
        <div class="mb-8 p-4 bg-slate-900/80 rounded-2xl border border-slate-800">
            <p class="text-[10px] uppercase tracking-widest text-slate-500 mb-3 font-bold">Frecuentes</p>
            <div class="flex gap-2 flex-wrap">
                {% for tc in top_canales %}
                <a href="https://orangetv.orange.es/lcn?extChId={{ tc.id }}&type=live" target="_blank" onclick="trackClick('{{ tc.id }}');" class="bg-slate-800 border border-slate-700 px-4 py-2 rounded-xl text-xs font-bold hover:bg-orange-600 hover:text-white transition-all shadow-sm">
                    {{ tc.nombre }}
                </a>
                {% endfor %}
            </div>
        </div>
        {% endif %}

        <nav class="flex gap-3 mb-8 overflow-x-auto pb-4 scrollbar-hide">
            <a href="/" onclick="showLoading()"
               class="flex-none px-8 py-4 rounded-2xl border-2 transition-all {{ 'border-red-600 bg-red-700 text-white shadow-lg' if mode == 'live' else 'border-slate-800 bg-slate-900 text-slate-400 hover:border-slate-600' }}">
                <span class="block text-sm font-black italic">LIVE NOW</span>
            </a>
            {% for day in days %}
            <a href="/?date={{ day.id }}" onclick="showLoading()"
               class="flex-none px-6 py-4 rounded-2xl border-2 transition-all {{ 'border-orange-500 bg-orange-600 text-white shadow-lg' if (current_date == day.id and mode != 'live') else 'border-slate-800 bg-slate-900 text-slate-400 hover:border-slate-600' }}">
                <span class="block text-sm font-black">{{ day.label.split(' ')[0] }}</span>
                <span class="block text-[10px] uppercase font-bold opacity-60">{{ day.label.split(' ')[1] }}</span>
            </a>
            {% endfor %}
        </nav>

        <div class="mb-8 max-w-xl">
            <div class="relative">
                <input type="text" id="canalSearch" onkeyup="filterTable()" placeholder="Filtrar por canal o programa..." 
                class="w-full bg-slate-900 border border-slate-700 rounded-2xl px-6 py-4 text-white focus:ring-2 focus:ring-orange-500 outline-none transition-all placeholder:text-slate-600 font-medium shadow-xl">
                <div class="absolute right-5 top-4 text-slate-700">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                </div>
            </div>
        </div>

        {% if filter_name %}
        <div class="mb-6 flex justify-between items-center">
            <a href="/{{ '?date=' + current_date if mode != 'live' else '' }}" onclick="showLoading()" class="text-orange-400 font-bold hover:underline flex items-center">
                <span class="mr-2">←</span> VOLVER AL LISTADO COMPLETO
            </a>
            <span class="bg-orange-500/10 text-orange-500 px-4 py-1 rounded-full text-xs font-black border border-orange-500/20 uppercase tracking-tighter">FILTRO: {{ filter_name }}</span>
        </div>
        {% endif %}

        <div class="bg-slate-900/50 rounded-3xl border border-slate-800 overflow-hidden shadow-2xl backdrop-blur-md">
            <table class="w-full text-left" id="epgTable">
                <thead>
                    <tr class="bg-slate-950/80 text-slate-500 text-[10px] uppercase tracking-widest border-b border-slate-800">
                        <th class="px-8 py-5">Canal</th>
                        <th class="px-8 py-5">Horario</th>
                        <th class="px-8 py-5">Programa</th>
                        <th class="px-8 py-5 text-center">Acciones</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-800/50">
                    {% for _, row in data.iterrows() %}
                    <tr class="hover:bg-slate-800/40 transition-all group">
                        <td class="px-8 py-6 canal-cell">
                            <a href="/?{{ 'date=' + current_date + '&' if mode != 'live' else '' }}filter={{ row.channel_id }}" 
                               onclick="trackClick('{{ row.channel_id }}'); showLoading();" 
                               class="text-orange-500 font-black text-lg hover:text-orange-400 transition-colors">
                                 {{ row.canal }}
                            </a>
                        </td>
                        <td class="px-8 py-6 font-mono text-sm text-slate-400 italic">
                            {{ row.inicio }} - {{ row.fin }}
                        </td>
                        <td class="px-8 py-6 programa-cell">
                            <span class="text-slate-100 font-bold group-hover:text-white transition-colors">{{ row.titulo }}</span>
                        </td>
                        <td class="px-8 py-6 text-center">
                            <div class="flex justify-center gap-2">
                                {% if mode == 'live' %}
                                <a href="{{ row.url_live }}" onclick="trackClick('{{ row.channel_id }}')" target="_blank" class="bg-slate-100 hover:bg-white text-slate-900 text-[10px] font-black px-4 py-2.5 rounded-xl uppercase transition-all shadow-md active:scale-95">Directo</a>
                                {% endif %}
                                <a href="{{ row.url_play }}" onclick="trackClick('{{ row.channel_id }}')" target="_blank" class="bg-orange-600 hover:bg-orange-500 text-white text-[10px] font-black px-4 py-2.5 rounded-xl uppercase transition-all shadow-md active:scale-95">Ver</a>
                            </div>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <script>
        function showLoading() { document.getElementById('loading-overlay').style.display = 'flex'; }
        
        function normalizeStr(str) {
            return str.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
        }

        function filterTable() {
            let input = normalizeStr(document.getElementById("canalSearch").value);
            let tr = document.getElementById("epgTable").getElementsByTagName("tr");
            for (let i = 1; i < tr.length; i++) {
                let canalTd = tr[i].getElementsByClassName("canal-cell")[0];
                let programaTd = tr[i].getElementsByClassName("programa-cell")[0];
                if (canalTd && programaTd) {
                    let canalText = normalizeStr(canalTd.textContent);
                    let programaText = normalizeStr(programaTd.textContent);
                    tr[i].style.display = (canalText.indexOf(input) > -1 || programaText.indexOf(input) > -1) ? "" : "none";
                }
            }
        }

        function trackClick(channelId) { fetch('/track/' + channelId, { method: 'POST',  cache: 'no-store'}); 
}
        window.onpageshow = function(event) { if (event.persisted) document.getElementById('loading-overlay').style.display = 'none'; };
    </script>
</body>
</html>
"""

# --- RUTAS FLASK ---

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(BASE_DIR, 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route("/track/<channel_id>", methods=['POST'])  # <-- Cambiado a POST
def track(channel_id):
    """Registra clics solo mediante peticiones POST explícitas."""
    with stats_lock:
        stats = cargar_stats()
        stats[channel_id] = stats.get(channel_id, 0) + 1
        guardar_stats(stats)
    return jsonify(success=True)

@app.route("/")
def index():
    now = datetime.now()
    now_ts = now.timestamp() * 1000
    target_date = request.args.get("date", now.strftime("%Y%m%d"))
    filter_channel = request.args.get("filter")
    
    mode = "date" if "date" in request.args else "live"
    if filter_channel: mode = "filter"

    # Generar Top Canales desde el archivo (siempre frescos)
    with stats_lock:
        actual_stats = cargar_stats()
    
    nombres = obtener_mapeo_canales()
    top_list = sorted(actual_stats.items(), key=lambda x: x[1], reverse=True)[:6]
    top_canales = [{"id": k, "nombre": nombres.get(k, k)} for k, v in top_list]

    days_nav = []
    for i in range(8):
        d = now - timedelta(days=i)
        days_nav.append({"id": d.strftime("%Y%m%d"), "label": d.strftime("%d/%m %a")})
    
    df = obtener_epg_dia(target_date)
    if df.empty: return "<h1>Error de conexión o datos no disponibles. Reintenta en unos segundos.</h1>"

    filter_name = ""
    if filter_channel:
        display_df = df[df['channel_id'] == filter_channel].sort_values("start")
        filter_name = display_df.iloc[0]['canal'] if not display_df.empty else ""
    elif mode == "live":
        display_df = df[(df['start'] <= now_ts) & (df['end'] >= now_ts)]
        if display_df.empty: display_df = df.groupby('canal').first().reset_index()
        display_df = display_df.sort_values("canal")
    else:
        display_df = df.sort_values(["canal", "start"])

    return render_template_string(
        HTML_TEMPLATE, data=display_df, days=days_nav, 
        current_date=target_date, mode=mode,
        filter_name=filter_name, top_canales=top_canales,
        now_time=now.strftime("%H:%M:%S")
    )

if __name__ == "__main__":
    # Inicializar archivo si no existe
    if not os.path.exists(STATS_FILE):
        guardar_stats({})
    
    app.run(host='0.0.0.0', port=5000, debug=True)
