# Sleeper GM V5

V5 upgrades the analysis engine.

## Added
- Power Rankings V2
- Team need and surplus model
- Trade target finder
- Trade partner fit finder
- Roster-adjusted trade analyser
- Waiver Engine V2
- Add/drop suggestions
- Matchup positional edge table
- Optional FantasyPros integration for:
  - consensus rankings
  - weekly projections
  - roster-relevant player news

## Optional FantasyPros API key

In Streamlit Community Cloud, open app settings -> Secrets and add:

```toml
FANTASYPROS_API_KEY = "your_key_here"
```

Without the key, the app still works using Sleeper data + your league's actual draft market.

## Files
- app.py
- requirements.txt
- .streamlit/config.toml
