"""Visual design: a pine-and-terracotta control room.

A warm stone page, white working surfaces, charcoal ink and terracotta for
anything you can act on, set against deep pine. Signal red / amber / green are used ONLY to mean
status. The memorable element is the highway gantry sign that carries the
headline figures. A pine sidebar holds the brand and navigation. Type is
Barlow Condensed (headings and numerals, from highway lettering) with Barlow
for text; both fall back to system fonts when offline.

Streamlit's own widgets are themed through ``.streamlit/config.toml``; this
file adds the custom pieces.
"""

import html

import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Condensed:wght@500;600;700&display=swap');

:root {
    --page: #F6F2ED;
    --surface: #FFFFFF;
    --ink: #1C2426;
    --ink-soft: #5E6A6C;
    --rule: #E1D9D0;
    --night: #11363B;          /* pine: gantry sign and sidebar */
    --night-deep: #0A2427;
    --accent: #B8481F;         /* terracotta: things you can act on */
    --accent-bright: #F0A27F;  /* the same, on pine */
    --paint: #FFFFFF;
    --red: #B3263A;
    --green: #1F9D63;
    --amber: #E3A008;
    --lift: 0 1px 2px rgba(28, 36, 38, .06), 0 6px 20px rgba(60, 40, 28, .07);
    --display: 'Barlow Condensed', 'Arial Narrow', 'Roboto Condensed', sans-serif;
    --text: 'Barlow', system-ui, -apple-system, 'Segoe UI', sans-serif;
}

.stApp, .stApp p, .stApp label, .stApp li,
.stApp input, .stApp textarea, .stApp button {
    font-family: var(--text);
}
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {
    font-family: var(--display);
    font-weight: 600;
    letter-spacing: 0.005em;
    color: var(--ink);
}
.stApp h2 { font-size: 1.9rem; }
.stApp h3 { font-size: 1.5rem; }

.block-container { max-width: 1200px; padding-top: 2.2rem; }
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }

:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }

/* -- page heading ------------------------------------------------------ */
.page-head { margin: 0 0 1.7rem; }
.page-head h1 {
    font-family: var(--display);
    font-size: 3rem; line-height: 1; font-weight: 700;
    margin: 0 0 .55rem; padding: 0; color: var(--ink);
}
.page-head p {
    font-size: 1.1rem; line-height: 1.5; max-width: 62ch;
    color: var(--ink-soft); margin: 0;
}
/* The stop line: a short, heavy terracotta bar under the title. */
.page-head::after {
    content: ""; display: block; width: 64px; height: 6px;
    border-radius: 3px; background: var(--accent); margin-top: 1.1rem;
}

/* -- gantry sign: the headline figures -------------------------------- */
.gantry {
    background: var(--night); border-radius: 16px; padding: 7px;
    margin: 0 0 1.5rem;
    box-shadow: 0 2px 4px rgba(10, 36, 39, .20), 0 14px 32px rgba(10, 36, 39, .24);
}
.gantry-inner {
    border: 2px solid rgba(255, 255, 255, .88); border-radius: 10px;
    padding: 4px 26px;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    column-gap: 52px;
}
.g-row {
    display: flex; align-items: center; justify-content: space-between;
    gap: 16px; padding: 13px 0;
    border-bottom: 1px solid rgba(255, 255, 255, .22);
    color: var(--paint);
}
/* No hairline under the last line of figures. */
.g-row:nth-last-child(-n+2) { border-bottom: 0; }
.g-name { display: flex; align-items: center; gap: 12px; min-width: 0; }
.g-name b { font-weight: 500; font-size: 1.12rem; line-height: 1.2; display: block;
    overflow-wrap: anywhere; }
