"""
Colheita incremental de escanteios/cartoes da API-Football (plano free).
Free = so temporadas 2022-2024 -> usamos p/ MEDIR as medias reais de
escanteios/cartoes de cada competicao (baseline), aguçando as estimativas.

- Orcamento: API_FOOTBALL_BUDGET req/run (default 85 de 100/dia)
- Ritmo: 6.5s entre chamadas (limite free: 10/min)
- Estado: apif_store.json (commitado; nunca re-busca o que ja tem)
- Sem chave (API_FOOTBALL_KEY) -> sai em silencio, nada quebra.
"""
import json, os, sys, time, urllib.request

KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
if not KEY:
    print("sem API_FOOTBALL_KEY; pulando colheita"); sys.exit(0)
BUDGET = int(os.environ.get("API_FOOTBALL_BUDGET", "85"))
STORE = "apif_store.json"

# fila de prioridade: (liga, temporada) - free so 2022-2024
TARGETS = [
    (71, 2024), (71, 2023), (13, 2024), (73, 2024), (11, 2024),
    (71, 2022), (13, 2023), (11, 2023), (73, 2023),
    (128, 2024), (262, 2024), (253, 2024), (98, 2024),
    (128, 2023), (262, 2023), (253, 2023), (98, 2023),
]

def api(path):
    global BUDGET
    if BUDGET <= 0: return None
    BUDGET -= 1
    req = urllib.request.Request(f"https://v3.football.api-sports.io/{path}",
                                 headers={"x-apisports-key": KEY})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            d = json.loads(r.read().decode())
    except Exception as e:
        print(f"  erro {path}: {e}"); return None
    time.sleep(6.5)
    if d.get("errors"):
        print(f"  api recusou {path}: {d['errors']}"); return None
    return d.get("response")

store = {"leagues": {}, "stats": {}}
if os.path.exists(STORE):
    store = json.load(open(STORE))

def save():
    json.dump(store, open(STORE, "w"))

novos = 0
for liga, season in TARGETS:
    if BUDGET <= 0: break
    k = f"{liga}_{season}"
    L = store["leagues"].setdefault(k, {})
    if "fixtures" not in L:
        resp = api(f"fixtures?league={liga}&season={season}")
        if resp is None: continue
        L["fixtures"] = [
            {"id": f["fixture"]["id"], "d": f["fixture"]["date"][:10],
             "h": f["teams"]["home"]["name"], "a": f["teams"]["away"]["name"],
             "hid": f["teams"]["home"]["id"], "aid": f["teams"]["away"]["id"],
             "hg": f["goals"]["home"], "ag": f["goals"]["away"]}
            for f in resp if f["fixture"]["status"]["short"] in ("FT", "AET", "PEN")
        ]
        save()
        print(f"{k}: lista com {len(L['fixtures'])} jogos terminados")
    falta = [f for f in L["fixtures"] if str(f["id"]) not in store["stats"]]
    for f in falta:
        if BUDGET <= 0: break
        resp = api(f"fixtures/statistics?fixture={f['id']}")
        if resp is None: continue
        lados = {}
        for t in resp:
            s = {x["type"]: x["value"] for x in t["statistics"]}
            lados[t["team"]["id"]] = s
        sh, sa = lados.get(f["hid"], {}), lados.get(f["aid"], {})
        hc, ac = sh.get("Corner Kicks"), sa.get("Corner Kicks")
        if hc is None or ac is None:
            store["stats"][str(f["id"])] = {"lg": k, "skip": 1}
        else:
            store["stats"][str(f["id"])] = {
                "lg": k, "hc": int(hc), "ac": int(ac),
                "hy": int(sh.get("Yellow Cards") or 0), "ay": int(sa.get("Yellow Cards") or 0),
                "hr": int(sh.get("Red Cards") or 0), "ar": int(sa.get("Red Cards") or 0)}
            novos += 1
        if novos % 10 == 0: save()
save()
ok = sum(1 for v in store["stats"].values() if "hc" in v)
print(f"colheita: +{novos} jogos | total no store: {ok} com stats | budget restante: {BUDGET}")
