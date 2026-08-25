import json
import math
from collections import Counter, defaultdict
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

DEFAULT_LEAGUE_ID = "1389344022107021312"
SLEEPER = "https://api.sleeper.app/v1"

st.set_page_config(page_title="Sleeper GM", page_icon="🏈", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
:root{--card:rgba(255,255,255,.055);--border:rgba(255,255,255,.09);--muted:rgba(250,250,250,.62);--good:#30d158;--warn:#ffd60a;--bad:#ff453a;--accent:#8b5cf6}
.block-container{max-width:1450px;padding-top:1.4rem;padding-bottom:4rem}
[data-testid="stSidebar"]{border-right:1px solid var(--border)}
.hero{padding:1.15rem 1.2rem 1rem;border:1px solid var(--border);border-radius:22px;background:linear-gradient(135deg,rgba(139,92,246,.18),rgba(59,130,246,.06));margin-bottom:1rem}
.hero h1{margin:0;font-size:clamp(2rem,5vw,3.6rem);line-height:1;letter-spacing:-.045em}.hero p{color:var(--muted);margin:.55rem 0 0}
.card{border:1px solid var(--border);background:var(--card);border-radius:18px;padding:1rem 1.05rem;height:100%}.eyebrow{color:var(--muted);text-transform:uppercase;letter-spacing:.09em;font-size:.74rem;font-weight:700}
.pill{display:inline-block;padding:.22rem .55rem;border-radius:999px;font-size:.76rem;font-weight:700;margin-right:.28rem;border:1px solid var(--border);background:rgba(255,255,255,.04)}.good{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}
div[data-testid="stMetric"]{border:1px solid var(--border);background:var(--card);padding:.75rem .85rem;border-radius:16px}div[data-testid="stDataFrame"]{border:1px solid var(--border);border-radius:16px;overflow:hidden}.stButton>button,.stDownloadButton>button{border-radius:12px}h1,h2,h3{letter-spacing:-.025em}
@media(max-width:700px){.block-container{padding-left:.75rem;padding-right:.75rem}.hero{border-radius:18px}}
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=300, show_spinner=False)
def sleeper_get(path):
    r = requests.get(f"{SLEEPER}{path}", timeout=25)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=3600, show_spinner=False)
def nfl_players():
    return sleeper_get("/players/nfl")

@st.cache_data(ttl=600, show_spinner=False)
def league_drafts(league_id):
    return sleeper_get(f"/league/{league_id}/drafts")

@st.cache_data(ttl=600, show_spinner=False)
def draft_picks(draft_id):
    return sleeper_get(f"/draft/{draft_id}/picks")

@st.cache_data(ttl=300, show_spinner=False)
def matchups(league_id, week):
    return sleeper_get(f"/league/{league_id}/matchups/{week}")

@st.cache_data(ttl=300, show_spinner=False)
def transactions(league_id, week):
    return sleeper_get(f"/league/{league_id}/transactions/{week}")

@st.cache_data(ttl=300, show_spinner=False)
def trending(kind="add", hours=24, limit=100):
    return sleeper_get(f"/players/nfl/trending/{kind}?lookback_hours={hours}&limit={limit}")

def user_team_name(user):
    md = user.get("metadata") or {}
    return md.get("team_name") or user.get("display_name") or user.get("username") or f"User {user.get('user_id','')}"

def pmeta(pid, players):
    p = players.get(str(pid), {})
    name = p.get("full_name") or " ".join(x for x in [p.get("first_name"), p.get("last_name")] if x).strip() or str(pid)
    return {"player_id":str(pid),"name":name,"position":p.get("position"),"team":p.get("team"),"status":p.get("status"),"injury_status":p.get("injury_status"),"depth":p.get("depth_chart_order"),"age":p.get("age"),"years_exp":p.get("years_exp"),"search_rank":p.get("search_rank")}

def injury_multiplier(status):
    s=(status or "").lower()
    if s in {"out","ir","pup"}: return .72
    if s=="doubtful": return .82
    if s=="questionable": return .93
    return 1.0

def pick_value(pick_no):
    if not pick_no: return 0.0
    p=max(1.0,float(pick_no)); return 118/(p**.48)

def search_rank_value(rank):
    try:r=float(rank)
    except Exception:return 4.0
    if r<=0:return 4.0
    return max(2.5,80/(r**.33))