.g-name small {
    display: block; font-size: .85rem; line-height: 1.3;
    color: rgba(255, 255, 255, .72);
}
.g-value {
    font-family: var(--display); font-weight: 700; font-size: 2.4rem;
    line-height: 1; font-variant-numeric: tabular-nums; white-space: nowrap;
}
.lamp {
    flex: none; width: 12px; height: 12px; border-radius: 50%;
    background: var(--lamp, var(--paint));
    box-shadow: 0 0 0 2px var(--night), 0 0 0 3px rgba(255, 255, 255, .8);
}
.lamp.red   { --lamp: #FF6B70; }
.lamp.green { --lamp: #4FD68C; }
.lamp.amber { --lamp: #FFC53D; }
.lamp.white { --lamp: #FFFFFF; }

@media (max-width: 760px) {
    .gantry-inner { grid-template-columns: minmax(0, 1fr); padding: 2px 18px; }
    .g-row:nth-last-child(2) { border-bottom: 1px solid rgba(255, 255, 255, .22); }
    .g-value { font-size: 2.1rem; }
    .page-head h1 { font-size: 2.4rem; }
}

/* -- panels and tags --------------------------------------------------- */
.panel {
    background: var(--surface); border: 1px solid var(--rule);
    border-radius: 12px; padding: 18px 22px; margin-bottom: 14px;
    box-shadow: var(--lift);
}
.panel h4 { margin: 0 0 .55rem; font-size: 1.25rem; }
.panel .note { color: var(--ink-soft); font-size: .95rem; margin-top: .45rem; }

.tag {
    display: inline-flex; align-items: center; gap: 7px;
    padding: 2px 11px 2px 9px; margin: 0 6px 4px 0;
    border-radius: 999px; border: 1px solid var(--rule);
    background: var(--surface); color: var(--ink);
    font-size: .88rem; font-weight: 500; line-height: 1.6;
}
.tag::before {
    content: ""; width: 9px; height: 9px; border-radius: 50%;
    background: var(--lamp, var(--accent));
}
.tag.ok     { --lamp: var(--green); }
.tag.warn   { --lamp: var(--amber); }
.tag.danger { --lamp: var(--red); }
.tag.info   { --lamp: var(--accent); }

/* -- Streamlit widgets ------------------------------------------------- */
.stButton > button, .stDownloadButton > button {
    border-radius: 8px; font-weight: 600;
    transition: box-shadow .15s ease, transform .15s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    box-shadow: 0 4px 14px rgba(184, 72, 31, .28);
}
.stTabs [data-baseweb="tab-list"] { gap: 6px; border-bottom: 1px solid var(--rule); }
.stTabs [data-baseweb="tab"] {
    font-weight: 600; font-size: 1.05rem; padding: 10px 16px;
}
div[data-testid="stFileUploader"] section,
div[data-testid="stFileUploaderDropzone"] {
    border: 2px dashed var(--accent); border-radius: 12px;
    background: var(--surface);
}
div[data-testid="stMetric"] {
    background: var(--surface); border: 1px solid var(--rule);
    border-radius: 12px; padding: 14px 18px; box-shadow: var(--lift);
}
div[data-testid="stMetricValue"] {
    font-family: var(--display); font-weight: 700; color: var(--ink);
}
div[data-testid="stDataFrame"] {
    border: 1px solid var(--rule); border-radius: 12px; overflow: hidden;
}
div[data-testid="stExpander"] {
    background: var(--surface); border: 1px solid var(--rule);
    border-radius: 12px;
}

/* -- sidebar: pine navigation ----------------------------------------- */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--night) 0%, var(--night-deep) 100%);
    border-right: 0;
}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
section[data-testid="stSidebar"] .brand span {
    color: #EDE8E2;
}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: #A9BDBF; }
section[data-testid="stSidebar"] hr { border-color: rgba(255, 255, 255, .14); }
/* Keep text readable inside boxes that bring their own background. */
section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] div[data-testid="stAlert"] p,
section[data-testid="stSidebar"] div[data-testid="stAlert"] span,
section[data-testid="stSidebar"] .stButton > button p {
    color: var(--ink);
}
section[data-testid="stSidebar"] div[role="radiogroup"] > label {
    padding: 7px 12px; border-radius: 10px; margin-bottom: 2px;
    border-left: 3px solid transparent;
}
section[data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
    background: rgba(255, 255, 255, .07);
}
section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {
    background: rgba(240, 162, 127, .16);
    border-left-color: var(--accent-bright);
}
section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) p {
    font-weight: 600; color: #FFFFFF;
}

/* Group headings inside the page list are added per page by nav_groups(). */
section[data-testid="stSidebar"] div[role="radiogroup"] { padding-top: 26px; }
section[data-testid="stSidebar"] div[role="radiogroup"] > label { position: relative; }

