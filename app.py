
import json
from datetime import datetime
from collections import Counter, defaultdict

import pandas as pd
import requests
import streamlit as st

LEAGUE_ID_DEFAULT = "1389344022107021312"
BASE = "https://api.sleeper.app/v1"

st.set_page_config(
    page_title="Sleeper League Portal",
    page_icon="🏈",
    layout="wide",
)

# ---------- Helpers ----------

@st.cache_data(ttl=300, show_spinner=False)
def api_get(path):
    url = f"{BASE}{path}"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=3600, show_spinner=False)
def get_players():
    # Sleeper recommends not hitting this constantly; cache it hard.
    return api_get("/players/nfl")

def safe_name(player_id, players):
    p = players.get(str(player_id), {})
    full = p.get("full_name")
    if full:
        return full
    first = p.get("first_name") or ""
    last = p.get("last_name") or ""
    name = (first + " " + last).strip()
    return name or str(player_id)

def player_meta(player_id, players):
    p = players.get(str(player_id), {})
    return {
        "player_id": str(player_id),
        "name": safe_name(player_id, players),
        "position": p.get("position"),
        "team": p.get("team"),
        "status": p.get("status"),
        "injury_status": p.get("injury_status"),
        "years_exp": p.get("years_exp"),
        "age": p.get("age"),
    }

def display_name_for_user(user):
    md = user.get("metadata") or {}
    return (
        md.get("team_name")
        or user.get("display_name")
        or user.get("username")
        or f"User {user.get('user_id','')}"
    )

def roster_to_rows(roster, players, owner_name):
    starters = set(str(x) for x in (roster.get("starters") or []))
    rows = []
    for pid in roster.get("players") or []:
        row = player_meta(pid, players)
        row["owner"] = owner_name
        row["starter"] = "Yes" if str(pid) in starters else "No"
        rows.append(row)
    return rows

def league_snapshot(league, users, rosters, players, drafts=None, trending=None):
    user_map = {str(u.get("user_id")): u for u in users}
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "league": {
            "league_id": league.get("league_id"),
            "name": league.get("name"),
            "season": league.get("season"),
            "status": league.get("status"),
            "total_rosters": league.get("total_rosters"),
            "settings": league.get("settings"),
            "scoring_settings": league.get("scoring_settings"),
            "roster_positions": league.get("roster_positions"),
        },
        "teams": [],
    }

    for r in rosters:
        owner_id = str(r.get("owner_id")) if r.get("owner_id") else None
        user = user_map.get(owner_id, {})
        owner_name = display_name_for_user(user) if user else f"Roster {r.get('roster_id')}"
        team = {
            "roster_id": r.get("roster_id"),
            "owner_id": owner_id,
            "owner_name": owner_name,
            "wins": (r.get("settings") or {}).get("wins"),
            "losses": (r.get("settings") or {}).get("losses"),
            "ties": (r.get("settings") or {}).get("ties"),
            "fpts": (r.get("settings") or {}).get("fpts"),
            "fpts_decimal": (r.get("settings") or {}).get("fpts_decimal"),
            "starters": [player_meta(x, players) for x in (r.get("starters") or []) if x != "0"],
            "players": [player_meta(x, players) for x in (r.get("players") or [])],
            "reserve": [player_meta(x, players) for x in (r.get("reserve") or [])],
            "taxi": [player_meta(x, players) for x in (r.get("taxi") or [])],
        }
        out["teams"].append(team)

    if drafts is not None:
        out["drafts"] = drafts
    if trending is not None:
        out["trending_adds"] = trending[:25]
    return out

def positional_counts(roster, players):
    c = Counter()
    for pid in roster.get("players") or []:
        pos = players.get(str(pid), {}).get("position")
        if pos:
            c[pos] += 1
    return c

# ---------- Sidebar / Load ----------

st.title("🏈 Sleeper League Portal")
st.caption("Live league dashboard powered by Sleeper's public read-only API.")

league_id = st.sidebar.text_input("Sleeper League ID", value=LEAGUE_ID_DEFAULT).strip()

if not league_id:
    st.info("Enter a Sleeper league ID in the sidebar.")
    st.stop()

try:
    with st.spinner("Loading league…"):
        league = api_get(f"/league/{league_id}")
        users = api_get(f"/league/{league_id}/users")
        rosters = api_get(f"/league/{league_id}/rosters")
        players = get_players()
except Exception as e:
    st.error(f"Could not load the league: {e}")
    st.stop()

user_map = {str(u.get("user_id")): u for u in users}
roster_owner_names = {}
for r in rosters:
    oid = str(r.get("owner_id")) if r.get("owner_id") else None
    roster_owner_names[r.get("roster_id")] = (
        display_name_for_user(user_map.get(oid, {}))
        if oid and oid in user_map
        else f"Roster {r.get('roster_id')}"
    )