def build_pick_map(picks):
    return {str(x.get("player_id")):x.get("pick_no") for x in picks if x.get("player_id") is not None}

def player_value(meta,pick_map):
    draft_v=pick_value(pick_map.get(meta["player_id"])); search_v=search_rank_value(meta.get("search_rank")); raw=max(draft_v,search_v*.78)
    scarcity={"RB":1.07,"WR":1.0,"TE":.96,"QB":.90,"K":.35,"DEF":.38}.get(meta.get("position"),.65)
    youth=1.0; age=meta.get("age")
    if meta.get("position") in {"RB","WR","TE"} and isinstance(age,(int,float)):
        if age<=24:youth=1.04
        elif age>=31:youth=.94
    return raw*scarcity*youth*injury_multiplier(meta.get("injury_status"))

def roster_rows(roster,players,pick_map):
    starters={str(x) for x in (roster.get("starters") or [])}; rows=[]
    for pid in roster.get("players") or []:
        m=pmeta(pid,players); m["starter"]=str(pid) in starters; m["value"]=round(player_value(m,pick_map),2); rows.append(m)
    return rows

def position_values(roster,players,pick_map):
    vals=defaultdict(list)
    for row in roster_rows(roster,players,pick_map):
        if row["position"]: vals[row["position"]].append(row["value"])
    for pos in vals: vals[pos].sort(reverse=True)
    return vals

def roster_power_raw(roster,players,pick_map):
    vals=position_values(roster,players,pick_map); weights={"QB":[1,.12],"RB":[1,.94,.66,.44,.28,.15],"WR":[1,.96,.78,.52,.32,.18],"TE":[1,.18],"K":[.08],"DEF":[.10]}; bd={}; total=0
    for pos,arr in vals.items():
        w=weights.get(pos,[.08]*len(arr)); score=sum(v*(w[i] if i<len(w) else .07) for i,v in enumerate(arr)); bd[pos]=score; total+=score
    return total,bd

def normalize_scores(items):
    vals=[x["raw"] for x in items]; lo,hi=min(vals),max(vals)
    for x in items:x["score"]=82.0 if hi==lo else 68+27*((x["raw"]-lo)/(hi-lo))
    return items

def needs_score(roster,players,pick_map):
    vals=position_values(roster,players,pick_map); target_counts={"QB":1,"RB":4,"WR":4,"TE":1}; thresholds={"QB":25,"RB":22,"WR":22,"TE":18}; needs={}
    for pos,cnt in target_counts.items():
        arr=vals.get(pos,[]); core=sum(arr[:cnt])/cnt if arr else 0; depth_missing=max(0,cnt-len(arr)); needs[pos]=max(0,thresholds[pos]-core)+depth_missing*7
    return needs

def grade(score):
    return "A+" if score>=92 else "A" if score>=88 else "A-" if score>=84 else "B+" if score>=80 else "B" if score>=76 else "B-" if score>=72 else "C"

def league_week(league):
    s=league.get("settings") or {}
    return int(s.get("leg") or s.get("week") or 1)

st.markdown('<div class="hero"><div class="eyebrow">Fantasy GM Command Centre</div><h1>Sleeper GM</h1><p>Power rankings, trades, waivers, matchup scouting and roster decisions — live from your league.</p></div>', unsafe_allow_html=True)
league_id=st.sidebar.text_input("Sleeper league ID",value=DEFAULT_LEAGUE_ID).strip()

try:
    league=sleeper_get(f"/league/{league_id}"); users=sleeper_get(f"/league/{league_id}/users"); rosters=sleeper_get(f"/league/{league_id}/rosters"); players=nfl_players()
except Exception as e:
    st.error(f"Couldn't load Sleeper league: {e}"); st.stop()

user_map={str(u.get("user_id")):u for u in users}; roster_names={}
for r in rosters:
    oid=str(r.get("owner_id")) if r.get("owner_id") else None
    roster_names[r.get("roster_id")]=user_team_name(user_map.get(oid,{})) if oid else f"Roster {r.get('roster_id')}"

