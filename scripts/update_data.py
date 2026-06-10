"""
Pipeline de atualizacao do Preditor de Futebol.
Roda no GitHub Actions (cron diario) ou local. So stdlib.

Baixa dados reais, recalcula forcas de todos os times e escreve data.json.
- Ligas "full": gols + escanteios + cartoes (football-data.co.uk /mmz4281/)
- Ligas "extras": so gols (football-data.co.uk /new/)
- Selecoes: martj42/international_results
- Fallback: liga full sem colunas de escanteio entra como so-gols (nao some)
- Temporadas: as 4 mais recentes, calculadas pela data de hoje
"""
import csv, io, json, math, statistics, datetime, urllib.request
from collections import defaultdict

UA = {"User-Agent": "Mozilla/5.0 (preditor-futebol updater)"}

def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8-sig", errors="ignore")
    except Exception as e:
        print(f"  aviso: falha em {url}: {e}")
        return None

def season_codes(n=4):
    """Codigos mmz4281 das n temporadas mais recentes (Europa: ago-mai)."""
    today = datetime.date.today()
    start = today.year if today.month >= 7 else today.year - 1
    out = []
    for i in range(n):
        y = start - i
        out.append((f"{y%100:02d}{(y+1)%100:02d}", [1.0, 0.7, 0.5, 0.35][i]))
    return out

def wmean(v):
    n = sum(x*w for x, w in v); d = sum(w for _, w in v)
    return n/d if d else 0

def fac(acc, t, s, pk, base, k=4.0):
    p = acc[t][pk]
    if p < 1 or base <= 0: return 1.0
    return round(((acc[t][s]/p/base)*p + k)/(p + k), 3)

# ---------------------------------------------------------------------------
# Ligas principais: tenta full (gols+escanteios+cartoes), cai p/ so-gols
# ---------------------------------------------------------------------------
def liga_main(code):
    full, gols = [], []
    for season, w in season_codes():
        txt = fetch(f"https://www.football-data.co.uk/mmz4281/{season}/{code}.csv")
        if not txt: continue
        for r in csv.DictReader(io.StringIO(txt)):
            try:
                base = {"h": r["HomeTeam"], "a": r["AwayTeam"], "w": w,
                        "hg": int(r["FTHG"]), "ag": int(r["FTAG"])}
            except (ValueError, KeyError):
                continue
            gols.append(base)
            try:
                full.append({**base, "hc": int(r["HC"]), "ac": int(r["AC"]),
                             "hk": int(r["HY"])+int(r["HR"]), "ak": int(r["AY"])+int(r["AR"])})
            except (ValueError, KeyError):
                pass
    if len(full) >= 150:
        return _build_full(full)
    if len(gols) >= 50:
        return _build_gols(gols)
    return None

def _acc_gols(jogos):
    acc = defaultdict(lambda: defaultdict(float))
    for j in jogos:
        w = j["w"]; h, a = j["h"], j["a"]
        acc[h]["wh"] += w; acc[a]["wa"] += w
        acc[h]["gf_h"] += j["hg"]*w; acc[h]["ga_h"] += j["ag"]*w
        acc[a]["gf_a"] += j["ag"]*w; acc[a]["ga_a"] += j["hg"]*w
    return acc

