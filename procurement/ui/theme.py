"""Global theme layer: the app's CSS design tokens.

One place defines the visual language, ported from the PurchasePilot agent
console design: a "desk and paper" palette — light grey desk, white working
surfaces, navy ink, one carbon-copy blue accent — Schibsted Grotesk for UI
text and Courier Prime for the typed (money/fact) values.

Semantic hues: blue = in progress, amber = uncertain/waiting, green = success,
red = failure. Every color pair used for text meets WCAG AA (4.5:1) on its
own background in the forced light theme:

  ink     #16233A on paper #E6EBF0            ~12.9:1
  muted   #5A6A7F on sheet #F8FAFB            ~5.4:1
  carbon  #22389A on wash #E3E8FA              ~7.4:1
  pass    #1E7A4E on wash #E2F2EA             ~5.3:1
  fail    #B8322A on wash #F7E3E1              ~5.9:1
  query   #9A620E on wash #FBEFD9              ~5.6:1
"""

from __future__ import annotations

import streamlit as st

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Schibsted+Grotesk:wght@400;500;600;700&family=Courier+Prime:wght@400;700&display=swap');

:root {
  --pp-paper: #E6EBF0;   /* the desk behind everything */
  --pp-sheet: #F8FAFB;   /* working surfaces / panels */
  --pp-ink: #16233A;     /* navy ink */
  --pp-muted: #5A6A7F;
  --pp-rule: #C8D1DB;    /* hairlines */
  --pp-carbon: #2B44B8;  /* carbon-copy blue: everything the agent does */
  --pp-carbon-hover: #22389A;
  --pp-carbon-wash: #E3E8FA;
  --pp-pass: #1E7A4E;   --pp-pass-wash: #E2F2EA;
  --pp-fail: #B8322A;   --pp-fail-wash: #F7E3E1;
  --pp-query: #9A620E;  --pp-query-wash: #FBEFD9;
  --pp-slip: #FFFDF6;    /* requisition slip paper */
  --pp-ui: "Schibsted Grotesk", system-ui, -apple-system, "Segoe UI", sans-serif;
  --pp-typed: "Courier Prime", "Courier New", monospace;
}

/* ---------- chrome ---------- */
#MainMenu, .stApp {
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  font-family: var(--pp-ui);
}
.stApp, [data-testid="stAppViewContainer"] {
  background: var(--pp-paper);
  color: var(--pp-ink);
}
[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 1.4rem; font-family: var(--pp-ui); color: var(--pp-ink); }
h1, h2, h3, h4 { letter-spacing: -0.01em; font-family: var(--pp-ui); color: var(--pp-ink); }
h1 { font-weight: 700; }
a { color: var(--pp-carbon); }

[data-testid="stSidebar"] {
  background: var(--pp-sheet);
  border-right: 1px solid var(--pp-rule);
}

/* Bordered containers become the design's "panels" */
[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--pp-sheet);
  border-color: var(--pp-rule) !important;
  border-radius: 10px;
}

/* Hide non-product chrome: Deploy button and the running toast */
[data-testid="stAppDeployButton"], .stDeployButton { display: none !important; }
[data-testid="stStatusWidget"] { display: none !important; }

/* Money and counts in tables keep a stable column width */
[data-testid="stTable"] td,
[data-testid="stDataFrame"] {
  font-variant-numeric: tabular-nums;
}

/* Primary buttons take the carbon accent; secondary become quiet outlines */
.stButton > button[kind="primary"],
.stButton > button[data-testid="st-base-button-primary"] {
  background-color: var(--pp-carbon);
  border-color: var(--pp-carbon);
  color: #fff;
  font-weight: 600;
}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="st-base-button-primary"]:hover {
  background-color: var(--pp-carbon-hover);
  border-color: var(--pp-carbon-hover);
  color: #fff;
}
.stButton > button[kind="secondary"],
.stButton > button[data-testid="st-base-button-secondary"] {
  background-color: transparent;
  border-color: var(--pp-rule);
  color: var(--pp-carbon);
  font-weight: 600;
}
.stButton > button[kind="secondary"]:hover,
.stButton > button[data-testid="st-base-button-secondary"]:hover {
  background-color: var(--pp-carbon-wash);
  border-color: var(--pp-carbon);
  color: var(--pp-carbon-hover);
}

/* ---------- status pills ---------- */
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
  background: #EDF1F5;
  border-color: #DCE3EA;
  color: #51616F;
}
.pp-badge--researching {
  background: var(--pp-carbon-wash);
  border-color: #C9D3F3;
  color: #22389A;
}
.pp-badge--pending {
  background: var(--pp-query-wash);
  border-color: #F0DFB6;
  color: var(--pp-query);
}
.pp-badge--success {
  background: var(--pp-pass-wash);
  border-color: #C4E4D2;
  color: var(--pp-pass);
}
.pp-badge--danger {
  background: var(--pp-fail-wash);
  border-color: #EDC8C4;
  color: var(--pp-fail);
}

