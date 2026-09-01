# -*- coding: utf-8 -*-
"""
streamlit_app.py — serwuje PM progress rank z gotowego ranking_data.json.

NIE łączy się z bazą w runtime. Dane generuje raz w tygodniu:
    python ranking_lnp.py           (z otwartym tunelem SSH)
co tworzy data/ranking/ranking_data.json — ten plik czyta ta apka.

URUCHOMIENIE:
    pip install streamlit
    streamlit run streamlit_app.py

Zawodnik może wejść na swój link:  <adres-apki>/?me=<player_lnp UUID>
— jego wiersz zostanie podświetlony i przewinięty.
"""
import json
import os
import streamlit as st
import streamlit.components.v1 as components

from ranking_lnp import build_html  # reużywamy generatora HTML

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "ranking", "ranking_data.json")

st.set_page_config(page_title="PM progress rank", page_icon="⚽",
                   layout="centered", initial_sidebar_state="collapsed")

# ukryj chrome Streamlita — czysty, mobilny widok
st.markdown("""<style>
  #MainMenu, header, footer {visibility:hidden;}
  .block-container {padding:0 !important; max-width:600px;}
  .stApp {background:#08080A;}
</style>""", unsafe_allow_html=True)


@st.cache_data(ttl=1800)
def load_data(path, mtime):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


if not os.path.exists(DATA):
    st.error("Brak danych rankingu. Najpierw wygeneruj je poleceniem:\n\n"
             "`python ranking_lnp.py`  (z otwartym tunelem SSH do LNP)")
    st.stop()

d = load_data(DATA, os.path.getmtime(DATA))
me = st.query_params.get("me", "")

html = build_html(
    d["players"], d.get("label", ""), "", d.get("footer", "jesteś jak twój ostatni mecz"),
    d.get("top", 5), d.get("metric", "overall"), d.get("mode", "progress"),
    logo=d.get("logo"), me=me,
)

# wysokość dobrana z zapasem; scrolling=True daje własny scroll wewnątrz
components.html(html, height=2200, scrolling=True)
