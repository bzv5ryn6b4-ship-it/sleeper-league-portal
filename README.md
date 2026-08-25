# Sleeper GM V5.1 — Trade Suggestions + Waiver Calibration

## Added
- Suggested Trades tab
- 1-for-1, 2-for-1 and 1-for-2 auto-generated deals
- fairness threshold
- simulated roster improvement for both teams
- trade-fit explanation

## Recalibrated
- Sleeper search rank is now only a weak supporting signal
- draft capital is blended rather than allowed to dominate
- depth-chart penalties for deep reserves
- trending add/drop activity is capped
- waiver add/drop suggestions compare base player value to bench value, not heat-inflated scores
- nonsense cross-position TE suggestions are blocked

Sleeper player metadata is cached for 24 hours.


## V5.2 waiver hotfix
- Requires `active == True` for waiver/free-agent candidates.
- Requires a current NFL team.
- Excludes retired/inactive historical records.
- Prevents stale Sleeper records such as Todd Gurley appearing as waiver recommendations.


## V6.0 — Trade Intelligence
- Trade suggestions now require both teams to improve.
- Adds a consolidation/stud premium for 2-for-1 and 1-for-2 deals.
- Adds a conservative acceptance-probability estimate.
- Separates FantasyPros ECR (expert value) from ADP (market price).
- Flags ECR/ADP market disagreement instead of hiding it in one average.
- Automatically maps Sleeper reception scoring to STD/HALF/PPR for FantasyPros.
- Keeps the existing Sleeper + league-draft model as a fallback when no FantasyPros key is configured.

### Enable FantasyPros
1. Obtain a FantasyPros API key.
2. In Streamlit Community Cloud open **Manage app → Settings → Secrets**.
3. Add:
   `FANTASYPROS_API_KEY = "your-key"`
4. Save and reboot the app.

Do not commit your real API key to GitHub.
