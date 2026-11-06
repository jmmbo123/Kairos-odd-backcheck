
import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import requests
import streamlit as st

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

LIVE_PHASES = {"inplay", "in_play", "in-play", "live"}
PAGE_SIZE = 15
CENT = Decimal("0.01")

st.set_page_config(
    page_title="KAIROS Odds Scanner 2.0",
    page_icon="⚽",
    layout="wide"
)

st.title("⚽ KAIROS ODDS SCANNER 2.0")
st.caption("Soccer | Over/Under du match complet | Heure du Québec")


def decimal_odd(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and number > 1 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def rounded_odd(number):
    return number.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_kickoff(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        return result.astimezone(TZ) if result.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def selection_from_quote(quote):
    side = str(quote.get("side") or "").strip().lower()
    if side not in {"over", "under"}:
        return None

    line = quote.get("line")
    if line is None or str(line).strip() == "":
        line = quote.get("handicap")

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

    if not isinstance(payload, dict) or not isinstance(
        payload.get("matches"), list
    ):
        raise ValueError("Format de réponse inattendu de MoviOdds.")

    return payload["matches"]


def scan_matches(matches, target, tolerance, days):
    now = datetime.now(TZ)
    accepted_dates = {
        now.date() + timedelta(days=i) for i in days
    }

    results = []
    seen = set()
    future_count = 0
    eligible_quotes = 0

    for match in matches:
        if not isinstance(match, dict):
            continue

        kickoff = parse_kickoff(match.get("kickoff_utc"))

        if (
            kickoff is None
            or kickoff <= now
            or kickoff.date() not in accepted_dates
        ):
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

            eligible_quotes += 1
            shown = rounded_odd(odd)

            if abs(shown - target) > tolerance:
                continue

            key = (
                home,
                away,
                kickoff.isoformat(),
                market.lower(),
                selection,
                str(shown)
            )

            if key in seen:
                continue

            seen.add(key)

            results.append({
                "Match": f"{home} vs {away}",
                "Ligue": league,
                "Date": kickoff.strftime("%d/%m/%Y"),
                "Heure (QC)": kickoff.strftime("%H:%M"),
                "Marché": market,
                "Sélection": selection,
                "Cote": f"{shown:.2f}",
                "Correspondance": (
                    "Exacte" if shown == target else "Proche"
                ),
                "Écart": f"{shown - target:+.2f}",
            })

    results.sort(
        key=lambda r: (
            datetime.strptime(r["Date"], "%d/%m/%Y"),
            r["Heure (QC)"],
            r["Match"],
            r["Sélection"]
        )
    )

    return results, future_count, eligible_quotes


with st.form("scanner_form"):
    target_text = st.text_input(
        "Cote recherchée",
        value="1.66",
        help="Exemple : 1.66 ou 1,66"
    )

    mode = st.radio(
        "Type de recherche",
        ["Exacte", "Approximative (±0.01)"],
        horizontal=True
    )

    period = st.selectbox(
        "Matchs à rechercher",
        [
            "Aujourd'hui",
            "Demain",
            "Aujourd'hui et demain"
        ]
    )

    scan = st.form_submit_button(
        "🔎 SCANNER",
        type="primary",
        use_container_width=True
    )


if scan:
    target = decimal_odd(
        target_text.strip().replace(",", ".")
    )

    if target is None:
        st.error(
            "Entre une cote décimale valide, par exemple 1.66."
        )
    else:
        target = rounded_odd(target)

        tolerance = (
            CENT
            if mode.startswith("Approximative")
            else Decimal("0.00")
        )

        if period == "Aujourd'hui et demain":
            days = [0, 1]
        elif period == "Demain":
            days = [1]
        else:
            days = [0]

        with st.spinner("Analyse des cotes en cours..."):
            try:
                matches = fetch_matches()

                results, future_count, eligible_quotes = (
                    scan_matches(
                        matches,
                        target,
                        tolerance,
                        days
                    )
                )

                st.session_state["kairos_scan"] = {
                    "results": results,
                    "future_count": future_count,
                    "eligible_quotes": eligible_quotes,
                    "target": f"{target:.2f}",
                    "mode": mode,
                    "period": period,
                    "timestamp": datetime.now(TZ).strftime(
                        "%d/%m/%Y %H:%M"
                    ),
                }

                st.session_state["kairos_page"] = 1

            except (requests.RequestException, ValueError) as exc:
                st.error(
                    f"Impossible de récupérer les cotes : {exc}"
                )


if "kairos_scan" in st.session_state:
    scan_data = st.session_state["kairos_scan"]
    results = scan_data["results"]

    st.success("Analyse terminée !")

    c1, c2 = st.columns(2)

    c1.metric(
        "Matchs à venir",
        scan_data["future_count"]
    )

    c2.metric(
        "Correspondances",
        len(results)
    )

    st.caption(
        f"Recherche {scan_data['mode'].lower()} | "
        f"{scan_data['target']} | "
        f"{scan_data['period']} | "
        f"{scan_data['timestamp']} (QC)"
    )

    if results:
        total_pages = (
            len(results) + PAGE_SIZE - 1
        ) // PAGE_SIZE

        page = st.selectbox(
            "Page de résultats",
            range(1, total_pages + 1),
            key="kairos_page",
            format_func=lambda p: (
                f"Page {p} / {total_pages}"
            )
        )

        start = (page - 1) * PAGE_SIZE

        st.caption(
            f"Résultats {start + 1} à "
            f"{min(start + PAGE_SIZE, len(results))} "
            f"sur {len(results)}"
        )

        for row in results[start:start + PAGE_SIZE]:
            with st.container(border=True):
                st.markdown(f"**{row['Match']}**")

                st.caption(
                    f"🏆 {row['Ligue']} | "
                    f"🗓️ {row['Date']} | "
                    f"🕒 {row['Heure (QC)']} (Québec)"
                )

                left, right = st.columns([3, 1])

                with left:
                    st.markdown(
                        f"**{row['Sélection']}**"
                    )

                    st.caption(row["Marché"])

                    if row["Correspondance"] == "Exacte":
                        st.caption("🎯 Cote exacte")
                    else:
                        st.caption(
                            "🔎 Cote proche "
                            f"({row['Écart']} par rapport "
                            "à la recherche)"
                        )

                with right:
                    st.metric("Cote", row["Cote"])

        output = io.StringIO()

        writer = csv.DictWriter(
            output,
            fieldnames=list(results[0].keys())
        )

        writer.writeheader()
        writer.writerows(results)

        st.download_button(
            "📥 Exporter tous les résultats (CSV)",
            data="\ufeff" + output.getvalue(),
            file_name="kairos_scanner.csv",
            mime="text/csv",
            use_container_width=True
        )

    else:
        st.info(
            "Aucune cote correspondante "
            "dans la période choisie."
        )

    st.caption(
        "Cotes Over/Under valides examinées : "
        f"{scan_data['eligible_quotes']}"
    )


st.caption(
    "Source : MoviOdds. Les cotes et horaires peuvent "
    "différer de Bet365. La provenance Bet365 et le "
    "statut pré-match des cotes sans phase ne sont "
    "pas vérifiés. Vérifie toujours le match, "
    "la sélection, l'heure et la cote sur Bet365."
)
