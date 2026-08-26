
import json
import math
import itertools
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

DEFAULT_LEAGUE_ID = "1389344022107021312"
SLEEPER = "https://api.sleeper.app/v1"
FP = "https://api.fantasypros.com/public/v2/json"

st.set_page_config(
    page_title="Sleeper GM",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# STYLE
# ============================================================

st.markdown("""
<style>
:root {
  --bg:#0b0f14; --panel:#111822; --panel2:#0f151d;
  --border:rgba(255,255,255,.08); --muted:#9aa6b2;
  --text:#f5f7fa; --accent:#7c3aed; --good:#22c55e;
  --warn:#f59e0b; --bad:#ef4444;
}
html, body, [data-testid="stAppViewContainer"] { background:var(--bg); color:var(--text); }
.block-container { max-width:1320px; padding-top:1.15rem; padding-bottom:4rem; }
[data-testid="stSidebar"] { background:#0d131b; border-right:1px solid var(--border); }
.hero {
  background:
    radial-gradient(900px 420px at 0% 0%, rgba(124,58,237,.25), transparent 55%),
    linear-gradient(135deg,#121927,#0f1520);
  border:1px solid var(--border); border-radius:24px; padding:26px 28px; margin-bottom:18px;
}
.hero .kicker { color:#c4b5fd; text-transform:uppercase; font-weight:800; font-size:.72rem; letter-spacing:.12em; }
.hero h1 { margin:.15rem 0 .35rem 0; font-size:clamp(2.2rem,5vw,4rem); letter-spacing:-.055em; line-height:.96; }
.hero p { color:var(--muted); margin:0; }
.stat-card {
  background:linear-gradient(180deg,rgba(255,255,255,.035),rgba(255,255,255,.015));
  border:1px solid var(--border); border-radius:18px; padding:16px 18px; min-height:108px;
}
.stat-label { color:var(--muted); font-size:.76rem; text-transform:uppercase; letter-spacing:.08em; font-weight:700; }
.stat-value { font-size:2rem; font-weight:800; letter-spacing:-.04em; margin-top:.28rem; }
.stat-sub { color:var(--muted); margin-top:.1rem; font-size:.84rem; }
.player-card {
  display:flex; align-items:center; justify-content:space-between; gap:14px;
  background:var(--panel); border:1px solid var(--border); border-radius:16px;
  padding:13px 14px; margin-bottom:8px;
}
.player-name { font-weight:800; font-size:1.02rem; }
.player-meta { color:var(--muted); font-size:.82rem; margin-top:2px; }
.player-score { font-weight:800; font-size:1.05rem; white-space:nowrap; }
.badge {
  display:inline-block; border:1px solid var(--border); background:rgba(255,255,255,.04);
  border-radius:999px; padding:.18rem .48rem; font-size:.72rem; font-weight:800; margin-left:.35rem;
}
.badge.good{color:var(--good)} .badge.warn{color:var(--warn)} .badge.bad{color:var(--bad)} .badge.accent{color:#c4b5fd}
.section-head { display:flex; align-items:end; justify-content:space-between; gap:12px; margin:1.5rem 0 .75rem; }
.section-head h2,.section-head h3{margin:0}.section-head span{color:var(--muted);font-size:.84rem}
.notice { border:1px solid var(--border); background:rgba(124,58,237,.08); border-radius:14px; padding:12px 14px; color:#ddd6fe; }
.goodbox { border:1px solid rgba(34,197,94,.25); background:rgba(34,197,94,.06); border-radius:14px; padding:12px 14px; }
.warnbox { border:1px solid rgba(245,158,11,.25); background:rgba(245,158,11,.06); border-radius:14px; padding:12px 14px; }
div[data-testid="stMetric"] { background:var(--panel); border:1px solid var(--border); border-radius:16px; padding:.7rem .85rem; }
div[data-testid="stDataFrame"] { border:1px solid var(--border); border-radius:14px; overflow:hidden; }
.stButton button,.stDownloadButton button{border-radius:12px!important;font-weight:700!important}
@media (max-width:760px){.block-container{padding-left:.7rem;padding-right:.7rem}.hero{padding:20px;border-radius:20px}.stat-value{font-size:1.65rem}}
</style>
""", unsafe_allow_html=True)

# ============================================================
# API HELPERS
# ============================================================

@st.cache_data(ttl=300, show_spinner=False)
def sleeper_get(path):
    r = requests.get(f"{SLEEPER}{path}", timeout=20)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=3600, show_spinner=False)
def players_db():
    return sleeper_get("/players/nfl")

def fp_key():
    try:
        return st.secrets.get("FANTASYPROS_API_KEY")
    except Exception:
        return None

