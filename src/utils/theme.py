"""
Enterprise visual theme for the GCC Research Intelligence Platform.

Centralizes the CSS injected into every page so the sidebar navigation,
KPI cards, and page headers share one consistent, polished look instead of
relying on Streamlit's default styling. Pure presentation -- no business
logic lives here.
"""

from __future__ import annotations

import streamlit as st

# Core palette. Kept as module-level constants (rather than buried in the
# CSS string) so other components can reuse the same colors for inline
# badges/accents without re-defining hex values in five different files.
NAVY = "#0f172a"
SLATE_900 = "#0f172a"
SLATE_800 = "#1e293b"
SLATE_700 = "#334155"
SLATE_500 = "#64748b"
SLATE_300 = "#cbd5e1"
SLATE_100 = "#f1f5f9"
SLATE_50 = "#f8fafc"
ACCENT_BLUE = "#2563eb"
ACCENT_BLUE_DARK = "#1d4ed8"
ACCENT_GREEN = "#16a34a"
ACCENT_AMBER = "#d97706"
ACCENT_RED = "#dc2626"
WHITE = "#ffffff"

_THEME_CSS = f"""
<style>
    /* ---------- Global typography / surface ---------- */
    .stApp {{
        background: {SLATE_50};
    }}
    h1, h2, h3, h4, h5 {{
        color: {SLATE_900};
        font-weight: 650;
        letter-spacing: -0.01em;
    }}
    [data-testid="stMainBlockContainer"] {{
        padding-top: 1.5rem;
    }}

    /* ---------- Sidebar shell ---------- */
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {SLATE_900} 0%, {SLATE_800} 100%);
        border-right: 1px solid {SLATE_700};
    }}
    [data-testid="stSidebar"] * {{
        color: {SLATE_100};
    }}
    [data-testid="stSidebar"] hr {{
        border-color: rgba(255,255,255,0.12);
    }}

    .gcc-brand {{
        display: flex;
        align-items: center;
        gap: 0.6rem;
        padding: 0.25rem 0 1rem 0;
    }}
    .gcc-brand-icon {{
        font-size: 1.8rem;
        line-height: 1;
    }}
    .gcc-brand-text-title {{
        font-size: 1.05rem;
        font-weight: 700;
        color: {WHITE};
        line-height: 1.2;
    }}
    .gcc-brand-text-sub {{
        font-size: 0.72rem;
        color: {SLATE_300};
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }}

    .gcc-nav-label {{
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: {SLATE_300};
        margin: 0.5rem 0 0.25rem 0.1rem;
    }}

    /* Sidebar radio re-styled to look like a nav menu */
    [data-testid="stSidebar"] div[role="radiogroup"] {{
        gap: 0.15rem;
    }}
    [data-testid="stSidebar"] div[role="radiogroup"] label {{
        width: 100%;
        padding: 0.5rem 0.7rem;
        border-radius: 8px;
        transition: background 0.15s ease;
        margin-bottom: 0.1rem;
    }}
    [data-testid="stSidebar"] div[role="radiogroup"] label:hover {{
        background: rgba(255,255,255,0.06);
    }}
    [data-testid="stSidebar"] div[role="radiogroup"] label[data-checked="true"],
    [data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {{
        background: {ACCENT_BLUE};
    }}
    [data-testid="stSidebar"] div[role="radiogroup"] label p {{
        font-size: 0.92rem;
        font-weight: 500;
    }}

    /* Sidebar buttons (logout / extend session) */
    [data-testid="stSidebar"] .stButton button {{
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.16);
        color: {WHITE};
        font-weight: 500;
    }}
    [data-testid="stSidebar"] .stButton button:hover {{
        background: rgba(255,255,255,0.16);
        border-color: rgba(255,255,255,0.3);
        color: {WHITE};
    }}

    .gcc-sidebar-user {{
        display: flex;
        align-items: center;
        gap: 0.6rem;
        padding: 0.6rem 0.2rem;
    }}
    .gcc-avatar {{
        width: 34px;
        height: 34px;
        min-width: 34px;
        border-radius: 50%;
        background: {ACCENT_BLUE};
        color: {WHITE};
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 0.85rem;
    }}
    .gcc-sidebar-user-name {{
        font-size: 0.88rem;
        font-weight: 600;
        color: {WHITE};
        line-height: 1.2;
    }}
    .gcc-sidebar-user-meta {{
        font-size: 0.72rem;
        color: {SLATE_300};
    }}

    .gcc-badge {{
        display: inline-block;
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.03em;
        padding: 0.15rem 0.55rem;
        border-radius: 999px;
        text-transform: uppercase;
    }}
    .gcc-badge-running {{ background: rgba(37,99,235,0.18); color: #93c5fd; }}
    .gcc-badge-stopped {{ background: rgba(217,119,6,0.2); color: #fcd34d; }}
    .gcc-badge-idle {{ background: rgba(255,255,255,0.08); color: {SLATE_300}; }}

    /* ---------- Page header ---------- */
    .gcc-page-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding-bottom: 0.75rem;
        margin-bottom: 1.25rem;
        border-bottom: 1px solid {SLATE_300};
    }}
    .gcc-page-title {{
        font-size: 1.6rem;
        font-weight: 700;
        color: {SLATE_900};
        margin: 0;
    }}
    .gcc-page-subtitle {{
        font-size: 0.92rem;
        color: {SLATE_500};
        margin-top: 0.15rem;
    }}

    /* ---------- KPI cards ---------- */
    .gcc-kpi-card {{
        background: {WHITE};
        border: 1px solid {SLATE_300};
        border-radius: 12px;
        padding: 1.1rem 1.25rem;
        box-shadow: 0 1px 2px rgba(15,23,42,0.04);
        height: 100%;
    }}
    .gcc-kpi-top {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 0.5rem;
    }}
    .gcc-kpi-label {{
        font-size: 0.78rem;
        font-weight: 600;
        color: {SLATE_500};
        text-transform: uppercase;
        letter-spacing: 0.03em;
    }}
    .gcc-kpi-icon {{
        font-size: 1.1rem;
        opacity: 0.85;
    }}
    .gcc-kpi-value {{
        font-size: 1.9rem;
        font-weight: 750;
        color: {SLATE_900};
        line-height: 1.1;
    }}
    .gcc-kpi-delta {{
        font-size: 0.78rem;
        font-weight: 600;
        margin-top: 0.3rem;
    }}
    .gcc-kpi-delta-pos {{ color: {ACCENT_GREEN}; }}
    .gcc-kpi-delta-neg {{ color: {ACCENT_RED}; }}
    .gcc-kpi-delta-neutral {{ color: {SLATE_500}; }}

    /* ---------- Generic content card ---------- */
    .gcc-card {{
        background: {WHITE};
        border: 1px solid {SLATE_300};
        border-radius: 12px;
        padding: 1.25rem 1.4rem;
        box-shadow: 0 1px 2px rgba(15,23,42,0.04);
    }}
    .gcc-card-title {{
        font-size: 0.95rem;
        font-weight: 700;
        color: {SLATE_900};
        margin-bottom: 0.75rem;
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }}

    .gcc-status-row {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.5rem 0;
        border-bottom: 1px solid {SLATE_100};
        font-size: 0.88rem;
    }}
    .gcc-status-row:last-child {{ border-bottom: none; }}
    .gcc-status-label {{ color: {SLATE_500}; }}
    .gcc-status-value {{ color: {SLATE_900}; font-weight: 600; }}

    .gcc-pill {{
        font-size: 0.72rem;
        font-weight: 700;
        padding: 0.15rem 0.6rem;
        border-radius: 999px;
        text-transform: uppercase;
        letter-spacing: 0.02em;
    }}
    .gcc-pill-green {{ background: #dcfce7; color: #15803d; }}
    .gcc-pill-red {{ background: #fee2e2; color: #b91c1c; }}
    .gcc-pill-amber {{ background: #fef3c7; color: #92400e; }}
    .gcc-pill-blue {{ background: #dbeafe; color: #1d4ed8; }}
    .gcc-pill-slate {{ background: {SLATE_100}; color: {SLATE_500}; }}

    /* Buttons in main content area */
    .stButton button[kind="primary"] {{
        background: {ACCENT_BLUE};
        border-color: {ACCENT_BLUE_DARK};
    }}
    .stButton button[kind="primary"]:hover {{
        background: {ACCENT_BLUE_DARK};
    }}
</style>
"""


