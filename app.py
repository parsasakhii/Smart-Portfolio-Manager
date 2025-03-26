import streamlit as st
import pandas as pd
import requests
from fpdf import FPDF
import matplotlib.pyplot as plt
import plotly.express as px
import io
import difflib
import os
from datetime import datetime

st.set_page_config(page_title="Smart Crypto Portfolio Tracker", layout="wide")
st.title("📊 Smart Crypto Portfolio Tracker")

uploaded_file = st.file_uploader("📥 Upload your Excel position file", type=["xlsx"])

def fetch_coin_list():
    cache_path = "coins_list.csv"
    max_age_seconds = 86400  # 1 روز

    if os.path.exists(cache_path):
        last_modified = os.path.getmtime(cache_path)
        age = datetime.now().timestamp() - last_modified
        if age < max_age_seconds:
            try:
                df_cached = pd.read_csv(cache_path)
                if 'symbol' in df_cached.columns:
                    return df_cached
            except:
                pass

    # اگر کش معتبر نبود، دریافت مجدد از API
    url = "https://api.coingecko.com/api/v3/coins/list"
    response = requests.get(url)
    if response.status_code == 200:
        coins = pd.DataFrame(response.json())
        if 'symbol' in coins.columns:
            coins.to_csv(cache_path, index=False)
        return coins
    return pd.DataFrame()

coins_df = fetch_coin_list()

# بررسی صحت ستون‌های مورد نیاز
if 'symbol' not in coins_df.columns:
    st.error("❌ CoinGecko response is missing 'symbol'. Please check your connection or try again later.")
    st.stop()

STABLE_TOKENS = ["USDT", "Tether", "BCC"]

def generate_pdf(df, active_alloc):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", 'B', 18)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 10, "Crypto Portfolio Summary", ln=True, align='C')
    pdf.ln(3)

    pdf.set_font("Arial", '', 10)
    today = datetime.today().strftime('%Y-%m-%d')
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, f"Generated on: {today}", ln=True, align='C')
    pdf.set_text_color(0, 0, 0)
    pdf.ln(10)

    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 10, f"Total Capital Deployed: {active_alloc:.2f}%", ln=True, align='L')
    pdf.ln(6)

    pdf.set_font("Arial", 'B', 12)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(0, 10, "Portfolio Breakdown", ln=True, align='L', fill=True)
    pdf.ln(2)

    pdf.set_font("Arial", 'B', 10)
    col_widths = [45, 40, 50, 40]
    headers = ["Token", "Target Allocation", "Live Price (USD)", "Activated (%)"]
    x_center = (210 - sum(col_widths)) / 2
    pdf.set_x(x_center)
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 8, header, border=1, align='C')
    pdf.ln()

    pdf.set_font("Arial", '', 9)
    for _, row in df.iterrows():
        values = [str(row['Token']), str(row['Target Allocation (%)']), str(row['Live Price (USD)']), str(row['Activated (%)'])]
        pdf.set_x(x_center)
        for i, val in enumerate(values):
            pdf.cell(col_widths[i], 8, val, border=1, align='C')
        pdf.ln()

    pdf.add_page()
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Target Allocation Chart", ln=True, align='C')
    pdf.ln(5)

    fig, ax = plt.subplots(figsize=(6, 6))
    wedges, texts, autotexts = ax.pie(
        df['Target Allocation (%)'],
        labels=None,
        autopct='%1.1f%%',
        startangle=140,
        textprops={'fontsize': 8}
    )
    ax.set_title('Distribution by Token', fontsize=12)
    ax.legend(df['Token'], loc='center left', bbox_to_anchor=(1, 0.5), fontsize=8)
    chart_path = "chart_temp.png"
    plt.tight_layout()
    plt.savefig(chart_path)
    plt.close()
    pdf.image(chart_path, x=30, w=150)
    os.remove(chart_path)

    output = io.BytesIO()
    pdf.output(output)
    return output

