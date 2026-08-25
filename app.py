
import json
import math
from collections import Counter, defaultdict
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

DEFAULT_LEAGUE_ID = "1389344022107021312"
SLEEPER = "https://api.sleeper.app/v1"

st.set_page_config(
    page_title="Sleeper GM",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------ STYLE ------------------

st.markdown("""
<style>
:root {
    --bg: #0b0f14;
    --panel: #111822;
    --panel2: #0f151d;
    --border: rgba(255,255,255,.08);
    --muted: #9aa6b2;
    --text: #f5f7fa;
    --accent: #7c3aed;
    --accent2: #2563eb;
    --good: #22c55e;
    --warn: #f59e0b;
    --bad: #ef4444;
}

html, body, [data-testid="stAppViewContainer"] {
    background: var(--bg);
    color: var(--text);
}

.block-container {
    max-width: 1320px;
    padding-top: 1.2rem;
    padding-bottom: 4rem;
}

[data-testid="stSidebar"] {
    background: #0d131b;
    border-right: 1px solid var(--border);
}

.hero {
    background:
      radial-gradient(1200px 500px at 0% 0%, rgba(124,58,237,.26), transparent 50%),
      linear-gradient(135deg, #121927, #0f1520);
    border: 1px solid var(--border);
    border-radius: 24px;
    padding: 26px 28px;
    margin-bottom: 18px;
}
.hero .kicker {
    color: #c4b5fd;
    text-transform: uppercase;
    font-weight: 800;
    font-size: .72rem;
    letter-spacing: .12em;
}
.hero h1 {
    margin: .15rem 0 .35rem 0;
    font-size: clamp(2.2rem, 5vw, 4rem);
    letter-spacing: -.055em;
    line-height: .96;
}
.hero p { color: var(--muted); margin: 0; }

.stat-card {
    background: linear-gradient(180deg, rgba(255,255,255,.035), rgba(255,255,255,.015));
    border: 1px solid var(--border);
    border-radius: 18px;
    padding: 16px 18px;
    min-height: 112px;
}
.stat-label {
    color: var(--muted);
    font-size: .78rem;
    text-transform: uppercase;
    letter-spacing: .08em;
    font-weight: 700;
}
.stat-value {
    font-size: 2rem;
    font-weight: 800;
    letter-spacing: -.04em;
    margin-top: .28rem;
}
.stat-sub {
    color: var(--muted);
    margin-top: .1rem;
    font-size: .85rem;
}

.player-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 13px 14px;
    margin-bottom: 8px;
}
.player-main { min-width: 0; }
.player-name { font-weight: 800; font-size: 1.02rem; }
.player-meta { color: var(--muted); font-size: .82rem; margin-top: 2px; }
.player-score { font-weight: 800; font-size: 1.05rem; white-space: nowrap; }

.badge {
    display:inline-block;
    border:1px solid var(--border);
    background: rgba(255,255,255,.04);
    border-radius:999px;
    padding:.18rem .48rem;
    font-size:.72rem;
    font-weight:800;
    margin-left:.35rem;
}
.badge.good { color: var(--good); }
.badge.warn { color: var(--warn); }
.badge.bad { color: var(--bad); }
.badge.accent { color:#c4b5fd; }

.section-head {
    display:flex;
    align-items:end;
    justify-content:space-between;
    gap:12px;
    margin: 1.6rem 0 .75rem 0;
}
.section-head h2, .section-head h3 { margin:0; }
.section-head span { color:var(--muted); font-size:.85rem; }

.notice {
    border:1px solid var(--border);
    background: rgba(124,58,237,.08);
    border-radius:14px;
    padding:12px 14px;
    color:#ddd6fe;
}

div[data-testid="stMetric"] {
    background: var(--panel);
    border:1px solid var(--border);
    border-radius:16px;
    padding:.7rem .85rem;
}
div[data-testid="stDataFrame"] {
    border:1px solid var(--border);
    border-radius:14px;
    overflow:hidden;
}
.stButton button, .stDownloadButton button {
    border-radius:12px !important;
    font-weight:700 !important;
}
[data-testid="stRadio"] > div {
    gap:.35rem;
}
@media (max-width: 760px) {
    .block-container { padding-left:.7rem; padding-right:.7rem; }
    .hero { padding:20px; border-radius:20px; }
    .stat-value { font-size:1.65rem; }
}
</style>
""", unsafe_allow_html=True)

# ------------------ API ------------------

@st.cache_data(ttl=300, show_spinner=False)
def get(path):
    r = requests.get(f"{SLEEPER}{path}", timeout=20)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=3600, show_spinner=False)