def _build_full(jogos):
    LG = {k: wmean([(j[k], j["w"]) for j in jogos]) for k in ["hg","ag","hc","ac"]}
    LG["hcard"] = wmean([(j["hk"], j["w"]) for j in jogos])
    LG["acard"] = wmean([(j["ak"], j["w"]) for j in jogos])
    ct = [j["hc"]+j["ac"] for j in jogos]
    m, v = statistics.mean(ct), statistics.variance(ct)
    rc = m*m/(v-m) if v > m else 60.0
    acc = _acc_gols(jogos)
    for j in jogos:
        w = j["w"]; h, a = j["h"], j["a"]
        acc[h]["cf_h"] += j["hc"]*w; acc[h]["ca_h"] += j["ac"]*w
        acc[a]["cf_a"] += j["ac"]*w; acc[a]["ca_a"] += j["hc"]*w
        acc[h]["kf_h"] += j["hk"]*w; acc[a]["kf_a"] += j["ak"]*w
    times = {}
    for t in acc:
        if acc[t]["wh"] + acc[t]["wa"] < 3: continue
        times[t] = {"atk_h": fac(acc,t,"gf_h","wh",LG["hg"]), "def_h": fac(acc,t,"ga_h","wh",LG["ag"]),
            "atk_a": fac(acc,t,"gf_a","wa",LG["ag"]), "def_a": fac(acc,t,"ga_a","wa",LG["hg"]),
            "cf_h": fac(acc,t,"cf_h","wh",LG["hc"]), "ca_h": fac(acc,t,"ca_h","wh",LG["ac"]),
            "cf_a": fac(acc,t,"cf_a","wa",LG["ac"]), "ca_a": fac(acc,t,"ca_a","wa",LG["hc"]),
            "kf_h": fac(acc,t,"kf_h","wh",LG["hcard"]), "kf_a": fac(acc,t,"kf_a","wa",LG["acard"])}
    return {"type": "club", "lg": {k: round(v,4) for k,v in LG.items()},
            "r_corners": round(rc,2), "times": times}

def _build_gols(jogos):
    LG = {"hg": wmean([(j["hg"], j["w"]) for j in jogos]),
          "ag": wmean([(j["ag"], j["w"]) for j in jogos])}
    acc = _acc_gols(jogos)
    times = {}
    for t in acc:
        if acc[t]["wh"] + acc[t]["wa"] < 3: continue
        times[t] = {"atk_h": fac(acc,t,"gf_h","wh",LG["hg"]), "def_h": fac(acc,t,"ga_h","wh",LG["ag"]),
            "atk_a": fac(acc,t,"gf_a","wa",LG["ag"]), "def_a": fac(acc,t,"ga_a","wa",LG["hg"])}
    return {"type": "club_g", "lg": {k: round(v,4) for k,v in LG.items()}, "times": times}

# ---------------------------------------------------------------------------
# Ligas extras (/new/: arquivo unico, so gols) - 3 temporadas mais recentes
# ---------------------------------------------------------------------------
def liga_extra(code):
    txt = fetch(f"https://www.football-data.co.uk/new/{code}.csv")
    if not txt: return None
    import re
    rows = list(csv.DictReader(io.StringIO(txt)))
    def yr(s):
        m = re.findall(r"\d{4}", str(s)); return int(m[-1]) if m else 0
    anos = sorted({yr(r.get("Season","")) for r in rows if yr(r.get("Season",""))}, reverse=True)[:3]
    if not anos: return None
    jogos = []
    for r in rows:
        y = yr(r.get("Season",""))
        if y not in anos: continue
        try:
            jogos.append({"h": r["Home"], "a": r["Away"], "w": 0.5**(anos[0]-y),
                          "hg": int(r["HG"]), "ag": int(r["AG"])})
        except (ValueError, KeyError):
            continue
    return _build_gols(jogos) if len(jogos) >= 50 else None

# ---------------------------------------------------------------------------
# Copas via API publica da ESPN (sem chave). Resultados dos ultimos ~30 meses,
# peso decai com a idade (meia-vida 18 meses). So gols -> corners/cartoes
# entram via estimativa calibrada, como nas ligas extras.
# ---------------------------------------------------------------------------
def copa_espn(slug):
    import json as _json
    hoje = datetime.date.today()
    jogos = []
    fim = hoje
    for _ in range(10):  # 10 janelas de ~3 meses = ~30 meses
        ini = fim - datetime.timedelta(days=91)
        url = (f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/"
               f"scoreboard?dates={ini:%Y%m%d}-{fim:%Y%m%d}&limit=500")
        txt = fetch(url, timeout=40)
        fim = ini - datetime.timedelta(days=1)
        if not txt: continue
        try: data = _json.loads(txt)
        except ValueError: continue
        for ev in data.get("events", []):
            try:
                if ev["status"]["type"]["state"] != "post": continue
                comp = ev["competitions"][0]
                lados = {c["homeAway"]: c for c in comp["competitors"]}
                hg, ag = int(lados["home"]["score"]), int(lados["away"]["score"])
                d = datetime.date.fromisoformat(ev["date"][:10])
                w = 0.5 ** (((hoje - d).days) / 548.0)
                jogos.append({"h": lados["home"]["team"]["displayName"],
                              "a": lados["away"]["team"]["displayName"],
                              "w": w, "hg": hg, "ag": ag})
            except (KeyError, ValueError, IndexError):
                continue
    # dedup (janelas podem se sobrepor em eventos de borda)
    vistos, unicos = set(), []
    for j in jogos:
        k = (j["h"], j["a"], j["hg"], j["ag"], round(j["w"], 4))
        if k not in vistos: vistos.add(k); unicos.append(j)
    return _build_gols(unicos) if len(unicos) >= 50 else None

