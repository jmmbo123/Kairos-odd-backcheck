
import csv
import io
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import requests
import streamlit as st

BASE = "https://moviodds.com/odds"
TZ = ZoneInfo("America/Toronto")
CENT = Decimal("0.01")
PAGE_SIZE = 15
LIVE = {"live", "inplay", "in_play", "in-play"}

SOCCER_GOALS = {"goals over/under", "alternative total goals", "goal line", "alternative goal line", "total goals", "alternative match goals", "match goals"}
SOCCER_TEAM = {"team total goals", "alternative team total goals", "alternative team totals", "home team total goals", "away team total goals"}
SOCCER_CORNERS = {"corners", "total corners", "alternative corners", "match corners", "corners 2-way", "asian corners"}
SOCCER_ML = {"full time result", "fulltime result"}

st.set_page_config(page_title="KAIROS Odds Scanner 4.0", page_icon="🏒", layout="wide")
st.title("⚽🏒 KAIROS ODDS SCANNER 4.0")
st.caption("Soccer + Hockey | Matchs à venir | Heure du Québec")


def decimal_value(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result > 1 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def rounded(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def kickoff_local(value):
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.astimezone(TZ) if date.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def line_value(value, signed=False):
    try:
        n = Decimal(str(value))
        if not n.is_finite():
            return None
        if not signed and n < 0:
            return None
        return f"{n.normalize():+}" if signed else str(n.normalize())
    except (InvalidOperation, ValueError, TypeError):
        return None


def over_under(quote):
    side = str(quote.get("side") or "").strip().lower()
    if side in ("o", "over"):
        direction = "Over"
    elif side in ("u", "under"):
        direction = "Under"
    else:
        direction = None
    number = quote.get("line")
    if number is None or str(number).strip() == "":
        number = quote.get("handicap")
    number = line_value(number)
    if direction and number is not None:
        return f"{direction} {number}"
    label = str(quote.get("label") or "")
    found = re.search(r"\b(over|under|o|u)\s*(\d+(?:\.\d+)?)\b", label, re.I)
    if found:
        direction = "Over" if found.group(1).lower() in ("o", "over") else "Under"
        return f"{direction} {found.group(2)}"
    return None


def soccer_selection(category, quote, home, away):
    name = str(quote.get("group_name") or "").strip().lower()
    if category == "goals" and name in SOCCER_GOALS:
        return over_under(quote)
    if category == "corners" and name in SOCCER_CORNERS:
        return over_under(quote)
    if category == "team" and name in SOCCER_TEAM:
        label = str(quote.get("label") or "")
        found = re.search(r"\b(over|under)\s*(\d+(?:\.\d+)?)", label, re.I)
        team = str(quote.get("side") or quote.get("n2") or "").strip()
        if found:
            if team.lower() in ("home", "1"):
                team = home
            elif team.lower() in ("away", "2"):
                team = away
            return f"{team} — {found.group(1).title()} {found.group(2)}" if team else None
        selection = over_under(quote)
        team = str(quote.get("n2") or "").strip()
        if team.lower() in ("home", "1"):
            team = home
        elif team.lower() in ("away", "2"):
            team = away
        return f"{team} — {selection}" if team and selection else None
    if category == "ml" and (name in SOCCER_ML or str(quote.get("group_id") or "") == "40"):
        outcome = str(quote.get("n2") or "").strip().lower()
        label = str(quote.get("label") or quote.get("side") or "").strip()
        if outcome == "1" or label.lower() in ("home", "1", home.lower()):
            return f"{home} (1)"
        if outcome == "x" or label.lower() in ("draw", "tie", "x", "nul"):
            return "Match nul (X)"
        if outcome == "2" or label.lower() in ("away", "2", away.lower()):
            return f"{away} (2)"
        return label or None
    return None


def hockey_selection(category, quote, home, away):
    # MoviOdds hockey: group 972 = pre-match Game grid.
    # line identifies the column: To Win / Total / Line.
    group = str(quote.get("group_name") or "").strip().lower()
    gid = str(quote.get("group_id") or "")
    if gid != "972" and group != "game":
        return None
    column = str(quote.get("line") or "").strip().lower()
    side = str(quote.get("side") or "").strip()
    label = str(quote.get("label") or "").strip()
    if category == "h_total" and column in ("total", "total goals"):
        direction = side.lower()
        if direction in ("o", "over", "u", "under"):
            direction = "Over" if direction in ("o", "over") else "Under"
            match = re.search(r"([0-9]+(?:\.[0-9]+)?)", label)
            if match:
                return f"{direction} {match.group(1)}"
        return over_under(quote)
    if category == "h_puck" and column in ("line", "puck line", "handicap"):
        team = home if side.lower() in ("home", "1", home.lower()) else away if side.lower() in ("away", "2", away.lower()) else side
        match = re.search(r"([+-]\s*\d+(?:\.\d+)?)", label)
        handicap = match.group(1).replace(" ", "") if match else None
        if handicap is None:
            handicap = line_value(quote.get("handicap"), signed=True)
        return f"{team} {handicap}" if team and handicap else None
    if category == "h_ml" and column in ("to win", "moneyline", "money line", "winner"):
        value = side or label
        if value.lower() in ("home", "1", home.lower()):
            return home
        if value.lower() in ("away", "2", away.lower()):
            return away
        if value.lower() in ("draw", "tie", "x"):
            return None  # Two-way moneyline, not 3-way result
        return value or None
    return None


@st.cache_data(ttl=60, show_spinner=False)
def fetch_matches(sport):
    response = requests.get(
        BASE,
        params={"sport": sport},
        headers={"Accept-Encoding": "gzip", "User-Agent": "KairosOddsScanner/4.0"},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("matches"), list):
        raise ValueError("Format de réponse MoviOdds inattendu")
    return payload["matches"]


def scan_matches(matches, sport, category, target, tolerance, days):
    now = datetime.now(TZ)
    dates = {now.date() + timedelta(days=day) for day in days}
    rows, seen, future = [], set(), set()
    examined = 0
    for match in matches:
        if not isinstance(match, dict) or match.get("in_play") is True:
            continue
        kickoff = kickoff_local(match.get("kickoff_utc"))
        if kickoff is None or kickoff <= now or kickoff.date() not in dates:
            continue
        home = str(match.get("home") or "?")
        away = str(match.get("away") or "?")
        league = str(match.get("league") or "")
        mid = str(match.get("id") or f"{home}|{away}|{kickoff.isoformat()}")
        future.add(mid)
        quotes = match.get("quotes") or []
        if not isinstance(quotes, list):
            continue
        for quote in quotes:
            if not isinstance(quote, dict):
                continue
            if quote.get("suspended") is True:
                continue
            phase = str(quote.get("phase") or "").strip().lower()
            if phase in LIVE:
                continue
            selection = (
                soccer_selection(category, quote, home, away)
                if sport == "soccer"
                else hockey_selection(category, quote, home, away)
            )
            odd = decimal_value(quote.get("odds_dec"))
            if not selection or odd is None:
                continue
            examined += 1
            shown = rounded(odd)
            if abs(shown - target) > tolerance:
                continue
            market = str(quote.get("group_name") or "")
            key = (mid, category, market, selection, str(shown))
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "Match": f"{home} vs {away}",
                "Ligue": league,
                "Date": kickoff.strftime("%d/%m/%Y"),
                "Heure (QC)": kickoff.strftime("%H:%M"),
                "Marché": market,
                "Sélection": selection,
                "Cote": f"{shown:.2f}",
                "Correspondance": "Exacte" if shown == target else "Proche",
                "Écart": f"{shown - target:+.2f}",
                "_sort": kickoff.isoformat(),
            })
    rows.sort(key=lambda row: (row["_sort"], row["Match"], row["Sélection"]))
    for row in rows:
        row.pop("_sort")
    return rows, len(future), examined