@st.cache_data(ttl=1800, show_spinner=False)
def fp_get(path, key):
    if not key:
        return None
    r = requests.get(
        f"{FP}{path}",
        headers={"x-api-key": key, "User-Agent": "SleeperGM/6.1"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()

def normalize_player_name(name):
    """Normalize Sleeper/FantasyPros names so suffixes and punctuation do not break matches."""
    text=unicodedata.normalize("NFKD", str(name or "")).encode("ascii","ignore").decode("ascii")
    text=text.lower().replace("’", "'")
    text=re.sub(r"[^a-z0-9 ]+", " ", text)
    parts=[x for x in text.split() if x not in {"jr","sr","ii","iii","iv","v"}]
    return " ".join(parts)

def ranking_lookup(rankings, name):
    if not rankings:
        return {}
    return rankings.get(normalize_player_name(name), {})

def fp_diagnostics(season, key, scoring="PPR"):
    """Make a small uncached request and report whether FantasyPros is truly returning usable rows."""
    diag={"key_present":bool(key),"ok":False,"status":None,"rows":0,"message":"No API key found"}
    if not key:
        return diag
    try:
        url=f"{FP}/nfl/{season}/consensus-rankings?position=RB&scoring={scoring}"
        r=requests.get(url,headers={"x-api-key":key,"User-Agent":"SleeperGM/6.1"},timeout=20)
        diag["status"]=r.status_code
        if not r.ok:
            diag["message"]=f"FantasyPros HTTP {r.status_code}: {r.text[:180]}"
            return diag
        payload=r.json()
        rows=flatten_rows(payload)
        diag["rows"]=len(rows)
        diag["ok"]=len(rows)>0
        diag["message"]=(f"FantasyPros returned {len(rows)} RB ranking rows" if rows else "FantasyPros responded, but no ranking rows were found")
        return diag
    except Exception as e:
        diag["message"]=f"FantasyPros request failed: {e}"
        return diag

def flatten_rows(payload):
    if payload is None: return []
    if isinstance(payload, list): return payload
    for k in ("players","results","data","items","news"):
        v = payload.get(k) if isinstance(payload, dict) else None
        if isinstance(v, list): return v
    return []

@st.cache_data(ttl=1800, show_spinner=False)
def fp_rankings(season, key, scoring="PPR"):
    """Return separate FantasyPros ECR and ADP signals.

    ECR is the expert-value layer; ADP is the market-price layer. They are
    deliberately kept separate so disagreement can be surfaced rather than
    averaged away.
    """
    if not key:
        return {}
    out = {}
    for pos in ["QB","RB","WR","TE","K","DST"]:
        # Expert consensus
        try:
            payload = fp_get(
                f"/nfl/{season}/consensus-rankings?position={pos}&scoring={scoring}",
                key,
            )
            for x in flatten_rows(payload):
                name = x.get("player_name") or x.get("name") or " ".join(
                    y for y in [x.get("player_first_name"), x.get("player_last_name")] if y
                ).strip()
                if not name:
                    continue
                rec = out.setdefault(normalize_player_name(name), {})
                rec["ecr"] = x.get("rank_ecr") or x.get("rank") or x.get("overall_rank")
                rec["tier"] = x.get("tier")
                # Some responses include ADP alongside ECR.
                rec["adp"] = x.get("rank_adp") or x.get("adp") or rec.get("adp")
        except Exception:
            pass

        # Explicit ADP request gives us a separate market-price signal.
        try:
            payload = fp_get(
                f"/nfl/{season}/consensus-rankings?position={pos}&scoring={scoring}&type=ADP",
                key,
            )
            for x in flatten_rows(payload):
                name = x.get("player_name") or x.get("name") or " ".join(
                    y for y in [x.get("player_first_name"), x.get("player_last_name")] if y
                ).strip()
                if not name:
                    continue
                rec = out.setdefault(normalize_player_name(name), {})
                rec["adp"] = (
                    x.get("rank_adp") or x.get("adp") or x.get("rank_ecr")
                    or x.get("rank") or x.get("overall_rank")
                )
        except Exception:
            pass
    return out

@st.cache_data(ttl=900, show_spinner=False)
def fp_weekly_projections(season, week, key, scoring="PPR"):
    if not key:
        return {}
    out={}
    for pos in ["QB","RB","WR","TE","K","DST"]:
        try:
            payload=fp_get(
                f"/nfl/{season}/projections?week={week}&position={pos}&scoring={scoring}",
                key,
            )
        except Exception:
            continue
        for x in flatten_rows(payload):
            name=x.get("player_name") or x.get("name") or " ".join(
                y for y in [x.get("player_first_name"),x.get("player_last_name")] if y
            ).strip()
            stats=x.get("stats") or {}
            pts=(
                x.get("fantasy_points") or x.get("fpts") or x.get("points")
                or stats.get("points_ppr" if scoring=="PPR" else ("points_half" if scoring=="HALF" else "points"))
            )
            if name:
                try: out[normalize_player_name(name)]=float(pts)
                except Exception: pass
    return out

@st.cache_data(ttl=900, show_spinner=False)
def fp_news(key):
    if not key: return []
    try:
        return flatten_rows(fp_get("/nfl/news", key))
    except Exception:
        return []

# ============================================================
# DATA / VALUE MODEL
# ============================================================

def display_name(user):
    md = user.get("metadata") or {}
    return md.get("team_name") or user.get("display_name") or user.get("username") or f"User {user.get('user_id','')}"

def pmeta(pid, players):
    p = players.get(str(pid), {})
    name = p.get("full_name") or " ".join(x for x in [p.get("first_name"), p.get("last_name")] if x).strip() or str(pid)
    return {
        "player_id": str(pid),
        "name": name,
        "position": p.get("position"),
        "team": p.get("team"),
        "injury": p.get("injury_status"),
        "status": p.get("status"),
        "depth": p.get("depth_chart_order"),
        "age": p.get("age"),
        "search_rank": p.get("search_rank"),
    }

def injury_mult(s):
    s=(s or "").lower()
    return {"out":.70,"ir":.70,"pup":.74,"doubtful":.82,"questionable":.93}.get(s,1.0)

def is_current_nfl_player(raw_player):
    """Filter stale historical Sleeper records from waiver/free-agent lists."""
    if not raw_player:
        return False
    if raw_player.get("active") is not True:
        return False
    if not raw_player.get("team"):
        return False
    status=str(raw_player.get("status") or "").lower()
    if status in {"retired","inactive"}:
        return False
    return True

def pick_value(pick_no):
    """Draft capital is useful early, then deliberately fades as current-season evidence grows."""
    if not pick_no: return 0.0
    p=max(1,float(pick_no))
    base=92/(p**0.38)
    week=max(1,int(globals().get("CURRENT_WEEK",1) or 1))
    # 100% in Week 1, ~70% by Week 9, ~48% by fantasy playoffs.
    decay=max(.42, 1.0-(week-1)*.038)
    return base*decay

def search_value(rank):
    try: r=float(rank)
    except Exception: return 0.0
    if r<=0: return 0.0
    return max(0.0,38/(r**0.28))

def ecr_value(ecr):
    try: e=float(ecr)
    except Exception: return 0.0
    return max(3.0,100/(max(1,e)**0.34))

def adp_value(adp):
    try: a=float(adp)
    except Exception: return 0.0
    return max(2.5,96/(max(1,a)**0.34))

def external_signal(rank_rec):
    """Blend expert consensus and market price without letting either dominate."""
    rank_rec = rank_rec or {}
    ev=ecr_value(rank_rec.get("ecr"))
    av=adp_value(rank_rec.get("adp"))
    if ev and av:
        value=ev*.68+av*.32
    else:
        value=ev or av
    disagreement=0.0
    if ev and av:
        disagreement=abs(ev-av)/max(ev,av)
    return value, disagreement

def asset_quality(combo):
    """Best-player concentration matters in fantasy trades."""
    if not combo:
        return 0.0
    vals=sorted((float(x["value"]) for x in combo), reverse=True)
    return vals[0] + (sum(vals[1:])*.58)

def consolidation_premium(combo):
    """Premium demanded when one side gives the best single asset for depth."""
    if len(combo) != 1:
        return 1.0
    v=float(combo[0]["value"])
    if v >= 42: return 1.20
    if v >= 34: return 1.16
    if v >= 27: return 1.12
    if v >= 20: return 1.08
    return 1.04

def value_source(meta,pick_map,rankings):
    rr=ranking_lookup(rankings,meta.get("name")) if rankings else {}
    sig=[]
    if rr.get("ecr") is not None: sig.append("FP ECR")
    if rr.get("adp") is not None: sig.append("FP ADP")
    if pick_map.get(meta.get("player_id")) is not None: sig.append("League draft")
    if meta.get("search_rank") is not None: sig.append("Sleeper market")
    if meta.get("depth") is not None: sig.append("Depth chart")
    return sig

def value_confidence(meta,pick_map,rankings):
    sig=value_source(meta,pick_map,rankings)
    score=3*("FP ECR" in sig)+2*("FP ADP" in sig)+2*("League draft" in sig)+("Sleeper market" in sig)+("Depth chart" in sig)
    return "Very High" if score>=7 else "High" if score>=5 else "Medium" if score>=3 else "Low"

def sleeper_market_value(meta):
    base=search_value(meta.get("search_rank"))
    d=meta.get("depth"); pos=meta.get("position")
    # Role matters most at positions where opportunity drives fantasy output.
    role={1:1.13,2:1.04,3:.97}.get(d, .88 if isinstance(d,(int,float)) and d>=4 else 1.0)
    if pos=="QB": role={1:1.07,2:.82,3:.68}.get(d,.72 if d else 1.0)
    return base*role

def position_curve(pos, raw):
    """League-aware scarcity curve. Elite RB/WR/TE assets separate; 1QB depth compresses."""
    scarcity=globals().get("POS_SCARCITY",{})
    mult={"RB":1.08,"WR":1.03,"TE":1.00,"QB":.82,"K":.24,"DEF":.27}.get(pos,.55)
    mult*=scarcity.get(pos,1.0)
    x=max(0.0,raw*mult)
    # Gentle elite premium; avoids making ordinary depth assets look like stars.
    if pos in {"RB","WR"} and x>28: x=28+(x-28)*1.10
    elif pos=="TE" and x>24: x=24+(x-24)*1.08
    elif pos=="QB" and x>32: x=32+(x-32)*1.04
    return x

def player_value(meta,pick_map,rankings):
    rr=ranking_lookup(rankings,meta["name"]) if rankings else {}
    ext,_=external_signal(rr) if rr else (0.0,0.0)
    drafted=pick_value(pick_map.get(meta["player_id"]))
    sleeper=sleeper_market_value(meta)
    base=drafted*.54+sleeper*.46 if drafted and sleeper else drafted or sleeper
    # External consensus is a corroborating signal, never the identity/value engine.
    ext_weight=.28 if rr.get("ecr") is not None and rr.get("adp") is not None else .18 if ext else 0
    raw=base*(1-ext_weight)+ext*ext_weight if ext and base else ext or base
    return max(0.0,position_curve(meta.get("position"),raw)*injury_mult(meta.get("injury")))

def roster_rows(roster,players,pick_map,rankings):
    starters={str(x) for x in (roster.get("starters") or [])}
    out=[]
    for pid in roster.get("players") or []:
        m=pmeta(pid,players); m["starter"]=str(pid) in starters
        m["value"]=round(player_value(m,pick_map,rankings)*(1.035 if m["starter"] and m.get("position") in {"RB","WR","TE"} else 1.015 if m["starter"] and m.get("position")=="QB" else 1.0),2)
        rr=ranking_lookup(rankings,m["name"]) if rankings else {}
        m["ecr"]=rr.get("ecr"); m["adp"]=rr.get("adp")
        _,dis=external_signal(rr) if rr else (0.0,0.0)
        m["market_disagreement"]=round(dis*100,1) if dis else 0.0
        sig=value_source(m,pick_map,rankings)
        m["value_source"]=" + ".join(sig) if sig else "Sleeper fallback"
        m["confidence"]=value_confidence(m,pick_map,rankings)
        out.append(m)
    return out

def pos_values(roster, players, pick_map, rankings):
    d=defaultdict(list)
    for r in roster_rows(roster,players,pick_map,rankings):
        if r["position"]:
            d[r["position"]].append(r["value"])
    for p in d: d[p].sort(reverse=True)
    return d

def raw_power(roster, players, pick_map, rankings):
    vals=pos_values(roster,players,pick_map,rankings)
    weights={
        "QB":[1,.12], "RB":[1,.94,.66,.44,.28,.15],
        "WR":[1,.96,.78,.52,.32,.18], "TE":[1,.18],
        "K":[.06], "DEF":[.08]
    }
    total=0; bd={}
    for pos, arr in vals.items():
        w=weights.get(pos,[.08]*len(arr))
        s=sum(v*(w[i] if i<len(w) else .07) for i,v in enumerate(arr))
        bd[pos]=s; total+=s
    return total,bd

def normalize(items):
    vals=[x["raw"] for x in items]; lo=min(vals); hi=max(vals)
    for x in items:
        x["score"]=82 if hi==lo else 68+27*((x["raw"]-lo)/(hi-lo))
    return items

def grade(score):
    if score>=92:return "A+"
    if score>=88:return "A"
    if score>=84:return "A-"
    if score>=80:return "B+"
    if score>=76:return "B"
    if score>=72:return "B-"
    return "C"

def needs(roster, players, pick_map, rankings):
    vals=pos_values(roster,players,pick_map,rankings)
    target={"QB":1,"RB":4,"WR":4,"TE":1}
    threshold={"QB":25,"RB":22,"WR":22,"TE":18}
    out={}
    for pos,c in target.items():
        arr=vals.get(pos,[])
        core=sum(arr[:c])/c if arr else 0
        out[pos]=max(0,threshold[pos]-core)+max(0,c-len(arr))*7
    return out

def surplus(roster, players, pick_map, rankings):
    vals=pos_values(roster,players,pick_map,rankings)
    baselines={"QB":1,"RB":4,"WR":4,"TE":1}
    out={}
    for pos,b in baselines.items():
        arr=vals.get(pos,[])
        extras=max(0,len(arr)-b)
        quality=sum(arr[b:b+extras]) if extras else 0
        out[pos]=quality + extras*3
    return out


def team_utility(roster, players, pick_map, rankings):
    raw,_=raw_power(roster,players,pick_map,rankings)
    return raw-sum(needs(roster,players,pick_map,rankings).values())*.35

def roster_after_trade(roster, give_ids, receive_ids):
    new=dict(roster)
    cur=[str(x) for x in (roster.get("players") or [])]
    cur=[x for x in cur if x not in set(give_ids)]
    cur.extend([str(x) for x in receive_ids if str(x) not in cur])
    new["players"]=cur
    return new

def combo_label(combo):
    return " + ".join(x["name"] for x in combo)


def starter_replacement_level(roster, players, pick_map, rankings, pos):
    vals=[x for x in roster_rows(roster,players,pick_map,rankings) if x["position"]==pos]
    vals=sorted(vals,key=lambda x:x["value"],reverse=True)
    starter_counts={"QB":1,"RB":2,"WR":2,"TE":1}
    n=starter_counts.get(pos,1)
    return vals[n]["value"] if len(vals)>n else (vals[-1]["value"]*.65 if vals else 0.0)

def expendability(row, roster, players, pick_map, rankings):
    """Higher = easier for that manager to move."""
    pos=row["position"]
    repl=starter_replacement_level(roster,players,pick_map,rankings,pos)
    gap=max(0.0,row["value"]-repl)
    score=55.0
    if row.get("starter"):
        score-=18
    score-=min(24,gap*.9)
    # Deep rooms make a player more moveable.
    depth_count=sum(1 for x in roster_rows(roster,players,pick_map,rankings) if x["position"]==pos)
    score+=min(16,max(0,depth_count-3)*4)
    if row.get("confidence")=="Low":
        score-=4
    return max(5,min(95,score))

def best_asset_premium(combo):
    if not combo:
        return 1.0
    best=max(float(x["value"]) for x in combo)
    if best>=60:return 1.24
    if best>=45:return 1.19
    if best>=35:return 1.15
    if best>=27:return 1.11
    return 1.06

def package_discount(combo):
    # Two lesser assets are worth less than their arithmetic sum in consolidation deals.
    if len(combo)<=1:
        return 1.0
    vals=sorted((float(x["value"]) for x in combo),reverse=True)
    second=vals[1] if len(vals)>1 else 0
    return max(.82,min(.94,.90 + min(4,second/25)*.01))

def confidence_multiplier(combo):
    if not combo:return 1.0
    weights={"Very High":1.0,"High":.98,"Medium":.94,"Low":.88}
    return sum(weights.get(x.get("confidence"),.92) for x in combo)/len(combo)

def human_trade_value(combo):
    if not combo:return 0.0
    raw=sum(float(x["value"]) for x in combo)
    raw*=package_discount(combo)
    raw*=confidence_multiplier(combo)
    if len(combo)==1:
        raw*=best_asset_premium(combo)
    return raw

def manager_incentive(give_combo, receive_combo, roster, players, pick_map, rankings):
    """How much this manager is motivated to swap these assets."""
    nd=needs(roster,players,pick_map,rankings)
    score=0.0
    for x in receive_combo:
        score += min(8,nd.get(x["position"],0)*.32)
    for x in give_combo:
        exp=expendability(x,roster,players,pick_map,rankings)
        score += (exp-50)/18
    return score

def offer_tier(acceptance, your_gain, their_gain):
    if acceptance>=68 and their_gain>=1.0 and your_gain>=.5:
        return "Strong"
    if acceptance>=55 and their_gain>=.25:
        return "Realistic"
    return "Aggressive"

def acceptance_label(p):
    if p>=70:return "High"
    if p>=55:return "Medium"
    return "Low"

def generate_trade_suggestions(my_roster, partner, players, pick_map, rankings, max_results=20):
    mine=[x for x in roster_rows(my_roster,players,pick_map,rankings)
          if x["position"] in {"QB","RB","WR","TE"} and x["value"]>=4]
    theirs=[x for x in roster_rows(partner,players,pick_map,rankings)
            if x["position"] in {"QB","RB","WR","TE"} and x["value"]>=4]

    base_me=team_utility(my_roster,players,pick_map,rankings)
    base_them=team_utility(partner,players,pick_map,rankings)

    my_sur=surplus(my_roster,players,pick_map,rankings)
    their_sur=surplus(partner,players,pick_map,rankings)

    # Singles plus controlled two-player packages.
    give=[[x] for x in mine]
    recv=[[x] for x in theirs]
    mp=sorted(mine,key=lambda x:(my_sur.get(x["position"],0),not x["starter"],x["value"]),reverse=True)[:10]
    tp=sorted(theirs,key=lambda x:(their_sur.get(x["position"],0),not x["starter"],x["value"]),reverse=True)[:10]
    give += [list(c) for c in itertools.combinations(mp,2)]
    recv += [list(c) for c in itertools.combinations(tp,2)]

    results=[]
    for g in give:
        for rc in recv:
            if len(g)==2 and len(rc)==2:
                continue

            gv=sum(x["value"] for x in g)
            rv=sum(x["value"] for x in rc)
            if gv<=0 or rv<=0:
                continue

            # Human market values, not arithmetic sum.
            hgv=human_trade_value(g)
            hrv=human_trade_value(rc)
            market_gap=abs(hgv-hrv)/max(hgv,hrv)
            if market_gap>.28:
                continue

            mn=roster_after_trade(my_roster,[x["player_id"] for x in g],[x["player_id"] for x in rc])
            tn=roster_after_trade(partner,[x["player_id"] for x in rc],[x["player_id"] for x in g])

            my_gain=team_utility(mn,players,pick_map,rankings)-base_me
            their_gain=team_utility(tn,players,pick_map,rankings)-base_them

            # A generated recommendation must benefit us. Opponent can be slightly negative
            # only for an aggressive opening offer, never for a "realistic" suggestion.
            if my_gain < .35 or their_gain < -.6:
                continue

            my_inc=manager_incentive(g,rc,my_roster,players,pick_map,rankings)
            their_inc=manager_incentive(rc,g,partner,players,pick_map,rankings)

            # Best-player-in-deal ownership matters heavily.
            best_g=max(g,key=lambda x:x["value"])
            best_r=max(rc,key=lambda x:x["value"])
            best_overall=max(g+rc,key=lambda x:x["value"])
            consolidation_penalty=0
            if len(g)==2 and len(rc)==1:
                consolidation_penalty=10
                if best_overall in rc:
                    consolidation_penalty+=8
            elif len(g)==1 and len(rc)==2:
                consolidation_penalty=6
                if best_overall in g:
                    consolidation_penalty+=6

            starter_penalty=0
            # If opponent gives a starter and receives no likely starter, acceptance drops.
            if any(x.get("starter") for x in rc) and not any(x.get("starter") for x in g):
                starter_penalty+=12

            exp_out=sum(expendability(x,partner,players,pick_map,rankings) for x in rc)/len(rc)
            exp_in=sum(expendability(x,my_roster,players,pick_map,rankings) for x in g)/len(g)

            fairness=max(0,100-market_gap*100)
            mutual=max(-8,min(12,their_gain*4.2))
            incentive=max(-10,min(12,their_inc*2.4))
            acceptance=(
                26
                + fairness*.34
                + mutual
                + incentive
                + (exp_out-50)*.12
                - consolidation_penalty
                - starter_penalty
            )
            acceptance=max(3,min(91,round(acceptance)))

            # Market disagreement lowers confidence in acceptance estimate.
            disagreements=[x.get("market_disagreement",0) for x in g+rc]
            max_dis=max(disagreements) if disagreements else 0
            if max_dis>=18:
                acceptance=max(3,acceptance-6)
                market_flag="High"
            elif max_dis>=10:
                acceptance=max(3,acceptance-3)
                market_flag="Medium"
            else:
                market_flag="Low"

            tier=offer_tier(acceptance,my_gain,their_gain)
            if tier=="Strong" and acceptance<65:
                continue
            if tier=="Realistic" and acceptance<52:
                continue
            if acceptance<38:
                continue

            why=[]
            nd=needs(partner,players,pick_map,rankings)
            for pos in {x["position"] for x in g}:
                if nd.get(pos,0)>=3:
                    why.append(f"fills their {pos} need")
            if exp_out>=60:
                why.append("their outgoing asset is relatively expendable")
            if len(g)>len(rc):
                why.append("you pay a consolidation premium")
            if not why:
                why.append("close market value with workable roster fit")

            results.append({
                "Tier":tier,
                "You send":combo_label(g),
                "You receive":combo_label(rc),
                "Send value":round(gv,1),
                "Receive value":round(rv,1),
                "Human send":round(hgv,1),
                "Human receive":round(hrv,1),
                "Your impact":round(my_gain,1),
                "Their impact":round(their_gain,1),
                "Fairness":round(fairness),
                "Acceptance":acceptance,
                "Acceptance level":acceptance_label(acceptance),
                "Market disagreement":market_flag,
                "Why":"; ".join(why),
                "_score":my_gain*2.2+their_gain*1.1+acceptance*.16+fairness*.05,
            })

    seen=set()
    out=[]
    for row in sorted(results,key=lambda x:(x["Tier"]=="Strong",x["Tier"]=="Realistic",x["_score"]),reverse=True):
        k=(row["You send"],row["You receive"])
        if k in seen:
            continue
        seen.add(k); out.append(row)
        if len(out)>=max_results:
            break
    return out

def card(label,value,sub=""):
    st.markdown(
        f'<div class="stat-card"><div class="stat-label">{label}</div>'
        f'<div class="stat-value">{value}</div><div class="stat-sub">{sub}</div></div>',
        unsafe_allow_html=True
    )

def player_card(row):
    inj=""
    if row["injury"]:
        cls="bad" if str(row["injury"]).lower() in {"out","ir","pup"} else "warn"
        inj=f'<span class="badge {cls}">{row["injury"]}</span>'
    starter='<span class="badge accent">STARTER</span>' if row.get("starter") else ''
    st.markdown(
        f'<div class="player-card"><div><div class="player-name">{row["name"]}{starter}{inj}</div>'
        f'<div class="player-meta">{row["position"] or "-"} · {row["team"] or "FA"}'
        f'{" · depth "+str(row["depth"]) if row["depth"] else ""}</div></div>'
        f'<div class="player-score">{row["value"]:.1f}</div></div>',
        unsafe_allow_html=True
    )

def optimize_lineup(roster, players, pick_map, rankings, slots, projections):
    remaining=roster_rows(roster,players,pick_map,rankings)
    chosen=[]

    def eligible(r,slot):
        p=r["position"]
        if slot in {"QB","RB","WR","TE","K","DEF"}: return p==slot
        if slot in {"FLEX","WRRB_FLEX","WRT_FLEX","REC_FLEX"}: return p in {"RB","WR","TE"}
        if slot=="SUPER_FLEX": return p in {"QB","RB","WR","TE"}
        return False

    for r in remaining:
        proj=projections.get(normalize_player_name(r["name"]))
        r["lineup_score"] = proj if proj is not None else r["value"]/5.0

    for slot in slots:
        if slot in {"BN","IR","TAXI"}: continue
        cand=[x for x in remaining if eligible(x,slot)]
        if not cand: continue
        best=max(cand,key=lambda x:x["lineup_score"])
        chosen.append({
            "Slot":slot,"Player":best["name"],"Pos":best["position"],"NFL":best["team"],
            "Injury":best["injury"],"Projected":round(best["lineup_score"],2)
        })
        remaining=[x for x in remaining if x["player_id"]!=best["player_id"]]
    return chosen

# ============================================================
# LOAD LEAGUE
# ============================================================

league_id=st.sidebar.text_input("Sleeper league ID",DEFAULT_LEAGUE_ID)

try:
    league=sleeper_get(f"/league/{league_id}")
    users=sleeper_get(f"/league/{league_id}/users")
    rosters=sleeper_get(f"/league/{league_id}/rosters")
    players=players_db()
except Exception as e:
    st.error(f"Could not load league: {e}")
    st.stop()

season=int(league.get("season") or 2026)
try:
    nfl_state=sleeper_get("/state/nfl")
    CURRENT_WEEK=int(nfl_state.get("week") or 1)
except Exception:
    CURRENT_WEEK=1
# League-format scarcity: required starter slots determine replacement pressure.
slots=league.get("roster_positions") or []
slot_counts=Counter(slots)
POS_SCARCITY={
    "QB": .88 if slot_counts.get("QB",0)<=1 and "SUPER_FLEX" not in slots else 1.14,
    "RB": 1.05 if slot_counts.get("RB",0)>=2 else 1.0,
    "WR": 1.04 if slot_counts.get("WR",0)>=2 else 1.0,
    "TE": 1.03 if slot_counts.get("TE",0)>=1 else .96,
    "K": .85, "DEF": .88,
}
key=fp_key()
rec_pts=float((league.get("scoring_settings") or {}).get("rec",0) or 0)
fp_scoring="PPR" if rec_pts>=.75 else ("HALF" if rec_pts>=.25 else "STD")
rankings=fp_rankings(season,key,fp_scoring) if key else {}
fp_diag=fp_diagnostics(season,key,fp_scoring)
fp_active=bool(fp_diag.get("ok") and rankings)

user_map={str(u.get("user_id")):u for u in users}
roster_names={}
for r in rosters:
    oid=str(r.get("owner_id")) if r.get("owner_id") else None
    roster_names[r["roster_id"]]=display_name(user_map.get(oid,{})) if oid else f"Roster {r['roster_id']}"

try: drafts=sleeper_get(f"/league/{league_id}/drafts")
except Exception: drafts=[]
latest=sorted(drafts,key=lambda x:x.get("created",0) or 0,reverse=True)[0] if drafts else None
picks=sleeper_get(f"/draft/{latest['draft_id']}/picks") if latest else []
pick_map={str(x.get("player_id")):x.get("pick_no") for x in picks if x.get("player_id") is not None}
engine_rows=[]
for _r in rosters:
    for _pid in (_r.get("players") or []):
        _m=pmeta(_pid,players)
        if _m.get("position") in {"QB","RB","WR","TE","K","DEF"}:
            _rr=ranking_lookup(rankings,_m["name"]) if rankings else {}
            engine_rows.append({"name":_m["name"],"fp":bool(_rr.get("ecr") is not None or _rr.get("adp") is not None)})
engine_total=len(engine_rows)
engine_identified=sum(1 for x in engine_rows if x["name"])
engine_fp=sum(1 for x in engine_rows if x["fp"])
engine_fallback=engine_total-engine_fp


team_options={roster_names[r["roster_id"]]:r["roster_id"] for r in rosters}
team_names=list(team_options.keys())

# team persistence
saved=st.query_params.get("myteam")
saved_rid=None
try: saved_rid=int(saved) if saved else None
except Exception: pass

if "my_rid" not in st.session_state:
    st.session_state.my_rid=saved_rid if saved_rid in team_options.values() else None

if st.session_state.my_rid is None:
    st.markdown('<div class="hero"><div class="kicker">Setup</div><h1>Sleeper GM</h1><p>Choose your team once. The portal will remember it.</p></div>',unsafe_allow_html=True)
    chosen=st.selectbox("Which team is yours?",["— Select your team —"]+team_names)
    if chosen!="— Select your team —":
        if st.button("Set as my team",type="primary"):
            rid=team_options[chosen]
            st.session_state.my_rid=rid
            st.query_params["myteam"]=str(rid)
            st.rerun()
    st.stop()

my_rid=st.session_state.my_rid
my_name=roster_names[my_rid]
my_roster=next(r for r in rosters if r["roster_id"]==my_rid)

st.sidebar.markdown("### My team")
st.sidebar.success(my_name)
if st.sidebar.button("Change my team"):
    st.session_state.my_rid=None
    if "myteam" in st.query_params: del st.query_params["myteam"]
    st.rerun()

st.sidebar.success("V8 · V7.1 Engine LOCKED")
st.sidebar.caption(f"{engine_identified}/{engine_total} recognised · {engine_fp} external-ranked · {engine_fallback} Sleeper-first fallback")
with st.sidebar.expander("Player engine diagnostics"):
    st.write({"Recognised":f"{engine_identified}/{engine_total}","FantasyPros ranked":engine_fp,"Sleeper-first fallback":engine_fallback,"FantasyPros API":"Connected" if fp_active else "Optional / unavailable","Model":"Sleeper-first multi-source"})
    st.caption("FantasyPros is optional. Missing external rankings no longer means a player is missing from the engine.")
    if st.button("Clear API caches and retry",key="v7cache"):
        st.cache_data.clear(); st.rerun()

PAGES=["Home","Power Rankings","My Team","Player Engine","Trade Centre","Waivers","Matchup Scout","Lineup","League Activity","Rosters","Export"]
page=st.sidebar.radio("Navigate",PAGES)
st.sidebar.markdown("---")
st.sidebar.caption(f"{league.get('name','League')} · {league.get('season','')}")

# power precompute
power=[]
for r in rosters:
    raw,bd=raw_power(r,players,pick_map,rankings)
    power.append({"rid":r["roster_id"],"team":roster_names[r["roster_id"]],"raw":raw,"bd":bd})
normalize(power)
power=sorted(power,key=lambda x:x["score"],reverse=True)
rank={x["rid"]:i+1 for i,x in enumerate(power)}
pscore={x["rid"]:x["score"] for x in power}

st.markdown(
    f'<div class="hero"><div class="kicker">Sleeper GM V7</div>'
    f'<h1>{my_name}</h1><p>{league.get("name","Sleeper League")} · live roster intelligence</p></div>',
    unsafe_allow_html=True
)

# ============================================================
# HOME
# ============================================================

if page=="Home":
    me=next(x for x in power if x["rid"]==my_rid)
    myneeds=needs(my_roster,players,pick_map,rankings)
    biggest=max(myneeds,key=myneeds.get)
    rows=roster_rows(my_roster,players,pick_map,rankings)
    injured=sum(1 for x in rows if x["injury"])

    c1,c2,c3,c4=st.columns(4)
    with c1: card("League rank",f"#{rank[my_rid]} / {len(rosters)}","Power model")
    with c2: card("Roster grade",grade(me["score"]),f"{me['score']:.1f} power")
    with c3: card("Biggest need",biggest,f"{myneeds[biggest]:.1f} need score")
    with c4: card("Status watch",injured,"players flagged")

    st.markdown('<div class="section-head"><h2>Your core</h2><span>Highest current roster values</span></div>',unsafe_allow_html=True)
    core=sorted(rows,key=lambda x:x["value"],reverse=True)[:8]
    c1,c2=st.columns(2)
    for i,row in enumerate(core):
        with (c1 if i%2==0 else c2): player_card(row)

    st.markdown('<div class="section-head"><h2>League top 5</h2><span>Current model</span></div>',unsafe_allow_html=True)
    st.dataframe(pd.DataFrame([
        {"Rank":i+1,"Team":x["team"],"Grade":grade(x["score"]),"Power":round(x["score"],1)}
        for i,x in enumerate(power[:5])
    ]),use_container_width=True,hide_index=True)

# ============================================================
# POWER RANKINGS V2
# ============================================================

elif page=="Power Rankings":
    st.markdown("## Power Rankings V2.1")
    st.caption("Starter strength first, then meaningful RB/WR depth. Kicker and D/ST have minimal weight.")

    table=[]
    for i,x in enumerate(power):
        table.append({
            "Rank":i+1,"Team":x["team"],"Grade":grade(x["score"]),"Power":round(x["score"],1),
            "QB":round(x["bd"].get("QB",0),1),"RB":round(x["bd"].get("RB",0),1),
            "WR":round(x["bd"].get("WR",0),1),"TE":round(x["bd"].get("TE",0),1)
        })
    st.dataframe(pd.DataFrame(table),use_container_width=True,hide_index=True)

    selected=st.selectbox("Team breakdown",[x["team"] for x in power])
    rid=team_options[selected]
    r=next(r for r in rosters if r["roster_id"]==rid)
    vals=pos_values(r,players,pick_map,rankings)
    nd=needs(r,players,pick_map,rankings)
    sd=surplus(r,players,pick_map,rankings)

    c1,c2=st.columns(2)
    with c1:
        st.markdown("### Needs")
        st.dataframe(pd.DataFrame([{"Position":k,"Need":round(v,1)} for k,v in sorted(nd.items(),key=lambda x:x[1],reverse=True)]),use_container_width=True,hide_index=True)
    with c2:
        st.markdown("### Surplus")
        st.dataframe(pd.DataFrame([{"Position":k,"Surplus":round(v,1)} for k,v in sorted(sd.items(),key=lambda x:x[1],reverse=True)]),use_container_width=True,hide_index=True)

# ============================================================
# MY TEAM
# ============================================================

elif page=="My Team":
    rows=roster_rows(my_roster,players,pick_map,rankings)
    starters=sorted([x for x in rows if x["starter"]],key=lambda x:(x["position"] or "",-x["value"]))
    bench=sorted([x for x in rows if not x["starter"]],key=lambda x:-x["value"])

    st.markdown('<div class="section-head"><h2>Starters</h2><span>Current Sleeper lineup</span></div>',unsafe_allow_html=True)
    c1,c2=st.columns(2)
    for i,row in enumerate(starters):
        with (c1 if i%2==0 else c2): player_card(row)

    st.markdown('<div class="section-head"><h2>Bench</h2><span>Best stashes first</span></div>',unsafe_allow_html=True)
    c1,c2=st.columns(2)
    for i,row in enumerate(bench):
        with (c1 if i%2==0 else c2): player_card(row)

# ============================================================
# TRADE CENTRE V2
# ============================================================

elif page=="Player Engine":
    st.markdown("## Player Engine · V7.1 Calibration")
    st.caption("League-aware positional curves, role weighting, decaying draft capital and confidence-weighted external consensus.")
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Recognised",f"{engine_identified}/{engine_total}")
    c2.metric("External ranked",engine_fp)
    c3.metric("Sleeper fallback",engine_fallback)
    c4.metric("Draft weight",f"{max(42,round((1-(max(1,CURRENT_WEEK)-1)*.038)*100))}%",f"Week {CURRENT_WEEK}")
    erows=[]
    for r in rosters:
        for x in roster_rows(r,players,pick_map,rankings):
            if x["position"] in {"QB","RB","WR","TE","K","DEF"}:
                erows.append({"Player":x["name"],"Pos":x["position"],"NFL":x["team"],"Owner":roster_names[r["roster_id"]],"Value":x["value"],"Starter":x["starter"],"Depth":x.get("depth"),"Confidence":x["confidence"],"Signals":x["value_source"],"FP ECR":x.get("ecr"),"FP ADP":x.get("adp"),"Disagreement %":x.get("market_disagreement",0)})
    edf=pd.DataFrame(erows).sort_values(["Value","Player"],ascending=[False,True])
    tabs=st.tabs(["Overall audit","By position","Disagreements","Low confidence"])
    with tabs[0]:
        st.dataframe(edf.head(50),use_container_width=True,hide_index=True)
    with tabs[1]:
        pos=st.selectbox("Audit position",["QB","RB","WR","TE","K","DEF"])
        st.dataframe(edf[edf["Pos"]==pos].head(40),use_container_width=True,hide_index=True)
    with tabs[2]:
        st.caption("Players where FantasyPros ECR and ADP disagree most. These deserve human review before the trade engine trusts them heavily.")
        st.dataframe(edf.sort_values("Disagreement %",ascending=False).head(30),use_container_width=True,hide_index=True)
    with tabs[3]:
        st.dataframe(edf[edf["Confidence"].isin(["Low","Medium"])].sort_values("Value",ascending=False).head(50),use_container_width=True,hide_index=True)
    st.info("V8 keeps the V7.1 Sleeper-first player engine locked. FantasyPros only calibrates players it can confidently match; unmatched players retain full Sleeper-first values.")

elif page=="Trade Centre":
    st.markdown("## Trade Centre V8")
    st.caption("Human-first trade intelligence built on the frozen V7.1 player engine.")

    tab0,tab1,tab2,tab3,tab4=st.tabs(["Best offers","Target builder","Partner finder","Analyser","League market"])

    with tab0:
        st.markdown('<div class="notice"><b>V8 only surfaces trades with a plausible human path to acceptance.</b> It applies starter value, best-player premium, consolidation tax, positional need, expendability and confidence — not just arithmetic value.</div>',unsafe_allow_html=True)
        filt=st.selectbox("Show offers against",["All teams"]+[x for x in team_names if x!=my_name],key="v8_all_filter")
        suggestions=[]
        for partner in rosters:
            if partner["roster_id"]==my_rid: continue
            if filt!="All teams" and roster_names[partner["roster_id"]]!=filt: continue
            for row in generate_trade_suggestions(my_roster,partner,players,pick_map,rankings,16):
                row["Partner"]=roster_names[partner["roster_id"]]
                suggestions.append(row)

        if suggestions:
            sdf=pd.DataFrame(suggestions).sort_values(["Tier","Acceptance","_score"],ascending=[True,False,False])
            for tier,title in [("Strong","Best realistic offers"),("Realistic","Worth proposing"),("Aggressive","Aggressive buy-low attempts")]:
                subset=sdf[sdf["Tier"]==tier].sort_values(["Acceptance","_score"],ascending=[False,False])
                if len(subset):
                    st.markdown(f"### {title}")
                    cols=["Partner","You send","You receive","Your impact","Their impact","Fairness","Acceptance","Market disagreement","Why"]
                    st.dataframe(subset[cols].head(12),use_container_width=True,hide_index=True)
        else:
            st.info("No generated trade currently clears V8's realism thresholds. Holding is better than manufacturing a fake offer.")

    with tab1:
        st.markdown("### Target builder")
        partner_name=st.selectbox("Choose a manager",[x for x in team_names if x!=my_name],key="v8_target_partner")
        prid=team_options[partner_name]
        partner=next(r for r in rosters if r["roster_id"]==prid)
        target_rows=[x for x in roster_rows(partner,players,pick_map,rankings) if x["position"] in {"QB","RB","WR","TE"}]
        target_name=st.selectbox("Player you want",[x["name"] for x in sorted(target_rows,key=lambda x:-x["value"])],key="v8_target_player")
        target=next(x for x in target_rows if x["name"]==target_name)

        proposals=[]
        for row in generate_trade_suggestions(my_roster,partner,players,pick_map,rankings,60):
            if target_name in row["You receive"]:
                proposals.append(row)

        c1,c2,c3=st.columns(3)
        c1.metric("Target value",round(target["value"],1))
        c2.metric("Their expendability",f"{round(expendability(target,partner,players,pick_map,rankings))}%")
        c3.metric("Confidence",target.get("confidence","—"))

        if proposals:
            pdf=pd.DataFrame(proposals).sort_values(["Acceptance","Your impact"],ascending=[False,False])
            realistic=pdf[pdf["Acceptance"]>=55]
            aggressive=pdf[(pdf["Acceptance"]>=38)&(pdf["Acceptance"]<55)]
            if len(aggressive):
                r=aggressive.iloc[0]
                st.markdown(f"**Opening offer:** {r['You send']} → **{target_name}**  \nAcceptance model: **{int(r['Acceptance'])}%**")
            if len(realistic):
                r=realistic.iloc[0]
                st.markdown(f"**Likely fair deal:** {r['You send']} → **{target_name}**  \nAcceptance model: **{int(r['Acceptance'])}%**")
                # walk-away uses highest human cost among plausible deals, but caps bad roster impact.
                walk=realistic.sort_values("Human send",ascending=False).iloc[0]
                st.markdown(f"**Walk-away price:** approximately **{walk['You send']}**. I would not automatically pay beyond this package.")
            st.dataframe(pdf[["Tier","You send","Your impact","Their impact","Fairness","Acceptance","Why"]].head(15),use_container_width=True,hide_index=True)
        else:
            st.warning("V8 can't find a defensible package for this target from your current roster. That usually means the player is too expensive or the manager has little reason to sell.")

    with tab2:
        st.markdown("### Partner finder")
        myneed=needs(my_roster,players,pick_map,rankings); mysur=surplus(my_roster,players,pick_map,rankings)
        rows=[]
        for r in rosters:
            if r["roster_id"]==my_rid: continue
            tneed=needs(r,players,pick_map,rankings); tsur=surplus(r,players,pick_map,rankings)
            fit=0; reasons=[]
            for pos in ["QB","RB","WR","TE"]:
                a=mysur.get(pos,0)*tneed.get(pos,0)
                b=tsur.get(pos,0)*myneed.get(pos,0)
                if a>8: fit+=a; reasons.append(f"you can help their {pos}")
                if b>8: fit+=b; reasons.append(f"they can help your {pos}")
            rows.append({"Team":roster_names[r["roster_id"]],"Fit score":round(fit,1),"Why":" · ".join(reasons) or "weak positional fit"})
        st.dataframe(pd.DataFrame(rows).sort_values("Fit score",ascending=False),use_container_width=True,hide_index=True)

    with tab3:
        st.markdown("### Manual analyser")
        partner_name=st.selectbox("Trade partner",[x for x in team_names if x!=my_name],key="v8_manual_partner")
        prid=team_options[partner_name]
        partner=next(r for r in rosters if r["roster_id"]==prid)
        mine={x["name"]:x for x in roster_rows(my_roster,players,pick_map,rankings)}
        theirs={x["name"]:x for x in roster_rows(partner,players,pick_map,rankings)}
        a,b=st.columns(2)
        with a: give=st.multiselect("You give",list(mine.keys()),key="v8_manual_give")
        with b: receive=st.multiselect("You receive",list(theirs.keys()),key="v8_manual_receive")
        gc=[mine[x] for x in give]; rc=[theirs[x] for x in receive]
        gv=human_trade_value(gc); rv=human_trade_value(rc)
        cols=st.columns(4)
        cols[0].metric("Human send",round(gv,1))
        cols[1].metric("Human receive",round(rv,1))
        cols[2].metric("Raw edge",round(rv-gv,1))
        fairness=100-abs(gv-rv)/max(gv,rv)*100 if gv and rv else 0
        cols[3].metric("Market fairness",f"{round(max(0,fairness))}%")
        if give and receive:
            mn=roster_after_trade(my_roster,[x["player_id"] for x in gc],[x["player_id"] for x in rc])
            tn=roster_after_trade(partner,[x["player_id"] for x in rc],[x["player_id"] for x in gc])
            mg=team_utility(mn,players,pick_map,rankings)-team_utility(my_roster,players,pick_map,rankings)
            tg=team_utility(tn,players,pick_map,rankings)-team_utility(partner,players,pick_map,rankings)
            st.write({"Your roster impact":round(mg,1),"Their roster impact":round(tg,1)})
            if fairness<72: st.error("Market values are too far apart.")
            elif tg<-1: st.warning("Values may be close, but the other manager's roster gets materially worse.")
            elif mg>0 and tg>=0: st.success("This has a plausible structure for both sides.")
            else: st.info("Fair-ish value, but roster fit does not strongly support the deal.")

    with tab4:
        st.markdown("### League market")
        st.caption("Completed Sleeper trades become behavioural context as your league develops.")
        hist=[]
        for wk in range(1, min(18, int(league.get("settings",{}).get("leg",1) or 1)+1)):
            try:
                tx=sleeper_get(f"/league/{league_id}/transactions/{wk}")
            except Exception:
                tx=[]
            for t in tx:
                if t.get("type")!="trade" or t.get("status")!="complete":
                    continue
                rids=t.get("roster_ids") or []
                hist.append({"Week":wk,"Managers":" ↔ ".join(roster_names.get(r,f"Roster {r}") for r in rids),"Adds":len(t.get("adds") or {}),"Drops":len(t.get("drops") or {})})
        if hist:
            st.dataframe(pd.DataFrame(hist),use_container_width=True,hide_index=True)
            st.caption(f"{len(hist)} completed league trades available as behavioural context.")
        else:
            st.info("No completed league trades yet. V8 is currently using roster construction and market-value behaviour only.")


elif page=="Waivers":
    st.markdown("## Waiver Engine V2.1")
    st.caption("Recalibrated so market heat helps identify movement while stale, retired and teamless historical records are filtered out.")
    rostered={str(pid) for r in rosters for pid in (r.get("players") or [])}
    try:
        adds=sleeper_get("/players/nfl/trending/add?lookback_hours=24&limit=100"); drops=sleeper_get("/players/nfl/trending/drop?lookback_hours=24&limit=100")
    except Exception: adds,drops=[],[]
    amap={str(x["player_id"]):x.get("count",0) for x in adds}; dmap={str(x["player_id"]):x.get("count",0) for x in drops}
    myneed=needs(my_roster,players,pick_map,rankings); rows=[]
    for pid,p in players.items():
        pid=str(pid)
        if pid in rostered or not is_current_nfl_player(p) or p.get("position") not in {"QB","RB","WR","TE"}: continue
        m=pmeta(pid,players); basev=player_value(m,pick_map,rankings); adds24=amap.get(pid,0); drops24=dmap.get(pid,0)
        if basev<4.5 and adds24<50: continue
        trend=min(5.0,math.log1p(adds24)*.9)-min(3.0,math.log1p(drops24)*.6)
        opp=3 if m["depth"]==1 else 1.5 if m["depth"]==2 else -1.5 if isinstance(m["depth"],(int,float)) and m["depth"]>=4 else 0
        fit=min(3.0,myneed.get(m["position"],0)*.12); score=basev+trend+opp+fit
        rows.append({"Player":m["name"],"Pos":m["position"],"NFL":m["team"],"Injury":m["injury"],"Depth":m["depth"],"Adds 24h":adds24,"Drops 24h":drops24,"Base value":round(basev,1),"Roster fit":round(fit,1),"Waiver score":round(score,1)})
    df=pd.DataFrame(rows); posf=st.multiselect("Position",["RB","WR","TE","QB"],default=["RB","WR","TE"])
    if posf and not df.empty: df=df[df["Pos"].isin(posf)]
    if not df.empty: st.dataframe(df.sort_values(["Waiver score","Base value"],ascending=False).head(75),use_container_width=True,hide_index=True)
    st.markdown("### Add / drop suggestions")
    bench=[x for x in roster_rows(my_roster,players,pick_map,rankings) if not x["starter"] and x["position"] in {"QB","RB","WR","TE"}]
    suggestions=[]
    if not df.empty:
        for _,fa in df.sort_values("Waiver score",ascending=False).head(25).iterrows():
            same=[x for x in bench if x["position"]==fa["Pos"]]; pool=same if same else bench
            if not pool: continue
            drop=min(pool,key=lambda x:x["value"]); upgrade=fa["Base value"]-drop["value"]
            if upgrade<1.5: continue
            if fa["Pos"]=="TE" and drop["position"]!="TE": continue
            suggestions.append({"Add":fa["Player"],"Drop":drop["name"],"Pos":fa["Pos"],"FA value":fa["Base value"],"Drop value":round(drop["value"],1),"Estimated upgrade":round(upgrade,1)})
    if suggestions: st.dataframe(pd.DataFrame(suggestions).sort_values("Estimated upgrade",ascending=False).head(12),use_container_width=True,hide_index=True)
    else: st.success("No free agent clears the current upgrade threshold over your bench. Holding is a valid move.")

# ============================================================
# MATCHUP SCOUT
# ============================================================

elif page=="Matchup Scout":
    week=st.number_input("Week",1,18,1,1)
    ms=sleeper_get(f"/league/{league_id}/matchups/{int(week)}")
    mine=next((m for m in ms if m.get("roster_id")==my_rid),None)
    if mine and mine.get("matchup_id") is not None:
        opp=next((m for m in ms if m.get("matchup_id")==mine.get("matchup_id") and m.get("roster_id")!=my_rid),None)
        if opp:
            orid=opp["roster_id"]
            oname=roster_names[orid]
            st.markdown(f"## {my_name} vs {oname}")
            c1,c2,c3=st.columns(3)
            c1.metric("Your rank",f"#{rank[my_rid]}")
            c2.metric("Opponent rank",f"#{rank[orid]}")
            c3.metric("Power edge",round(pscore[my_rid]-pscore[orid],1))
            op=next(r for r in rosters if r["roster_id"]==orid)
            minep=next(x for x in power if x["rid"]==my_rid)
            oppp=next(x for x in power if x["rid"]==orid)
            comp=[]
            for pos in ["QB","RB","WR","TE"]:
                a=minep["bd"].get(pos,0); b=oppp["bd"].get(pos,0)
                comp.append({"Position":pos,"You":round(a,1),"Opponent":round(b,1),"Edge":round(a-b,1)})
            st.dataframe(pd.DataFrame(comp),use_container_width=True,hide_index=True)
        else: st.info("Opponent not posted yet.")
    else: st.info("No matchup data for that week yet.")

# ============================================================
# LINEUP
# ============================================================

elif page=="Lineup":
    st.markdown("## Lineup Optimizer")
    week=st.number_input("Week",1,18,1,1,key="lineupweek")
    projections=fp_weekly_projections(season,week,key,fp_scoring) if key else {}
    if key:
        st.success("Using live weekly projection feed.")
    else:
        st.warning("No projection API connected yet, so this falls back to roster market value.")

    chosen=optimize_lineup(
        my_roster,players,pick_map,rankings,league.get("roster_positions") or [],projections
    )
    st.dataframe(pd.DataFrame(chosen),use_container_width=True,hide_index=True)

# ============================================================
# LEAGUE ACTIVITY / NEWS
# ============================================================

elif page=="League Activity":
    st.markdown("## League Activity")
    week=st.number_input("Week",1,18,1,1,key="activityweek")
    try: tx=sleeper_get(f"/league/{league_id}/transactions/{int(week)}")
    except Exception: tx=[]

    feed=[]
    for t in sorted(tx,key=lambda x:x.get("created",0),reverse=True):
        adds=t.get("adds") or {}
        drops=t.get("drops") or {}
        details=[]
        if adds: details.append("Added "+", ".join(pmeta(pid,players)["name"] for pid in adds))
        if drops: details.append("Dropped "+", ".join(pmeta(pid,players)["name"] for pid in drops))
        if t.get("type")=="trade": details.append("Trade completed")
        feed.append({"Type":str(t.get("type","")).upper(),"Details":" · ".join(details),"Status":t.get("status")})
    if feed:
        st.dataframe(pd.DataFrame(feed),use_container_width=True,hide_index=True)

    st.markdown("### Roster-relevant news")
    if key:
        news=fp_news(key)
        owned={}
        for r in rosters:
            for x in roster_rows(r,players,pick_map,rankings):
                owned[x["name"].lower()]=roster_names[r["roster_id"]]
        nrows=[]
        for n in news:
            name=n.get("player_name") or n.get("name") or ""
            owner=owned.get(name.lower())
            if owner:
                nrows.append({
                    "Player":name,"Owner":owner,
                    "Headline":n.get("headline") or n.get("title"),
                    "Impact":n.get("impact") or n.get("analysis") or n.get("description"),
                    "Updated":n.get("updated") or n.get("date")
                })
        if nrows:
            st.dataframe(pd.DataFrame(nrows).head(100),use_container_width=True,hide_index=True)
        else:
            st.info("No rostered-player news returned.")
    else:
        alerts=[]
        for r in rosters:
            for x in roster_rows(r,players,pick_map,rankings):
                if x["injury"]:
                    alerts.append({"Player":x["name"],"Owner":roster_names[r["roster_id"]],"Pos":x["position"],"NFL":x["team"],"Injury":x["injury"]})
        if alerts:
            st.dataframe(pd.DataFrame(alerts),use_container_width=True,hide_index=True)

# ============================================================
# ROSTERS
# ============================================================

elif page=="Rosters":
    selected=st.selectbox("Team",team_names)
    rid=team_options[selected]
    r=next(r for r in rosters if r["roster_id"]==rid)
    rows=sorted(roster_rows(r,players,pick_map,rankings),key=lambda x:(not x["starter"],-x["value"]))
    c1,c2=st.columns(2)
    for i,row in enumerate(rows):
        with (c1 if i%2==0 else c2): player_card(row)

# ============================================================
# EXPORT
# ============================================================

elif page=="Export":
    snapshot={
        "generated_at":datetime.now().isoformat(timespec="seconds"),
        "league":{
            "id":league_id,"name":league.get("name"),"season":league.get("season"),
            "scoring":league.get("scoring_settings"),"roster_positions":league.get("roster_positions")
        },
        "my_team":{"name":my_name,"roster_id":my_rid},
        "power_rankings":[
            {"rank":i+1,"team":x["team"],"roster_id":x["rid"],"score":round(x["score"],1),"grade":grade(x["score"])}
            for i,x in enumerate(power)
        ],
        "teams":[]
    }
    for r in rosters:
        snapshot["teams"].append({
            "name":roster_names[r["roster_id"]],
            "roster_id":r["roster_id"],
            "players":roster_rows(r,players,pick_map,rankings),
            "needs":needs(r,players,pick_map,rankings),
            "surplus":surplus(r,players,pick_map,rankings),
        })

    raw=json.dumps(snapshot,indent=2,ensure_ascii=False)
    st.download_button("Download league snapshot",raw,file_name=f"sleeper_{league_id}_snapshot.json",mime="application/json",use_container_width=True)