COPAS = {
    "Libertadores (CONMEBOL)": "conmebol.libertadores",
    "Sul-Americana (CONMEBOL)": "conmebol.sudamericana",
    "Copa do Brasil (BRA)": "bra.copa_do_brazil",
}

# ---------------------------------------------------------------------------
# Medias medidas via API-Football (apif_store.json, colhido pelo harvester)
# ---------------------------------------------------------------------------
APIF_MAP = {
    "Brasileirao (BRA)": 71, "Libertadores (CONMEBOL)": 13,
    "Sul-Americana (CONMEBOL)": 11, "Copa do Brasil (BRA)": 73,
    "Primera (ARG)": 128, "Liga MX (MEX)": 262, "MLS (EUA)": 253,
    "J1 League (JAP)": 98,
}

def load_apif_means():
    import os
    if not os.path.exists("apif_store.json"): return {}
    try: store = json.load(open("apif_store.json"))
    except ValueError: return {}
    por_liga = {}
    for v in store.get("stats", {}).values():
        if "hc" not in v: continue
        lid = int(v["lg"].split("_")[0])
        por_liga.setdefault(lid, []).append(v)
    out = {}
    for lid, rows in por_liga.items():
        if len(rows) < 60: continue
        n = len(rows)
        hc = sum(r["hc"] for r in rows)/n; ac = sum(r["ac"] for r in rows)/n
        hcard = sum(r["hy"]+r["hr"] for r in rows)/n
        acard = sum(r["ay"]+r["ar"] for r in rows)/n
        tots = [r["hc"]+r["ac"] for r in rows]
        m = sum(tots)/n; v_ = sum((t-m)**2 for t in tots)/max(n-1,1)
        r_ = m*m/(v_-m) if v_ > m else 60.0
        out[lid] = {"hc": round(hc,4), "ac": round(ac,4), "hcard": round(hcard,4),
                    "acard": round(acard,4), "r": round(r_,2), "n": n}
    return out

# ---------------------------------------------------------------------------
# Selecoes (Copa do Mundo)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Calibracao cruzada: nas ligas completas, mede como escanteios/cartoes
# se relacionam com forca de ataque/defesa. Usa isso p/ ESTIMAR esses
# mercados nas ligas que so publicam gols (marcadas com est=true).
# ---------------------------------------------------------------------------
def fit_exponent(pairs, default):
    """regressao log-log pela origem: y = x^b"""
    num = den = 0.0
    for x, y in pairs:
        if x <= 0 or y <= 0: continue
        lx, ly = math.log(x), math.log(y)
        num += lx*ly; den += lx*lx
    return round(num/den, 3) if den > 0 else default

def calibrate(fulls):
    p_atk_cf, p_def_ca, p_def_kf = [], [], []
    lgs, rs = [], []
    for d in fulls:
        lgs.append(d["lg"]); rs.append(d["r_corners"])
        for t in d["times"].values():
            p_atk_cf += [(t["atk_h"], t["cf_h"]), (t["atk_a"], t["cf_a"])]
            p_def_ca += [(t["def_h"], t["ca_h"]), (t["def_a"], t["ca_a"])]
            p_def_kf += [(t["def_h"], t["kf_h"]), (t["def_a"], t["kf_a"])]
    n = len(lgs) or 1
    glob = {k: round(sum(l[k] for l in lgs)/n, 4) for k in ["hc","ac","hcard","acard"]}
    glob["r"] = round(sum(rs)/n, 2)
    return {"glob": glob,
            "b_cf": fit_exponent(p_atk_cf, 0.7),
            "b_ca": fit_exponent(p_def_ca, 0.5),
            "b_kf": fit_exponent(p_def_kf, 0.3)}