/* ---------- verdict stamps (evidence panel) ---------- */
.pp-stamp {
  display: inline-block;
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: 0.02em;
  padding: 1px 7px;
  border-radius: 4px;
  border: 1.5px solid;
  margin-left: 6px;
  vertical-align: 1px;
  white-space: nowrap;
}
.pp-stamp--PASS { color: var(--pp-pass); border-color: var(--pp-pass); background: var(--pp-pass-wash); }
.pp-stamp--FAIL { color: var(--pp-fail); border-color: var(--pp-fail); background: var(--pp-fail-wash); }
.pp-stamp--UNKNOWN { color: var(--pp-query); border-color: var(--pp-query); background: var(--pp-query-wash); }
.pp-stamp--WAIT { color: var(--pp-muted); border-color: var(--pp-rule); }
.pp-stamp--REC { color: var(--pp-carbon-hover); border-color: var(--pp-carbon); background: var(--pp-carbon-wash); }

/* Streamlit's markdown container styles semantic tags (p/ul/ol/li/dl) with a
   specificity that beats plain component classes, silently resetting the
   design's sizes to 16px. The component selectors below are prefixed with
   the container's own testid to win that fight. */
[data-testid="stMarkdownContainer"] .pp-parsed { list-style: none; margin: 0; padding: 0; font-size: 14px; }
[data-testid="stMarkdownContainer"] .pp-parsed li {
  display: flex; justify-content: space-between; gap: 12px;
  padding: 5px 0; border-bottom: 1px dashed var(--pp-rule);
}
[data-testid="stMarkdownContainer"] .pp-parsed li span:first-child { color: var(--pp-muted); }
[data-testid="stMarkdownContainer"] .pp-parsed li span:last-child { text-align: right; font-weight: 500; }