team_options = {
    roster_owner_names[r.get("roster_id")]: r.get("roster_id")
    for r in rosters
}
my_team_name = st.sidebar.selectbox(
    "My team",
    list(team_options.keys()),
    index=0 if team_options else None
)
my_roster_id = team_options.get(my_team_name)

st.sidebar.markdown("---")
st.sidebar.caption("Data refresh: league 5 min • players 1 hr")

# ---------- Tabs ----------

tabs = st.tabs([
    "Overview",
    "Rosters",
    "My Team",
    "League Matrix",
    "Trending / Waivers",
    "Draft",
    "Matchups",
    "ChatGPT Snapshot",
])

# Overview
with tabs[0]:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("League", league.get("name") or "—")
    c2.metric("Season", league.get("season") or "—")
    c3.metric("Teams", league.get("total_rosters") or len(rosters))
    c4.metric("Status", league.get("status") or "—")

    st.subheader("Roster format")
    rp = league.get("roster_positions") or []
    st.write(" • ".join(rp) if rp else "No roster positions returned.")

    st.subheader("Scoring settings")
    scoring = league.get("scoring_settings") or {}
    if scoring:
        score_df = pd.DataFrame(
            sorted(scoring.items(), key=lambda kv: kv[0]),
            columns=["Setting", "Points"]
        )
        st.dataframe(score_df, use_container_width=True, hide_index=True)

    st.subheader("Standings")
    standings = []
    for r in rosters:
        s = r.get("settings") or {}
        standings.append({
            "Team": roster_owner_names.get(r.get("roster_id")),
            "W": s.get("wins", 0),
            "L": s.get("losses", 0),
            "T": s.get("ties", 0),
            "PF": (s.get("fpts", 0) or 0) + ((s.get("fpts_decimal", 0) or 0) / 100),
        })
    st.dataframe(
        pd.DataFrame(standings).sort_values(["W", "PF"], ascending=[False, False]),
        use_container_width=True,
        hide_index=True
    )

# Rosters
with tabs[1]:
    st.subheader("All rosters")
    selected_team = st.selectbox(
        "Team",
        list(team_options.keys()),
        key="roster_team_select"
    )
    rid = team_options[selected_team]
    roster = next(r for r in rosters if r.get("roster_id") == rid)
    rows = roster_to_rows(roster, players, selected_team)
    if rows:
        df = pd.DataFrame(rows)
        order = {"QB":0,"RB":1,"WR":2,"TE":3,"K":4,"DEF":5}
        df["_ord"] = df["position"].map(order).fillna(99)
        df = df.sort_values(["starter", "_ord", "name"], ascending=[False, True, True]).drop(columns="_ord")
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No players found for this roster.")

# My Team
with tabs[2]:
    st.subheader(my_team_name)
    my_roster = next(r for r in rosters if r.get("roster_id") == my_roster_id)
    counts = positional_counts(my_roster, players)
    cols = st.columns(6)
    for i, pos in enumerate(["QB","RB","WR","TE","K","DEF"]):
        cols[i].metric(pos, counts.get(pos, 0))

    my_rows = roster_to_rows(my_roster, players, my_team_name)
    my_df = pd.DataFrame(my_rows)
    if not my_df.empty:
        st.dataframe(my_df, use_container_width=True, hide_index=True)

    st.info(
        "This portal intentionally does not invent a proprietary 'power score' without projection data. "
        "Use the ChatGPT Snapshot export below for a deeper qualitative ranking using live news, ADP and expert rankings."
    )

# League Matrix
with tabs[3]:
    st.subheader("Positional depth matrix")
    matrix = []
    for r in rosters:
        counts = positional_counts(r, players)
        matrix.append({
            "Team": roster_owner_names.get(r.get("roster_id")),
            "QB": counts.get("QB", 0),
            "RB": counts.get("RB", 0),
            "WR": counts.get("WR", 0),
            "TE": counts.get("TE", 0),
            "K": counts.get("K", 0),
            "DEF": counts.get("DEF", 0),
            "Total": sum(counts.values()),
        })
    st.dataframe(pd.DataFrame(matrix), use_container_width=True, hide_index=True)

    st.subheader("Player ownership map")
    all_rows = []
    for r in rosters:
        owner = roster_owner_names.get(r.get("roster_id"))
        all_rows.extend(roster_to_rows(r, players, owner))
    own_df = pd.DataFrame(all_rows)
    if not own_df.empty:
        pos_filter = st.multiselect(
            "Positions",
            ["QB","RB","WR","TE","K","DEF"],
            default=["QB","RB","WR","TE"]
        )
        shown = own_df[own_df["position"].isin(pos_filter)] if pos_filter else own_df
        st.dataframe(shown[["name","position","team","owner","starter","injury_status"]],
                     use_container_width=True, hide_index=True)