def synthesize(comp, cal, meas=None):
    """adiciona escanteios/cartoes estimados a uma competicao so-gols.
    meas = medias MEDIDAS da propria competicao (API-Football 2022-24);
    quando presentes, substituem o baseline europeu."""
    g = meas or cal["glob"]
    comp["lg"].update({"hc": g["hc"], "ac": g["ac"], "hcard": g["hcard"], "acard": g["acard"]})
    comp["r_corners"] = g["r"]
    comp["est"] = True
    if meas: comp["meas_base"] = True
    for t in comp["times"].values():
        ah, aa = t["atk_h"], t["atk_a"]
        dh, da = t["def_h"], t["def_a"]
        t["cf_h"] = round(ah**cal["b_cf"], 3); t["cf_a"] = round(aa**cal["b_cf"], 3)
        t["ca_h"] = round(dh**cal["b_ca"], 3); t["ca_a"] = round(da**cal["b_ca"], 3)
        t["kf_h"] = round(dh**cal["b_kf"], 3); t["kf_a"] = round(da**cal["b_kf"], 3)
    return comp

def selecoes():
    txt = fetch("https://raw.githubusercontent.com/martj42/international_results/master/results.csv", timeout=120)
    if not txt: return None
    HOJE = datetime.date.today(); HL = 3.0; JAN = 8
    jogos = []
    for r in csv.DictReader(io.StringIO(txt)):
        if r["home_score"] in ("", "NA"): continue
        try:
            d = datetime.date.fromisoformat(r["date"])
            hs, as_ = int(r["home_score"]), int(r["away_score"])
        except ValueError:
            continue
        jogos.append({"d": d, "c": r["home_team"], "f": r["away_team"], "gc": hs, "gf": as_})
    pw = lambda d: 0.5**(((HOJE-d).days/365.25)/HL)
    lim = HOJE - datetime.timedelta(days=int(JAN*365.25))
    rec = [j for j in jogos if j["d"] >= lim]
    MG = sum((j["gc"]+j["gf"])*pw(j["d"]) for j in rec) / sum(2*pw(j["d"]) for j in rec)
    mk, sf, pe = defaultdict(float), defaultdict(float), defaultdict(float)
    for j in rec:
        w = pw(j["d"])
        for t, gm, gs in [(j["c"], j["gc"], j["gf"]), (j["f"], j["gf"], j["gc"])]:
            mk[t] += gm*w; sf[t] += gs*w; pe[t] += w
    elo = {}
    for j in sorted(jogos, key=lambda x: x["d"]):
        ra, rb = elo.get(j["c"], 1500.0), elo.get(j["f"], 1500.0)
        ea = 1/(1+10**(-(ra-rb)/400))
        sa = 1.0 if j["gc"] > j["gf"] else (0.5 if j["gc"] == j["gf"] else 0.0)
        g = math.log(max(abs(j["gc"]-j["gf"]), 1)+1)
        elo[j["c"]] = ra + 40*g*(sa-ea); elo[j["f"]] = rb + 40*g*((1-sa)-(1-ea))
    times = {}
    for t in pe:
        if pe[t] < 4: continue
        n = pe[t]; k = 6.0
        atk = round(((mk[t]/n/MG)*n+k)/(n+k), 3)
        dfc = round(((sf[t]/n/MG)*n+k)/(n+k), 3)
        # formato unico (clube): jogo neutro -> mesma forca casa/fora e hg=ag
        times[t] = {"elo": round(elo.get(t, 1500)),
                    "atk_h": atk, "atk_a": atk, "def_h": dfc, "def_a": dfc}
    return {"type": "intl", "lg": {"hg": round(MG, 4), "ag": round(MG, 4)}, "times": times}

