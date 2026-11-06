
import streamlit as st
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import Counter

st.set_page_config(
    page_title="Kairos Odds Scanner",
    page_icon="⚽",
    layout="wide"
)

st.title("⚽ KAIROS ODDS SCANNER")
st.caption("Soccer | Over/Under buts | Pré-match")

target = st.number_input(
    "Cote exacte recherchée",
    min_value=1.01,
    value=1.44,
    step=0.01,
    format="%.2f"
)

MARKETS = (
    "goals over/under",
    "goal line",
    "total goals",
    "total buts",
    "over/under"
)

if st.button("🔎 SCANNER", use_container_width=True):

    with st.spinner("Analyse des cotes en cours..."):

        try:
            url = "https://moviodds.com/odds?sport=soccer"

            response = requests.get(
                url,
                timeout=45,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json"
                }
            )

            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                st.error("Format API inattendu.")
                st.stop()

            matches = data.get("matches", [])

            if not isinstance(matches, list):
                st.error("Liste des matchs invalide.")
                st.stop()

            now = datetime.now(
                ZoneInfo("America/Toronto")
            )

            results = []
            future_count = 0
            quote_count = 0

            phases = Counter()
            markets = Counter()

            example = None
            exact_examples = []

            for match in matches:

                if not isinstance(match, dict):
                    continue

                kickoff = match.get("kickoff_utc")

                if not kickoff:
                    continue

                try:
                    start = datetime.fromisoformat(
                        str(kickoff).replace(
                            "Z", "+00:00"
                        )
                    ).astimezone(
                        ZoneInfo("America/Toronto")
                    )
                except (ValueError, TypeError):
                    continue

                if start.date() != now.date():
                    continue

                if start <= now:
                    continue

                if match.get("in_play") is True:
                    continue

                future_count += 1

                quotes = match.get("quotes", [])

                if not isinstance(quotes, list):
                    continue

                for quote in quotes:

                    if not isinstance(quote, dict):
                        continue

                    quote_count += 1

                    phase = str(
                        quote.get("phase") or "absent"
                    ).lower()

                    market = str(
                        quote.get("group_name") or ""
                    )

                    phases[phase] += 1
                    markets[market] += 1

                    name = market.lower()

                    goal_market = any(
                        keyword in name
                        for keyword in MARKETS
                    )

                    if not goal_market:
                        continue

                    if example is None:
                        example = {
                            "match": (
                                f"{match.get('home', '?')} vs "
                                f"{match.get('away', '?')}"
                            ),
                            "kickoff": kickoff,
                            "quote": quote
                        }

                    # Exclure les phases en direct
                    if phase in (
                        "inplay",
                        "in_play",
                        "live"
                    ):
                        continue

                    # Accepter les phases connues
                    # et les phases absentes,
                    # sans garantir le statut pré-match.
                    if phase not in (
                        "prematch",
                        "pre_match",
                        "pre-match",
                        "pre",
                        "absent"
                    ):
                        continue

                    odd = quote.get("odds_dec")

                    try:
                        odd = float(odd)
                    except (ValueError, TypeError):
                        continue

                    if round(odd, 2) != round(target, 2):
                        continue

                    item = {
                        "Match": (
                            f"{match.get('home', '?')} vs "
                            f"{match.get('away', '?')}"
                        ),
                        "Ligue": match.get("league", ""),
                        "Heure": start.strftime("%H:%M"),
                        "Marché": market,
                        "Sélection": quote.get("label", ""),
                        "Cote": odd,
                        "Phase": phase
                    }

                    results.append(item)

                    if len(exact_examples) < 3:
                        exact_examples.append({
                            "match": item["Match"],
                            "quote": quote
                        })

            st.success("Analyse terminée !")

            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric(
                    "Matchs futurs",
                    future_count
                )

            with col2:
                st.metric(
                    "Cotes examinées",
                    quote_count
                )

            with col3:
                st.metric(
                    "Cotes trouvées",
                    len(results)
                )

            if results:
                st.dataframe(
                    results,
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.warning(
                    "Aucune cote correspondante trouvée."
                )

            st.divider()

            st.subheader("🔍 EXEMPLE DE COTE RÉELLE")

            if example:
                st.json(example)
            else:
                st.warning(
                    "Aucun exemple de marché "
                    "Over/Under trouvé."
                )

            st.subheader("🎯 EXEMPLES DE COTES EXACTES")

            if exact_examples:
                st.json(exact_examples)
            else:
                st.info(
                    "Aucun exemple exact avec "
                    "le champ odds_dec."
                )

            st.divider()

            st.subheader("🔧 DIAGNOSTIC API")

            st.write(
                "Nombre total de matchs :",
                len(matches)
            )

            st.write(
                "Matchs futurs analysés :",
                future_count
            )

            st.write(
                "Cotes examinées :",
                quote_count
            )

            with st.expander("PHASES DES COTES"):
                st.json(dict(phases))

            with st.expander("MARCHÉS DISPONIBLES"):
                st.json(dict(markets))

            st.caption(
                "Source : MoviOdds. "
                "Les phases absentes ne permettent pas "
                "de confirmer le statut pré-match. "
                "La provenance Bet365 n'est pas vérifiée."
            )

        except requests.RequestException as e:
            st.error(
                f"Erreur de connexion API : {e}"
            )

        except (ValueError, TypeError) as e:
            st.error(
                f"Erreur de lecture des données : {e}"
            )