drafts=league_drafts(league_id); latest_draft=sorted(drafts,key=lambda x:x.get("created",0) or 0,reverse=True)[0] if drafts else None; picks=draft_picks(latest_draft["draft_id"]) if latest_draft else []; pick_map=build_pick_map(picks)
team_options={roster_names[r["roster_id"]]:r["roster_id"] for r in rosters}; team_names=list(team_options.keys())
qp_team=st.query_params.get("team")
try: default_rid=int(qp_team) if qp_team else None
except Exception: default_rid=None
if "my_roster_id" not in st.session_state: st.session_state.my_roster_id=default_rid if default_rid in team_options.values() else list(team_options.values())[0]
current_name=next((n for n,rid in team_options.items() if rid==st.session_state.my_roster_id),team_names[0])
st.sidebar.markdown("### Your team")
chosen_name=st.sidebar.selectbox("Select once",team_names,index=team_names.index(current_name),label_visibility="collapsed")
st.session_state.my_roster_id=team_options[chosen_name]; st.query_params["team"]=str(st.session_state.my_roster_id)
my_rid=st.session_state.my_roster_id; my_name=roster_names[my_rid]; my_roster=next(r for r in rosters if r["roster_id"]==my_rid); current_week=league_week(league)
NAV=["Home","Power Rankings","My Team","Trade Centre","Waivers","Matchup Scout","Lineup Optimizer","League Activity","Rosters","Export"]
page=st.sidebar.radio("Navigate",NAV); st.sidebar.markdown("---"); st.sidebar.caption(f"{league.get('name','League')} · {league.get('season','')} · Week {current_week}"); st.sidebar.caption("Data refreshes automatically.")

power=[]
for r in rosters:
    raw,bd=roster_power_raw(r,players,pick_map); power.append({"rid":r["roster_id"],"team":roster_names[r["roster_id"]],"raw":raw,"bd":bd})
normalize_scores(power); power=sorted(power,key=lambda x:x["score"],reverse=True); power_rank={x["rid"]:i+1 for i,x in enumerate(power)}

if page=="Home":
    mine=next(x for x in power if x["rid"]==my_rid); my_needs=needs_score(my_roster,players,pick_map); biggest_need=max(my_needs,key=my_needs.get)
    c1,c2,c3,c4=st.columns(4); c1.metric("Power rank",f"#{power_rank[my_rid]} / {len(rosters)}"); c2.metric("Roster grade",grade(mine["score"])); c3.metric("Power score",f"{mine['score']:.1f}"); c4.metric("Biggest need",biggest_need)
    left,right=st.columns([1.35,1])
    with left:
        st.markdown("### Your core"); rows=pd.DataFrame(roster_rows(my_roster,players,pick_map)); starters=rows[rows["starter"]==True] if not rows.empty else rows
        if not starters.empty: st.dataframe(starters[["name","position","team","injury_status","value"]].rename(columns={"value":"Market score"}),use_container_width=True,hide_index=True)
    with right:
        st.markdown("### Roster pressure"); st.dataframe(pd.DataFrame([{"Position":k,"Need score":round(v,1)} for k,v in sorted(my_needs.items(),key=lambda x:x[1],reverse=True)]),use_container_width=True,hide_index=True)
        st.caption("Transparent model: your league's draft capital + Sleeper player rank + positional scarcity + injury status.")
    st.markdown("### Top of the league"); st.dataframe(pd.DataFrame([{"Rank":i+1,"Team":x["team"],"Score":round(x["score"],1),"Grade":grade(x["score"])} for i,x in enumerate(power[:5])]),use_container_width=True,hide_index=True)

elif page=="Power Rankings":
    st.markdown("## League Power Rankings"); st.caption("Starter strength matters most. RB/WR depth still carries real weight; kicker and D/ST barely move the model.")
    table=[]
    for i,x in enumerate(power):
        bd=x["bd"]; table.append({"Rank":i+1,"Team":x["team"],"Grade":grade(x["score"]),"Power":round(x["score"],1),"QB":round(bd.get("QB",0),1),"RB":round(bd.get("RB",0),1),"WR":round(bd.get("WR",0),1),"TE":round(bd.get("TE",0),1)})
    st.dataframe(pd.DataFrame(table),use_container_width=True,hide_index=True)

