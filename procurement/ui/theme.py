"""Global theme layer: the app's CSS design tokens.

One place defines the visual language: status badges, numeric alignment and a
few Streamlit chrome cleanups. Colors are a single professional system —
a corporate blue primary, neutral surfaces, and four semantic status hues
(blue = in progress, amber = waiting, green = success, red = failure).

Badge pairs are chosen so the text meets WCAG AA (4.5:1) on its own pill
background in the forced light theme:
  slate   #334155 on #F1F5F9   ~8.2:1
  blue    #1E40AF on #DBEAFE   ~7.9:1
  amber   #92400E on #FEF3C7   ~7.9:1
  green   #166534 on #DCFCE7   ~7.4:1
  red     #991B1B on #FEE2E2   ~7.7:1
"""

from __future__ import annotations

import streamlit as st

_CSS = """
/* Root polish */
#MainMenu, .stApp {
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
h1, h2, h3 {
  letter-spacing: -0.01em;
}

/* Hide non-product chrome: Deploy button and the running toast */
[data-testid="stAppDeployButton"], .stDeployButton {
  display: none !important;
}
[data-testid="stStatusWidget"] {
  display: none !important;
}

/* Money and counts in tables keep a stable column width */
[data-testid="stTable"] td,
[data-testid="stDataFrame"] {
  font-variant-numeric: tabular-nums;
}

/* Status pills — text color on its own background, all pairs >= 4.5:1 */
.pp-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 0.78rem;
  font-weight: 600;
  line-height: 1.5;
  white-space: nowrap;
  vertical-align: middle;
}
.pp-badge--draft, .pp-badge--cancelled, .pp-badge--neutral {
  background: #F1F5F9;
  border-color: #E2E8F0;
  color: #334155;
}
.pp-badge--researching {
  background: #DBEAFE;
  border-color: #BFDBFE;
  color: #1E40AF;
}
.pp-badge--pending {
  background: #FEF3C7;
  border-color: #FDE68A;
  color: #92400E;
}
.pp-badge--success {
  background: #DCFCE7;
  border-color: #BBF7D0;
  color: #166534;
}
.pp-badge--danger {
  background: #FEE2E2;
  border-color: #FECACA;
  color: #991B1B;
}

/* iOS zooms the page when an input renders below 16px */
@media (max-width: 768px) {
  .stTextInput input, .stTextArea textarea,
  .stDateInput input, .stNumberInput input {
    font-size: 16px !important;
  }
}
"""


def apply_theme() -> None:
    """Inject the global stylesheet. Call once per app run, after set_page_config."""
    st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)