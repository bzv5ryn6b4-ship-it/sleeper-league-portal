
import json
import math
import itertools
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
    r = requests.get(f"{FP}{path}", headers={"x-api-key":key}, timeout=20)
    r.raise_for_status()
    return r.json()

def flatten_rows(payload):
    if payload is None: return []
    if isinstance(payload, list): return payload
    for k in ("players","results","data","items","news"):
        v = payload.get(k) if isinstance(payload, dict) else None
        if isinstance(v, list): return v
    return []

@st.cache_data(ttl=1800, show_spinner=False)
def fp_rankings(season, key):
    if not key: return {}
    out = {}
    for pos in ["QB","RB","WR","TE","K","DST"]:
        try:
            payload = fp_get(f"/nfl/{season}/consensus-rankings?position={pos}&scoring=PPR", key)
            for x in flatten_rows(payload):
                name = x.get("player_name") or x.get("name") or " ".join(
                    y for y in [x.get("player_first_name"), x.get("player_last_name")] if y
                ).strip()
                if not name: continue
                out[name.lower()] = {
                    "ecr": x.get("rank_ecr") or x.get("rank") or x.get("overall_rank"),
                    "adp": x.get("rank_adp") or x.get("adp"),
                    "tier": x.get("tier"),
                }
        except Exception:
            pass
    return out

@st.cache_data(ttl=900, show_spinner=False)
def fp_weekly_projections(season, week, key):
    if not key: return {}
    try:
        payload = fp_get(f"/nfl/{season}/projections?week={week}", key)
    except Exception:
        return {}
    out = {}
    for x in flatten_rows(payload):
        name = x.get("player_name") or x.get("name") or " ".join(
            y for y in [x.get("player_first_name"), x.get("player_last_name")] if y
        ).strip()
        pts = x.get("fantasy_points") or x.get("fpts") or x.get("points") or x.get("projection")
        if name:
            try: out[name.lower()] = float(pts)
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

def pick_value(pick_no):
    if not pick_no: return 0.0
    p=max(1,float(pick_no))
    return 92/(p**0.38)

def search_value(rank):
    try: r=float(rank)
    except Exception: return 0.0
    if r<=0: return 0.0
    return max(0.0,38/(r**0.28))

def ecr_value(ecr):
    try: e=float(ecr)
    except Exception: return 0.0
    return max(3.0,100/(max(1,e)**0.34))

def player_value(meta, pick_map, rankings):
    name_key=(meta["name"] or "").lower()
    live=ecr_value(rankings.get(name_key,{}).get("ecr")) if rankings else 0.0
    drafted=pick_value(pick_map.get(meta["player_id"]))
    sleeper=search_value(meta.get("search_rank"))
    if live:
        raw=live*.62+drafted*.28+sleeper*.10
    elif drafted:
        raw=drafted*.78+sleeper*.22
    else:
        raw=sleeper
    pos_mult={"RB":1.05,"WR":1.0,"TE":.95,"QB":.88,"K":.28,"DEF":.30}.get(meta["position"],.60)
    age_mult=1.0
    age=meta["age"]
    if meta["position"] in {"RB","WR","TE"} and isinstance(age,(int,float)):
        if age<=24: age_mult=1.04
        elif age>=31: age_mult=.94
    depth_mult=1.0
    d=meta.get("depth")
    if meta["position"] in {"RB","WR","TE"}:
        if d==1: depth_mult=1.05
        elif d==2: depth_mult=1.01
        elif isinstance(d,(int,float)) and d>=4: depth_mult=.92
    return raw*pos_mult*age_mult*depth_mult*injury_mult(meta["injury"])

def roster_rows(roster, players, pick_map, rankings):
    starters={str(x) for x in (roster.get("starters") or [])}
    out=[]
    for pid in roster.get("players") or []:
        m=pmeta(pid,players)
        m["starter"]=str(pid) in starters
        m["value"]=round(player_value(m,pick_map,rankings),2)
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