def inject_enterprise_theme() -> None:
    """Inject the shared enterprise CSS theme. Call once per page render."""
    st.markdown(_THEME_CSS, unsafe_allow_html=True)


def render_page_header(title: str, subtitle: str = "") -> None:
    """Render the standard enterprise page header (title + subtitle + rule)."""
    subtitle_html = f'<div class="gcc-page-subtitle">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div class="gcc-page-header">
            <div>
                <p class="gcc-page-title">{title}</p>
                {subtitle_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi_card(column, label: str, value: str, icon: str = "", delta: str = "", delta_kind: str = "neutral") -> None:
    """
    Render one KPI card inside a Streamlit column.

    Args:
        column: the `st.columns(...)` slot to render into.
        label: short uppercase label, e.g. "Companies Researched".
        value: the big headline value, already formatted as a string.
        icon: optional emoji/icon shown top-right of the card.
        delta: optional small caption below the value (e.g. "+12 this week").
        delta_kind: one of "positive", "negative", "neutral" -- controls delta color.
    """
    delta_class = {
        "positive": "gcc-kpi-delta-pos",
        "negative": "gcc-kpi-delta-neg",
    }.get(delta_kind, "gcc-kpi-delta-neutral")
    delta_html = f'<div class="gcc-kpi-delta {delta_class}">{delta}</div>' if delta else ""
    icon_html = f'<span class="gcc-kpi-icon">{icon}</span>' if icon else ""

    with column:
        st.markdown(
            f"""
            <div class="gcc-kpi-card">
                <div class="gcc-kpi-top">
                    <span class="gcc-kpi-label">{label}</span>
                    {icon_html}
                </div>
                <div class="gcc-kpi-value">{value}</div>
                {delta_html}
            </div>
            """,
            unsafe_allow_html=True,
        )


def pill(text: str, kind: str = "slate") -> str:
    """Return an HTML pill/badge snippet for embedding in other markdown blocks."""
    return f'<span class="gcc-pill gcc-pill-{kind}">{text}</span>'
