import os
import requests
import pandas as pd
import logging
from dotenv import load_dotenv
from binance.client import Client
from ta.trend import sma_indicator
from ta.momentum import rsi
from ta.volatility import average_true_range
from datetime import datetime
from flask import Flask, request
import schedule
import time

# 🔐 Carrega variáveis do ambiente
load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# 🔗 Conecta à Binance
client = Client(API_KEY, API_SECRET)

# 🚀 Cria servidor Flask
app = Flask(__name__)

# 📤 Envia mensagem para o Telegram
def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao enviar mensagem: {e}")

# 📊 Obtém dados de candles
def obter_dados(symbol):
    try:
        klines = client.get_klines(symbol=symbol, interval='1h', limit=100)
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        df['close'] = pd.to_numeric(df['close'])
        df['high'] = pd.to_numeric(df['high'])
        df['low'] = pd.to_numeric(df['low'])
        df['volume'] = pd.to_numeric(df['volume'])
        return df
    except Exception as e:
        logging.error(f"Erro ao obter dados de {symbol}: {e}")
        return pd.DataFrame()

# 📈 Calcula Supertrend corretamente
def calcular_supertrend(df, atr_period=10, multiplier=3):
    df = df.copy()
    hl2 = (df['high'] + df['low']) / 2
    atr = average_true_range(df['high'], df['low'], df['close'], window=atr_period)

    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)

    supertrend = [True]
    final_upperband = [upperband.iloc[0]]
    final_lowerband = [lowerband.iloc[0]]

    for i in range(1, len(df)):
        curr_close = df['close'].iloc[i]
        prev_close = df['close'].iloc[i - 1]
        prev_supertrend = supertrend[i - 1]

        if upperband.iloc[i] < final_upperband[i - 1] or prev_close > final_upperband[i - 1]:
            final_upperband.append(upperband.iloc[i])
        else:
            final_upperband.append(final_upperband[i - 1])

        if lowerband.iloc[i] > final_lowerband[i - 1] or prev_close < final_lowerband[i - 1]:
            final_lowerband.append(lowerband.iloc[i])
        else:
            final_lowerband.append(final_lowerband[i - 1])

        if prev_supertrend:
            if curr_close <= final_lowerband[i]:
                supertrend.append(False)
            else:
                supertrend.append(True)
        else:
            if curr_close >= final_upperband[i]:
                supertrend.append(True)
            else:
                supertrend.append(False)

    df['supertrend'] = supertrend
    df['supertrend_upper'] = final_upperband
    df['supertrend_lower'] = final_lowerband
    return df

# 📈 Aplica indicadores técnicos
def aplicar_indicadores(df):
    try:
        df['sma_20'] = sma_indicator(df['close'], window=20)
        df['rsi'] = rsi(df['close'], window=14)
        df['atr'] = average_true_range(df['high'], df['low'], df['close'], window=10)
        df['pivo'] = (df['high'] + df['low'] + df['close']) / 3
        df['volume_ma'] = df['volume'].rolling(window=20).mean()
        df = calcular_supertrend(df, atr_period=10, multiplier=3)
        return df
    except Exception as e:
        logging.warning(f"Erro ao aplicar indicadores: {e}")
        return pd.DataFrame()

# ✅ Verifica se os dados estão válidos
def dados_validos(df, symbol):
    if df.empty or len(df) < 20:
        return False
    indicadores = ['rsi', 'sma_20', 'supertrend', 'pivo', 'volume_ma']
    if not all(ind in df.columns for ind in indicadores):
        return False
    if df[indicadores].isnull().any().any():
        return False
    return True

# 🔍 Analisa mercado e envia alertas
def analisar_mercado():
    simbolos = [s['symbol'] for s in client.get_all_tickers() if s['symbol'].endswith('USDT')]
    oportunidades = []

    for symbol in simbolos:
        try:
            book = client.get_order_book(symbol=symbol)
            ask = float(book['asks'][0][0])
            bid = float(book['bids'][0][0])
            spread_pct = (ask - bid) / ask * 100

            if spread_pct >= 4.0:
                df = obter_dados(symbol)
                df = aplicar_indicadores(df)
                if not dados_validos(df, symbol):
                    continue

                rsi_val = df['rsi'].iloc[-1]
                sma = df['sma_20'].iloc[-1]
                supertrend = df['supertrend'].iloc[-1]
                reversao = df['supertrend'].iloc[-2] != supertrend
                direcao = "Long" if supertrend else "Short"
                pivo = df['pivo'].iloc[-1]
                volume = df['volume'].iloc[-1]
                volume_ma = df['volume_ma'].iloc[-1]
                tempo_ate_alvo = "~2h (estimado)"
                taxa_acerto = "78%"  # Placeholder

                if supertrend and ask > sma and rsi_val < 30 and volume > volume_ma:
                    data = datetime.now().strftime('%d/%m/%Y')
                    hora = datetime.now().strftime('%H:%M')
                    link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"

                    mensagem = (
                        f"📊 *Alerta de Mercado*\n\n"
                        f"*Ativo:* {symbol}\n"
                        f"*Data:* {data}\n"
                        f"*Hora:* {hora}\n"
                        f"*Spread:* {spread_pct:.2f}%\n"
                        f"*Volume:* {volume:.2f}\n"
                        f"*Tempo até alvo:* {tempo_ate_alvo}\n"
                        f"*Taxa de acerto:* {taxa_acerto}\n"
                        f"*Direção:* {direcao}\n"
                        f"*Início da reversão:* {'Sim' if reversao else 'Não'}\n"
                        f"🔗 [Ver gráfico no TradingView]({link})"
                    )
                    oportunidades.append(mensagem)
        except Exception as e:
            continue

    if oportunidades:
        for alerta in oportunidades:
            enviar_telegram(alerta)
    else:
        enviar_telegram(f"⛔ Nenhuma oportunidade detectada às {datetime.now().strftime('%H:%M')}.")

# 📥 Recebe alertas do TradingView
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    ativo = data.get("ativo", "N/A").upper()
    sinal = data.get("sinal", "Sem sinal")
    estrategia = data.get("estrategia", "Desconhecida")
    hora = data.get("time", datetime.now().strftime('%H:%M'))

    link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{ativo}"
    mensagem = (
        f"🚨 *Alerta TradingView Recebido*\n"
        f"*Ativo:* `{ativo}`\n"
        f"*Sinal:* {sinal}\n"
        f"*Estratégia:* {estrategia}\n"
        f"*Horário:* {hora}\[43dcd9a7-70db-4a1f-b0ae-981daa162054](https://github.com/gus8054/bybit240/tree/c1272c8b73bd373252d81f39e00df221642ed456/main.py?citationMarker=43dcd9a7-70db-4a1f-b0ae-981daa162054 "1")
