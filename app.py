
import streamlit as st
import requests
import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

API_URL = "https://moviodds.com/odds?sport=soccer"
TZ = ZoneInfo("America/Toronto")

ALLOWED_MARKETS = {
    "goals over/under",
    "alternative total goals",
    "goal line",
    "alternative goal line",
    "total goals",
    "alternative match goals",
}

LIVE_PHASES = {
    "inplay", "in_play", "in-play", "live"
}

st.set_page_config(
    page_title="KAIROS Odds Scanner",
    page_icon="⚽",
    layout="wide"
)

st.title("⚽ KAIROS ODDS SCANNER")
st.caption(
    "Soccer | Over/Under du match complet | Heures du Québec"
)


def decimal_odd(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 1:
            return None
        return number
    except (InvalidOperation, ValueError, TypeError):
        return None


def display_odd(value):
    return value.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )


def parse_kickoff(value):
    if not isinstance(value, str):
        return None

    try:
        kickoff = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        if kickoff.tzinfo is None:
            return None
        return kickoff.astimezone(TZ)
    except (ValueError, TypeError):
        return None


def selection_from_quote(quote):
    side = str(quote.get("side") or "").strip().lower()

    if side not in {"over", "under"}:
        return None

    line = quote.get("line")
    if line is None or str(line).strip() == "":
        line = quote.get("handicap")

    if line is None:
        return None

    try:
        number = Decimal(str(line))

        if not number.is_finite() or number < 0:
            return None

    except (InvalidOperation, ValueError, TypeError):
        return None

    return f"{side.title()} {number.normalize()}"


@st.cache_data(ttl=60, show_spinner=False)
def fetch_matches():
    response = requests.get(API_URL, timeout=45)
    response.raise_for_status()

    payload = response.json()

    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("matches"), list)
    ):
        raise ValueError(
            "Format de réponse inattendu de MoviOdds."
        )

    return payload["matches"]


target_text = st.text_input(
    "Cote recherchée",
    value="1.44",
    help="Exemple : 1.44 ou 1,44"
)

scan = st.button(
    "🔎 SCANNER",
    use_container_width=True,
    type="primary"
)

if scan:
    target = decimal_odd(
        target_text.strip().replace(",", ".")
    )

    if target is None:
        st.error(
            "Entre une cote décimale valide, par exemple 1.44."
        )
        st.stop()

    target = display_odd(target)

    with st.spinner("Recherche des matchs et des cotes..."):
        try:
            matches = fetch_matches()

        except (requests.RequestException, ValueError) as exc:
            st.error(
                f"Impossible de récupérer les cotes : {exc}"
            )
            st.stop()

    now = datetime.now(TZ)

    results = []
    future_count = 0
    seen = set()

    for match in matches:
        if not isinstance(match, dict):
            continue

        kickoff = parse_kickoff(
            match.get("kickoff_utc")
        )

        if kickoff is None:
            continue

        if kickoff.date() != now.date():
            continue

        if kickoff <= now:
            continue

        if match.get("in_play") is True:
            continue

        future_count += 1

        home = str(match.get("home") or "?")
        away = str(match.get("away") or "?")
        league = str(match.get("league") or "")

        quotes = match.get("quotes") or []

        if not isinstance(quotes, list):
            continue

        for quote in quotes:
            if not isinstance(quote, dict):
                continue

            phase = str(
                quote.get("phase") or ""
            ).strip().lower()

            if phase in LIVE_PHASES:
                continue

            market = str(
                quote.get("group_name") or ""
            ).strip()

            if market.lower() not in ALLOWED_MARKETS:
                continue

            selection = selection_from_quote(quote)
            odd = decimal_odd(quote.get("odds_dec"))

            if selection is None or odd is None:
                continue

            rounded_odd = display_odd(odd)

            if rounded_odd != target:
                continue

            key = (
                home,
                away,
                kickoff.isoformat(),
                market.lower(),
                selection,
                str(rounded_odd),
            )

            if key in seen:
                continue

            seen.add(key)

            results.append({
                "Match": f"{home} vs {away}",
                "Ligue": league,
                "Heure (QC)": kickoff.strftime("%H:%M"),
                "Marché": market,
                "Sélection": selection,
                "Cote": f"{rounded_odd:.2f}",
            })

    results.sort(
        key=lambda row: (
            row["Heure (QC)"],
            row["Match"],
            row["Sélection"]
        )
    )

    st.success("Analyse terminée !")

    col1, col2 = st.columns(2)

    col1.metric(
        "Matchs à venir aujourd'hui",
        future_count
    )

    col2.metric(
        "Correspondances",
        len(results)
    )

    if results:
        st.dataframe(
            results,
            use_container_width=True,
            hide_index=True
        )

        output = io.StringIO()

        writer = csv.DictWriter(
            output,
            fieldnames=list(results[0].keys())
        )

        writer.writeheader()
        writer.writerows(results)

        st.download_button(
            "📥 Exporter les résultats (CSV)",
            data="\ufeff" + output.getvalue(),
            file_name="kairos_scanner.csv",
            mime="text/csv"
        )

    else:
        st.info(
            "Aucune correspondance trouvée "
            "pour cette cote aujourd'hui."
        )

    st.caption(
        "Source : MoviOdds. Les cotes peuvent changer. "
        "La provenance Bet365 et le statut pré-match "
        "des cotes sans phase ne sont pas vérifiés. "
        "Confirme chaque sélection manuellement."
    )