elif page=="My Team":
    st.markdown(f"## {my_name}"); mine=next(x for x in power if x["rid"]==my_rid); rows=pd.DataFrame(roster_rows(my_roster,players,pick_map)); counts=Counter(rows["position"]) if not rows.empty else Counter(); c1,c2,c3,c4,c5=st.columns(5); c1.metric("League rank",f"#{power_rank[my_rid]}"); c2.metric("Grade",grade(mine["score"])); c3.metric("RBs",counts.get("RB",0)); c4.metric("WRs",counts.get("WR",0)); c5.metric("Injured",int(rows["injury_status"].notna().sum()) if not rows.empty else 0)
    st.markdown("### Starters"); starters=rows[rows["starter"]==True].sort_values(["position","value"],ascending=[True,False]); st.dataframe(starters[["name","position","team","injury_status","depth","value"]].rename(columns={"depth":"Depth","value":"Market score"}),use_container_width=True,hide_index=True)
    st.markdown("### Bench"); bench=rows[rows["starter"]==False].sort_values("value",ascending=False); st.dataframe(bench[["name","position","team","injury_status","depth","value"]].rename(columns={"depth":"Depth","value":"Market score"}),use_container_width=True,hide_index=True)

elif page=="Trade Centre":
    st.markdown("## Trade Centre"); t1,t2=st.tabs(["Targets","Analyser"])
    with t1:
        my_needs=needs_score(my_roster,players,pick_map); need_pos=max(my_needs,key=my_needs.get); st.info(f"Model sees **{need_pos}** as your biggest current need.")
        candidates=[]
        for r in rosters:
            if r["roster_id"]==my_rid: continue
            their_needs=needs_score(r,players,pick_map); rows=roster_rows(r,players,pick_map); pos_rows=sorted([x for x in rows if x["position"]==need_pos],key=lambda x:x["value"],reverse=True)
            for p in pos_rows:
                surplus=max(0,len(pos_rows)-3); target_score=p["value"]+surplus*2.5-their_needs.get(need_pos,0)*.4; candidates.append({"Target":p["name"],"Pos":p["position"],"NFL":p["team"],"Manager":roster_names[r["roster_id"]],"Player value":round(p["value"],1),"Their depth":len(pos_rows),"Targetability":round(target_score,1)})
        if candidates: st.dataframe(pd.DataFrame(candidates).sort_values("Targetability",ascending=False).head(30),use_container_width=True,hide_index=True)
    with t2:
        partner_name=st.selectbox("Trade partner",[x for x in team_names if x!=my_name]); partner_rid=team_options[partner_name]; partner=next(r for r in rosters if r["roster_id"]==partner_rid); mine_rows=roster_rows(my_roster,players,pick_map); theirs_rows=roster_rows(partner,players,pick_map); mine_lookup={x["name"]:x for x in mine_rows}; theirs_lookup={x["name"]:x for x in theirs_rows}; c1,c2=st.columns(2)
        with c1: give=st.multiselect("You give",list(mine_lookup.keys()))
        with c2: receive=st.multiselect("You receive",list(theirs_lookup.keys()))
        gv=sum(mine_lookup[x]["value"] for x in give); rv=sum(theirs_lookup[x]["value"] for x in receive); my_need=needs_score(my_roster,players,pick_map); pn=needs_score(partner,players,pick_map); your_adj=rv+sum(my_need.get(theirs_lookup[x]["position"],0)*.10 for x in receive)-gv; their_adj=gv+sum(pn.get(mine_lookup[x]["position"],0)*.10 for x in give)-rv; a,b,c=st.columns(3); a.metric("You send",round(gv,1)); b.metric("You receive",round(rv,1)); c.metric("Roster-adjusted edge",round(your_adj,1))
        if give or receive:
            st.success("Strong structure for you, and still plausible for them.") if your_adj>6 and their_adj>-8 else st.error("You are giving up too much according to this model.") if your_adj<-6 else st.info("Roughly balanced. Upside and fresh news should decide it.")