def get_players():
    return get("/players/nfl")

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
    if not pick_no:
        return 0.0
    return 118/(max(1,float(pick_no))**0.48)

def search_value(rank):
    try:
        r=float(rank)
    except Exception:
        return 4.0
    return max(2.5,80/(max(1,r)**0.33))

def player_value(meta, pick_map):
    base=max(pick_value(pick_map.get(meta["player_id"])), search_value(meta["search_rank"])*.78)
    pos_mult={"RB":1.07,"WR":1.0,"TE":.96,"QB":.90,"K":.35,"DEF":.38}.get(meta["position"],.65)
    age_mult=1.0
    age=meta["age"]
    if meta["position"] in {"RB","WR","TE"} and isinstance(age,(int,float)):
        if age <= 24: age_mult=1.04
        elif age >= 31: age_mult=.94
    return base*pos_mult*age_mult*injury_mult(meta["injury"])

def roster_rows(roster, players, pick_map):
    starters={str(x) for x in (roster.get("starters") or [])}
    out=[]
    for pid in roster.get("players") or []:
        m=pmeta(pid,players)
        m["starter"]=str(pid) in starters
        m["value"]=round(player_value(m,pick_map),2)
        out.append(m)
    return out

def pos_values(roster, players, pick_map):
    d=defaultdict(list)
    for r in roster_rows(roster,players,pick_map):
        if r["position"]:
            d[r["position"]].append(r["value"])
    for p in d: d[p].sort(reverse=True)
    return d

def raw_power(roster, players, pick_map):
    vals=pos_values(roster,players,pick_map)
    weights={
        "QB":[1,.12], "RB":[1,.94,.66,.44,.28,.15],
        "WR":[1,.96,.78,.52,.32,.18], "TE":[1,.18],
        "K":[.08], "DEF":[.10]
    }
    total=0
    bd={}
    for pos, arr in vals.items():
        w=weights.get(pos,[.08]*len(arr))
        s=sum(v*(w[i] if i<len(w) else .07) for i,v in enumerate(arr))
        bd[pos]=s
        total+=s
    return total,bd

def normalize(items):
    vals=[x["raw"] for x in items]
    lo,hi=min(vals),max(vals)
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

def needs(roster, players, pick_map):
    vals=pos_values(roster,players,pick_map)
    counts={"QB":1,"RB":4,"WR":4,"TE":1}
    thresholds={"QB":25,"RB":22,"WR":22,"TE":18}
    out={}
    for pos,c in counts.items():
        arr=vals.get(pos,[])
        core=sum(arr[:c])/c if arr else 0
        out[pos]=max(0,thresholds[pos]-core)+max(0,c-len(arr))*7
    return out

def card(label,value,sub=""):
    st.markdown(
        f'<div class="stat-card"><div class="stat-label">{label}</div>'
        f'<div class="stat-value">{value}</div><div class="stat-sub">{sub}</div></div>',
        unsafe_allow_html=True
    )

def player_card(row):
    inj = ""
    if row["injury"]:
        cls="bad" if str(row["injury"]).lower() in {"out","ir","pup"} else "warn"
        inj=f'<span class="badge {cls}">{row["injury"]}</span>'
    starter='<span class="badge accent">STARTER</span>' if row.get("starter") else ''
    pos=row["position"] or "-"
    team=row["team"] or "FA"
    st.markdown(
        f'<div class="player-card"><div class="player-main">'
        f'<div class="player-name">{row["name"]}{starter}{inj}</div>'
        f'<div class="player-meta">{pos} · {team}'
        f'{" · depth "+str(row["depth"]) if row["depth"] else ""}</div></div>'
        f'<div class="player-score">{row["value"]:.1f}</div></div>',
        unsafe_allow_html=True
    )

# ------------------ LOAD ------------------

league_id=st.sidebar.text_input("Sleeper league ID",DEFAULT_LEAGUE_ID)