# Trending / Waivers
with tabs[4]:
    st.subheader("Trending adds")
    try:
        trending = api_get("/players/nfl/trending/add?lookback_hours=24&limit=50")
    except Exception:
        trending = []
    rostered_ids = {str(pid) for r in rosters for pid in (r.get("players") or [])}
    tr_rows = []
    for item in trending:
        pid = str(item.get("player_id"))
        meta = player_meta(pid, players)
        meta["adds_24h"] = item.get("count")
        meta["rostered_in_this_league"] = "Yes" if pid in rostered_ids else "No"
        tr_rows.append(meta)
    if tr_rows:
        st.dataframe(pd.DataFrame(tr_rows), use_container_width=True, hide_index=True)

    st.subheader("Free-agent finder")
    position = st.selectbox("Position", ["RB","WR","TE","QB","K","DEF"], index=0)
    search = st.text_input("Search player name", "")
    fa = []
    for pid, p in players.items():
        if str(pid) in rostered_ids:
            continue
        if p.get("position") != position:
            continue
        if p.get("active") is False:
            continue
        name = p.get("full_name") or f"{p.get('first_name','')} {p.get('last_name','')}".strip()
        if search and search.lower() not in name.lower():
            continue
        fa.append({
            "name": name,
            "team": p.get("team"),
            "position": p.get("position"),
            "status": p.get("status"),
            "injury_status": p.get("injury_status"),
            "years_exp": p.get("years_exp"),
            "age": p.get("age"),
            "player_id": pid,
        })
    fa_df = pd.DataFrame(fa)
    if not fa_df.empty:
        st.dataframe(fa_df.sort_values(["team","name"]), use_container_width=True, hide_index=True)
    else:
        st.info("No matching free agents.")

# Draft
with tabs[5]:
    st.subheader("Draft history")
    try:
        drafts = api_get(f"/league/{league_id}/drafts")
    except Exception:
        drafts = []
    if not drafts:
        st.info("No draft returned for this league.")
    else:
        draft_labels = {
            f"{d.get('season','')} • {d.get('type','draft')} • {d.get('draft_id')}": d.get("draft_id")
            for d in drafts
        }
        label = st.selectbox("Draft", list(draft_labels.keys()))
        draft_id = draft_labels[label]
        try:
            picks = api_get(f"/draft/{draft_id}/picks")
        except Exception as e:
            st.warning(f"Could not load picks: {e}")
            picks = []
        pick_rows = []
        for p in picks:
            pid = str(p.get("player_id"))
            md = p.get("metadata") or {}
            pick_rows.append({
                "overall": p.get("pick_no"),
                "round": p.get("round"),
                "pick_in_round": p.get("draft_slot"),
                "player": md.get("first_name","") + " " + md.get("last_name",""),
                "position": md.get("position"),
                "team": md.get("team"),
                "roster_id": p.get("roster_id"),
                "manager": roster_owner_names.get(p.get("roster_id"), f"Roster {p.get('roster_id')}"),
            })
        if pick_rows:
            st.dataframe(pd.DataFrame(pick_rows), use_container_width=True, hide_index=True)

# Matchups
with tabs[6]:
    st.subheader("Weekly matchups")
    week = st.number_input("Week", min_value=1, max_value=18, value=1, step=1)
    try:
        matchups = api_get(f"/league/{league_id}/matchups/{int(week)}")
    except Exception as e:
        st.warning(f"Could not load matchups: {e}")
        matchups = []
    if matchups:
        rows = []
        for m in matchups:
            rows.append({
                "matchup_id": m.get("matchup_id"),
                "team": roster_owner_names.get(m.get("roster_id"), f"Roster {m.get('roster_id')}"),
                "points": m.get("points"),
                "roster_id": m.get("roster_id"),
            })
        md = pd.DataFrame(rows).sort_values(["matchup_id","team"])
        st.dataframe(md, use_container_width=True, hide_index=True)
    else:
        st.info("No matchup data returned yet.")

# Snapshot
with tabs[7]:
    st.subheader("ChatGPT Snapshot")
    st.write(
        "Exports the league settings, every roster, starters, injury labels and trending adds "
        "into one compact JSON file. Upload that file to ChatGPT and ask for a league-wide audit."
    )
    try:
        drafts_for_export = api_get(f"/league/{league_id}/drafts")
    except Exception:
        drafts_for_export = []
    try:
        trending_for_export = api_get("/players/nfl/trending/add?lookback_hours=24&limit=50")
    except Exception:
        trending_for_export = []

    snapshot = league_snapshot(
        league, users, rosters, players,
        drafts=drafts_for_export,
        trending=trending_for_export
    )
    snapshot_json = json.dumps(snapshot, indent=2, ensure_ascii=False)
    st.download_button(
        "⬇️ Download ChatGPT snapshot",
        snapshot_json,
        file_name=f"sleeper_{league_id}_snapshot.json",
        mime="application/json",
    )

    st.code(
        "Suggested prompt:\n"
        "Analyse this Sleeper league from scratch. Rank every roster, identify my strongest rivals, "
        "positional strengths/weaknesses, waiver and trade opportunities, and be critical rather than agreeing with me. "
        "Cross-reference current injuries, ADP and expert rankings online.",
        language="text"
    )