def match_token_to_id(token, coins_df):
    token_lower = token.lower()
    exact_symbol = coins_df[coins_df['symbol'].str.lower() == token_lower]
    if not exact_symbol.empty:
        if token_lower == 'btc':
            btc_row = exact_symbol[exact_symbol['name'].str.lower() == 'bitcoin']
            if not btc_row.empty:
                return btc_row.iloc[0]['id']
        name_matches = exact_symbol['name'].str.lower().tolist()
        close_name = difflib.get_close_matches(token_lower, name_matches, n=1)
        if close_name:
            matched_row = exact_symbol[exact_symbol['name'].str.lower() == close_name[0]]
            return matched_row.iloc[0]['id']
        return exact_symbol.iloc[0]['id']
    else:
        name_match = coins_df[coins_df['name'].str.lower() == token_lower]
        if not name_match.empty:
            return name_match.iloc[0]['id']
    return None

if uploaded_file:
    df = pd.read_excel(uploaded_file)
    df.columns = df.columns.str.strip()
    df = df[df["Token"].notna()]

    target_allocations = {}
    tokens = list(df['Token'].unique())
    use_custom_alloc = "Target Allocation" in df.columns
    total_alloc = 0

    for token in tokens:
        if use_custom_alloc:
            alloc = df[df['Token'] == token]["Target Allocation"].values[0]
        else:
            alloc = round(100 / len(tokens), 2)
        target_allocations[token] = alloc
        total_alloc += alloc

    token_id_map = {}
    unmatched_tokens = []
    for token in tokens:
        matched_id = match_token_to_id(token, coins_df)
        if matched_id:
            token_id_map[token] = matched_id
        else:
            unmatched_tokens.append(token)

    matched_ids = list(token_id_map.values())
    prices = {}
    if matched_ids:
        ids = '%2C'.join(matched_ids)
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd"
        response = requests.get(url)
        prices = response.json() if response.status_code == 200 else {}

    entry_percent = {}
    live_prices = []
    coingecko_ids = []

    st.subheader("✏️ Adjust Activation Manually (Optional)")

    for token in tokens:
        row = df[df['Token'] == token]
        entry1 = row["entry/%(50%)"].values[0] if "entry/%(50%)" in row.columns and not pd.isna(row["entry/%(50%)"].values[0]) else None
        entry2 = row["entry2/%(50%)"].values[0] if "entry2/%(50%)" in row.columns and not pd.isna(row["entry2/%(50%)"].values[0]) else None

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

        manual_value = st.slider(f"{token} - Activated (%)", 0, 100, int(default_percent * 100), step=5)
        entry_percent[token] = manual_value / 100

    active_alloc = sum([target_allocations[t] * entry_percent[t] for t in tokens])

# 📦 بررسی پوزیشن‌های تازه فعال‌شده
import json
state_file = "active_state.json"
previous_state = {}
newly_activated = []

try:
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            previous_state = json.load(f)
except Exception as e:
    st.info("ℹ️ No previous state found or could not be read.")

for token in tokens:
    current = target_allocations[token] * entry_percent[token]
    previous = previous_state.get(token, 0)
    if current > 0 and previous == 0:
        newly_activated.append(f"{token} – {current:.2f}% activated")

if newly_activated:
    with st.expander("🔔 پوزیشن‌های تازه فعال‌شده"):
        for msg in newly_activated:
            st.write(f"- {msg}")

        # 📲 ارسال پیام به تلگرام
        # 📲 ارسال پیام به تلگرام
import requests
bot_token = "7936691621:AAFv9Hh3xXWJCroEIShSDiy9F5ZHRVmWbHA"
chat_id = "711552574"

for msg in newly_activated:
    text = f"🚨 پوزیشن جدید فعال شد:\n{msg}"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, data=payload)
    except:
        st.error("❌ ارسال به تلگرام ناموفق بود")


# 📦 بررسی پوزیشن‌های تازه فعال‌شده
import json
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
    st.warning("🚨 New positions just activated:")
    for msg in newly_activated:
        st.write(f"- {msg}")

