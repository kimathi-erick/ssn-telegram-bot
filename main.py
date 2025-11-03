import os
import re
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Set in Railway
HGL_URL = "https://www.ssa.gov/employer/highgroup.txt"

# === CACHE FOR HIGH GROUP LIST ===
hgl_cache = {}
hgl_last_update = None

# === STATE-AREA RANGES (Pre-2011) ===
STATE_AREA_RANGES = {
    "CT": [(10,34)],"ME": [(4,7)],"MA": [(10,34)],"NH": [(1,3)],"RI": [(35,39)],"VT": [(8,9)],
    "NJ": [(135,158)],"NY": [(50,134)],"PA": [(159,211)],"DE": [(221,222)],"DC": [(577,579)],
    "FL": [(261,267),(589,595)],"GA": [(252,260),(667,675)],"MD": [(212,220)],
    "NC": [(232,236),(237,246),(681,690)],"SC": [(247,251),(654,658)],"VA": [(223,231),(691,699)],"WV": [(232,236)],
    "IL": [(318,361),(362,386)],"IN": [(303,317)],"MI": [(362,386)],"MN": [(468,477)],"OH": [(268,302)],"WI": [(387,399)],
    "AZ": [(526,527),(600,601)],"NM": [(525,525),(585,585)],"OK": [(440,448)],"TX": [(449,467),(627,645)],
    "CO": [(521,524),(650,653)],"ID": [(518,519)],"MT": [(516,517)],"NV": [(530,530),(680,680)],"UT": [(528,529)],"WY": [(520,520)],
    "AK": [(574,574)],"CA": [(545,573),(602,626)],"HI": [(575,576),(586,586)],"OR": [(540,544)],"WA": [(531,539)],
    "PR": [(580,584),(596,599)],"VI": [(580,584)],"GU": [(586,586)],"AS": [(586,586)],"MP": [(586,586)],"RR": [(700,728)]
}

# === FETCH HIGH GROUP LIST ===
def get_hgl():
    """Fetch the SSA high group list and cache it."""
    global hgl_cache, hgl_last_update
    now = datetime.now()
    if hgl_last_update is None or (now - hgl_last_update).total_seconds() > 21600:  # 6 hours
        try:
            r = requests.get(HGL_URL, timeout=10)
            r.raise_for_status()
            hgl = {}
            for line in r.text.splitlines()[2:]:
                parts = re.split(r'\s+', line.strip())
                if len(parts) >= 2:
                    area = parts[0].zfill(3)
                    group = int(parts[1])
                    if area not in hgl:
                        hgl[area] = []
                    hgl[area].append(group)
            hgl_cache = hgl
            hgl_last_update = now
        except Exception as e:
            print("Failed to fetch high group list:", e)
    return hgl_cache

# === ESTIMATE ISSUE YEAR FROM GROUP ===
def estimate_year(area_str: str, group: int):
    hgl = get_hgl()
    if area_str not in hgl:
        return "Unknown"
    groups = hgl[area_str]
    try:
        idx = groups.index(group)
        # Approximate year: assuming first issuance 1936, each group ~2 years
        year = 1936 + idx * 2
        return f"Approx Year: {year}"
    except ValueError:
        return "Group exceeds issued high group"

# === VALIDATE SSN ===
def validate_ssn(ssn: str, state: str = None, dob: str = None):
    s = re.sub(r'\D', '', ssn)
    if len(s) != 9 or not s.isdigit():
        return False, "Must be 9 digits", None, None

    area_str = s[:3]
    group = int(s[3:5])
    area = int(area_str)

    # Basic rules
    if area == 0: return False, "Area cannot be 000", None, None
    if area == 666: return False, "Area 666 not issued", None, None
    if 900 <= area <= 999: return False, "Area 900–999 reserved", None, None
    if int(s[5:]) == 0: return False, "Serial cannot be 0000", None, None

    # High Group Check
    hgl = get_hgl()
    if hgl and area_str in hgl and group > max(hgl[area_str]):
        return False, f"Group {group} > issued {max(hgl[area_str])}", None, None

    # State-Area Match (pre-2011)
    state_name = None
    if state and state.upper() in STATE_AREA_RANGES:
        valid = any(lo <= area <= hi for lo, hi in STATE_AREA_RANGES[state.upper()])
        state_name = state.upper()
        if not valid:
            return False, f"Area {area} not issued in {state_name}", state_name, None

    # Estimate year
    est_year = estimate_year(area_str, group)

    return True, "Valid", state_name, est_year

# === BOT COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "SSN Checker Pro\n\n"
        "Send: `123456789 [STATE] [DOB]`\n"
        "Example: `@yourbot 494089675 ME 10/11/1993`\n\n"
        "Returns: validity, state, and approximate issuance year.",
        parse_mode='Markdown'
    )

async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    text = message.text.strip()

    # In group: require @botname
    if message.chat.type in ['group', 'supergroup']:
        bot = await context.bot.get_me()
        if not text.lower().startswith(f"@{bot.username.lower()}"):
            return
        text = re.sub(f'@{bot.username}', '', text, count=1, flags=re.IGNORECASE).strip()

    parts = text.split()
    if len(parts) < 1:
        await message.reply_text("Send SSN [STATE] [DOB]")
        return

    ssn = parts[0]
    state = parts[1].upper() if len(parts) > 1 else None
    dob = parts[2] if len(parts) > 2 else None

    valid, reason, state_name, est_year = validate_ssn(ssn, state, dob)

    result = f"{'✅ VALID' if valid else '❌ INVALID'} `{ssn}`\n"
    if state_name: result += f"State: `{state_name}`\n"
    if est_year: result += f"{est_year}\n"
    if dob: result += f"DOB: `{dob}`\n"
    result += f"\n{reason}"

    await message.reply_text(result, parse_mode='Markdown')

# === MAIN ===
def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set!")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check))

    print("SSN Checker Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
