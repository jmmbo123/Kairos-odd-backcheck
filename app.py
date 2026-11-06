
import streamlit as st
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

st.set_page_config(page_title="Kairos Odds Scanner", page_icon="⚽")

st.title("⚽ KAIROS ODDS SCANNER")
st.caption("Scanner de cotes soccer - Pre-match uniquement")

target = st.number_input(
    "Cote exacte recherchee",
    min_value=1.01,
    value=1.44,
    step=0.01,
    format="%.2f"
)

if st.button("🔎 SCANNER", use_container_width=True):
    with st.spinner("Recherche des cotes..."):
        try:
            url = "https://moviodds.com/odds?sport=soccer"
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            now = datetime.now(ZoneInfo("America/Toronto"))
            results = []
            prematch_count = 0
            markets_found = set()

            for match in data.get("matches", []):
                kickoff = match.get("kickoff_utc")
                if not kickoff:
                    continue

                try:
                    start = datetime.fromisoformat(
                        kickoff.replace("Z", "+00:00")
                    ).astimezone(ZoneInfo("America/Toronto"))
                except ValueError:
                    continue

                if start.date() != now.date() or start <= now:
                    continue

                if match.get("in_play") is True:
                    continue

                prematch_count += 1

                for quote in match.get("quotes", []):
                    if quote.get("phase") != "prematch":
                        continue

                    market = str(quote.get("group_name", ""))
                    markets_found.add(market)

                    name = market.lower()

                    # Uniquement les marches de buts Over/Under
                    if not (
                        "over/under" in name
                        or "total goals" in name
                        or "total buts" in name
                    ):
                        continue

                    odd = quote.get("odds_dec")
                    try:
                        if abs(float(odd) - target) > 0.0001:
                            continue
                    except (ValueError, TypeError):
                        continue

                    results.append({
                        "Match": (
                            f"{match.get('home', '?')} vs "
                            f"{match.get('away', '?')}"
                        ),
                        "Ligue": match.get("league", ""),
                        "Heure": start.strftime("%H:%M"),
                        "Marche": market,
                        "Selection": quote.get("label", ""),
                        "Cote": odd
                    })

            st.info(f"Matchs futurs analyses : {prematch_count}")

            if results:
                st.success(f"{len(results)} cote(s) trouvee(s) !")
                st.dataframe(results, use_container_width=True)
            else:
                st.warning("Aucune cote correspondante trouvee.")

            with st.expander("Diagnostic des marches disponibles"):
                st.write(sorted(markets_found)[:100])
                st.caption(
                    "Ce test ne confirme pas encore que les "
                    "cotes proviennent de Bet365."
                )

        except Exception as e:
