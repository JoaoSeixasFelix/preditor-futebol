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
# Selecoes (Copa do Mundo)
# ---------------------------------------------------------------------------
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
        times[t] = {"elo": round(elo.get(t, 1500)),
                    "atk": round(((mk[t]/n/MG)*n+k)/(n+k), 3),
                    "def": round(((sf[t]/n/MG)*n+k)/(n+k), 3)}
    return {"type": "intl", "media_gol": round(MG, 4), "times": times}

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
    out = {}
    sel = selecoes()
    if sel: out["Copa do Mundo"] = sel; print(f"Copa do Mundo: {len(sel['times'])} selecoes")
    for nome, code in MAIN.items():
        d = liga_main(code)
        if d:
            out[nome] = d
            print(f"{nome}: {len(d['times'])} times ({'completo' if d['type']=='club' else 'gols'})")
        else:
            print(f"{nome}: SEM DADOS, pulada")
    for nome, code in EXTRA.items():
        d = liga_extra(code)
        if d: out[nome] = d; print(f"{nome}: {len(d['times'])} times (gols)")
        else: print(f"{nome}: SEM DADOS, pulada")
    payload = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "competitions": out}
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(f"\nTOTAL: {len(out)} competicoes -> data.json ({len(json.dumps(payload))} bytes)")
