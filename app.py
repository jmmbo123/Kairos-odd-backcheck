
import csv
import io
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import requests
import streamlit as st

API_URL = "https://moviodds.com/odds?sport=soccer"
TZ = ZoneInfo("America/Toronto")
CENT = Decimal("0.01")
PAGE_SIZE = 15

TABS = {
    "⚽ Over / Under": "goals",
    "👥 Team Total Goals": "team",
    "🚩 Corners": "corners",
    "🏆 Moneyline": "ml",
}

GOAL_MARKETS = {
    "goals over/under",
    "alternative total goals",
    "goal line",
    "alternative goal line",
    "total goals",
    "alternative match goals",
    "match goals",
}

TEAM_MARKETS = {
    "team total goals",
    "alternative team total goals",
    "alternative team totals",
    "home team total goals",
    "away team total goals",
}

CORNER_MARKETS = {
    "corners",
    "total corners",
    "alternative corners",
    "match corners",
    "corners 2-way",
    "asian corners",
}

ML_MARKETS = {"full time result"}

LIVE_PHASES = {
    "live", "inplay", "in_play", "in-play"
}

st.set_page_config(
    page_title="KAIROS Odds Scanner 3.0",
    page_icon="⚽",
    layout="wide"
)

st.title("⚽ KAIROS ODDS SCANNER 3.0")
st.caption(
    "Soccer | 4 marchés | Pré-match | Heures du Québec"
)


def get_decimal(value):
    try:
        result = Decimal(str(value))
        if result.is_finite() and result > 1:
            return result
    except (InvalidOperation, ValueError, TypeError):
        pass
    return None


def round_odd(value):
    return value.quantize(
        CENT, rounding=ROUND_HALF_UP
    )


def parse_date(value):
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        if date.tzinfo is None:
            return None
        return date.astimezone(TZ)
    except (ValueError, TypeError, OverflowError):
        return None


