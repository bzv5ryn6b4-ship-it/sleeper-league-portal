# Sleeper GM — Fantasy Football League Portal

A sleek, live Streamlit dashboard for a Sleeper fantasy football league.

## Features
- Home GM dashboard
- League power rankings
- My Team roster/depth analysis
- Trade target finder
- Multi-player trade analyser
- Waiver/free-agent board
- Add/drop helper
- Opponent scouting
- Lineup value optimizer
- League-specific transaction feed
- Injury/status watch
- All-roster browser
- ChatGPT league snapshot export

## Data model
The app uses Sleeper's public read-only API. The current power/trade/waiver model is intentionally transparent and uses your league's actual draft capital, Sleeper player search rank, roster depth, positional scarcity, age and injury status.

It does **not** pretend those are weekly fantasy projections. A future upgrade can plug in a true projection feed for start/sit decisions.

## Deploy
Upload the full contents of this folder to your GitHub repository and set Streamlit's main file path to `app.py`.