def render_scanner(sport, category, title):
    st.subheader(title)
    with st.form(f"form_{category}"):
        target_text = st.text_input("Cote recherchée", value="1.66", key=f"target_{category}")
        mode = st.radio("Recherche", ["Exacte", "Approximative (±0.01)"], key=f"mode_{category}")
        period = st.selectbox("Période", ["Aujourd'hui", "Demain", "Aujourd'hui et demain"], key=f"period_{category}")
        submitted = st.form_submit_button("🔎 SCANNER", type="primary", width="stretch")

    state_key = f"scan_{category}"
    if submitted:
        target = decimal_value(target_text.strip().replace(",", "."))
        if target is None:
            st.error("Entre une cote décimale valide (exemple : 1.66).")
        else:
            target = rounded(target)
            tolerance = CENT if mode.startswith("Approximative") else Decimal("0.00")
            days = [1] if period == "Demain" else [0, 1] if period == "Aujourd'hui et demain" else [0]
            with st.spinner("Récupération et analyse des cotes..."):
                try:
                    matches = fetch_matches(sport)
                    results, future_count, examined = scan_matches(matches, sport, category, target, tolerance, days)
                    st.session_state[state_key] = {
                        "results": results,
                        "future": future_count,
                        "examined": examined,
                        "target": f"{target:.2f}",
                        "mode": mode,
                        "period": period,
                        "timestamp": datetime.now(TZ).strftime("%d/%m/%Y %H:%M"),
                    }
                    st.session_state[f"page_{category}"] = 1
                except (requests.RequestException, ValueError, TypeError) as exc:
                    st.error(f"API temporairement indisponible ou réponse invalide : {exc}")
                    st.info("Réessaie plus tard. Les résultats de la session précédente restent visibles s'il y en a.")

    if state_key not in st.session_state:
        st.info("Choisis une cote et lance le scanner.")
        return

    data = st.session_state[state_key]
    rows = data["results"]
    st.caption(f"Dernier scan : {data['timestamp']} (QC) · {data['mode']} · {data['target']} · {data['period']}")
    c1, c2 = st.columns(2)
    c1.metric("Matchs à venir", data["future"])
    c2.metric("Correspondances", len(rows))
    st.caption(f"Sélections valides examinées : {data['examined']}")
    if not rows:
        st.warning("Aucune correspondance pour cette cote et cette période.")
        return

    pages = (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE
    page_key = f"page_{category}"
    if st.session_state.get(page_key, 1) > pages:
        st.session_state[page_key] = 1
    page = st.selectbox("Page", range(1, pages + 1), key=page_key,
                        format_func=lambda p: f"Page {p} / {pages}")
    start = (page - 1) * PAGE_SIZE
    st.caption(f"Résultats {start + 1} à {min(start + PAGE_SIZE, len(rows))} sur {len(rows)}")
    for row in rows[start:start + PAGE_SIZE]:
        with st.container(border=True):
            st.markdown(f"**{row['Match']}**")
            st.caption(f"🏆 {row['Ligue']} · 📅 {row['Date']} · 🕒 {row['Heure (QC)']} (QC)")
            left, right = st.columns([3, 1])
            with left:
                st.markdown(f"**{row['Sélection']}**")
                st.caption(row["Marché"])
                st.caption("🎯 Cote exacte" if row["Correspondance"] == "Exacte" else f"🔎 Cote proche ({row['Écart']})")
            with right:
                st.metric("Cote", row["Cote"])
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    st.download_button("📥 Exporter tous les résultats (CSV)",
                       data="\ufeff" + output.getvalue(), file_name=f"kairos_{category}.csv",
                       mime="text/csv", width="stretch", key=f"export_{category}")


soccer_tab, hockey_tab = st.tabs(["⚽ SOCCER", "🏒 HOCKEY"])
with soccer_tab:
    sub = st.tabs(["Over/Under", "Team Total Goals", "Corners", "Moneyline (1X2)"])
    for tab, category, title in zip(sub, ["goals", "team", "corners", "ml"],
                                    ["Total des buts", "Buts d'une équipe", "Total des corners", "Résultat à 90 minutes (1X2)"]):
        with tab:
            render_scanner("soccer", category, title)
with hockey_tab:
    st.caption("Toutes les ligues disponibles dans MoviOdds : NHL, AHL, Europe, etc.")
    sub = st.tabs(["Moneyline", "Over/Under", "Puck Line"])
    for tab, category, title in zip(sub, ["h_ml", "h_total", "h_puck"],
                                    ["Vainqueur du match (To Win)", "Total des buts", "Handicap / Puck Line"]):
        with tab:
            render_scanner("ice_hockey", category, title)

st.divider()
st.caption("Source : MoviOdds. Les prix peuvent changer. Vérifie les sélections, les règles de prolongation, les heures et les cotes sur ton bookmaker avant toute décision. Les cotes proches ne sont pas exactes.")