try:
    league=get(f"/league/{league_id}")
    users=get(f"/league/{league_id}/users")
    rosters=get(f"/league/{league_id}/rosters")
    players=get_players()
except Exception as e:
    st.error(f"Could not load league: {e}")
    st.stop()

user_map={str(u.get("user_id")):u for u in users}
roster_names={}
for r in rosters:
    oid=str(r.get("owner_id")) if r.get("owner_id") else None
    roster_names[r["roster_id"]]=display_name(user_map.get(oid,{})) if oid else f"Roster {r['roster_id']}"

# latest draft
try:
    drafts=get(f"/league/{league_id}/drafts")
except Exception:
    drafts=[]
latest=sorted(drafts,key=lambda x:x.get("created",0) or 0,reverse=True)[0] if drafts else None
picks=get(f"/draft/{latest['draft_id']}/picks") if latest else []
pick_map={str(x.get("player_id")):x.get("pick_no") for x in picks if x.get("player_id") is not None}

team_options={roster_names[r["roster_id"]]:r["roster_id"] for r in rosters}
team_names=list(team_options.keys())

# ------------------ MY TEAM FIX ------------------

saved_team = st.query_params.get("myteam")
saved_rid = None
try:
    saved_rid=int(saved_team) if saved_team else None
except Exception:
    pass

if "my_rid" not in st.session_state:
    st.session_state.my_rid = saved_rid if saved_rid in team_options.values() else None

if st.session_state.my_rid is None:
    st.markdown('<div class="hero"><div class="kicker">Setup</div><h1>Sleeper GM</h1><p>Choose your team once, then the portal will remember it in the URL.</p></div>',unsafe_allow_html=True)
    chosen=st.selectbox("Which team is yours?",["— Select your team —"]+team_names)
    if chosen!="— Select your team —":
        rid=team_options[chosen]
        if st.button("Set as my team",type="primary"):
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
    if "myteam" in st.query_params:
        del st.query_params["myteam"]
    st.rerun()

# ------------------ NAV ------------------

PAGES=["Home","Power Rankings","My Team","Trade Centre","Waivers","Matchup Scout","Lineup","League Activity","Rosters","Export"]
page=st.sidebar.radio("Navigate",PAGES)
st.sidebar.markdown("---")
st.sidebar.caption(f"{league.get('name','League')} · {league.get('season','')}")

# power
power=[]
for r in rosters:
    raw,bd=raw_power(r,players,pick_map)
    power.append({"rid":r["roster_id"],"team":roster_names[r["roster_id"]],"raw":raw,"bd":bd})
normalize(power)
power=sorted(power,key=lambda x:x["score"],reverse=True)
rank={x["rid"]:i+1 for i,x in enumerate(power)}
pscore={x["rid"]:x["score"] for x in power}

# ------------------ HEADER ------------------

st.markdown(
    f'<div class="hero"><div class="kicker">Fantasy GM Command Centre</div>'
    f'<h1>{my_name}</h1><p>{league.get("name","Sleeper League")} · live roster intelligence</p></div>',
    unsafe_allow_html=True
)

# ------------------ HOME ------------------

if page=="Home":
    me=next(x for x in power if x["rid"]==my_rid)
    myneeds=needs(my_roster,players,pick_map)
    biggest=max(myneeds,key=myneeds.get)

    c1,c2,c3,c4=st.columns(4)
    with c1: card("League rank",f"#{rank[my_rid]} / {len(rosters)}","Power model")
    with c2: card("Roster grade",grade(me["score"]),f"{me['score']:.1f} power")
    with c3: card("Biggest need",biggest,f"{myneeds[biggest]:.1f} need score")
    with c4:
        rows=roster_rows(my_roster,players,pick_map)
        injured=sum(1 for x in rows if x["injury"])
        card("Status watch",injured,"players flagged")

    st.markdown('<div class="section-head"><h2>Your core</h2><span>Highest current roster values</span></div>',unsafe_allow_html=True)
    core=sorted(roster_rows(my_roster,players,pick_map),key=lambda x:x["value"],reverse=True)[:8]
    c1,c2=st.columns(2)
    for i,row in enumerate(core):
        with (c1 if i%2==0 else c2):
            player_card(row)

    st.markdown('<div class="section-head"><h2>League top 5</h2><span>Current model</span></div>',unsafe_allow_html=True)
    top=pd.DataFrame([{"Rank":i+1,"Team":x["team"],"Grade":grade(x["score"]),"Power":round(x["score"],1)} for i,x in enumerate(power[:5])])
    st.dataframe(top,use_container_width=True,hide_index=True)