def format_line(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0:
            return None
        return str(number.normalize())
    except (InvalidOperation, ValueError, TypeError):
        return None


def get_line(quote):
    value = quote.get("line")
    if value is None or str(value).strip() == "":
        value = quote.get("handicap")
    return format_line(value)


def get_total_selection(quote):
    side = str(
        quote.get("side") or ""
    ).strip().lower()

    if side in {"o", "over"}:
        side = "Over"
    elif side in {"u", "under"}:
        side = "Under"
    else:
        label = str(quote.get("label") or "")
        match = re.search(
            r"\b(over|under)\s*(\d+(?:\.\d+)?)",
            label,
            re.IGNORECASE
        )
        if match:
            return (
                f"{match.group(1).title()} "
                f"{match.group(2)}"
            )
        return None

    line = get_line(quote)
    if line is None:
        return None

    return f"{side} {line}"


def get_team_selection(quote, home, away):
    side = str(quote.get("side") or "").strip()
    label = str(quote.get("label") or "").strip()
    n2 = str(quote.get("n2") or "").strip()

    team = ""
    selection = ""

    # Format MoviOdds Team Total Goals:
    # side = équipe, label = "Over 1.5"
    match = re.search(
        r"\b(over|under)\s*(\d+(?:\.\d+)?)",
        label,
        re.IGNORECASE
    )

    if match:
        selection = (
            f"{match.group(1).title()} "
            f"{match.group(2)}"
        )
        team = side or n2

    # Autre format possible :
    # n2 = équipe, side = Over, line = 1.5
    elif side.lower() in {"over", "under", "o", "u"}:
        line = get_line(quote)
        if line is None:
            return None

        direction = (
            "Over"
            if side.lower() in {"over", "o"}
            else "Under"
        )
        selection = f"{direction} {line}"
        team = n2

    if not selection:
        return None

    if team.lower() in {"home", "1"}:
        team = home
    elif team.lower() in {"away", "2"}:
        team = away

    if not team:
        return None

    return f"{team} — {selection}"


def get_corner_selection(quote):
    result = get_total_selection(quote)
    if result:
        return result

    label = str(quote.get("label") or "")
    match = re.search(
        r"\b(over|under)\s*(\d+(?:\.\d+)?)",
        label,
        re.IGNORECASE
    )

    if match:
        return (
            f"{match.group(1).title()} "
            f"{match.group(2)}"
        )

    return None


def get_ml_selection(quote, home, away):
    label = str(
        quote.get("label") or ""
    ).strip()

    side = str(
        quote.get("side") or ""
    ).strip()

    value = label or side
    normalized = value.lower()

    if normalized in {
        "draw", "tie", "x", "nul"
    }:
        return "Match nul (X)"

    if normalized in {
        "home", "1", home.lower()
    }:
        return f"{home} (1)"

    if normalized in {
        "away", "2", away.lower()
    }:
        return f"{away} (2)"

    # Certaines sélections contiennent
    # directement le nom complet de l'équipe.
    if value:
        return value

    return None


def classify_market(name):
    market = name.strip().lower()

    if market in GOAL_MARKETS:
        return "goals"

    if market in TEAM_MARKETS:
        return "team"

    if market in CORNER_MARKETS:
        return "corners"

    if market in ML_MARKETS:
        return "ml"

    return None


def extract_selection(category, quote, home, away):
    if category == "goals":
        return get_total_selection(quote)

    if category == "team":
        return get_team_selection(
            quote, home, away
        )

    if category == "corners":
        return get_corner_selection(quote)

    if category == "ml":
        return get_ml_selection(
            quote, home, away
        )

    return None


@st.cache_data(ttl=60, show_spinner=False)
def fetch_matches():
    # gzip réduit les réponses volumineuses
    # et évite certaines limites de MoviOdds.
    response = requests.get(
        API_URL,
        headers={
            "Accept-Encoding": "gzip",
            "User-Agent": "KairosOddsScanner/3.0"
        },
        timeout=60
    )

    response.raise_for_status()
    data = response.json()

    if (
        not isinstance(data, dict)
        or not isinstance(data.get("matches"), list)
    ):
        raise ValueError(
            "Réponse MoviOdds invalide."
        )

    return data["matches"]


def scan_market(matches, category, target,
                tolerance, days):

    now = datetime.now(TZ)

    dates = {
        now.date() + timedelta(days=i)
        for i in days
    }

    results = []
    seen = set()

    future_matches = set()
    examined = 0

    for match in matches:
        if not isinstance(match, dict):
            continue

        kickoff = parse_date(
            match.get("kickoff_utc")
        )

        if kickoff is None:
            continue

        if kickoff <= now:
            continue

        if kickoff.date() not in dates:
            continue

        if match.get("in_play") is True:
            continue

        home = str(match.get("home") or "?")
        away = str(match.get("away") or "?")
        league = str(match.get("league") or "")

        match_id = str(
            match.get("id") or
            f"{home}|{away}|{kickoff.isoformat()}"
        )

        future_matches.add(match_id)

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

            if quote.get("suspended") is True:
                continue

            market = str(
                quote.get("group_name") or ""
            ).strip()

            if classify_market(market) != category:
                continue

            selection = extract_selection(
                category, quote, home, away
            )

            odd = get_decimal(
                quote.get("odds_dec")
            )

            if selection is None or odd is None:
                continue

            examined += 1
            shown = round_odd(odd)

            if abs(shown - target) > tolerance:
                continue

            key = (
                match_id,
                market.lower(),
                selection.lower(),
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
                    "Exacte"
                    if shown == target
                    else "Proche"
                ),
                "Écart": f"{shown - target:+.2f}",
                "_sort": kickoff.isoformat()
            })

    results.sort(
        key=lambda row: (
            row["_sort"],
            row["Match"],
            row["Sélection"]
        )
    )

    for row in results:
        row.pop("_sort", None)

    return results, len(future_matches), examined


