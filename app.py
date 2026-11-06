
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
st.caption("Soccer | Over/Under buts | Matchs à venir")

target = st.number_input(
    "Cote exacte recherchée",
    min_value=1.01,
    value=1.44,
    step=0.01,
    format="%.2f"
)

tolerance = st.selectbox(
    "Tolérance de recherche",
    ["Exacte", "±0.01", "±0.05"],
    index=0
)

period = st.selectbox(
    "Période",
    ["Aujourd'hui", "Prochaines 24 heures", "7 prochains jours"]
)

if st.button("🔎 SCANNER", use_container_width=True):
    with st.spinner("Analyse des cotes en cours..."):
        try:
            response = requests.get(
                "https://moviodds.com/odds?sport=soccer",
                timeout=45
            )
            response.raise_for_status()
            data = response.json()

            now = datetime.now(ZoneInfo("America/Toronto"))
            matches = data.get("matches", [])

            results = []
            future_count = 0
            examined = 0
            phases = Counter()
            markets = Counter()

            margin = {
                "Exacte": 0.0001,
                "±0.01": 0.010001,
                "±0.05": 0.050001
            }[tolerance]

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
                except (ValueError, TypeError, AttributeError):
                    continue

                if start <= now:
                    continue

                if period == "Aujourd'hui":
                    if start.date() != now.date():
                        continue

                elif period == "Prochaines 24 heures":
                    if (start - now).total_seconds() > 86400:
                        continue

                elif period == "7 prochains jours":
                    if (start - now).total_seconds() > 604800:
                        continue

                if match.get("in_play") is True:
                    continue

                future_count += 1

                for quote in match.get("quotes", []):
                    examined += 1

                    phase = str(
                        quote.get("phase") or "absent"
                    ).lower().strip()

                    market = str(
                        quote.get("group_name") or ""
                    )

                    phases[phase] += 1
                    markets[market] += 1

                    # Exclure les cotes identifiees en direct
                    if phase in (
                        "inplay",
                        "in_play",
                        "in-play",
                        "live"
                    ):
                        continue

                    # Accepter les phases pre-match
                    # ainsi que les phases absentes.
                    if phase not in (
                        "prematch",
                        "pre_match",
                        "pre-match",
                        "pre",
                        "absent"
                    ):
                        continue

                    name = market.lower()

                    # Marches de total de buts
                    goal_market = any(
                        word in name
                        for word in (
                            "over/under",
                            "total goals",
                            "total buts",
                            "goal line",
                            "match goals",
                            "1st half goals",
                            "2nd half goals"
                        )
                    )

                    if not goal_market:
                        continue

                    label = str(
                        quote.get("label") or ""
                    )

                    # Garder uniquement les selections
                    # clairement Over ou Under.
                    label_lower = label.lower().strip()

                    if not (
                        label_lower.startswith("over")
                        or label_lower.startswith("under")
                        or label_lower.startswith("o ")
                        or label_lower.startswith("u ")
                    ):
                        continue

                    try:
                        odd = float(quote.get("odds_dec"))
                    except (ValueError, TypeError):
                        continue

                    if abs(odd - target) > margin:
                        continue

                    results.append({
                        "Match": (
                            f"{match.get('home', '?')} vs "
                            f"{match.get('away', '?')}"
                        ),
                        "Ligue": match.get("league", ""),
                        "Date": start.strftime("%d/%m/%Y"),
                        "Heure": start.strftime("%H:%M"),
                        "Marche": market,
                        "Selection": label,
                        "Cote": odd,
                        "Phase": phase
                    })

            st.success("Analyse terminee !")

            col1, col2, col3 = st.columns(3)

            col1.metric("Matchs futurs", future_count)
            col2.metric("Cotes examinees", examined)
            col3.metric("Cotes trouvees", len(results))

            if results:
                results.sort(
                    key=lambda x: (
                        x["Date"],
                        x["Heure"],
                        x["Match"]
                    )
                )

                st.dataframe(
                    results,
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.warning(
                    "Aucune cote correspondante trouvee."
                )

            st.divider()
            st.subheader("🔧 DIAGNOSTIC API")

            st.write("Nombre total de matchs :", len(matches))
            st.write("Matchs futurs analyses :", future_count)
            st.write("Cotes examinees :", examined)

            with st.expander("PHASES DES COTES"):
                st.json(dict(phases))

            with st.expander("MARCHES DISPONIBLES"):
                st.json(dict(markets))

            st.caption(
                "Source : MoviOdds. "
                "Les cotes sans phase sont acceptees "
                "uniquement pour les matchs futurs "
                "non signales en direct. "
                "Cela ne garantit pas leur statut pre-match. "
                "La provenance Bet365 reste non verifiee."
            )

        except requests.RequestException as e:
            st.error(f"Erreur API : {e}")

        except (ValueError, TypeError, KeyError) as e:
            st.error(f"Erreur de donnees : {e}")