elif page=="Power Rankings":
    st.markdown("## Power Rankings")
    table=[]
    for i,x in enumerate(power):
        table.append({
            "Rank":i+1,"Team":x["team"],"Grade":grade(x["score"]),"Power":round(x["score"],1),
            "QB":round(x["bd"].get("QB",0),1),"RB":round(x["bd"].get("RB",0),1),
            "WR":round(x["bd"].get("WR",0),1),"TE":round(x["bd"].get("TE",0),1)
        })
    st.dataframe(pd.DataFrame(table),use_container_width=True,hide_index=True)

elif page=="My Team":
    st.markdown("## My Team")
    rows=roster_rows(my_roster,players,pick_map)
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

elif page=="Trade Centre":
    tab1,tab2=st.tabs(["Trade targets","Trade analyser"])
    with tab1:
        myneeds=needs(my_roster,players,pick_map)
        needpos=max(myneeds,key=myneeds.get)
        st.markdown(f'<div class="notice">Your largest modeled need is <b>{needpos}</b>. Targets below are filtered for teams with depth at that position.</div>',unsafe_allow_html=True)
        candidates=[]
        for r in rosters:
            if r["roster_id"]==my_rid: continue
            rows=[x for x in roster_rows(r,players,pick_map) if x["position"]==needpos]
            theirneed=needs(r,players,pick_map).get(needpos,0)
            for x in rows:
                targetability=x["value"]+max(0,len(rows)-3)*2.5-theirneed*.35
                candidates.append({
                    "Target":x["name"],"Pos":needpos,"NFL":x["team"],"Owner":roster_names[r["roster_id"]],
                    "Value":round(x["value"],1),"Their depth":len(rows),"Targetability":round(targetability,1)
                })
        if candidates:
            st.dataframe(pd.DataFrame(candidates).sort_values("Targetability",ascending=False).head(30),use_container_width=True,hide_index=True)

    with tab2:
        partner_name=st.selectbox("Trade partner",[x for x in team_names if x!=my_name])
        partner_rid=team_options[partner_name]
        partner=next(r for r in rosters if r["roster_id"]==partner_rid)

        mine={x["name"]:x for x in roster_rows(my_roster,players,pick_map)}
        theirs={x["name"]:x for x in roster_rows(partner,players,pick_map)}
        a,b=st.columns(2)
        with a: give=st.multiselect("You give",list(mine.keys()))
        with b: receive=st.multiselect("You receive",list(theirs.keys()))
        gv=sum(mine[x]["value"] for x in give)
        rv=sum(theirs[x]["value"] for x in receive)
        c1,c2,c3=st.columns(3)
        c1.metric("Send",round(gv,1))
        c2.metric("Receive",round(rv,1))
        c3.metric("Raw edge",round(rv-gv,1))
        if give or receive:
            if rv-gv>5: st.success("Leans your way.")
            elif rv-gv<-5: st.error("You are paying too much.")
            else: st.info("Roughly balanced on current market value.")

elif page=="Waivers":
    rostered={str(pid) for r in rosters for pid in (r.get("players") or [])}
    try:
        adds=get("/players/nfl/trending/add?lookback_hours=24&limit=100")
        drops=get("/players/nfl/trending/drop?lookback_hours=24&limit=100")
    except Exception:
        adds,drops=[],[]
    amap={str(x["player_id"]):x.get("count",0) for x in adds}
    dmap={str(x["player_id"]):x.get("count",0) for x in drops}

    rows=[]
    for pid,p in players.items():
        pid=str(pid)
        if pid in rostered or p.get("active") is False: continue
        if p.get("position") not in {"QB","RB","WR","TE","K","DEF"}: continue
        m=pmeta(pid,players)
        score=player_value(m,pick_map)+math.log1p(amap.get(pid,0))*3.2-math.log1p(dmap.get(pid,0))*1.15
        if m["position"] in {"RB","WR","TE"} and m["depth"] in [1,2]:
            score+=5 if m["depth"]==1 else 2.5
        rows.append({
            "Player":m["name"],"Pos":m["position"],"NFL":m["team"],"Injury":m["injury"],
            "Depth":m["depth"],"Adds 24h":amap.get(pid,0),"Waiver score":round(score,1)
        })
    df=pd.DataFrame(rows)
    posf=st.multiselect("Position",["RB","WR","TE","QB","K","DEF"],default=["RB","WR","TE"])
    if posf: df=df[df["Pos"].isin(posf)]
    st.dataframe(df.sort_values(["Waiver score","Adds 24h"],ascending=False).head(100),use_container_width=True,hide_index=True)