def render_category(category, title):
    st.subheader(title)

    with st.form(f"form_{category}"):
        target_text = st.text_input(
            "Cote recherchée",
            value="1.66",
            key=f"target_{category}"
        )

        mode = st.radio(
            "Type de recherche",
            [
                "Exacte",
                "Approximative (±0.01)"
            ],
            key=f"mode_{category}"
        )

        period = st.selectbox(
            "Matchs à rechercher",
            [
                "Aujourd'hui",
                "Demain",
                "Aujourd'hui et demain"
            ],
            key=f"period_{category}"
        )

        submitted = st.form_submit_button(
            "🔎 SCANNER",
            type="primary",
            use_container_width=True
        )

    state_key = f"results_{category}"

    if submitted:
        target = get_decimal(
            target_text.strip().replace(",", ".")
        )

        if target is None:
            st.error("Entre une cote valide.")
        else:
            target = round_odd(target)

            tolerance = (
                CENT
                if mode.startswith("Approximative")
                else Decimal("0.00")
            )

            if period == "Demain":
                days = [1]
            elif period == "Aujourd'hui et demain":
                days = [0, 1]
            else:
                days = [0]

            with st.spinner("Analyse en cours..."):
                try:
                    matches = fetch_matches()

                    results, count, examined = (
                        scan_market(
                            matches,
                            category,
                            target,
                            tolerance,
                            days
                        )
                    )

                    st.session_state[state_key] = {
                        "results": results,
                        "matches": count,
                        "examined": examined,
                        "target": f"{target:.2f}",
                        "mode": mode,
                        "period": period,
                        "time": datetime.now(TZ).strftime(
                            "%d/%m/%Y %H:%M"
                        )
                    }

                    st.session_state[
                        f"page_{category}"
                    ] = 1

                except requests.RequestException as exc:
                    st.error(
                        "MoviOdds est temporairement "
                        f"indisponible : {exc}"
                    )

                    st.info(
                        "Réessaie plus tard. "
                        "Les anciens résultats, "
                        "s'ils existent, restent affichés."
                    )

                except (ValueError, TypeError) as exc:
                    st.error(
                        f"Erreur de lecture : {exc}"
                    )

    if state_key not in st.session_state:
        st.info(
            "Entre une cote et appuie sur SCANNER."
        )
        return

    data = st.session_state[state_key]
    results = data["results"]

    st.caption(
        f"Dernier scan : {data['time']} (QC) | "
        f"Cote : {data['target']} | "
        f"{data['mode']}"
    )

    c1, c2 = st.columns(2)

    c1.metric(
        "Matchs à venir",
        data["matches"]
    )

    c2.metric(
        "Correspondances",
        len(results)
    )

    st.caption(
        f"Sélections examinées : {data['examined']}"
    )

    if not results:
        st.warning(
            "Aucune correspondance pour cette recherche."
        )
        return

    total_pages = (
        len(results) + PAGE_SIZE - 1
    ) // PAGE_SIZE

    page_key = f"page_{category}"

    if st.session_state.get(page_key, 1) > total_pages:
        st.session_state[page_key] = 1

    page = st.selectbox(
        "Page de résultats",
        options=list(range(1, total_pages + 1)),
        key=page_key,
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
            st.markdown(
                f"**{row['Match']}**"
            )

            st.caption(
                f"🏆 {row['Ligue']} | "
                f"📅 {row['Date']} | "
                f"🕒 {row['Heure (QC)']} (QC)"
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
                        f"({row['Écart']})"
                    )

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
        file_name=f"kairos_{category}.csv",
        mime="text/csv",
        use_container_width=True,
        key=f"download_{category}"
    )


tabs = st.tabs(list(TABS.keys()))

for tab, (title, category) in zip(
    tabs, TABS.items()
):
    with tab:
        render_category(category, title)


st.divider()

st.caption(
    "Source : MoviOdds. Les cotes peuvent changer. "
    "Les marchés et horaires doivent être vérifiés "
    "sur Bet365. Les données sans phase confirmée "
    "ne garantissent pas le statut pré-match. "
    "Les cotes proches ne sont pas des "
    "correspondances exactes."
)
