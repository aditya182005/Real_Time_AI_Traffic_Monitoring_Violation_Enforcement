"""Visual design: a road-signage look.

Concrete-grey page, asphalt ink, road-sign blue, and signal red / amber /
green used ONLY to mean status. Headline figures sit on one highway gantry
sign; everything else stays quiet. Type is Barlow Condensed (headings and
numerals, from highway lettering) with Barlow for text; both fall back to
system fonts when offline.

Streamlit's own widgets are themed through ``.streamlit/config.toml``; this
file adds the custom pieces.
"""

import html

import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Condensed:wght@500;600;700&display=swap');

:root {
    --concrete: #E8EAEC;
    --surface: #F7F8F9;
    --ink: #14202B;
    --ink-soft: #4A5866;
    --rule: #C6CBD1;
    --sign: #0F4C9A;
    --sign-deep: #0B3A78;
    --paint: #FFFFFF;
    --red: #D6333A;
    --green: #2E9E5B;
    --amber: #E9A100;
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

:focus-visible { outline: 3px solid var(--sign); outline-offset: 2px; }

/* -- page heading ------------------------------------------------------ */
.page-head { margin: 0 0 1.6rem; }
.page-head h1 {
    font-family: var(--display);
    font-size: 3rem; line-height: 1; font-weight: 700;
    margin: 0 0 .55rem; padding: 0; color: var(--ink);
}
.page-head p {
    font-size: 1.1rem; line-height: 1.5; max-width: 62ch;
    color: var(--ink-soft); margin: 0;
}
/* The stop line: a short, heavy bar under the title. */
.page-head::after {
    content: ""; display: block; width: 64px; height: 6px;
    background: var(--ink); margin-top: 1.1rem;
}

/* -- gantry sign: the headline figures -------------------------------- */
.gantry {
    background: var(--sign); border-radius: 14px; padding: 7px;
    margin: 0 0 1.4rem;
}
.gantry-inner {
    border: 2px solid var(--paint); border-radius: 9px;
    padding: 4px 26px;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    column-gap: 52px;
}
.g-row {
    display: flex; align-items: center; justify-content: space-between;
    gap: 16px; padding: 13px 0;
    border-bottom: 1px solid rgba(255, 255, 255, .32);
    color: var(--paint);
}
/* No hairline under the last line of figures. */
.g-row:nth-last-child(-n+2) { border-bottom: 0; }
.g-name { display: flex; align-items: center; gap: 12px; min-width: 0; }
.g-name b { font-weight: 500; font-size: 1.12rem; line-height: 1.2; display: block; }
.g-name small {
    display: block; font-size: .85rem; line-height: 1.3;
    color: rgba(255, 255, 255, .78);
}
.g-value {
    font-family: var(--display); font-weight: 700; font-size: 2.4rem;
    line-height: 1; font-variant-numeric: tabular-nums; white-space: nowrap;
}
.lamp {
    flex: none; width: 12px; height: 12px; border-radius: 50%;
    background: var(--lamp, var(--paint));
    box-shadow: 0 0 0 2px var(--sign), 0 0 0 3px rgba(255, 255, 255, .85);
}
.lamp.red   { --lamp: #FF6B70; }
.lamp.green { --lamp: #5FD68A; }
.lamp.amber { --lamp: #FFC53D; }
.lamp.white { --lamp: #FFFFFF; }

@media (max-width: 760px) {
    .gantry-inner { grid-template-columns: minmax(0, 1fr); padding: 2px 18px; }
    .g-row:nth-last-child(2) { border-bottom: 1px solid rgba(255, 255, 255, .32); }
    .g-value { font-size: 2.1rem; }
    .page-head h1 { font-size: 2.4rem; }
}

/* -- panels and tags --------------------------------------------------- */
.panel {
    background: var(--surface); border: 1px solid var(--rule);
    border-radius: 8px; padding: 16px 20px; margin-bottom: 12px;
}
.panel h4 { margin: 0 0 .55rem; font-size: 1.25rem; }
.panel .note { color: var(--ink-soft); font-size: .95rem; margin-top: .45rem; }

.tag {
    display: inline-flex; align-items: center; gap: 7px;
    padding: 2px 11px 2px 9px; margin: 0 6px 4px 0;
    border-radius: 4px; border: 1px solid var(--rule);
    background: var(--paint); color: var(--ink);
    font-size: .88rem; font-weight: 500; line-height: 1.6;
}
.tag::before {
    content: ""; width: 9px; height: 9px; border-radius: 50%;
    background: var(--lamp, var(--sign));
}
.tag.ok     { --lamp: var(--green); }
.tag.warn   { --lamp: var(--amber); }
.tag.danger { --lamp: var(--red); }
.tag.info   { --lamp: var(--sign); }

/* -- Streamlit widgets ------------------------------------------------- */
.stButton > button, .stDownloadButton > button {
    border-radius: 6px; font-weight: 600;
}
.stTabs [data-baseweb="tab-list"] { gap: 6px; border-bottom: 2px solid var(--rule); }
.stTabs [data-baseweb="tab"] {
    font-weight: 600; font-size: 1.05rem; padding: 10px 16px;
}
div[data-testid="stFileUploader"] section,
div[data-testid="stFileUploaderDropzone"] {
    border: 2px dashed var(--sign); border-radius: 8px;
    background: var(--paint);
}
section[data-testid="stSidebar"] { border-right: 1px solid var(--rule); }

.brand { display: flex; align-items: center; gap: 12px; margin: .2rem 0 .1rem; }
.brand span {
    font-family: var(--display); font-weight: 700; font-size: 1.9rem;
    line-height: 1; color: var(--ink);
}
.fine-print { color: var(--ink-soft); font-size: .88rem; }
</style>
"""

# A signal head: three lamps in a dark housing (inline SVG, decorative).
SIGNAL_HEAD = (
    '<svg width="26" height="40" viewBox="0 0 26 40" role="img" '
    'aria-label="Traffic signal">'
    '<rect x="1" y="1" width="24" height="38" rx="6" fill="#14202B"/>'
    '<circle cx="13" cy="9" r="4.5" fill="#D6333A"/>'
    '<circle cx="13" cy="20" r="4.5" fill="#3a4651"/>'
    '<circle cx="13" cy="31" r="4.5" fill="#2E9E5B"/>'
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