elif page=="Waivers":
    st.markdown("## Waiver & Free-Agent Board"); rostered={str(pid) for r in rosters for pid in (r.get("players") or [])}
    try:adds=trending("add",24,100); drops=trending("drop",24,100)
    except Exception:adds,drops=[],[]
    add_map={str(x["player_id"]):x.get("count",0) for x in adds}; drop_map={str(x["player_id"]):x.get("count",0) for x in drops}; rows=[]
    for pid,p in players.items():
        pid=str(pid)
        if pid in rostered or p.get("active") is False: continue
        pos=p.get("position")
        if pos not in {"QB","RB","WR","TE","K","DEF"}: continue
        m=pmeta(pid,players); base_v=player_value(m,pick_map); a=add_map.get(pid,0); d=drop_map.get(pid,0); depth_bonus=5 if pos in {"RB","WR","TE"} and m.get("depth")==1 else 2.5 if pos in {"RB","WR","TE"} and m.get("depth")==2 else 0; score=base_v+math.log1p(a)*3.3-math.log1p(d)*1.2+depth_bonus; rows.append({"Player":m["name"],"Pos":pos,"NFL":m["team"],"Injury":m["injury_status"],"Depth":m["depth"],"Adds 24h":a,"Drops 24h":d,"Waiver score":round(score,1)})
    wdf=pd.DataFrame(rows); pos_filter=st.multiselect("Position",["RB","WR","TE","QB","K","DEF"],default=["RB","WR","TE"]); wdf=wdf[wdf["Pos"].isin(pos_filter)] if pos_filter else wdf; st.dataframe(wdf.sort_values(["Waiver score","Adds 24h"],ascending=False).head(100),use_container_width=True,hide_index=True)
    st.markdown("### Lowest-value bench spots"); my_rows=sorted(roster_rows(my_roster,players,pick_map),key=lambda x:x["value"]); dc=[x for x in my_rows if not x["starter"] and x["position"] in {"RB","WR","TE","QB"}][:8]; st.dataframe(pd.DataFrame(dc)[["name","position","team","injury_status","value"]].rename(columns={"value":"Market score"}),use_container_width=True,hide_index=True) if dc else None

elif page=="Matchup Scout":
    st.markdown("## Opponent Scout"); week=st.number_input("Week",1,18,max(1,current_week),1); ms=matchups(league_id,int(week)); mine=next((m for m in ms if m.get("roster_id")==my_rid),None)
    if not mine or mine.get("matchup_id") is None: st.info("No matchup has been posted for that week yet.")
    else:
        opp=next((m for m in ms if m.get("matchup_id")==mine.get("matchup_id") and m.get("roster_id")!=my_rid),None)
        if not opp: st.info("Opponent not available yet.")
        else:
            opp_rid=opp["roster_id"]; opp_name=roster_names[opp_rid]; opp_roster=next(r for r in rosters if r["roster_id"]==opp_rid); st.markdown(f"### {my_name}  **vs**  {opp_name}"); mp=next(x for x in power if x["rid"]==my_rid); op=next(x for x in power if x["rid"]==opp_rid); c1,c2,c3=st.columns(3); c1.metric("Your league rank",f"#{power_rank[my_rid]}"); c2.metric("Opponent rank",f"#{power_rank[opp_rid]}"); c3.metric("Power edge",round(mp["score"]-op["score"],1)); comp=[]
            for pos in ["QB","RB","WR","TE"]:
                y=mp["bd"].get(pos,0); t=op["bd"].get(pos,0); comp.append({"Position":pos,"You":round(y,1),"Opponent":round(t,1),"Edge":round(y-t,1)})
            st.dataframe(pd.DataFrame(comp),use_container_width=True,hide_index=True); odf=pd.DataFrame(roster_rows(opp_roster,players,pick_map)).sort_values(["starter","value"],ascending=[False,False]); st.dataframe(odf[["name","position","team","starter","injury_status","value"]].rename(columns={"value":"Market score"}),use_container_width=True,hide_index=True)

elif page=="Lineup Optimizer":
    st.markdown("## Lineup Optimizer"); st.warning("This version is a **roster-value optimizer**, not a true weekly projection engine. We'll upgrade it once a projection feed is connected."); slots=league.get("roster_positions") or []; rows=roster_rows(my_roster,players,pick_map); remaining=rows.copy(); chosen=[]
    def eligible(row,slot):
        pos=row["position"]
        if slot in {"QB","RB","WR","TE","K","DEF"}: return pos==slot
        if slot in {"FLEX","WRRB_FLEX","WRT_FLEX","REC_FLEX"}: return pos in {"RB","WR","TE"}
        if slot=="SUPER_FLEX": return pos in {"QB","RB","WR","TE"}
        return False
    for slot in slots:
        if slot in {"BN","IR","TAXI"}: continue
        cand=[x for x in remaining if eligible(x,slot)]
        if not cand: continue
        best=max(cand,key=lambda x:x["value"]); chosen.append({"Slot":slot,"Player":best["name"],"Pos":best["position"],"NFL":best["team"],"Injury":best["injury_status"],"Score":round(best["value"],1)}); remaining=[x for x in remaining if x["player_id"]!=best["player_id"]]
    st.dataframe(pd.DataFrame(chosen),use_container_width=True,hide_index=True)