.brand { display: flex; align-items: center; gap: 12px; margin: .2rem 0 .1rem; }
.brand span {
    font-family: var(--display); font-weight: 700; font-size: 1.9rem;
    line-height: 1; color: var(--ink);
}
.fine-print { color: var(--ink-soft); font-size: .88rem; }

@media (prefers-reduced-motion: reduce) {
    .stButton > button, .stDownloadButton > button { transition: none; }
}
</style>
"""

# A signal head: three lamps in a dark housing (inline SVG, decorative).
SIGNAL_HEAD = (
    '<svg width="26" height="40" viewBox="0 0 26 40" role="img" '
    'aria-label="Traffic signal">'
    '<rect x="1" y="1" width="24" height="38" rx="6" fill="#1C2426" stroke="#7E9A9D" stroke-width="1.2"/>'
    '<circle cx="13" cy="9" r="4.5" fill="#B3263A"/>'
    '<circle cx="13" cy="20" r="4.5" fill="#3A4C4F"/>'
    '<circle cx="13" cy="31" r="4.5" fill="#1F9D63"/>'
    '</svg>'
)


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def brand():
    st.markdown(
        f'<div class="brand">{SIGNAL_HEAD}<span>Traffic Agent</span></div>',
        unsafe_allow_html=True,
    )


def page_head(title, subtitle=""):
    sub = f"<p>{html.escape(subtitle)}</p>" if subtitle else ""
    st.markdown(
        f'<div class="page-head"><h1>{html.escape(title)}</h1>{sub}</div>',
        unsafe_allow_html=True,
    )


def gantry(rows):
    """The headline figures, as one highway gantry sign.

    ``rows``: ``(label, value, hint, lamp)`` tuples; ``hint`` and ``lamp``
    (red / green / amber / white) are optional.
    """

    cells = []

    for row in rows:
        label, value = row[0], row[1]
        hint = row[2] if len(row) > 2 else ""
        lamp = row[3] if len(row) > 3 and row[3] else "white"

        hint_html = f"<small>{html.escape(str(hint))}</small>" if hint else ""
        cells.append(
            '<div class="g-row"><div class="g-name">'
            f'<span class="lamp {html.escape(lamp)}"></span>'
            f'<div><b>{html.escape(str(label))}</b>{hint_html}</div></div>'
            f'<div class="g-value">{html.escape(str(value))}</div></div>'
        )

    st.markdown(
        '<div class="gantry"><div class="gantry-inner">'
        + "".join(cells)
        + "</div></div>",
        unsafe_allow_html=True,
    )


def pill(text, kind="info"):
    """A small status tag. ``kind``: ok, warn, danger or info."""

    return f'<span class="tag {html.escape(kind)}">{html.escape(text)}</span>'


def card(title, body_html):
    """A quiet panel. ``body_html`` must already be escaped / trusted."""

    st.markdown(
        f'<div class="panel"><h4>{html.escape(title)}</h4>{body_html}</div>',
        unsafe_allow_html=True,
    )


def nav_groups(starts):
    """Headings for the sidebar page list.

    ``starts`` maps a page's position in the list (0 is the first) to the
    heading that begins a group there. Streamlit draws the list as one
    radio group, so each heading is a CSS label above the first page of the
    group; the page names themselves do not change. The first heading has
    no gap above it, so it sits on the top edge of the list.
    """

    rules = []

    for position, heading in starts.items():
        safe = html.escape(str(heading)).replace("\\", "").replace('"', "")
        gap = "0" if position == 0 else "34px"
        selector = (
            'section[data-testid="stSidebar"] div[role="radiogroup"] > '
            f'label:nth-child({int(position) + 1})'
        )
        # The heading is drawn above the row, outside its highlight.
        rules.append(f"{selector} {{ margin-top: {gap}; }}")
        rules.append(
            f'{selector}::before {{ content: "{safe}"; position: absolute;'
            ' top: -24px; left: 2px; font-size: .78rem; font-weight: 600;'
            ' letter-spacing: .06em; color: #A9BDBF; }'
        )

    st.markdown("<style>" + " ".join(rules) + "</style>",
                unsafe_allow_html=True)
