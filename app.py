
import streamlit as st
import pandas as pd
import requests
from fpdf import FPDF
import matplotlib.pyplot as plt
import plotly.express as px
import io
import difflib
import os
import json
from datetime import datetime

st.set_page_config(page_title="Smart Crypto Portfolio Tracker", layout="wide")
st.title("📊 Smart Crypto Portfolio Tracker")

uploaded_file = st.file_uploader("📥 Upload your Excel position file", type=["xlsx"])

def fetch_coin_list():
    cache_path = "coins_list.csv"
    max_age_seconds = 86400
    if os.path.exists(cache_path):
        last_modified = os.path.getmtime(cache_path)
        age = datetime.now().timestamp() - last_modified
        if age < max_age_seconds:
            try:
                df_cached = pd.read_csv(cache_path)
                if 'symbol' in df_cached.columns:
                    return df_cached
            except: pass
    url = "https://api.coingecko.com/api/v3/coins/list"
    response = requests.get(url)
    if response.status_code == 200:
        coins = pd.DataFrame(response.json())
        if 'symbol' in coins.columns:
            coins.to_csv(cache_path, index=False)
            return coins
    return pd.DataFrame()

coins_df = fetch_coin_list()

if 'symbol' not in coins_df.columns:
    st.error("❌ CoinGecko response is missing 'symbol'.")
    st.stop()

STABLE_TOKENS = ["USDT", "Tether", "BCC"]

def match_token_to_id(token, coins_df):
    token_lower = token.lower()
    exact_symbol = coins_df[coins_df['symbol'].str.lower() == token_lower]
    if not exact_symbol.empty:
        if token_lower == 'btc':
            btc_row = exact_symbol[exact_symbol['name'].str.lower() == 'bitcoin']
            if not btc_row.empty:
                return btc_row.iloc[0]['id']
        return exact_symbol.iloc[0]['id']
    close = difflib.get_close_matches(token_lower, coins_df['name'].str.lower(), n=1)
    if close:
        fuzzy = coins_df[coins_df['name'].str.lower() == close[0]]
        if not fuzzy.empty:
            return fuzzy.iloc[0]['id']
    return None

if uploaded_file:
    df = pd.read_excel(uploaded_file)
    df.columns = df.columns.str.strip()
    df = df[df["Token"].notna()]
    tokens = list(df["Token"].unique())
    target_allocations = {}
    use_custom_alloc = "Target Allocation" in df.columns

    for token in tokens:
        if use_custom_alloc:
            alloc = df[df["Token"] == token]["Target Allocation"].values[0]
        else:
            alloc = round(100 / len(tokens), 2)
        target_allocations[token] = alloc

    token_id_map = {}
    for token in tokens:
        matched_id = match_token_to_id(token, coins_df)
        if matched_id:
            token_id_map[token] = matched_id

    ids = "%2C".join(token_id_map.values())
    prices = {}
    if ids:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd"
        response = requests.get(url)
        if response.status_code == 200:
            prices = response.json()

    entry_percent = {}
    live_prices = []
    coingecko_ids = []

    st.subheader("✏️ Adjust Activation Manually (Optional)")

    for token in tokens:
        row = df[df["Token"] == token]
        entry1 = row["entry/%(50%)"].values[0] if "entry/%(50%)" in row.columns else None
        entry2 = row["entry2/%(50%)"].values[0] if "entry2/%(50%)" in row.columns else None

        try:
            entry1 = float(str(entry1).replace(",", "").replace("$", "").strip()) if entry1 else None
        except: entry1 = None
        try:
            entry2 = float(str(entry2).replace(",", "").replace("$", "").strip()) if entry2 else None
        except: entry2 = None

        coingecko_id = token_id_map.get(token, "N/A")
        price = prices.get(coingecko_id, {}).get("usd") if coingecko_id != "N/A" else None
        coingecko_ids.append(coingecko_id)
        live_prices.append(price if price else "-")

        default_percent = 0.0
        if token.upper() in STABLE_TOKENS:
            default_percent = 1.0
        elif entry1 and not entry2:
            if price and price <= entry1:
                default_percent = 1.0
        elif entry1 and entry2:
            if price and price <= entry1:
                default_percent += 0.5
            if price and price <= entry2:
                default_percent += 0.5

        manual_value = st.slider(f"{token} – Activated (%)", 0, 100, int(default_percent * 100), step=5)
        entry_percent[token] = manual_value / 100

    state_file = "active_state.json"
    previous_state = {}
    newly_activated = []

    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            previous_state = json.load(f)

    for token in tokens:
        current = target_allocations[token] * entry_percent[token]
        previous = previous_state.get(token, 0)
        if current > 0 and previous == 0:
            newly_activated.append(f"{token} – {current:.2f}% activated")

    if newly_activated:
        with st.expander("🔔 پوزیشن‌های تازه فعال‌شده"):
            for msg in newly_activated:
                st.write(f"- {msg}")

        bot_token = os.environ.get("BOT_TOKEN")
        chat_id = os.environ.get("CHAT_ID")
        if bot_token and chat_id:
            for msg in newly_activated:
                text = f"🚨 پوزیشن جدید فعال شد:\n{msg}"
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {"chat_id": chat_id, "text": text}
                try:
                    requests.post(url, data=payload)
                except:
                    st.error("❌ ارسال به تلگرام ناموفق بود")

    with open(state_file, "w") as f:
        json.dump({t: target_allocations[t] * entry_percent[t] for t in tokens}, f)