/* ---------- browser viewer ---------- */
.pp-viewer {
  border: 1px solid var(--pp-rule);
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
  margin-bottom: 14px;
}
.pp-viewer__url {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--pp-rule);
  font-size: 13px; color: var(--pp-muted);
  background: #F1F4F7;
}
.pp-viewer__dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #B9C3CF; flex: none;
}
.pp-viewer--live .pp-viewer__dot {
  background: var(--pp-carbon);
  animation: pp-pulse 1.2s ease-in-out infinite;
}
.pp-viewer__url code {
  font-family: var(--pp-ui); font-size: 13px; color: var(--pp-ink);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.pp-viewer__doing { padding: 10px 12px; font-size: 13px; line-height: 1.45; min-height: 40px; }
.pp-viewer__doing em { font-style: normal; color: var(--pp-carbon); font-weight: 600; }
@keyframes pp-pulse { 50% { opacity: 0.35; } }

/* ---------- run track ---------- */
[data-testid="stMarkdownContainer"] .pp-track { list-style: none; margin: 0; padding: 0; position: relative; }
[data-testid="stMarkdownContainer"] .pp-step { position: relative; padding: 0 0 22px 40px; }
.pp-step::before {
  content: ""; position: absolute; left: 13px; top: 28px; bottom: 0;
  width: 2px; background: var(--pp-rule);
}
.pp-step:last-child::before { display: none; }
.pp-step__mark {
  position: absolute; left: 0; top: 0;
  width: 28px; height: 28px; border-radius: 50%;
  border: 2px solid var(--pp-rule);
  background: var(--pp-sheet);
  display: grid; place-items: center;
  font-size: 13px; font-weight: 700; color: var(--pp-muted);
}
.pp-step--working .pp-step__mark { border-color: var(--pp-carbon); color: var(--pp-carbon); }
.pp-step--working .pp-step__mark::after {
  content: ""; position: absolute; inset: -6px; border-radius: 50%;
  border: 2px solid var(--pp-carbon); opacity: 0.25;
  animation: pp-pulse 1.2s infinite;
}
.pp-step--done .pp-step__mark { background: var(--pp-carbon); border-color: var(--pp-carbon); color: #fff; }
.pp-step--skipped .pp-step__mark { border-style: dashed; }
.pp-step__title { margin: 2px 0 3px; font-size: 14.5px; font-weight: 600; color: var(--pp-ink); }
[data-testid="stMarkdownContainer"] .pp-step__sub { margin: 0 0 4px; font-size: 12px; line-height: 1.45; color: var(--pp-muted); }
[data-testid="stMarkdownContainer"] .pp-log { list-style: none; margin: 6px 0 0; padding: 0; font-size: 12.5px; line-height: 1.45; }
[data-testid="stMarkdownContainer"] .pp-log li { padding: 2.5px 0 2.5px 14px; position: relative; }
.pp-log li::before {
  content: ""; position: absolute; left: 0; top: 11px;
  width: 6px; height: 2px; background: var(--pp-carbon);
}
.pp-log li.pp-log--found::before { background: var(--pp-pass); }
.pp-log li.pp-log--warn::before { background: var(--pp-query); }
.pp-log li.pp-log--fail::before { background: var(--pp-fail); }

/* Run-console panels wrap to full-width rows instead of squashing on
   narrow viewports (scoped to the console via its kicker, so other column
   layouts — chat sessions, approvals — are untouched). */
[data-testid="stHorizontalBlock"]:has(.pp-kicker) {
  flex-wrap: wrap;
}
[data-testid="stHorizontalBlock"]:has(.pp-kicker) > [data-testid="stColumn"] {
  flex: 1 1 340px;
  min-width: 320px;
}

/* ---------- offers ---------- */
[data-testid="stMarkdownContainer"] .pp-offer {
  display: grid; grid-template-columns: 1fr auto; gap: 2px 10px;
  padding: 9px 0; border-bottom: 1px solid var(--pp-rule);
}
.pp-offer__name { font-weight: 600; font-size: 14px; color: var(--pp-ink); }
.pp-offer__price {
  text-align: right; font-weight: 600; font-size: 14px;
  font-family: var(--pp-typed); color: var(--pp-ink);
}
.pp-offer__meta { grid-column: 1 / -1; font-size: 12.5px; color: var(--pp-muted); }
.pp-offer__why { grid-column: 1 / -1; font-size: 12.5px; color: var(--pp-fail); }
.pp-offer--unknown .pp-offer__why { color: var(--pp-query); }
[data-testid="stMarkdownContainer"] .pp-empty { font-size: 13.5px; color: var(--pp-muted); padding: 14px 0; }

/* ---------- requisition slip (the signature piece) ---------- */
.pp-slip {
  background: var(--pp-slip);
  border: 1px solid #DAD3BE;
  border-radius: 4px 4px 0 0;
  padding: 18px 18px 22px;
  position: relative;
  box-shadow: 0 10px 24px rgba(22, 35, 58, 0.10);
  animation: pp-print 0.9s cubic-bezier(0.2, 0.8, 0.2, 1);
  margin-bottom: 8px;
}
.pp-slip::after {
  content: ""; position: absolute; left: 0; right: 0; bottom: -8px; height: 8px;
  background: radial-gradient(circle at 6px -2px, transparent 6px, var(--pp-slip) 6.5px) 0 0 / 12px 8px repeat-x;
}
.pp-slip__header {
  display: flex; justify-content: space-between; align-items: baseline;
  border-bottom: 1.5px solid var(--pp-ink);
  padding-bottom: 6px; margin-bottom: 10px;
}
.pp-slip__header strong { font-size: 15px; color: var(--pp-ink); }
.pp-slip__header span { font-size: 12.5px; color: var(--pp-muted); }
[data-testid="stMarkdownContainer"] .pp-slip__says { font-size: 14px; margin: 0 0 12px; color: var(--pp-ink); }
[data-testid="stMarkdownContainer"] .pp-slip dl {
  display: grid; grid-template-columns: auto 1fr;
  gap: 5px 14px; margin: 0; font-size: 13px;
}
[data-testid="stMarkdownContainer"] .pp-slip dt { color: var(--pp-muted); }
[data-testid="stMarkdownContainer"] .pp-slip dd {
  margin: 0; text-align: right;
  font-family: var(--pp-typed); font-size: 14px; color: var(--pp-ink);
}
[data-testid="stMarkdownContainer"] .pp-slip dd.pp-slip__total { font-weight: 700; font-size: 16px; }
.pp-slip__notes {
  margin: 12px 0 0; padding: 10px 0 0;
  border-top: 1px dashed #CFC6AC; font-size: 13px; color: var(--pp-muted);
}
[data-testid="stMarkdownContainer"] .pp-slip__notes p { margin: 0 0 6px; }
.pp-approved {
  display: inline-block; transform: rotate(-6deg);
  border: 2.5px solid var(--pp-pass); color: var(--pp-pass);
  font-weight: 700; padding: 2px 9px; border-radius: 5px; font-size: 13px;
}

@keyframes pp-print {
  from { transform: translateY(24px); opacity: 0; }
  to { transform: none; opacity: 1; }
}

/* ---------- misc ---------- */
[data-testid="stMarkdownContainer"] .pp-kicker { font-size: 13px; font-weight: 600; color: var(--pp-muted); margin: 0 0 8px; }
.pp-total-row { font-family: var(--pp-typed); }

/* iOS zooms the page when an input renders below 16px */
@media (max-width: 768px) {
  .stTextInput input, .stTextArea textarea,
  .stDateInput input, .stNumberInput input {
    font-size: 16px !important;
  }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
"""


def apply_theme() -> None:
    """Inject the global stylesheet. Call once per app run, after set_page_config."""
    st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)