# ---------------------------------------------------------------------------
# Catalogo de competicoes (paridade: divisoes inferiores onde existem)
# ---------------------------------------------------------------------------
MAIN = {
    "Premier League (ING)": "E0", "Championship (ING)": "E1",
    "League One (ING)": "E2", "League Two (ING)": "E3", "National League (ING)": "EC",
    "Premiership (ESC)": "SC0", "Championship (ESC)": "SC1",
    "League One (ESC)": "SC2", "League Two (ESC)": "SC3",
    "Bundesliga (ALE)": "D1", "2. Bundesliga (ALE)": "D2",
    "La Liga (ESP)": "SP1", "La Liga 2 (ESP)": "SP2",
    "Serie A (ITA)": "I1", "Serie B (ITA)": "I2",
    "Ligue 1 (FRA)": "F1", "Ligue 2 (FRA)": "F2",
    "Eredivisie (HOL)": "N1", "Pro League (BEL)": "B1",
    "Primeira Liga (POR)": "P1", "Super Lig (TUR)": "T1", "Super League (GRE)": "G1",
}
EXTRA = {
    "Brasileirao (BRA)": "BRA", "Primera (ARG)": "ARG", "Liga MX (MEX)": "MEX",
    "MLS (EUA)": "USA", "J1 League (JAP)": "JPN", "Super League (CHN)": "CHN",
    "Eliteserien (NOR)": "NOR", "Allsvenskan (SUE)": "SWE", "Superliga (DIN)": "DNK",
    "Bundesliga (AUT)": "AUT", "Ekstraklasa (POL)": "POL", "Premier Liga (RUS)": "RUS",
    "Premier (IRL)": "IRL", "Veikkausliiga (FIN)": "FIN", "Liga I (ROM)": "ROU",
    "Super League (SUI)": "SWZ",
}

if __name__ == "__main__":
    main_results, fulls = {}, []
    for nome, code in MAIN.items():
        d = liga_main(code)
        if d:
            main_results[nome] = d
            if d["type"] == "club": fulls.append(d)
            print(f"{nome}: {len(d['times'])} times ({'completo' if d['type']=='club' else 'gols->estimado'})")
        else:
            print(f"{nome}: SEM DADOS, pulada")
    cal = calibrate(fulls)
    print(f"calibracao ({len(fulls)} ligas): corners~atk^{cal['b_cf']}  "
          f"corners_contra~def^{cal['b_ca']}  cartoes~def^{cal['b_kf']}")
    MEAS = load_apif_means()
    def meas_de(nome): return MEAS.get(APIF_MAP.get(nome))
    if MEAS:
        for lid, m in MEAS.items():
            print(f"  baseline medido liga {lid}: corners {m['hc']+m['ac']:.1f} cartoes {m['hcard']+m['acard']:.1f} ({m['n']} jogos)")
    out = {}
    sel = selecoes()
    if sel:
        out["Copa do Mundo"] = synthesize(sel, cal)
        print(f"Copa do Mundo: {len(sel['times'])} selecoes (corners/cartoes estimados)")
    for nome, slug in COPAS.items():
        d = copa_espn(slug)
        if d:
            out[nome] = synthesize(d, cal, meas_de(nome))
            base = "baseline medido" if d.get("meas_base") else "baseline europeu"
            print(f"{nome}: {len(d['times'])} times (ESPN, {base})")
        else:
            print(f"{nome}: SEM DADOS, pulada")
    for nome, d in main_results.items():
        out[nome] = d if d["type"] == "club" else synthesize(d, cal, meas_de(nome))
    for nome, code in EXTRA.items():
        d = liga_extra(code)
        if d:
            out[nome] = synthesize(d, cal, meas_de(nome))
            base = "baseline medido" if d.get("meas_base") else "baseline europeu"
            print(f"{nome}: {len(d['times'])} times ({base})")
        else:
            print(f"{nome}: SEM DADOS, pulada")
    payload = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "competitions": out}
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(f"\nTOTAL: {len(out)} competicoes -> data.json ({len(json.dumps(payload))} bytes)")