with open(state_file, "w") as f:
    json.dump({t: target_allocations[t] * entry_percent[t] * 100 for t in tokens}, f)


with open(state_file, "w") as f:
    json.dump({t: target_allocations[t] * entry_percent[t] * 100 for t in tokens}, f)

    # بررسی فعال‌شدن‌های جدید و ذخیره وضعیت
import json
state_file = "active_state.json"
previous_state = {}
newly_activated = []

if os.path.exists(state_file):
    with open(state_file, "r") as f:
        previous_state = json.load(f)

for token in tokens:
    current = target_allocations[token] * entry_percent[token] * 100
    previous = previous_state.get(token, 0)
    if current > 0 and previous == 0:
        newly_activated.append(f"{token} – {current:.2f}% activated")

if newly_activated:
    st.warning("🚨 New positions just activated:")
    for msg in newly_activated:
        st.write(f"- {msg}")

with open(state_file, "w") as f:
    json.dump({t: target_allocations[t] * entry_percent[t] * 100 for t in tokens}, f)

# 📦 بررسی پوزیشن‌های تازه فعال‌شده
import json
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
    st.warning("🚨 New positions just activated:")
    for msg in newly_activated:
        st.write(f"- {msg}")

with open(state_file, "w") as f:
    json.dump({t: target_allocations[t] * entry_percent[t] for t in tokens}, f)

result_df = pd.DataFrame({
    "Token": tokens,
    "CoinGecko ID": coingecko_ids,
    "Target Allocation (%)": [target_allocations[t] for t in tokens],
    "Live Price (USD)": live_prices,
    "Activated (%)": [target_allocations[t] * entry_percent[t] for t in tokens]
})

# ذخیره و بررسی وضعیت فعال شدن جدید
import json
state_file = "active_state.json"
previous_state = {}
newly_activated = []

if os.path.exists(state_file):
    with open(state_file, "r") as f:
        previous_state = json.load(f)

for token in tokens:
    current = target_allocations[token] * entry_percent[token] * 100
    previous = previous_state.get(token, 0)
    if current > 0 and previous == 0:
        newly_activated.append(f"{token} – {current:.2f}% activated")

# نمایش نوتیفیکیشن در اپلیکیشن
if newly_activated:
    st.warning("🚨 New positions just activated:")
    for msg in newly_activated:
        st.write(f"- {msg}")

# به‌روزرسانی وضعیت برای دفعات بعد
with open(state_file, "w") as f:
    json.dump({t: target_allocations[t] * entry_percent[t] * 100 for t in tokens}, f)

    st.subheader("📋 Portfolio Summary")

    # 📊 Pie Chart
    result_df['Target Allocation (%)'] = result_df['Target Allocation (%)'].astype(float)
    result_df['Activated (%)'] = result_df['Activated (%)'].astype(float)

    fig_pie = px.pie(
        result_df,
        names='Token',
        values='Target Allocation (%)',
        title='Target Allocation by Token',
        hole=0.3
    )
    st.plotly_chart(fig_pie, use_container_width=True)

    # 📉 Bar Chart (normalized)
    df_chart = result_df.copy()
    # مقدار واقعی Activated بدون نرمال‌سازی برای بارچارت
# df_chart['Activated (%)'] = df_chart['Activated (%)'] / 100  # حذف نرمال‌سازی

    fig_bar = px.bar(
        df_chart,
        x='Token',
        y=['Target Allocation (%)', 'Activated (%)'],
        barmode='group',
        title='Target vs Activated Allocation (Normalized)'
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    st.dataframe(result_df)

    if st.button("📄 Generate PDF Report"):
        pdf_file = generate_pdf(result_df, active_alloc)
        st.download_button(
            label="📥 Download Portfolio Report (PDF)",
            data=pdf_file,
            file_name="portfolio_report.pdf",
            mime="application/pdf"
        )