elif page=="Matchup Scout":
    week=st.number_input("Week",1,18,1,1)
    ms=get(f"/league/{league_id}/matchups/{int(week)}")
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
            for row in sorted(roster_rows(op,players,pick_map),key=lambda x:(not x["starter"],-x["value"])):
                player_card(row)
        else: st.info("Opponent not posted yet.")
    else: st.info("No matchup data for that week yet.")

elif page=="Lineup":
    st.markdown("## Lineup")
    st.warning("This is still a roster-value lineup, not a true weekly projection optimizer yet.")
    slots=league.get("roster_positions") or []
    remaining=roster_rows(my_roster,players,pick_map)
    chosen=[]
    def eligible(r,slot):
        pos=r["position"]
        if slot in {"QB","RB","WR","TE","K","DEF"}: return pos==slot
        if slot in {"FLEX","WRRB_FLEX","WRT_FLEX","REC_FLEX"}: return pos in {"RB","WR","TE"}
        if slot=="SUPER_FLEX": return pos in {"QB","RB","WR","TE"}
        return False
    for slot in slots:
        if slot in {"BN","IR","TAXI"}: continue
        cand=[x for x in remaining if eligible(x,slot)]
        if not cand: continue
        best=max(cand,key=lambda x:x["value"])
        chosen.append({"Slot":slot,"Player":best["name"],"Pos":best["position"],"NFL":best["team"],"Injury":best["injury"],"Score":round(best["value"],1)})
        remaining=[x for x in remaining if x["player_id"]!=best["player_id"]]
    st.dataframe(pd.DataFrame(chosen),use_container_width=True,hide_index=True)

elif page=="League Activity":
    st.markdown("## League Activity")
    week=st.number_input("Week",1,18,1,1,key="activityweek")
    try: tx=get(f"/league/{league_id}/transactions/{int(week)}")
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
    if feed: st.dataframe(pd.DataFrame(feed),use_container_width=True,hide_index=True)

    st.markdown("### Injury watch")
    alerts=[]
    for r in rosters:
        for x in roster_rows(r,players,pick_map):
            if x["injury"]:
                alerts.append({"Player":x["name"],"Owner":roster_names[r["roster_id"]],"Pos":x["position"],"NFL":x["team"],"Injury":x["injury"]})
    if alerts: st.dataframe(pd.DataFrame(alerts),use_container_width=True,hide_index=True)

elif page=="Rosters":
    selected=st.selectbox("Team",team_names)
    rid=team_options[selected]
    r=next(r for r in rosters if r["roster_id"]==rid)
    rows=sorted(roster_rows(r,players,pick_map),key=lambda x:(not x["starter"],-x["value"]))
    c1,c2=st.columns(2)
    for i,row in enumerate(rows):
        with (c1 if i%2==0 else c2): player_card(row)

elif page=="Export":
    snapshot={
        "generated_at":datetime.now().isoformat(timespec="seconds"),
        "league":{"id":league_id,"name":league.get("name"),"season":league.get("season"),"scoring":league.get("scoring_settings")},
        "my_team":{"name":my_name,"roster_id":my_rid},
        "power_rankings":[{"rank":i+1,"team":x["team"],"roster_id":x["rid"],"score":round(x["score"],1),"grade":grade(x["score"])} for i,x in enumerate(power)],
        "teams":[]
    }
    for r in rosters:
        snapshot["teams"].append({"name":roster_names[r["roster_id"]],"roster_id":r["roster_id"],"players":roster_rows(r,players,pick_map)})
    raw=json.dumps(snapshot,indent=2,ensure_ascii=False)
    st.download_button("Download league snapshot",raw,file_name=f"sleeper_{league_id}_snapshot.json",mime="application/json",use_container_width=True)
