
import streamlit as st
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import Counter

st.set_page_config(
    page_title="Kairos Odds Scanner",
    page_icon="⚽"
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

if st.button("🔎 SCANNER", use_container_width=True):
    with st.spinner("Analyse des cotes en cours..."):
        try:
            url = "https://moviodds.com/odds?sport=soccer"
            response = requests.get(url, timeout=45)
            response.raise_for_status()
            data = response.json()

            now = datetime.now(
                ZoneInfo("America/Toronto")
            )

            matches = data.get("matches", [])
            phases = Counter()
            groups = Counter()
            future_phases = Counter()
            future_groups = Counter()

            results = []
            future_count = 0
            quote_count = 0

            # Diagnostic global
            for match in matches:
                for quote in match.get("quotes", []):
                    phase = str(
                        quote.get("phase", "ABSENT")
                    )
                    group = str(
                        quote.get("group_name", "ABSENT")
                    )
                    phases[phase] += 1
                    groups[group] += 1

            # Analyse des matchs futurs
            for match in matches:
                kickoff = match.get("kickoff_utc")

                if not kickoff:
                    continue

                try:
                    start = datetime.fromisoformat(
                        kickoff.replace("Z", "+00:00")
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

                for quote in match.get("quotes", []):
                    quote_count += 1

                    phase = str(
                        quote.get("phase", "ABSENT")
                    ).lower()

                    market = str(
                        quote.get("group_name", "")
                    )

                    future_phases[phase] += 1
                    future_groups[market] += 1

                    # Exclure les cotes en direct
                    if phase in (
                        "inplay",
                        "in_play",
                        "live"
                    ):
                        continue

                    # Accepter uniquement le pré-match
                    if phase not in (
                        "prematch",
                        "pre_match",
                        "pre-match",
                        "pre"
                    ):
                        continue

                    name = market.lower()

                    # Over/Under de buts uniquement
                    goal_market = (
                        "over/under" in name
                        or "total goals" in name
                        or "total buts" in name
                        or "goal line" in name
                    )

                    if not goal_market:
                        continue

                    odd = quote.get("odds_dec")

                    try:
                        if abs(
                            float(odd) - target
                        ) > 0.0001:
                            continue
                    except (ValueError, TypeError):
                        continue

                    results.append({
                        "Match": (
                            f"{match.get('home', '?')} vs "
                            f"{match.get('away', '?')}"
                        ),
                        "Ligue": match.get(
                            "league", ""
                        ),
                        "Heure": start.strftime(
                            "%H:%M"
                        ),
                        "Marché": market,
                        "Sélection": quote.get(
                            "label", ""
                        ),
                        "Cote": float(odd)
                    })

            st.success("Analyse terminée !")

            col1, col2 = st.columns(2)

            with col1:
                st.metric(
                    "Matchs futurs",
                    future_count
                )

            with col2:
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
            st.subheader("🔧 DIAGNOSTIC API")

            st.write(
                "Nombre total de matchs :",
                len(matches)
            )

            st.write(
                "Cotes examinées sur les matchs futurs :",
                quote_count
            )

            st.write("PHASES DISPONIBLES :")
            st.json(dict(phases))

            st.write("PHASES DES MATCHS FUTURS :")
            st.json(dict(future_phases))

            with st.expander(
                "MARCHÉS DISPONIBLES"
            ):
                st.json(dict(groups))

            with st.expander(
                "MARCHÉS DES MATCHS FUTURS"
            ):
                st.json(dict(future_groups))

            st.caption(
                "Source : MoviOdds. "
                "La provenance Bet365 des cotes "
                "n'est pas encore vérifiée."
            )

        except requests.RequestException as e:
            st.error(
                f"Erreur de connexion à l'API : {e}"
            )

        except (ValueError, TypeError) as e:
            st.error(
                f"Erreur de lecture des données : {e}"
            )
