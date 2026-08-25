
# Sleeper League Portal

A lightweight Streamlit dashboard for a Sleeper fantasy football league.

## What it does

- Loads league settings and scoring
- Shows every roster and starter/bench status
- Gives a league-wide positional depth matrix
- Shows trending Sleeper adds
- Lets you browse free agents
- Shows draft history
- Shows weekly matchups
- Exports a compact **ChatGPT Snapshot** JSON containing the entire league

The default league ID is already set to:

`1389344022107021312`

You can replace it in the sidebar at any time.

## Run locally

1. Install Python 3.10+
2. Open Terminal in this folder
3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Start the app:

```bash
streamlit run app.py
```

Your browser should open automatically.

## Deploy free with Streamlit Community Cloud

1. Create a GitHub repository and upload:
   - `app.py`
   - `requirements.txt`
2. Go to Streamlit Community Cloud.
3. Connect the GitHub repo.
4. Choose `app.py` as the entry point.
5. Deploy.

No Sleeper API key is needed. Sleeper's league API is public and read-only.

## Best workflow with ChatGPT

Open the **ChatGPT Snapshot** tab, click **Download ChatGPT snapshot**, then upload the JSON file to ChatGPT with a prompt such as:

> Analyse this Sleeper league from scratch. Rank every roster, identify my strongest rivals, positional strengths/weaknesses, waiver and trade opportunities, and be critical rather than agreeing with me. Cross-reference current injuries, ADP and expert rankings online.

That gives ChatGPT all roster data without needing screenshots.

## Notes

- Player metadata is cached for one hour.
- League data refreshes every five minutes.
- The portal deliberately does **not** create a fake numerical "power rating" without projection data.
- For genuinely useful power rankings, export the snapshot and let ChatGPT combine the live rosters with current public projections, injuries, depth charts and ADP.