def generate_trade_suggestions(my_roster, partner, players, pick_map, rankings, max_results=10):
    mine=[x for x in roster_rows(my_roster,players,pick_map,rankings) if x["position"] in {"QB","RB","WR","TE"} and x["value"]>=4]
    theirs=[x for x in roster_rows(partner,players,pick_map,rankings) if x["position"] in {"QB","RB","WR","TE"} and x["value"]>=4]
    my_need=needs(my_roster,players,pick_map,rankings); their_need=needs(partner,players,pick_map,rankings)
    my_sur=surplus(my_roster,players,pick_map,rankings); their_sur=surplus(partner,players,pick_map,rankings)
    base_me=team_utility(my_roster,players,pick_map,rankings); base_them=team_utility(partner,players,pick_map,rankings)
    give=[[x] for x in mine]; recv=[[x] for x in theirs]
    mp=sorted(mine,key=lambda x:(my_sur.get(x["position"],0),not x["starter"],x["value"]),reverse=True)[:9]
    tp=sorted(theirs,key=lambda x:(their_sur.get(x["position"],0),not x["starter"],x["value"]),reverse=True)[:9]
    give += [list(c) for c in itertools.combinations(mp,2)]
    recv += [list(c) for c in itertools.combinations(tp,2)]
    results=[]
    for g in give:
        gv=sum(x["value"] for x in g)
        for rc in recv:
            if len(g)==2 and len(rc)==2: continue
            rv=sum(x["value"] for x in rc)
            if not gv or not rv: continue
            fairness=abs(gv-rv)/max(gv,rv)
            if fairness>.30: continue
            mn=roster_after_trade(my_roster,[x["player_id"] for x in g],[x["player_id"] for x in rc])
            tn=roster_after_trade(partner,[x["player_id"] for x in rc],[x["player_id"] for x in g])
            mg=team_utility(mn,players,pick_map,rankings)-base_me + sum(my_need.get(x["position"],0) for x in rc)*.10
            tg=team_utility(tn,players,pick_map,rankings)-base_them + sum(their_need.get(x["position"],0) for x in g)*.10
            if mg < -1 or tg < -3: continue
            why=[]
            for pos in {x["position"] for x in rc}:
                if my_need.get(pos,0)>=4: why.append(f"addresses your {pos} need")
            for pos in {x["position"] for x in g}:
                if their_need.get(pos,0)>=4: why.append(f"helps their {pos} need")
            score=mg*2.2+tg*.8+(100-fairness*100)*.15
            results.append({"You send":combo_label(g),"You receive":combo_label(rc),"Send value":round(gv,1),"Receive value":round(rv,1),"Your improvement":round(mg,1),"Their improvement":round(tg,1),"Fairness":round(100-fairness*100),"Why":"; ".join(why) or "balanced value / roster fit","_score":score})
    seen=set(); out=[]
    for row in sorted(results,key=lambda x:x["_score"],reverse=True):
        k=(row["You send"],row["You receive"])
        if k in seen: continue
        seen.add(k); out.append(row)
        if len(out)>=max_results: break
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
        proj=projections.get((r["name"] or "").lower())
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
key=fp_key()
rankings=fp_rankings(season,key) if key else {}

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

if key:
    st.sidebar.success("Live FantasyPros layer connected")
else:
    st.sidebar.info("Using Sleeper + draft market model")
    st.sidebar.caption("Add FantasyPros API key later for live ECR, projections and player news.")

PAGES=["Home","Power Rankings","My Team","Trade Centre","Waivers","Matchup Scout","Lineup","League Activity","Rosters","Export"]
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
    f'<div class="hero"><div class="kicker">Fantasy GM Command Centre</div>'
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

