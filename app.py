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
import tempfile
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

def generate_pdf(df, active_alloc):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "Crypto Portfolio Summary", ln=True, align='C')
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 10, f"Total Capital Deployed: {active_alloc:.2f}%", ln=True, align='C')
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 10)
    headers = ["Token", "Live Price (USD)", "Target Allocation (%)", "Activated (%)"]
    col_widths = [40, 40, 50, 50]
    x_start = (210 - sum(col_widths)) / 2
    pdf.set_x(x_start)
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 8, header, border=1, align='C')
    pdf.ln()

    pdf.set_font("Arial", '', 10)
    for _, row in df.iterrows():
        values = [str(row["Token"]), str(row["Live Price (USD)"]),
                  str(row["Target Allocation (%)"]), str(row["Activated (%)"])]
        pdf.set_x(x_start)
        for i, val in enumerate(values):
            pdf.cell(col_widths[i], 8, val, border=1, align='C')
        pdf.ln()

    chart_path = "pie_chart_temp.png"
    fig, ax = plt.subplots(figsize=(6, 6))
    wedges, texts, autotexts = ax.pie(df['Target Allocation (%)'], autopct='%1.1f%%', startangle=140)

    legend_labels = [
        f"{token} ({percent:.1f}%)"
        for token, percent in zip(df['Token'], df['Target Allocation (%)'])
    ]

    ax.legend(legend_labels, title="Tokens", loc="center left", bbox_to_anchor=(1, 0.5), fontsize=8)
    ax.set_title("Target Allocation Pie Chart", fontsize=12)
    plt.tight_layout()
    plt.savefig(chart_path)
    plt.close()

    pdf.add_page()
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Target Allocation Chart", ln=True, align='C')
    pdf.image(chart_path, x=30, w=150)
    os.remove(chart_path)

    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        pdf.output(tmp.name)
        tmp.seek(0)
        return tmp.read()

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
        entry_percent[token] = default_percent

    result_df = pd.DataFrame({
        "Token": tokens,
        "Live Price (USD)": live_prices,
        "Target Allocation (%)": [target_allocations[t] for t in tokens],
        "Activated (%)": [target_allocations[t] * entry_percent[t] for t in tokens]
    })

    active_alloc = sum(result_df["Activated (%)"])

    st.subheader("📊 Portfolio Summary")
    st.plotly_chart(
        px.pie(result_df, names='Token', values='Target Allocation (%)', title='Target Allocation'),
        use_container_width=True
    )

    st.plotly_chart(
        px.bar(result_df, x='Token', y=['Target Allocation (%)', 'Activated (%)'],
               barmode='group', title='Target vs Activated Allocation'),
        use_container_width=True
    )

    st.dataframe(result_df)

    if st.button("📄 Generate PDF Report"):
        pdf_file = generate_pdf(result_df, active_alloc)
        st.download_button(
            label="📥 Download Portfolio Report",
            data=pdf_file,
            file_name="portfolio_report.pdf",
            mime="application/pdf"
        )