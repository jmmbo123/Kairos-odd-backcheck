
import csv
import io
from datetime import datetime
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
        return number if number.is_finite() and number > 1 else None
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
        result = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        return result.astimezone(TZ) if result.tzinfo else None
    except (ValueError, TypeError):
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
        raise ValueError(
            "Format de réponse inattendu de MoviOdds."
        )

    return payload["matches"]


def scan_matches(matches, target):
    now = datetime.now(TZ)
    results = []
    future_count = 0
    seen = set()

    for match in matches:
        if not isinstance(match, dict):
            continue

        kickoff = parse_kickoff(match.get("kickoff_utc"))

        if (
            kickoff is None
            or kickoff.date() != now.date()
            or kickoff <= now
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

            if (
                selection is None
                or odd is None
                or display_odd(odd) != target
            ):
                continue

            key = (
                home,
                away,
                kickoff.isoformat(),
                market.lower(),
                selection,
                str(target)
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
                "Cote": f"{display_odd(odd):.2f}",
            })

    results.sort(
        key=lambda r: (
            r["Heure (QC)"],
            r["Match"],
            r["Sélection"]
        )
    )

    return results, future_count


target_text = st.text_input(
    "Cote recherchée",
    value="1.44",
    help="Exemple : 1.44 ou 1,44"
)

if st.button(
    "🔎 SCANNER",
    use_container_width=True,
    type="primary"
):
    target = decimal_odd(
        target_text.strip().replace(",", ".")
    )

    if target is None:
        st.error(
            "Entre une cote décimale valide, par exemple 1.44."
        )
    else:
        with st.spinner("Recherche des matchs et des cotes..."):
            try:
                matches = fetch_matches()
                results, future_count = scan_matches(
                    matches, display_odd(target)
                )

                st.session_state["scan_results"] = results
                st.session_state["future_count"] = future_count
                st.session_state["scanned_odd"] = (
                    f"{display_odd(target):.2f}"
                )
                st.session_state["scan_date"] = (
                    datetime.now(TZ).date().isoformat()
                )
                st.session_state["result_page"] = 1

            except (requests.RequestException, ValueError) as exc:
                st.error(
                    f"Impossible de récupérer les cotes : {exc}"
                )


if "scan_results" in st.session_state:
    results = st.session_state["scan_results"]

    st.success("Analyse terminée !")

    col1, col2 = st.columns(2)

    col1.metric(
        "Matchs à venir aujourd'hui",
        st.session_state["future_count"]
    )

    col2.metric(
        "Correspondances",
        len(results)
    )

    st.caption(
        f"Dernière recherche : "
        f"{st.session_state['scanned_odd']} | "
        f"Date : {st.session_state['scan_date']}"
    )

    if results:
        total_pages = (
            len(results) + PAGE_SIZE - 1
        ) // PAGE_SIZE

        if st.session_state.get("result_page", 1) > total_pages:
            st.session_state["result_page"] = 1

        page = st.selectbox(
            "Page de résultats",
            options=list(range(1, total_pages + 1)),
            key="result_page",
            format_func=lambda p: (
                f"Page {p} / {total_pages}"
            ),
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
                    f"🕒 {row['Heure (QC)']} (Québec)"
                )

                left, right = st.columns(
                    [3, 1],
                    vertical_alignment="center"
                )

                with left:
                    st.markdown(
                        f"**{row['Sélection']}**"
                    )
                    st.caption(row["Marché"])

                with right:
                    st.metric(
                        "Cote",
                        row["Cote"]
                    )

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
            use_container_width=True,
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