elif page=="Trade Centre":
    st.markdown("## Trade Centre V2.1")
    tab0,tab1,tab2,tab3=st.tabs(["Suggested trades","Targets","Partner finder","Analyser"])

    with tab0:
        st.markdown('<div class="notice"><b>Suggested Trades</b> scans every other roster for 1-for-1, 2-for-1 and 1-for-2 deals. It rejects lopsided deals and scores whether both rosters actually improve.</div>',unsafe_allow_html=True)
        filt=st.selectbox("Show suggestions against",["All teams"]+[x for x in team_names if x!=my_name])
        suggestions=[]
        for partner in rosters:
            if partner["roster_id"]==my_rid: continue
            if filt!="All teams" and roster_names[partner["roster_id"]]!=filt: continue
            for row in generate_trade_suggestions(my_roster,partner,players,pick_map,rankings,8):
                row["Partner"]=roster_names[partner["roster_id"]]
                suggestions.append(row)
        if suggestions:
            sdf=pd.DataFrame(suggestions).sort_values(["Your improvement","Fairness"],ascending=[False,False])
            cols=["Partner","You send","You receive","Send value","Receive value","Your improvement","Their improvement","Fairness","Why"]
            st.dataframe(sdf[cols].head(30),use_container_width=True,hide_index=True)
            st.markdown("### Best 3 to investigate")
            for _,r in sdf.head(3).iterrows():
                st.markdown(f"**{r['Partner']}** — Send **{r['You send']}** for **{r['You receive']}**  \nYour improvement **{r['Your improvement']:+.1f}** · Their improvement **{r['Their improvement']:+.1f}** · Fairness **{int(r['Fairness'])}%**  \n*{r['Why']}*")
        else:
            st.info("No deal cleared the fairness and roster-improvement thresholds. The engine will not manufacture a trade just to fill the page.")

    with tab1:
        myneeds=needs(my_roster,players,pick_map,rankings); needpos=max(myneeds,key=myneeds.get)
        candidates=[]
        for r in rosters:
            if r["roster_id"]==my_rid: continue
            rows=[x for x in roster_rows(r,players,pick_map,rankings) if x["position"]==needpos]
            tneed=needs(r,players,pick_map,rankings).get(needpos,0); tsur=surplus(r,players,pick_map,rankings).get(needpos,0)
            for x in rows:
                candidates.append({"Target":x["name"],"Pos":needpos,"NFL":x["team"],"Owner":roster_names[r["roster_id"]],"Value":round(x["value"],1),"Targetability":round(x["value"]+tsur*.25-tneed*.35,1)})
        if candidates: st.dataframe(pd.DataFrame(candidates).sort_values("Targetability",ascending=False).head(30),use_container_width=True,hide_index=True)

    with tab2:
        mysur=surplus(my_roster,players,pick_map,rankings); myneed=needs(my_roster,players,pick_map,rankings); rows=[]
        for r in rosters:
            if r["roster_id"]==my_rid: continue
            tn=needs(r,players,pick_map,rankings); ts=surplus(r,players,pick_map,rankings); fit=0; why=[]
            for pos in ["QB","RB","WR","TE"]:
                a=mysur.get(pos,0)*tn.get(pos,0); b=ts.get(pos,0)*myneed.get(pos,0)
                if a>8: fit+=a; why.append(f"you can help their {pos}")
                if b>8: fit+=b; why.append(f"they can help your {pos}")
            rows.append({"Team":roster_names[r["roster_id"]],"Fit score":round(fit,1),"Why":" · ".join(why) or "weak fit"})
        st.dataframe(pd.DataFrame(rows).sort_values("Fit score",ascending=False),use_container_width=True,hide_index=True)

    with tab3:
        partner_name=st.selectbox("Trade partner",[x for x in team_names if x!=my_name],key="manualpartner")
        partner_rid=team_options[partner_name]; partner=next(r for r in rosters if r["roster_id"]==partner_rid)
        mine={x["name"]:x for x in roster_rows(my_roster,players,pick_map,rankings)}; theirs={x["name"]:x for x in roster_rows(partner,players,pick_map,rankings)}
        a,b=st.columns(2)
        with a: give=st.multiselect("You give",list(mine.keys()))
        with b: receive=st.multiselect("You receive",list(theirs.keys()))
        gv=sum(mine[x]["value"] for x in give); rv=sum(theirs[x]["value"] for x in receive)
        c1,c2,c3=st.columns(3); c1.metric("You send",round(gv,1)); c2.metric("You receive",round(rv,1)); c3.metric("Raw edge",round(rv-gv,1))
        if give or receive:
            if rv-gv>4: st.success("Value leans your way.")
            elif rv-gv<-4: st.error("You are paying too much.")
            else: st.info("Close enough that role, upside and current news should decide it.")

# ============================================================
# WAIVER ENGINE V2
# ============================================================

elif page=="Waivers":
    st.markdown("## Waiver Engine V2.1")
    st.caption("Recalibrated so market heat helps identify movement without turning deep reserves into fake must-adds.")
    rostered={str(pid) for r in rosters for pid in (r.get("players") or [])}
    try:
        adds=sleeper_get("/players/nfl/trending/add?lookback_hours=24&limit=100"); drops=sleeper_get("/players/nfl/trending/drop?lookback_hours=24&limit=100")
    except Exception: adds,drops=[],[]
    amap={str(x["player_id"]):x.get("count",0) for x in adds}; dmap={str(x["player_id"]):x.get("count",0) for x in drops}
    myneed=needs(my_roster,players,pick_map,rankings); rows=[]
    for pid,p in players.items():
        pid=str(pid)
        if pid in rostered or p.get("active") is False or p.get("position") not in {"QB","RB","WR","TE"}: continue
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
    projections=fp_weekly_projections(season,week,key) if key else {}
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
