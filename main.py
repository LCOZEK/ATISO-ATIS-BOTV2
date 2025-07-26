import discord
from discord.ext import commands
import aiohttp
import datetime
import asyncio
from gtts import gTTS
import os
import re
import csv

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

AVWX_API_TOKEN = "DDToehwLH7NUo1qAaj0YlmTeMGBFgDrpnIdS-vAX_Fk"

phonetic_dict = {
    'A': 'Alpha', 'B': 'Bravo', 'C': 'Charlie', 'D': 'Delta', 'E': 'Echo',
    'F': 'Foxtrot', 'G': 'Golf', 'H': 'Hotel', 'I': 'India', 'J': 'Juliet',
    'K': 'Kilo', 'L': 'Lima', 'M': 'Mike', 'N': 'November', 'O': 'Oscar',
    'P': 'Papa', 'Q': 'Quebec', 'R': 'Romeo', 'S': 'Sierra', 'T': 'Tango',
    'U': 'Uniform', 'V': 'Victor', 'W': 'Whiskey', 'X': 'X-ray', 'Y': 'Yankee',
    'Z': 'Zulu'
}

def phonetic(text):
    return ' '.join(phonetic_dict.get(c.upper(), c) for c in text)

def phonetic_replace(match):
    word = match.group(0)
    if len(word) == 4 and word.isalpha():
        return phonetic(word)
    elif len(word) == 1 and word.isalpha():
        return phonetic(word)
    else:
        return word

def phonetic_text(text):
    pattern = re.compile(r'\b([A-Za-z]{4}|[A-Za-z]{1})\b')
    return pattern.sub(phonetic_replace, text)

def prepare_speech_text(text):
    def repl(m):
        return ' '.join(m.group(0))
    text = re.sub(r'\d+', repl, text)
    text = text.replace('Zulu', 'Z')
    return text

def parse_iso_time(dt_str):
    if dt_str is None:
        return None
    if dt_str.endswith('Z'):
        dt_str = dt_str[:-1] + '+00:00'
    try:
        return datetime.datetime.fromisoformat(dt_str)
    except Exception:
        return None