elif page=="League Activity":
    st.markdown("## League Activity"); st.caption("Actual league-specific transactions plus roster injury alerts."); week=st.number_input("Transaction week",1,18,max(1,current_week),1)
    try:tx=transactions(league_id,int(week))
    except Exception:tx=[]
    feed=[]
    for t in sorted(tx,key=lambda x:x.get("created",0),reverse=True):
        typ=t.get("type","transaction").upper(); rids=t.get("roster_ids") or []; managers=", ".join(roster_names.get(r,f"Roster {r}") for r in rids); am=t.get("adds") or {}; dm=t.get("drops") or {}; at=", ".join(f"{pmeta(pid,players)['name']} → {roster_names.get(rid,rid)}" for pid,rid in am.items()); dt=", ".join(f"{pmeta(pid,players)['name']} ← {roster_names.get(rid,rid)}" for pid,rid in dm.items()); parts=[]; parts += (["Added "+at] if at else []); parts += (["Dropped "+dt] if dt else []); parts += (["Trade completed"] if typ=="TRADE" else []); feed.append({"Type":typ,"Managers":managers,"Details":" · ".join(parts) if parts else typ.title(),"Status":t.get("status")})
    st.dataframe(pd.DataFrame(feed),use_container_width=True,hide_index=True) if feed else st.info("No transactions returned for this week yet.")
    st.markdown("### Injury / status watch"); alerts=[]
    for r in rosters:
        for row in roster_rows(r,players,pick_map):
            if row["injury_status"] or (row["status"] and str(row["status"]).lower()!="active"): alerts.append({"Player":row["name"],"Owner":roster_names[r["roster_id"]],"Pos":row["position"],"NFL":row["team"],"Status":row["status"],"Injury":row["injury_status"]})
    st.dataframe(pd.DataFrame(alerts),use_container_width=True,hide_index=True) if alerts else st.success("No rostered injury/status flags found.")

elif page=="Rosters":
    st.markdown("## League Rosters"); selected=st.selectbox("Team",team_names); rid=team_options[selected]; r=next(r for r in rosters if r["roster_id"]==rid); rdf=pd.DataFrame(roster_rows(r,players,pick_map)).sort_values(["starter","position","value"],ascending=[False,True,False]); st.dataframe(rdf[["name","position","team","starter","injury_status","depth","value"]].rename(columns={"value":"Market score"}),use_container_width=True,hide_index=True)

elif page=="Export":
    st.markdown("## ChatGPT Analysis Export"); snapshot={"generated_at":datetime.now().isoformat(timespec="seconds"),"league":{"league_id":league_id,"name":league.get("name"),"season":league.get("season"),"week":current_week,"roster_positions":league.get("roster_positions"),"scoring_settings":league.get("scoring_settings")},"my_team":{"name":my_name,"roster_id":my_rid},"power_rankings":[{"rank":i+1,"team":x["team"],"roster_id":x["rid"],"score":round(x["score"],1),"grade":grade(x["score"])} for i,x in enumerate(power)],"teams":[]}
    for r in rosters:snapshot["teams"].append({"name":roster_names[r["roster_id"]],"roster_id":r["roster_id"],"players":roster_rows(r,players,pick_map)})
    raw=json.dumps(snapshot,indent=2,ensure_ascii=False); st.download_button("Download league snapshot",raw,file_name=f"sleeper_{league_id}_snapshot.json",mime="application/json",use_container_width=True); st.code('Upload the JSON to ChatGPT and say:\n"Analyse this league from scratch. Rank the teams, scout my opponent, find trade targets and waiver adds, and cross-reference current injuries, depth charts and expert rankings online. Challenge my assumptions rather than agreeing with me."',language="text")