def load_runways_from_csv(filename='runways.csv'):
    runways_dict = {}
    try:
        with open(filename, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                icao = row['airport_ident']
                runway_name = row['le_ident']
                if icao not in runways_dict:
                    runways_dict[icao] = []
                if runway_name and runway_name not in runways_dict[icao]:
                    runways_dict[icao].append(runway_name)
    except FileNotFoundError:
        print(f"Brak pliku {filename}. Używany będzie pusty słownik pasów.")
    return runways_dict

runways_dict = load_runways_from_csv()

def build_atis_text(data, icao, atis_letter):
    time_recorded_iso = data.get('time', {}).get('dt')
    dt = parse_iso_time(time_recorded_iso)
    if dt:
        recorded_time = dt.strftime('%H%M') + " Zulu"
    else:
        now = datetime.datetime.utcnow()
        recorded_time = now.strftime('%H%M') + " Zulu"

    wind_dir = data.get('wind_direction', {}).get('value')
    wind_speed = data.get('wind_speed', {}).get('value')
    visibility = data.get('visibility', {}).get('value')
    temp = data.get('temperature', {}).get('value')
    dewpoint = data.get('dewpoint', {}).get('value')
    altimeter = data.get('altimeter', {}).get('value')

    remarks = data.get('remarks', '')
    runway_conditions = data.get('runway_conditions', '')

    runways = []
    if 'runway' in data and data['runway']:
        if isinstance(data['runway'], list):
            for rwy in data['runway']:
                if isinstance(rwy, dict) and 'name' in rwy:
                    runways.append(rwy['name'])
                elif isinstance(rwy, str):
                    runways.append(rwy)
        elif isinstance(data['runway'], dict):
            if 'name' in data['runway']:
                runways.append(data['runway']['name'])
        elif isinstance(data['runway'], str):
            runways.append(data['runway'])

    if not runways and runway_conditions:
        if isinstance(runway_conditions, list):
            for cond in runway_conditions:
                if isinstance(cond, dict) and 'runway' in cond and 'name' in cond['runway']:
                    runways.append(cond['runway']['name'])
                elif isinstance(cond, str):
                    runways += re.findall(r'\b\d{1,2}[LR]?\b', cond)
        elif isinstance(runway_conditions, dict):
            if 'runway' in runway_conditions and 'name' in runway_conditions['runway']:
                runways.append(runway_conditions['runway']['name'])
        elif isinstance(runway_conditions, str):
            runways += re.findall(r'\b\d{1,2}[LR]?\b', runway_conditions)

    if not runways and remarks:
        runways += re.findall(r'\b\d{1,2}[LR]?\b', remarks)

    if not runways:
        runways = runways_dict.get(icao, [])

    if runways and isinstance(runways[0], str) and "/" in runways[0]:
        rwy_arrival, rwy_departure = runways[0].split('/')
    elif runways:
        rwy_arrival = runways[0]
        rwy_departure = runways[1] if len(runways) > 1 else runways[0]
    else:
        rwy_arrival = rwy_departure = "Unknown"

    embed_text = (
        f"{icao} Tower Information {atis_letter.upper()} recorded at {recorded_time}.\n"
        f"{icao} METAR {recorded_time.replace('Zulu', 'Z')} "
    )
    if wind_dir is not None and wind_speed is not None:
        embed_text += f"{wind_dir:03d}{wind_speed}KT "
    if visibility is not None:
        embed_text += f"Visibility {visibility} meters "
    if temp is not None and dewpoint is not None:
        embed_text += f"Temperature {temp} degrees Celsius, Dewpoint {dewpoint} degrees Celsius "
    if altimeter is not None:
        embed_text += f"Altimeter {altimeter} hectopascals\n"

    embed_text += (
        f"ARR RWY {rwy_arrival} / DEP RWY {rwy_departure} / TRL FL80 / TA 6500ft\n"
        f"RWY {rwy_arrival} RWY {rwy_departure} "
    )
    if runway_conditions:
        embed_text += f"RWY condition codes. {runway_conditions}\n"
    elif remarks:
        embed_text += f"{remarks}\n"

    embed_text += f"Confirm ATIS info {atis_letter.upper()} on initial contact."

    speech_text = phonetic_text(embed_text)
    speech_text = prepare_speech_text(speech_text)

    return embed_text, speech_text

@bot.command()
async def atis(ctx, icao: str):
    icao = icao.upper()
    atis_letter = "Charlie"

    if ctx.author.voice and ctx.author.voice.channel:
        voice_channel = ctx.author.voice.channel
    else:
        await ctx.send("Musisz być na kanale głosowym, żeby odtworzyć ATIS.")
        return

    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {AVWX_API_TOKEN}"}
        url = f"https://avwx.rest/api/metar/{icao}"
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                await ctx.send(f"Nie udało się pobrać danych dla {icao}.")
                return
            data = await resp.json()

    embed_text, speech_text = build_atis_text(data, icao, atis_letter)

    embed = discord.Embed(title=f"ATIS dla {icao}", description=embed_text, color=0x1E90FF)
    await ctx.send(embed=embed)

    try:
        vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        if not vc or not vc.is_connected():
            vc = await voice_channel.connect()
        elif vc.channel != voice_channel:
            await vc.move_to(voice_channel)
    except Exception as e:
        await ctx.send(f"Nie udało się połączyć z kanałem głosowym: {e}")
        return

    filename = f"atis_{icao}.mp3"
    tts = gTTS(speech_text, lang='en', slow=False, tld='com')
    tts.save(filename)

    def after_playing(error):
        coro = vc.disconnect()
        fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        try:
            fut.result()
        except Exception:
            pass
        try:
            os.remove(filename)
        except Exception:
            pass

    vc.play(discord.FFmpegPCMAudio(executable="ffmpeg", source=filename), after=after_playing)

@bot.command()
async def metar(ctx, icao: str, *, opis: str = None):
    icao = icao.upper()
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {AVWX_API_TOKEN}"}
        url = f"https://avwx.rest/api/metar/{icao}"
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                await ctx.send(f"Nie udało się pobrać danych METAR dla {icao}.")
                return
            data = await resp.json()

    raw_metar = data.get("raw", "Brak danych METAR.")
    czas = data.get("time", {}).get("repr", "Nieznany")

    embed = discord.Embed(
        title=f"METAR dla {icao}",
        description=f"```\n{raw_metar}\n```",
        color=0x0fa3ff
    )
    embed.set_footer(text=f"Czas raportu: {czas}")

    if opis:
        embed.add_field(name="Opis", value=opis, inline=False)

    await ctx.send(embed=embed)

bot.run("MTM1MTU5NDU4MDUyNDUzMTc4Mg.GOjcS5.w0EDhN6LrkApgUAmmPBm3Uup3fL_cujLLQKNQc")
