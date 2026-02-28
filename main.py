# -*- coding: utf-8 -*-
import telebot  # ИСПРАВЛЕНО: было "Import telebot" (с заглавной)
import sqlite3
import time
import random
import threading
import functools
from telebot import types

TOKEN = '8539716689:AAGMlLbxq7lAlS2t51iZvm_r2UIjCfxJStE'
ADMIN_IDS = [6115517123, 2046462689, 7787565361]
ALLOWED_GROUP_IDS = [-1003880025896, -1003790960557]

bot = telebot.TeleBot(TOKEN, parse_mode=None)

# ==============================================================
# ДЕКОРАТОРЫ
# functools.wraps обязателен - без него telebot видит все хендлеры
# как одну функцию "wrapper" и регистрирует только первый
# ==============================================================
def group_only(func):
    @functools.wraps(func)
    def wrapper(message):
        if message.chat.id not in ALLOWED_GROUP_IDS:
            return
        func(message)
    return wrapper

def admin_only(func):
    @functools.wraps(func)
    def wrapper(message):
        # Разрешаем из личного чата (для админов) и из разрешённых групп
        is_private = message.chat.type == 'private'
        in_group   = message.chat.id in ALLOWED_GROUP_IDS
        if not is_private and not in_group:
            return
        if not is_admin(message.from_user.id):
            return bot.reply_to(message, "Нет доступа.")
        func(message)
    return wrapper

# ==============================================================
# БД
# ==============================================================
def db_query(query, args=(), fetchone=False):
    conn = sqlite3.connect('aurelia_economy.db', check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()
    c.execute(query, args)
    if query.strip().upper().startswith("SELECT"):
        result = c.fetchone() if fetchone else c.fetchall()
    else:
        conn.commit()
        result = None
    conn.close()
    return result

def init_db():
    conn = sqlite3.connect('aurelia_economy.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT,
        balance INTEGER DEFAULT 1000, level INTEGER DEFAULT 1,
        last_cash REAL DEFAULT 0, troops INTEGER DEFAULT 0,
        last_draft REAL DEFAULT 0, ep INTEGER DEFAULT 0,
        last_ep REAL DEFAULT 0, banned INTEGER DEFAULT 0,
        morale INTEGER DEFAULT 100
    )''')
    for col in [
        "ALTER TABLE users ADD COLUMN ep INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN last_ep REAL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN morale INTEGER DEFAULT 100",
        "ALTER TABLE users ADD COLUMN country_name TEXT DEFAULT NULL",
    ]:
        try: c.execute(col)
        except: pass

    c.execute('''CREATE TABLE IF NOT EXISTS business_types (
        name TEXT PRIMARY KEY, display_name TEXT, cost INTEGER,
        income_per_hour INTEGER, description TEXT, ep_per_12h INTEGER DEFAULT 0
    )''')
    try: c.execute("ALTER TABLE business_types ADD COLUMN ep_per_12h INTEGER DEFAULT 0")
    except: pass

    c.execute('''CREATE TABLE IF NOT EXISTS user_businesses (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        business_name TEXT, quantity INTEGER DEFAULT 1,
        UNIQUE(user_id, business_name)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS market_assets (
        name TEXT PRIMARY KEY, display_name TEXT,
        price REAL, base_price REAL, last_updated REAL DEFAULT 0, emoji TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_portfolio (
        user_id INTEGER, asset_name TEXT, quantity REAL DEFAULT 0,
        avg_buy_price REAL DEFAULT 0, PRIMARY KEY (user_id, asset_name)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS military_types (
        name TEXT PRIMARY KEY, display_name TEXT, steel_cost INTEGER,
        money_cost INTEGER, description TEXT,
        power_value INTEGER DEFAULT 1, category TEXT DEFAULT 'ground',
        oil_per_unit REAL DEFAULT 0, coal_per_unit REAL DEFAULT 0
    )''')
    for col in [
        "ALTER TABLE military_types ADD COLUMN category TEXT DEFAULT 'ground'",
        "ALTER TABLE military_types ADD COLUMN oil_per_unit REAL DEFAULT 0",
        "ALTER TABLE military_types ADD COLUMN coal_per_unit REAL DEFAULT 0",
    ]:
        try: c.execute(col)
        except: pass

    c.execute('''CREATE TABLE IF NOT EXISTS user_military (
        user_id INTEGER, unit_name TEXT, quantity INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, unit_name)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_extractors (
        user_id INTEGER PRIMARY KEY, quantity INTEGER DEFAULT 0, last_extract REAL DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_resource_buildings (
        user_id INTEGER, resource TEXT,
        quantity INTEGER DEFAULT 0, last_extract REAL DEFAULT 0,
        PRIMARY KEY (user_id, resource)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS tech_types (
        name TEXT PRIMARY KEY, display_name TEXT, max_level INTEGER DEFAULT 5,
        ep_cost_per_level INTEGER, description TEXT, effect TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_tech (
        user_id INTEGER, tech_name TEXT, level INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, tech_name)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS trade_offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, seller_username TEXT,
        offer_type TEXT, offer_name TEXT, offer_qty REAL,
        want_type TEXT, want_name TEXT, want_qty REAL,
        created_at REAL DEFAULT 0, status TEXT DEFAULT 'open'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS event_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, event_type TEXT, description TEXT, created_at REAL DEFAULT 0
    )''')
    conn.commit()

    businesses = [
        ('farm',     '🌾 Ферма',          4000,   40,  'Базовый доход',             0),
        ('factory',  '🏭 Завод',          10000,  120, 'Производство + ОЭ',         50),
        ('mine',     '⛏️ Шахта',          16000,  220, 'Добыча + ОЭ',               50),
        ('casino',   '🎰 Казино',         30000,  450, 'Большой доход',             20),
        ('bank_biz', '🏦 Частный банк',   60000,  950, 'Максимальный доход',        30),
        ('lab',      '🔬 Лаборатория',    45000,  300, 'Много ОЭ',                 100),
        ('nps',      '⚛️ АЭС',           500000, 1200, 'Энерг. Ур.3. -25% топлива армии', 80),
    ]
    c.executemany('INSERT OR IGNORE INTO business_types VALUES (?,?,?,?,?,?)', businesses)
    for name, _, _, _, _, ep in businesses:
        c.execute("UPDATE business_types SET ep_per_12h=? WHERE name=?", (ep, name))

    assets = [
        ('oil',   '🛢️ Нефть',           100.0, 100.0, '🛢️'),
        ('gold',  '🥇 Золото',          500.0, 500.0, '🥇'),
        ('steel', '⚙️ Сталь',            80.0,  80.0, '⚙️'),
        ('aur',   '💎 Аурит',           300.0, 300.0, '💎'),
        ('food',  '🌽 Продовольствие',   50.0,  50.0, '🌽'),
        ('coal',  '🪨 Уголь',            60.0,  60.0, '🪨'),
    ]
    c.executemany(
        'INSERT OR IGNORE INTO market_assets (name,display_name,price,base_price,emoji) VALUES (?,?,?,?,?)',
        assets)

    military = [
        ('rifle',       '🔫 Винтовки',              2,    200,   'Базовая пехота',          1,   'ground', 0,     0),
        ('machinegun',  '🔥 Пулемёты',              5,    500,   'Поддержка пехоты',        3,   'ground', 0,     0),
        ('mortar',      '💣 Миномёты',              15,   2000,  'Огневая поддержка',       8,   'ground', 0,     0),
        ('apc',         '🚗 БТР',                   25,   4000,  'Бронетранспортёр',        20,  'ground', 0,     0),
        ('tank',        '🛡️ Танки',                 50,   10000, 'Основная боевая машина',  50,  'ground', 0.002, 0),
        ('artillery',   '💥 Артиллерия',            80,   16000, 'Дальнобойная поддержка',  40,  'ground', 0,     0),
        ('aa_gun',      '🎯 ПВО',                   60,   14000, 'Зенитные орудия',         30,  'ground', 0,     0),
        ('mlrs',        '🚀 РСЗО',                  120,  25000, 'Залповый огонь',          80,  'ground', 0,     0),
        ('missile',     '☢️ Баллист. ракеты',       200,  50000, 'Стратегические ракеты',   150, 'ground', 0,     0),
        ('plane',       '✈️ Истребители',            120,  30000, 'Реактивные перехватчики', 80,  'air',    0.003, 0),
        ('bomber',      '💣 Бомбардировщики',       180,  50000, 'Стратег. бомбардировщики',100, 'air',    0.005, 0),
        ('helicopter',  '🚁 Вертолёты',             80,   20000, 'Поддержка с воздуха',     50,  'air',    0.002, 0),
        ('bomb',        '💥 Авиабомбы',             20,   3000,  'Боеприпасы авиации',      5,   'air',    0,     0),
        ('corvette',    '🚤 Корветы',               80,   15000, 'Лёгкие боевые корабли',   40,  'navy',   0,     0.003),
        ('ship',        '🚢 Эсминцы',               200,  50000, 'Основа флота',            120, 'navy',   0,     0.008),
        ('submarine',   '🛥️ Подлодки',              150,  40000, 'Скрытые удары',           100, 'navy',   0,     0.005),
        ('cruiser',     '⛵ Крейсеры',              400,  90000, 'Тяжёлые корабли',         250, 'navy',   0,     0.015),
        ('carrier',     '⛴️ Авианосцы',             1000, 300000,'Господство в океане',     500, 'navy',   0,     0.05),
        ('nuclear_sub', '☢️ Атомные подлодки',      2000, 600000,'Ядерное сдерживание',    1000, 'navy',   0,     0.02),
    ]
    c.executemany('INSERT OR IGNORE INTO military_types VALUES (?,?,?,?,?,?,?,?,?)', military)
    for row in military:
        c.execute("UPDATE military_types SET power_value=?,category=?,oil_per_unit=?,coal_per_unit=? WHERE name=?",
                  (row[5], row[6], row[7], row[8], row[0]))

    techs = [
        ('finance',    '💹 Финансы',          5, 300,  '+10% к доходу /cash за уровень',        '+10%cash'),
        ('logistics',  '🚛 Логистика',        5, 450,  '-10% содержание армии за уровень',      '-10%maint'),
        ('metallurgy', '🔩 Металлургия',      5, 600,  '-8% расход стали при крафте',           '-8%steel'),
        ('engineering','⚙️ Инженерия',        5, 600,  '-8% денежный расход при крафте',        '-8%money'),
        ('military_sc','🎖️ Военная наука',    5, 750,  '+15% боевой мощи за уровень',           '+15%power'),
        ('industry',   '🏗️ Индустриализация', 5, 540,  '+20% генерация ОЭ за уровень',          '+20%EP'),
        ('energy',     '⚡ Энергетика',       5, 660,  '-10% расход топлива за уровень',        '-10%fuel'),
        ('trading',    '🤝 Торговля',         3, 450,  '-1% комиссии на бирже за уровень',      '-1%fee'),
        ('espionage',  '🕵️ Разведка',         3, 900,  'Расширенные возможности разведки',      'spy'),
        ('naval',      '⚓ Морское дело',      5, 750,  '+20% мощь флота за уровень',            '+20%navy'),
        ('morale_tech','🎺 Политработа',      5, 540,  '+5% морали, -5% дезертирства за уровень','+morale'),
        ('nuclear',    '☢️ Ядерная программа',5, 1200, 'Открывает ядерное оружие',              'nuclear'),
    ]
    c.executemany('INSERT OR IGNORE INTO tech_types VALUES (?,?,?,?,?,?)', techs)
    for row in techs:
        c.execute("UPDATE tech_types SET ep_cost_per_level=? WHERE name=?", (row[3], row[0]))

    conn.commit()
    conn.close()

init_db()

# ==============================================================
# КОНСТАНТЫ
# ==============================================================
UNIT_TECH_REQUIREMENTS = {
    'artillery':  [('military_sc', 1)],
    'aa_gun':     [('military_sc', 1)],
    'mlrs':       [('military_sc', 2)],
    'missile':    [('military_sc', 4), ('nuclear', 3)],
    'bomber':     [('military_sc', 1)],
    'submarine':  [('naval', 2)],
    'cruiser':    [('naval', 3)],
    'carrier':    [('naval', 4)],
    'nuclear_sub':[('naval', 5), ('military_sc', 3), ('nuclear', 5)],
}

UNIT_RESOURCE_REQUIREMENTS = {
    'missile':    {'aur': 10, 'oil': 5},
    'nuclear_sub':{'aur': 80},
}

RESOURCE_BUILDINGS = {
    'gold':  ('🥇', 'Золотой рудник',      1, 14400),
    'steel': ('⚙️', 'Сталелитейный завод', 2, 10800),
    'coal':  ('🪨', 'Угольная шахта',       3, 7200),
    'aur':   ('💎', 'Аурит-шахта',          1, 21600),
}

# ==============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==============================================================
def is_admin(uid): return uid in ADMIN_IDS
def is_banned(uid):
    r = db_query("SELECT banned FROM users WHERE user_id=?", (uid,), fetchone=True)
    return r and r[0] == 1

def get_tech(uid, name):
    r = db_query("SELECT level FROM user_tech WHERE user_id=? AND tech_name=?", (uid, name), fetchone=True)
    return r[0] if r else 0

def get_price_arrow(price, base):
    if price > base * 1.1: return "📈"
    if price < base * 0.9: return "📉"
    return "➡️"

def calc_power(uid):
    units = db_query('''SELECT um.quantity, mt.power_value, mt.category
                        FROM user_military um JOIN military_types mt ON um.unit_name=mt.name
                        WHERE um.user_id=? AND um.quantity>0''', (uid,))
    troops = (db_query("SELECT troops FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    morale = (db_query("SELECT morale FROM users WHERE user_id=?", (uid,), fetchone=True) or [100])[0] or 100
    naval_bonus = 1 + get_tech(uid, 'naval') * 0.20
    power = troops
    for qty, pv, cat in (units or []):
        b = naval_bonus if cat == 'navy' else 1.0
        power += int(qty * pv * b)
    mil_bonus = 1 + get_tech(uid, 'military_sc') * 0.15
    return int(power * mil_bonus * max(0.1, morale / 100))

def ensure_user(message):
    uid = message.from_user.id
    uname = message.from_user.username or f"player_{uid}"
    if db_query("SELECT user_id FROM users WHERE user_id=?", (uid,), fetchone=True):
        db_query("UPDATE users SET username=? WHERE user_id=?", (uname, uid))
    else:
        db_query("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (uid, uname))
    return uid, uname

def find_user(username_arg):
    u = username_arg.lstrip('@').lower()
    return db_query("SELECT user_id, username FROM users WHERE LOWER(username)=?", (u,), fetchone=True)

def log_event(uid, event_type, description):
    db_query("INSERT INTO event_log (user_id,event_type,description,created_at) VALUES (?,?,?,?)",
             (uid, event_type, description, time.time()))

def add_asset(uid, asset_name, amount):
    e = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid, asset_name), fetchone=True)
    if e:
        db_query("UPDATE user_portfolio SET quantity=quantity+? WHERE user_id=? AND asset_name=?", (amount, uid, asset_name))
    else:
        db_query("INSERT INTO user_portfolio VALUES (?,?,?,?)", (uid, asset_name, amount, 0))

def md(text):
    """Отправить с Markdown разметкой"""
    return text

# ==============================================================
# INLINE КЛАВИАТУРЫ - ФАБРИКИ
# ==============================================================
def kb_main():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("👤 Профиль",     callback_data="m:profile"),
        types.InlineKeyboardButton("💵 Налоги",      callback_data="m:cash"),
        types.InlineKeyboardButton("🏢 Бизнесы",     callback_data="m:biz"),
        types.InlineKeyboardButton("📊 Биржа",        callback_data="m:market"),
        types.InlineKeyboardButton("⚔️ Армия",        callback_data="m:army"),
        types.InlineKeyboardButton("🔬 Технологии",  callback_data="m:tech"),
        types.InlineKeyboardButton("⛏️ Добыча",       callback_data="m:extract"),
        types.InlineKeyboardButton("🤝 Торговля",    callback_data="m:trade"),
        types.InlineKeyboardButton("🏆 Рейтинги",    callback_data="m:top"),
        types.InlineKeyboardButton("🌍 Мир",          callback_data="m:world"),
    )
    return kb

def kb_back(target="m:main"):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data=target))
    return kb

def kb_back_row(target="m:main"):
    return [types.InlineKeyboardButton("◀️ Назад", callback_data=target)]

# ==============================================================
# ТЕКСТОВЫЕ СБОРЩИКИ (для inline-меню)
# ==============================================================
def build_profile_text(uid):
    user = db_query("SELECT balance,level,troops,ep,morale,country_name FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return "Введите /start"
    bal, lv, troops, ep, morale, country_name = user
    morale = morale or 100
    iph = (db_query('''SELECT SUM(ub.quantity*bt.income_per_hour) FROM user_businesses ub
                        JOIN business_types bt ON ub.business_name=bt.name WHERE ub.user_id=?''',
                    (uid,), fetchone=True) or [0])[0] or 0
    ext = (db_query("SELECT quantity FROM user_extractors WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    power = calc_power(uid)

    # Техника по категориям + общее кол-во
    mil = db_query('''SELECT mt.category, SUM(um.quantity) FROM user_military um
                      JOIN military_types mt ON um.unit_name=mt.name
                      WHERE um.user_id=? GROUP BY mt.category''', (uid,))
    mil_map = {cat: (qty or 0) for cat, qty in (mil or [])}
    ground_u = mil_map.get('ground', 0)
    air_u    = mil_map.get('air', 0)
    navy_u   = mil_map.get('navy', 0)
    total_units = ground_u + air_u + navy_u

    # Топ-3 юнита по количеству
    top_units = db_query('''SELECT m.display_name, u.quantity FROM user_military u
                            JOIN military_types m ON u.unit_name=m.name
                            WHERE u.user_id=? AND u.quantity>0
                            ORDER BY u.quantity DESC LIMIT 3''', (uid,)) or []

    # Содержание армии
    logistics_lv = (db_query("SELECT level FROM user_tech WHERE user_id=? AND tech_name='logistics'", (uid,), fetchone=True) or [0])[0] or 0
    maint_units = db_query('''SELECT mt.maintenance_per_hour, SUM(um.quantity)
                              FROM user_military um JOIN military_types mt ON um.unit_name=mt.name
                              WHERE um.user_id=? GROUP BY mt.maintenance_per_hour''', (uid,)) or []
    raw_maint = sum((m or 0) * (q or 0) for m, q in maint_units)
    discount = 1.0 - logistics_lv * 0.10
    maint = int(raw_maint * discount)
    net_income = iph - maint

    # Бизнесы
    biz_count = (db_query("SELECT SUM(quantity) FROM user_businesses WHERE user_id=?", (uid,), fetchone=True) or [0])[0] or 0
    biz_types = (db_query("SELECT COUNT(*) FROM user_businesses WHERE user_id=?", (uid,), fetchone=True) or [0])[0] or 0
    res_bld   = (db_query("SELECT SUM(quantity) FROM user_resource_buildings WHERE user_id=?", (uid,), fetchone=True) or [0])[0] or 0
    has_nps = (db_query("SELECT quantity FROM user_businesses WHERE user_id=? AND business_name='nps'", (uid,), fetchone=True) or [0])[0] or 0

    # Ресурсы
    def get_asset(name):
        return (db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid, name), fetchone=True) or [0])[0] or 0
    steel = get_asset('steel'); oil = get_asset('oil')
    aur   = get_asset('aur');   food = get_asset('food')
    coal  = get_asset('coal');  gold = get_asset('gold')

    # Ключевые техи
    def tlv(name):
        return (db_query("SELECT level FROM user_tech WHERE user_id=? AND tech_name=?", (uid, name), fetchone=True) or [0])[0] or 0
    mil_sc  = tlv('military_sc')
    nuclear = tlv('nuclear')
    naval   = tlv('naval')
    fin_lv  = tlv('finance')
    eng_lv  = tlv('engineering')
    tech_count = (db_query("SELECT COUNT(*) FROM user_tech WHERE user_id=? AND level>0", (uid,), fetchone=True) or [0])[0] or 0

    # Рейтинг
    rank_bal   = (db_query("SELECT COUNT(*)+1 FROM users WHERE balance>? AND banned=0", (bal,), fetchone=True) or [1])[0]
    rank_power = (db_query("""SELECT COUNT(*)+1 FROM users u WHERE banned=0
                               AND (SELECT COALESCE(SUM(um.quantity*mt.power_value),0)
                                    FROM user_military um JOIN military_types mt ON um.unit_name=mt.name
                                    WHERE um.user_id=u.user_id) > ?""", (power,), fetchone=True) or [1])[0]

    # Налог
    if   bal >= 2_000_000: tax_str = "3.5%/ч 🔴"
    elif bal >= 1_000_000: tax_str = "3.0%/ч 🔴"
    elif bal >= 500_000:   tax_str = "2.5%/ч 🟠"
    elif bal >= 200_000:   tax_str = "2.0%/ч 🟠"
    elif bal >= 100_000:   tax_str = "1.0%/ч 🟡"
    elif bal >= 50_000:    tax_str = "0.5%/ч 🟡"
    else:                  tax_str = "нет ✅"

    # Мораль
    if   morale >= 80: morale_str = f"{morale}% 💚"
    elif morale >= 50: morale_str = f"{morale}% 🟡"
    elif morale >= 25: morale_str = f"{morale}% 🟠"
    else:              morale_str = f"{morale}% 🔴 КРИЗИС"

    # Чистый доход
    net_str = f"+{net_income:,}" if net_income >= 0 else f"{net_income:,}"
    net_icon = "💹" if net_income >= 0 else "📉"

    coal  = get_asset('coal')
    gold  = get_asset('gold')
    tax_day = int(iph * 24)

    top_units = db_query('''SELECT mt.display_name, um.quantity FROM user_military um
                             JOIN military_types mt ON um.unit_name=mt.name
                             WHERE um.user_id=? AND um.quantity>0
                             ORDER BY mt.power_value DESC LIMIT 3''', (uid,))

    max_techs = (db_query("SELECT COUNT(*) FROM user_tech ut JOIN tech_types tt ON ut.tech_name=tt.name WHERE ut.user_id=? AND ut.level>=tt.max_level", (uid,), fetchone=True) or [0])[0]
    rank_mil  = (db_query("SELECT COUNT(*)+1 FROM users u WHERE banned=0 AND (SELECT COALESCE(SUM(um.quantity*mt.power_value),0) FROM user_military um JOIN military_types mt ON um.unit_name=mt.name WHERE um.user_id=u.user_id) > ?", (power,), fetchone=True) or [1])[0]

    uname = (db_query("SELECT username FROM users WHERE user_id=?", (uid,), fetchone=True) or ['?'])[0]

    country_header = f"\U0001f30d *{country_name}*\n" if country_name else "\U0001f30d *Без названия* - задай: `/rename Название`\n"

    units_str = ""
    for disp, qty in (top_units or []):
        units_str += f"  {disp}: {qty:,}\n"
    if not units_str: units_str = "  Нет техники\n"

    return (
        f"{country_header}"
        f"\U0001f464 Правитель: @{uname}\n"
        f"\U0001f3c6 Рейтинг: #{rank} (\U0001f4b0) | #{rank_mil} (\u2694\ufe0f)\n\n"
        f"\U0001f4b0 *ЭКОНОМИКА*\n"
        f"Баланс: {bal:,} \U0001f4b0\n"
        f"Доход: ~{iph:,}/ч | ~{tax_day:,}/сут\n"
        f"Уровень: {lv} | Налог: {tax_str}\n\n"
        f"\u2694\ufe0f *АРМИЯ*\n"
        f"Пехота: {troops:,} \U0001fab6 | Мораль: {morale_str}\n"
        f"\U0001f52b Наземных: {ground_u:,} | \u2708\ufe0f Авиация: {air_u:,} | \U0001f6a2 Флот: {navy_u:,}\n"
        f"Топ техника:\n{units_str}"
        f"Боевая мощь: {power:,} \u2694\ufe0f\n\n"
        f"\U0001f3ed *ПРОИЗВОДСТВО*\n"
        f"Бизнесов: {biz_count} шт. ({biz_types} типов)\n"
        f"Нефтекачки: {ext} \U0001f6e2\ufe0f | Рес. здания: {res_bld}\n\n"
        f"\U0001f4e6 *РЕСУРСЫ*\n"
        f"\u2699\ufe0f Сталь: {steel:.0f} | \U0001f6e2\ufe0f Нефть: {oil:.0f}\n"
        f"\U0001faa8 Уголь: {coal:.0f} | \U0001f947 Золото: {gold:.0f}\n"
        f"\U0001f48e Аурит: {aur:.1f} | \U0001f33d Еда: {food:.0f}\n\n"
        f"\U0001f52c *НАУКА*\n"
        f"ОЭ: {ep} | Техов: {tech_count}/12 | Макс. ур.: {max_techs}"
    )

def build_market_text():
    assets = db_query("SELECT name,display_name,price,base_price FROM market_assets")
    text = "📊 *Мировая биржа:*\n\n"
    for name, disp, price, base in assets:
        arr = get_price_arrow(price, base)
        pct = ((price - base) / base) * 100
        sign = "+" if pct >= 0 else ""
        text += f"{arr} *{disp}*: {price:.2f}💰 ({sign}{pct:.1f}%)\n"
    text += "\n_Покупка:_ `/buy [актив] [кол-во]`\n_Продажа:_ `/sell [актив] [кол-во]`"
    return text

def build_army_text(uid):
    user = db_query("SELECT troops, morale FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return "Введите /start"
    troops, morale = user
    morale = morale or 100
    units = db_query('''SELECT u.unit_name, m.display_name, u.quantity, m.category,
                               m.oil_per_unit, m.coal_per_unit
                        FROM user_military u JOIN military_types m ON u.unit_name=m.name
                        WHERE u.user_id=? AND u.quantity>0''', (uid,))
    secs = {'ground': [], 'air': [], 'navy': []}
    total_oil = total_coal = 0.0
    energy_mult = max(0.1, 1 - get_tech(uid, 'energy') * 0.10)
    has_aes = db_query("SELECT quantity FROM user_businesses WHERE user_id=? AND business_name='nps'", (uid,), fetchone=True)
    nps_b = 0.25 if (has_aes and has_aes[0] > 0) else 0.0
    fuel_mult = max(0.05, energy_mult - nps_b)

    for uname, disp, qty, cat, oil_pu, coal_pu in (units or []):
        secs.get(cat, secs['ground']).append(f"  {disp}: {qty:,}")
        total_oil  += oil_pu  * qty * fuel_mult
        total_coal += coal_pu * qty * fuel_mult

    logi = get_tech(uid, 'logistics')
    maint = int((troops / 5) * max(0.1, 1 - logi * 0.10))
    power = calc_power(uid)

    text = f"⚔️ *Вооружённые силы:*\n\n"
    text += f"🪖 *Наземные:*\n  Пехота: {troops:,}\n"
    text += ("\n".join(secs['ground']) + "\n") if secs['ground'] else "  Нет техники\n"
    text += f"\n✈️ *Авиация:*\n"
    text += ("\n".join(secs['air']) + "\n") if secs['air'] else "  Нет авиации\n"
    text += f"\n🚢 *Флот:*\n"
    text += ("\n".join(secs['navy']) + "\n") if secs['navy'] else "  Нет флота\n"
    text += f"\n⚔️ *Мощь: {power:,}* (мораль: {morale}%)\n"
    text += f"💸 Содержание пехоты: ~{maint} 💰/ч\n"
    if total_oil > 0:
        text += f"🛢️ Расход нефти: {total_oil:.2f}/3ч"
        if nps_b > 0: text += " (⚛️ -25%)"
        text += "\n"
    if total_coal > 0:
        text += f"🪨 Расход угля: {total_coal:.2f}/3ч"
        if nps_b > 0: text += " (⚛️ -25%)"
        text += "\n"
    return text

def build_craft_text(uid, category):
    cat_names = {'ground': '🪖 Наземные', 'air': '✈️ Авиация', 'navy': '🚢 Флот'}
    units = db_query(
        "SELECT name,display_name,steel_cost,money_cost,oil_per_unit,coal_per_unit FROM military_types WHERE category=?",
        (category,))
    text = f"⚙️ *Производство - {cat_names.get(category, category)}:*\n\n"
    for name, disp, steel, money, oil_pu, coal_pu in (units or []):
        fuel_str = ""
        if oil_pu > 0:  fuel_str = f" | 🛢️{oil_pu}/3ч"
        if coal_pu > 0: fuel_str = f" | 🪨{coal_pu}/3ч"
        req_parts = []
        for tname, tlv in UNIT_TECH_REQUIREMENTS.get(name, []):
            cur = get_tech(uid, tname)
            req_parts.append("✅" if cur >= tlv else f"❌{tname}Ур.{tlv}")
        req_str = f" [{', '.join(req_parts)}]" if req_parts else ""
        text += f"*{disp}* (`{name}`)\n  {steel}⚙️ + {money:,}💰{fuel_str}{req_str}\n"
    text += f"\n_Команда:_ `/craft [тип] [кол-во]`\n_Пример:_ `/craft tank 5`"
    return text

def build_tech_text(uid):
    techs = db_query("SELECT name,display_name,max_level,ep_cost_per_level,description FROM tech_types")
    ep = (db_query("SELECT ep FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    text = f"🔬 *Технологии*  |  💡 ОЭ: {ep}\n\n"
    for name, disp, maxlv, cost, desc in (techs or []):
        lv = get_tech(uid, name)
        if lv >= maxlv:
            status = "✅ МАКС"
        else:
            status = f"Ур.{lv}/{maxlv} - {cost} ОЭ"
        text += f"*{disp}* `{name}`\n_{desc}_\n{status}\n\n"
    text += "_Команда:_ `/researchtech [название]`"
    return text

def build_extract_text(uid):
    ext = db_query("SELECT quantity,last_extract FROM user_extractors WHERE user_id=?", (uid,), fetchone=True)
    text = "⛏️ *Добыча ресурсов:*\n\n"
    now = time.time()

    # Нефть
    oil_qty = ext[0] if ext else 0
    if oil_qty > 0:
        last = ext[1] if ext else 0
        if now - (last or 0) < 3600:
            left = int(3600 - (now - last))
            cd = f"через {left//60}м {left%60}с"
        else:
            cd = "✅ Готово!"
        text += f"🛢️ *Нефтекачек*: {oil_qty} шт. - {cd}\n  `/extractoil`\n\n"
    else:
        text += f"🛢️ *Нефть*: нет качек\n\n"

    # Ресурсные здания
    for res, (emoji, name, yld, cd_sec) in RESOURCE_BUILDINGS.items():
        row = db_query("SELECT quantity,last_extract FROM user_resource_buildings WHERE user_id=? AND resource=?", (uid, res), fetchone=True)
        qty = row[0] if row else 0
        last = row[1] if row else 0
        if qty > 0:
            if now - (last or 0) < cd_sec:
                left = int(cd_sec - (now - last))
                cd_str = f"через {left//3600}ч {(left%3600)//60}м" if left >= 3600 else f"через {left//60}м"
            else:
                cd_str = f"✅ +{qty*yld}{emoji}"
            text += f"{emoji} *{name}*: {qty} шт. - {cd_str}\n  `/extract {res}`\n\n"
        else:
            text += f"{emoji} *{name}*: нет зданий\n\n"
    return text

def build_trades_text():
    offers = db_query('''SELECT id,seller_username,offer_type,offer_name,offer_qty,
                                want_type,want_name,want_qty FROM trade_offers
                         WHERE status='open' ORDER BY id DESC LIMIT 15''')
    if not offers: return "📭 Открытых предложений нет.\n\n_Создать: `/trade тип что кол-во тип что кол-во`_"
    text = "🤝 *Торговые предложения:*\n\n"
    for tid, seller, ot, on, oq, wt, wn, wq in offers:
        ostr = f"{int(oq):,}💰" if ot == 'money' else f"{oq} {on}"
        wstr = f"{int(wq):,}💰" if wt == 'money' else f"{wq} {wn}"
        text += f"*#{tid}* @{seller}: {ostr} → {wstr}  `/accept {tid}`\n"
    text += "\n_Отменить: `/canceltrade ID`_"
    return text

def build_top_text():
    text = "🏆 *Рейтинги:*\n\n"
    rows = db_query("SELECT username,balance FROM users WHERE banned=0 ORDER BY balance DESC LIMIT 5")
    text += "*💰 Топ по балансу:*\n"
    medals = ["🥇","🥈","🥉","4.","5."]
    for i,(u,v) in enumerate(rows or []):
        text += f"{medals[i]} @{u} - {v:,}💰\n"
    text += "\n"
    rows = db_query("SELECT username,ep FROM users WHERE banned=0 ORDER BY ep DESC LIMIT 5")
    text += "*🔬 Топ по ОЭ:*\n"
    for i,(u,v) in enumerate(rows or []):
        text += f"{medals[i]} @{u} - {v:,}ОЭ\n"
    text += "\n⚔️ Военный рейтинг: /toparmy"
    return text

# ==============================================================
# ФОНОВЫЕ ПОТОКИ
# ==============================================================
def market_updater():
    while True:
        time.sleep(3600)
        for name, price, base in db_query("SELECT name,price,base_price FROM market_assets"):
            change = random.uniform(-0.20, 0.20)
            new_p = max(base * 0.4, min(base * 2.5, price * (1 + change)))
            db_query("UPDATE market_assets SET price=?,last_updated=? WHERE name=?", (round(new_p, 2), time.time(), name))

def passive_income():
    while True:
        time.sleep(600)
        rows = db_query('''SELECT ub.user_id, SUM(ub.quantity*bt.income_per_hour)
                           FROM user_businesses ub JOIN business_types bt ON ub.business_name=bt.name
                           GROUP BY ub.user_id''')
        for uid, total in (rows or []):
            income = int(total * (600 / 3600))
            if income > 0:
                db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (income, uid))

def ep_gen():
    EP_INT = 43200
    while True:
        time.sleep(600)
        now = time.time()
        ep_map = dict(db_query('''
            SELECT ub.user_id, SUM(ub.quantity*bt.ep_per_12h)
            FROM user_businesses ub JOIN business_types bt ON ub.business_name=bt.name
            WHERE bt.ep_per_12h>0 GROUP BY ub.user_id''') or [])
        for uid, last_ep in (db_query("SELECT user_id,last_ep FROM users") or []):
            if uid in ep_map and (now - (last_ep or 0)) >= EP_INT:
                bonus = 1 + get_tech(uid, 'industry') * 0.20
                gain = int(ep_map[uid] * bonus * random.uniform(0.90, 1.10))
                if gain > 0:
                    db_query("UPDATE users SET ep=ep+?, last_ep=? WHERE user_id=?", (gain, now, uid))

def army_upkeep():
    fuel_acc = {}
    tick = 0
    while True:
        time.sleep(3600)
        tick += 1
        users = db_query("SELECT user_id,troops,balance,morale FROM users WHERE banned=0")
        for uid, troops, bal, morale in (users or []):
            morale = morale or 100
            logi = get_tech(uid, 'logistics')
            maint = int((troops / 5) * max(0.1, 1 - logi * 0.10))
            if   bal >= 2_000_000: tax = int(bal * 0.035)
            elif bal >= 1_000_000: tax = int(bal * 0.030)
            elif bal >= 500_000:   tax = int(bal * 0.025)
            elif bal >= 200_000:   tax = int(bal * 0.020)
            elif bal >= 150_000:   tax = int(bal * 0.015)
            elif bal >= 100_000:   tax = int(bal * 0.010)
            elif bal >= 50_000:    tax = int(bal * 0.005)
            else:                  tax = 0
            total_deduct = maint + tax
            if total_deduct == 0: continue

            if bal >= total_deduct:
                db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (total_deduct, uid))
            else:
                unpaid_maint = max(0, maint - bal)
                db_query("UPDATE users SET balance=0 WHERE user_id=?", (uid,))
                if troops > 0 and unpaid_maint > 0:
                    morale_tech = get_tech(uid, 'morale_tech')
                    base_rate = max(0.005, 0.03 - morale_tech * 0.005)
                    morale_factor = max(1.0, (100 - morale) / 50 + 1)
                    rate = min(0.15, base_rate * morale_factor)
                    lost = min(max(10, int(troops * rate)), troops)
                    db_query("UPDATE users SET troops=MAX(0,troops-?) WHERE user_id=?", (lost, uid))
                    new_morale = max(10, morale - random.randint(3, 8))
                    db_query("UPDATE users SET morale=? WHERE user_id=?", (new_morale, uid))
                    log_event(uid, 'desertion', f"Дезертировало {lost} солдат. Мораль: {new_morale}")

            if bal >= total_deduct * 2 and morale < 100:
                new_morale = min(100, morale + random.randint(1, 3) + get_tech(uid, 'morale_tech'))
                db_query("UPDATE users SET morale=? WHERE user_id=?", (new_morale, uid))

        if tick % 3 == 0:
            energy_units = db_query('''SELECT user_id, unit_name, quantity, oil_per_unit, coal_per_unit
                                       FROM user_military um JOIN military_types mt ON um.unit_name=mt.name
                                       WHERE (mt.oil_per_unit>0 OR mt.coal_per_unit>0) AND um.quantity>0''')
            fuel_needs = {}
            for uid, unit_name, qty, oil_pu, coal_pu in (energy_units or []):
                if uid not in fuel_needs: fuel_needs[uid] = {'oil': 0.0, 'coal': 0.0}
                energy_tech = get_tech(uid, 'energy')
                has_aes = db_query("SELECT quantity FROM user_businesses WHERE user_id=? AND business_name='nps'", (uid,), fetchone=True)
                nps_b = 0.25 if (has_aes and has_aes[0] > 0) else 0.0
                fm = max(0.05, 1 - energy_tech * 0.10 - nps_b)
                fuel_needs[uid]['oil']  += oil_pu  * qty * fm
                fuel_needs[uid]['coal'] += coal_pu * qty * fm

            for uid, needs in fuel_needs.items():
                if uid not in fuel_acc: fuel_acc[uid] = {'oil': 0.0, 'coal': 0.0}
                for res in ('oil', 'coal'):
                    fuel_acc[uid][res] += needs[res]
                    to_ded = int(fuel_acc[uid][res])
                    if to_ded > 0:
                        fuel_acc[uid][res] -= to_ded
                        row = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid, res), fetchone=True)
                        actual = min(to_ded, int(row[0]) if row else 0)
                        if actual > 0:
                            db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name=?", (actual, uid, res))
                        if actual < to_ded:
                            mr = db_query("SELECT morale FROM users WHERE user_id=?", (uid,), fetchone=True)
                            if mr:
                                db_query("UPDATE users SET morale=? WHERE user_id=?",
                                         (max(20, (mr[0] or 100) - random.randint(1, 3)), uid))

def food_consumption():
    while True:
        time.sleep(21600)
        for uid, troops, morale in (db_query("SELECT user_id,troops,morale FROM users WHERE troops>0 AND banned=0") or []):
            morale = morale or 100
            food_needed = max(1, troops // 1000)
            fr = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name='food'", (uid,), fetchone=True)
            food_have = int(fr[0]) if fr else 0
            if food_have >= food_needed:
                db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name='food'", (food_needed, uid))
                if morale < 100:
                    db_query("UPDATE users SET morale=MIN(100,morale+1) WHERE user_id=?", (uid,))
            else:
                if food_have > 0:
                    db_query("DELETE FROM user_portfolio WHERE user_id=? AND asset_name='food'", (uid,))
                new_morale = max(5, morale - random.randint(2, 5))
                db_query("UPDATE users SET morale=? WHERE user_id=?", (new_morale, uid))
                if troops > 0:
                    lost = max(5, int(troops * 0.01))
                    db_query("UPDATE users SET troops=MAX(0,troops-?) WHERE user_id=?", (lost, uid))
                    log_event(uid, 'hunger', f"Голод! -{lost} солдат, мораль: {new_morale}")

for fn in [market_updater, passive_income, ep_gen, army_upkeep, food_consumption]:
    threading.Thread(target=fn, daemon=True).start()

# ==============================================================
# УСТАНОВИТЬ ПОДСКАЗКИ КОМАНД В TELEGRAM
# ==============================================================
def set_commands():
    bot.set_my_commands([
        types.BotCommand("/menu",         "🎮 Главное меню"),
        types.BotCommand("/profile",      "👤 Ваш профиль"),
        types.BotCommand("/cash",         "💵 Собрать налоги"),
        types.BotCommand("/pay",          "💸 Перевести деньги"),
        types.BotCommand("/army",         "⚔️ Состав армии"),
        types.BotCommand("/craft",        "⚙️ Производство техники"),
        types.BotCommand("/draft",        "🪖 Призвать армию"),
        types.BotCommand("/market",       "📊 Биржа ресурсов"),
        types.BotCommand("/portfolio",    "💼 Портфель активов"),
        types.BotCommand("/tech",         "🔬 Технологии"),
        types.BotCommand("/trades",       "🤝 Торговые предложения"),
        types.BotCommand("/top",          "🏆 Рейтинги"),
        types.BotCommand("/events",       "📋 Журнал событий"),
        types.BotCommand("/rename",       "✏️ Переименовать страну"),
        types.BotCommand("/help",         "📖 Все команды"),
    ])

# ==============================================================
# ГЛАВНАЯ КОМАНДА: /menu
# ==============================================================
@bot.message_handler(commands=['menu', 'start'])
@group_only
def cmd_menu(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return bot.reply_to(message, "Вы заблокированы.")
    text = (
        "🌍 *Аурелия - экономическая стратегия*\n\n"
        "Выберите раздел:"
    )
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=kb_main())

# ==============================================================
# CALLBACK HANDLER - весь inline-интерфейс
# ==============================================================
@bot.callback_query_handler(func=lambda c: True)
def callback_handler(call):
    if call.message.chat.id not in ALLOWED_GROUP_IDS:
        return bot.answer_callback_query(call.id)

    uid = call.from_user.id
    if is_banned(uid):
        return bot.answer_callback_query(call.id, "Вы заблокированы.")

    # Убеждаемся что пользователь есть в БД
    uname = call.from_user.username or f"player_{uid}"
    if not db_query("SELECT user_id FROM users WHERE user_id=?", (uid,), fetchone=True):
        db_query("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (uid, uname))

    data = call.data

    def edit(text, kb=None):
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                                  parse_mode="Markdown", reply_markup=kb)
        except Exception:
            pass
        bot.answer_callback_query(call.id)

    # ─── Главное меню ───────────────────────────────────────────
    if data == "m:main":
        edit("🌍 *Аурелия - экономическая стратегия*\n\nВыберите раздел:", kb_main())

    # ─── Профиль ────────────────────────────────────────────────
    elif data == "m:profile":
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("💵 Собрать налоги", callback_data="m:cash"),
            types.InlineKeyboardButton("📈 Улучшить экономику", callback_data="m:upgrade"),
            types.InlineKeyboardButton("📋 Журнал событий", callback_data="m:events"),
            types.InlineKeyboardButton("🎺 Мораль армии", callback_data="m:morale"),
        )
        kb.row(types.InlineKeyboardButton("◀️ Назад", callback_data="m:main"))
        edit(build_profile_text(uid), kb)

    # ─── Налоги ─────────────────────────────────────────────────
    elif data == "m:cash":
        user = db_query("SELECT balance,level,last_cash FROM users WHERE user_id=?", (uid,), fetchone=True)
        if not user:
            return bot.answer_callback_query(call.id, "Введите /start")
        bal, lv, last = user
        now = time.time()
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:profile"))
        if now - (last or 0) < 1800:
            left = int(1800 - (now - last))
            edit(f"⏳ *Казна пуста.*\nСледующий сбор через {left//60} мин. {left%60} сек.", kb)
        else:
            earned = int(500 * (1 + lv * 0.2) * (1 + get_tech(uid, 'finance') * 0.10) * random.uniform(0.8, 1.2))
            db_query("UPDATE users SET balance=balance+?, last_cash=? WHERE user_id=?", (earned, now, uid))
            edit(f"💵 *Налоги собраны!*\n+{earned:,} 💰\nБаланс: {bal+earned:,}", kb)

    # ─── Улучшение экономики ─────────────────────────────────────
    elif data == "m:upgrade":
        user = db_query("SELECT balance,level FROM users WHERE user_id=?", (uid,), fetchone=True)
        if not user: return bot.answer_callback_query(call.id, "Введите /start")
        bal, lv = user
        cost = lv * 3000
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:profile"))
        if bal < cost:
            edit(f"📈 *Улучшение экономики*\n\nТекущий уровень: {lv}\nСтоимость: {cost:,} 💰\nВаш баланс: {bal:,} 💰\n\n❌ Недостаточно средств.", kb)
        else:
            db_query("UPDATE users SET balance=balance-?, level=level+1 WHERE user_id=?", (cost, uid))
            edit(f"✅ *Экономика улучшена!*\nУровень: {lv} → *{lv+1}*\nПотрачено: {cost:,} 💰", kb)

    # ─── Мораль ──────────────────────────────────────────────────
    elif data == "m:morale":
        user = db_query("SELECT morale, troops, balance FROM users WHERE user_id=?", (uid,), fetchone=True)
        if not user: return bot.answer_callback_query(call.id, "Введите /start")
        morale, troops, bal = user
        morale = morale or 100
        logi = get_tech(uid, 'logistics')
        maint = int((troops / 5) * max(0.1, 1 - logi * 0.10))
        if   morale >= 90: status = "💚 Непобедимый дух"
        elif morale >= 70: status = "🟢 Высокий боевой дух"
        elif morale >= 50: status = "🟡 Нормальный дух"
        elif morale >= 30: status = "🟠 Низкий дух - дезертирство"
        elif morale >= 15: status = "🔴 Кризис морали"
        else:              status = "☠️ Коллапс армии"
        morale_tech = get_tech(uid, 'morale_tech')
        text = (
            f"🎺 *Мораль армии:*\n\n"
            f"Мораль: *{morale}%* - {status}\n\n"
            f"🪖 Пехота: {troops:,}\n"
            f"💸 Содержание: ~{maint} 💰/ч\n"
            f"💰 Баланс: {bal:,}\n\n"
            f"*Как поднять мораль:*\n"
            f"- Платить содержание армии\n"
            f"- Снабжать едой (`/buy food`)\n"
            f"- Технология Политработа Ур.{morale_tech}/5"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:profile"))
        edit(text, kb)

    # ─── Журнал событий ──────────────────────────────────────────
    elif data == "m:events":
        rows = db_query('''SELECT event_type, description, created_at FROM event_log
                           WHERE user_id=? ORDER BY created_at DESC LIMIT 10''', (uid,))
        if not rows:
            text = "📋 *Журнал событий:*\n\nСобытий нет."
        else:
            text = "📋 *Последние события:*\n\n"
            for etype, desc, ts in rows:
                dt = time.strftime('%d.%m %H:%M', time.localtime(ts))
                icon = {'desertion': '🏃', 'hunger': '🍽️', 'crisis': '💥'}.get(etype, '📌')
                text += f"{icon} [{dt}] {desc}\n"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:profile"))
        edit(text, kb)

    # ─── Бизнесы ─────────────────────────────────────────────────
    elif data == "m:biz":
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("🛒 Магазин бизнесов", callback_data="m:shop"),
            types.InlineKeyboardButton("📋 Мои бизнесы",      callback_data="m:mybiz"),
            types.InlineKeyboardButton("◀️ Назад",            callback_data="m:main"),
        )
        edit("🏢 *Бизнесы:*\nВыберите раздел:", kb)

    elif data == "m:shop":
        rows = db_query("SELECT name,display_name,cost,income_per_hour,description,ep_per_12h FROM business_types")
        text = "🏪 *Магазин бизнесов:*\n\n"
        for name, disp, cost, iph, desc, ep12 in rows:
            ep_str = f" | 🔬+{ep12}ОЭ/12ч" if ep12 else ""
            text += f"*{disp}*\n💰 {cost:,} | ~{iph}💰/ч{ep_str}\n_{desc}_\n`/buybiz {name} [кол-во]`\n\n"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:biz"))
        edit(text, kb)

    elif data == "m:mybiz":
        rows = db_query('''SELECT bt.display_name,ub.quantity,bt.income_per_hour,bt.ep_per_12h
                           FROM user_businesses ub JOIN business_types bt ON ub.business_name=bt.name
                           WHERE ub.user_id=?''', (uid,))
        if not rows:
            text = "🏢 *Мои бизнесы:*\n\nУ вас нет бизнесов.\n_Купить:_ `/buybiz [название]`"
        else:
            text = "🏢 *Мои бизнесы:*\n\n"
            ti = te = 0
            for disp, qty, iph, ep12 in rows:
                si = iph * qty; se = ep12 * qty; ti += si; te += se
                ep_str = f" | +{se}ОЭ" if se else ""
                text += f"*{disp}* ×{qty} - {si}💰/ч{ep_str}\n"
            text += f"\n📊 *~{ti}💰/ч | 🔬+{te}ОЭ/12ч*"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:biz"))
        edit(text, kb)

    # ─── Биржа ───────────────────────────────────────────────────
    elif data == "m:market":
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📊 Цены",       callback_data="m:prices"),
            types.InlineKeyboardButton("💼 Портфель",   callback_data="m:portfolio"),
            types.InlineKeyboardButton("◀️ Назад",      callback_data="m:main"),
        )
        edit("📊 *Биржа ресурсов:*\nВыберите раздел:", kb)

    elif data == "m:prices":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:market"))
        edit(build_market_text(), kb)

    elif data == "m:portfolio":
        rows = db_query('''SELECT p.asset_name,p.quantity,p.avg_buy_price,m.price,m.display_name
                           FROM user_portfolio p JOIN market_assets m ON p.asset_name=m.name
                           WHERE p.user_id=? AND p.quantity>0''', (uid,))
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:market"))
        if not rows:
            edit("💼 *Портфель пуст.*\n\n_Покупка:_ `/buy [актив] [кол-во]`", kb)
        else:
            text = "💼 *Портфель:*\n\n"
            ti = tc = 0.0
            for _, qty, avg, cur, disp in rows:
                inv = avg * qty; cv = cur * qty; pnl = cv - inv
                ti += inv; tc += cv
                e = "📈" if pnl >= 0 else "📉"
                pstr = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
                text += f"{e} *{disp}* ×{qty:.1f} | avg:{avg:.2f}→{cur:.2f} | {pstr}💰\n"
            tp = tc - ti
            tstr = f"+{tp:.2f}" if tp >= 0 else f"{tp:.2f}"
            text += f"\n{'📈' if tp>=0 else '📉'} *P&L: {tstr}💰*"
            edit(text, kb)

    # ─── Армия ───────────────────────────────────────────────────
    elif data == "m:army":
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("📋 Состав",         callback_data="m:armyinfo"),
            types.InlineKeyboardButton("🪖 Призыв",         callback_data="m:draft"),
            types.InlineKeyboardButton("🔫 Наземные",       callback_data="m:craft:ground"),
            types.InlineKeyboardButton("✈️ Авиация",         callback_data="m:craft:air"),
            types.InlineKeyboardButton("🚢 Флот",           callback_data="m:craft:navy"),
            types.InlineKeyboardButton("🎺 Мораль",         callback_data="m:morale"),
        )
        kb.row(types.InlineKeyboardButton("◀️ Назад", callback_data="m:main"))
        edit("⚔️ *Армия:*\nВыберите раздел:", kb)

    elif data == "m:armyinfo":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:army"))
        edit(build_army_text(uid), kb)

    elif data == "m:draft":
        user = db_query("SELECT troops,last_draft,morale FROM users WHERE user_id=?", (uid,), fetchone=True)
        if not user: return bot.answer_callback_query(call.id, "Введите /start")
        troops, last, morale = user
        now = time.time()
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:army"))
        if now - (last or 0) < 7200:
            left = int(7200 - (now - last))
            edit(f"⏳ Следующий призыв через {left//3600}ч {(left%3600)//60}м.", kb)
        else:
            morale = morale or 100
            morale_factor = max(0.3, morale / 100)
            new_recruits = int(random.randint(1000, 2000) * morale_factor)
            db_query("UPDATE users SET troops=troops+?, last_draft=? WHERE user_id=?", (new_recruits, now, uid))
            note = f"\n⚠️ Низкая мораль ({morale}%) сократила призыв!" if morale < 60 else ""
            edit(f"🪖 *Призыв!*\n+*{new_recruits}* новобранцев\nВсего: {troops+new_recruits:,}{note}", kb)

    elif data.startswith("m:craft:"):
        category = data.split(":")[2]
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:army"))
        edit(build_craft_text(uid, category), kb)

    # ─── Технологии ──────────────────────────────────────────────
    elif data == "m:tech":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:main"))
        edit(build_tech_text(uid), kb)

    # ─── Добыча ──────────────────────────────────────────────────
    elif data == "m:extract":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:main"))
        edit(build_extract_text(uid), kb)

    # ─── Торговля ────────────────────────────────────────────────
    elif data == "m:trade":
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:main"))
        text = build_trades_text()
        text += "\n\n_Создать предложение:_\n`/trade тип что кол-во тип что кол-во`"
        edit(text, kb)

    # ─── Рейтинги ────────────────────────────────────────────────
    elif data == "m:top":
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(
            types.InlineKeyboardButton("⚔️ Военный рейтинг", callback_data="m:toparmy"),
            types.InlineKeyboardButton("◀️ Назад",            callback_data="m:main"),
        )
        edit(build_top_text(), kb)

    elif data == "m:toparmy":
        users = db_query("SELECT user_id,username FROM users WHERE banned=0")
        powers = sorted([(uname, calc_power(u)) for u, uname in (users or [])], key=lambda x: x[1], reverse=True)
        powers = [(u, p) for u, p in powers if p > 0][:10]
        medals = ["🥇","🥈","🥉"]
        text = "⚔️ *Рейтинг военной мощи:*\n\n"
        for i, (u, p) in enumerate(powers, 1):
            text += f"{medals[i-1] if i<=3 else str(i)+'.'} @{u} - {p:,}⚔️\n"
        if not powers: text += "Пусто."
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:top"))
        edit(text, kb)

    # ─── Мировая статистика ──────────────────────────────────────
    elif data == "m:world":
        money   = (db_query("SELECT SUM(balance) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
        troops  = (db_query("SELECT SUM(troops) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
        count   = (db_query("SELECT COUNT(*) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
        ep      = (db_query("SELECT SUM(ep) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
        oil     = (db_query("SELECT SUM(quantity) FROM user_portfolio WHERE asset_name='oil'", fetchone=True) or [0])[0] or 0
        trades  = (db_query("SELECT COUNT(*) FROM trade_offers WHERE status='open'", fetchone=True) or [0])[0] or 0
        avg_m   = (db_query("SELECT AVG(morale) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
        nps     = (db_query("SELECT COUNT(*) FROM user_businesses WHERE business_name='nps' AND quantity>0", fetchone=True) or [0])[0] or 0
        miss    = (db_query("SELECT SUM(quantity) FROM user_military WHERE unit_name='missile'", fetchone=True) or [0])[0] or 0
        nsubs   = (db_query("SELECT SUM(quantity) FROM user_military WHERE unit_name='nuclear_sub'", fetchone=True) or [0])[0] or 0
        text = (
            f"🌍 *Мировая статистика Аурелии:*\n\n"
            f"👥 Правителей: {count}\n"
            f"💰 Денег в мире: {money:,}💰\n"
            f"🪖 Войск: {troops:,}\n"
            f"🎺 Средняя мораль: {avg_m:.0f}%\n"
            f"🔬 ОЭ: {ep:,}\n"
            f"🛢️ Нефти: {oil:.1f}\n"
            f"⚛️ АЭС в мире: {nps}\n"
            f"☢️ Баллист. ракет: {int(miss or 0)}\n"
            f"☢️ Атомных подлодок: {int(nsubs or 0)}\n"
            f"🤝 Открытых сделок: {trades}"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="m:main"))
        edit(text, kb)

    else:
        bot.answer_callback_query(call.id)

# ==============================================================
# ТЕКСТОВЫЕ КОМАНДЫ (для прямого доступа + продвинутые операции)
# ==============================================================
@bot.message_handler(commands=['help'])
@group_only
def cmd_help(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    bot.reply_to(message,
        "📋 *Команды Аурелии:*\n\n"
        "🎮 /menu - главное меню (рекомендуется)\n\n"
        "👤 *Профиль:* /profile /cash /upgrade\n"
        "💸 *Переводы:* `/pay @user сумма` | `/senditem @user актив кол`\n"
        "🏢 *Бизнес:* `/buybiz название [кол]` | /mybiz\n"
        "📊 *Биржа:* `/buy актив кол` | `/sell актив кол` | /portfolio\n"
        "⚔️ *Армия:* /army | /draft | `/craft [тип] [кол]`\n"
        "🎁 *Подарить:* `/giftunit @user тип кол`\n"
        "🔬 *Техи:* /tech | `/researchtech название`\n"
        "⛏️ *Добыча:* /extractoil | `/extract [gold|steel|coal|aur]`\n"
        "🤝 *Торговля:* `/trade тип что кол тип что кол`\n"
        "📋 *Сделки:* /trades | `/accept ID` | `/canceltrade ID`\n"
        "🏆 *Рейтинги:* `/top [money|ep|oil|gold|...]` | /toparmy\n"
        "📋 /events - журнал событий\n"
        "✏️ `/rename Название` - переименовать страну\n"
        "🌍 /worldstats\n\n"
        "*Активы:* oil gold steel aur food coal",
        parse_mode="Markdown")

@bot.message_handler(commands=['profile'])
@group_only
def cmd_profile(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💵 Налоги",     callback_data="m:cash"),
        types.InlineKeyboardButton("📈 Улучшить",   callback_data="m:upgrade"),
    )
    bot.reply_to(message, build_profile_text(uid), parse_mode="Markdown", reply_markup=kb)

@bot.message_handler(commands=['cash'])
@group_only
def cmd_cash(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    user = db_query("SELECT balance,level,last_cash FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return bot.reply_to(message, "Введите /start или /menu")
    bal, lv, last = user
    now = time.time()
    if now - (last or 0) < 1800:
        left = int(1800 - (now - last))
        return bot.reply_to(message, f"⏳ Казна пуста. Через {left//60} мин. {left%60} сек.")
    earned = int(500 * (1 + lv*0.2) * (1 + get_tech(uid,'finance')*0.10) * random.uniform(0.8, 1.2))
    db_query("UPDATE users SET balance=balance+?, last_cash=? WHERE user_id=?", (earned, now, uid))
    bot.reply_to(message, f"💵 *+{earned:,}* 💰 в казну!\nБаланс: {bal+earned:,}", parse_mode="Markdown")

@bot.message_handler(commands=['upgrade'])
@group_only
def cmd_upgrade(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    user = db_query("SELECT balance,level FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return bot.reply_to(message, "Введите /menu")
    bal, lv = user
    cost = lv * 3000
    if bal < cost: return bot.reply_to(message, f"Нужно {cost:,} 💰, у вас {bal:,}")
    db_query("UPDATE users SET balance=balance-?, level=level+1 WHERE user_id=?", (cost, uid))
    bot.reply_to(message, f"✅ Экономика - уровень *{lv+1}* за {cost:,} 💰!", parse_mode="Markdown")

@bot.message_handler(commands=['morale'])
@group_only
def cmd_morale(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎮 Меню", callback_data="m:main"))
    # Просто показываем через callback-текст через фейковый call - или напрямую собираем
    user = db_query("SELECT morale, troops, balance FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return
    morale, troops, bal = user
    morale = morale or 100
    logi = get_tech(uid, 'logistics')
    maint = int((troops / 5) * max(0.1, 1 - logi * 0.10))
    if morale >= 90: status = "💚 Непобедимый дух"
    elif morale >= 70: status = "🟢 Высокий боевой дух"
    elif morale >= 50: status = "🟡 Нормальный"
    elif morale >= 30: status = "🟠 Дезертирство"
    elif morale >= 15: status = "🔴 Кризис"
    else: status = "☠️ Коллапс"
    morale_tech = get_tech(uid, 'morale_tech')
    bot.reply_to(message,
        f"🎺 *Мораль:* {morale}% - {status}\n\n"
        f"🪖 Пехота: {troops:,} | 💸 Содержание: ~{maint}/ч\n"
        f"Политработа: Ур.{morale_tech}/5\n\n"
        f"Повышение: оплата армии + `/buy food`",
        parse_mode="Markdown", reply_markup=kb)

@bot.message_handler(commands=['events'])
@group_only
def cmd_events(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    rows = db_query('''SELECT event_type, description, created_at FROM event_log
                       WHERE user_id=? ORDER BY created_at DESC LIMIT 10''', (uid,))
    if not rows: return bot.reply_to(message, "Событий нет.")
    text = "📋 *Последние события:*\n\n"
    for etype, desc, ts in rows:
        dt = time.strftime('%d.%m %H:%M', time.localtime(ts))
        icon = {'desertion': '🏃', 'hunger': '🍽️'}.get(etype, '📌')
        text += f"{icon} [{dt}] {desc}\n"
    bot.reply_to(message, text, parse_mode="Markdown")

# --- Нефтедобыча ---
@bot.message_handler(commands=['extractoil'])
@group_only
def cmd_extractoil(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    ext = db_query("SELECT quantity,last_extract FROM user_extractors WHERE user_id=?", (uid,), fetchone=True)
    if not ext or ext[0] <= 0:
        return bot.reply_to(message, "В вашей стране нет нефтекачек.")
    qty, last = ext
    now = time.time()
    if now - (last or 0) < 3600:
        left = int(3600 - (now - last))
        return bot.reply_to(message, f"⏳ Следующая добыча через {left//60} мин. {left%60} сек.")
    db_query("UPDATE user_extractors SET last_extract=? WHERE user_id=?", (now, uid))
    add_asset(uid, 'oil', qty)
    total = (db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name='oil'", (uid,), fetchone=True) or [0])[0]
    bot.reply_to(message, f"🛢️ Добыто *{qty}* нефти\nВсего: {total:.1f}", parse_mode="Markdown")

@bot.message_handler(commands=['extract'])
@group_only
def cmd_extract(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) < 2:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⛏️ Открыть Добычу", callback_data="m:extract"))
        return bot.reply_to(message, "Использование: `/extract [gold|steel|coal|aur]`", parse_mode="Markdown", reply_markup=kb)
    res = args[1].lower()
    if res not in RESOURCE_BUILDINGS:
        return bot.reply_to(message, f"Доступно: {', '.join(RESOURCE_BUILDINGS.keys())}")
    emoji, name, yld, cd = RESOURCE_BUILDINGS[res]
    row = db_query("SELECT quantity,last_extract FROM user_resource_buildings WHERE user_id=? AND resource=?", (uid, res), fetchone=True)
    if not row or row[0] <= 0:
        return bot.reply_to(message, f"В вашей стране нет {name}.")
    qty, last = row
    now = time.time()
    if now - (last or 0) < cd:
        left = int(cd - (now - last))
        cd_str = f"{left//3600}ч {(left%3600)//60}м" if left >= 3600 else f"{left//60}м {left%60}с"
        return bot.reply_to(message, f"⏳ Следующая добыча через {cd_str}.")
    gained = qty * yld
    db_query("UPDATE user_resource_buildings SET last_extract=? WHERE user_id=? AND resource=?", (now, uid, res))
    add_asset(uid, res, gained)
    total = (db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid, res), fetchone=True) or [0])[0]
    bot.reply_to(message, f"{emoji} Добыто *{gained}* ({qty} зд. ×{yld})\nВсего: {total:.1f}", parse_mode="Markdown")

# --- Технологии ---
@bot.message_handler(commands=['tech'])
@group_only
def cmd_tech(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎮 Меню", callback_data="m:tech"))
    bot.reply_to(message, build_tech_text(uid), parse_mode="Markdown", reply_markup=kb)

@bot.message_handler(commands=['researchtech'])
@group_only
def cmd_researchtech(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) < 2: return bot.reply_to(message, "Использование: `/researchtech [название]`\nСписок: /tech", parse_mode="Markdown")
    tech_name = args[1].lower()
    tech = db_query("SELECT display_name,max_level,ep_cost_per_level FROM tech_types WHERE name=?", (tech_name,), fetchone=True)
    if not tech: return bot.reply_to(message, f"Технология '{tech_name}' не найдена. /tech")
    disp, maxlv, cost = tech
    lv = get_tech(uid, tech_name)
    if lv >= maxlv: return bot.reply_to(message, f"✅ *{disp}* уже максимальная.", parse_mode="Markdown")
    ep = (db_query("SELECT ep FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    if ep < cost: return bot.reply_to(message, f"Нужно {cost} ОЭ, у вас {ep}")
    db_query("UPDATE users SET ep=ep-? WHERE user_id=?", (cost, uid))
    if lv == 0:
        db_query("INSERT INTO user_tech VALUES (?,?,1)", (uid, tech_name))
    else:
        db_query("UPDATE user_tech SET level=level+1 WHERE user_id=? AND tech_name=?", (uid, tech_name))
    bot.reply_to(message, f"🔬 *{disp}* - Ур.*{lv+1}/{maxlv}*\nПотрачено: {cost} ОЭ", parse_mode="Markdown")

# --- Армия ---
@bot.message_handler(commands=['army'])
@group_only
def cmd_army(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🪖 Призыв",    callback_data="m:draft"),
        types.InlineKeyboardButton("🎺 Мораль",    callback_data="m:morale"),
        types.InlineKeyboardButton("🔫 Наземные",  callback_data="m:craft:ground"),
        types.InlineKeyboardButton("✈️ Авиация",    callback_data="m:craft:air"),
        types.InlineKeyboardButton("🚢 Флот",      callback_data="m:craft:navy"),
    )
    bot.reply_to(message, build_army_text(uid), parse_mode="Markdown", reply_markup=kb)

@bot.message_handler(commands=['draft'])
@group_only
def cmd_draft(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    user = db_query("SELECT troops,last_draft,morale FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return bot.reply_to(message, "Введите /menu")
    troops, last, morale = user
    now = time.time()
    if now - (last or 0) < 7200:
        left = int(7200 - (now - last))
        return bot.reply_to(message, f"⏳ Следующий призыв через {left//3600}ч {(left%3600)//60}мин.")
    morale = morale or 100
    new_recruits = int(random.randint(1000, 2000) * max(0.3, morale / 100))
    db_query("UPDATE users SET troops=troops+?, last_draft=? WHERE user_id=?", (new_recruits, now, uid))
    note = f"\n⚠️ Низкая мораль ({morale}%) сократила призыв!" if morale < 60 else ""
    bot.reply_to(message, f"🪖 *Призыв!* +*{new_recruits}* новобранцев\nВсего: {troops+new_recruits:,}{note}", parse_mode="Markdown")

@bot.message_handler(commands=['craft'])
@group_only
def cmd_craft(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()

    if len(args) < 3:
        kb = types.InlineKeyboardMarkup(row_width=3)
        kb.add(
            types.InlineKeyboardButton("🔫 Наземные", callback_data="m:craft:ground"),
            types.InlineKeyboardButton("✈️ Авиация",   callback_data="m:craft:air"),
            types.InlineKeyboardButton("🚢 Флот",      callback_data="m:craft:navy"),
        )
        return bot.reply_to(message, "⚙️ *Производство:* выберите категорию\nИли: `/craft [тип] [кол-во]`", parse_mode="Markdown", reply_markup=kb)

    unit_name = args[1].lower()
    try: qty = int(args[2])
    except: return bot.reply_to(message, "Количество - число.")
    if qty <= 0: return bot.reply_to(message, "Количество > 0.")
    unit = db_query("SELECT display_name,steel_cost,money_cost FROM military_types WHERE name=?", (unit_name,), fetchone=True)
    if not unit: return bot.reply_to(message, f"Тип '{unit_name}' не найден. /craft")
    disp, steel_c, money_c = unit

    if unit_name in UNIT_TECH_REQUIREMENTS:
        missing = []
        for tname, min_lv in UNIT_TECH_REQUIREMENTS[unit_name]:
            cur_lv = get_tech(uid, tname)
            if cur_lv < min_lv:
                td = db_query("SELECT display_name FROM tech_types WHERE name=?", (tname,), fetchone=True)
                missing.append(f"{td[0] if td else tname} Ур.{min_lv} (у вас: {cur_lv})")
        if missing:
            return bot.reply_to(message, f"❌ Требования для *{disp}*:\n" + "\n".join(f"- {m}" for m in missing), parse_mode="Markdown")

    total_steel = int(steel_c * qty * max(0.2, 1 - get_tech(uid, 'metallurgy') * 0.08))
    total_money = int(money_c * qty * max(0.2, 1 - get_tech(uid, 'engineering') * 0.08))
    bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    sr = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name='steel'", (uid,), fetchone=True)
    cur_steel = int(sr[0]) if sr else 0

    if bal < total_money or cur_steel < total_steel:
        return bot.reply_to(message, f"Нужно: {total_steel}⚙️ + {total_money:,}💰\nЕсть: {cur_steel}⚙️ + {bal:,}💰")

    extra_needed = {}
    if unit_name in UNIT_RESOURCE_REQUIREMENTS:
        for asset, per_unit in UNIT_RESOURCE_REQUIREMENTS[unit_name].items():
            needed = per_unit * qty
            row = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid, asset), fetchone=True)
            have = row[0] if row else 0
            if have < needed:
                ar = db_query("SELECT display_name FROM market_assets WHERE name=?", (asset,), fetchone=True)
                return bot.reply_to(message, f"❌ Ядерное: нужно *{needed}x {ar[0] if ar else asset}*, у вас {have:.1f}", parse_mode="Markdown")
            extra_needed[asset] = needed

    db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (total_money, uid))
    db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name='steel'", (total_steel, uid))
    for asset, needed in extra_needed.items():
        db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name=?", (needed, uid, asset))
    db_query("INSERT INTO user_military VALUES (?,?,?) ON CONFLICT(user_id,unit_name) DO UPDATE SET quantity=quantity+?", (uid, unit_name, qty, qty))
    extra_str = " | ".join(f"-{v}x{k}" for k, v in extra_needed.items())
    bot.reply_to(message, f"🏭 *{qty}× {disp}* произведено!\n-{total_steel}⚙️ | -{total_money:,}💰" + (f" | {extra_str}" if extra_str else ""), parse_mode="Markdown")

@bot.message_handler(commands=['giftunit'])
@group_only
def cmd_giftunit(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 4: return bot.reply_to(message, "Использование: `/giftunit @user [тип] [кол-во]`", parse_mode="Markdown")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, f"{args[1]} не найден.")
    unit_name = args[2].lower()
    try: qty = int(args[3])
    except: return bot.reply_to(message, "Количество - число.")
    if qty <= 0 or t[0] == uid: return bot.reply_to(message, "Нельзя.")
    unit = db_query("SELECT display_name FROM military_types WHERE name=?", (unit_name,), fetchone=True)
    if not unit: return bot.reply_to(message, f"Тип '{unit_name}' не найден.")
    row = db_query("SELECT quantity FROM user_military WHERE user_id=? AND unit_name=?", (uid, unit_name), fetchone=True)
    if not row or row[0] < qty: return bot.reply_to(message, f"У вас только {row[0] if row else 0} {unit[0]}")
    db_query("UPDATE user_military SET quantity=quantity-? WHERE user_id=? AND unit_name=?", (qty, uid, unit_name))
    e = db_query("SELECT quantity FROM user_military WHERE user_id=? AND unit_name=?", (t[0], unit_name), fetchone=True)
    if e: db_query("UPDATE user_military SET quantity=quantity+? WHERE user_id=? AND unit_name=?", (qty, t[0], unit_name))
    else: db_query("INSERT INTO user_military VALUES (?,?,?)", (t[0], unit_name, qty))
    bot.reply_to(message, f"🎁 *{qty}× {unit[0]}* подарено @{t[1]}!", parse_mode="Markdown")

# --- Биржа ---
@bot.message_handler(commands=['market'])
@group_only
def cmd_market(message):
    if is_banned(message.from_user.id): return
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("💼 Портфель",  callback_data="m:portfolio"),
        types.InlineKeyboardButton("📊 Обновить",  callback_data="m:prices"),
    )
    bot.reply_to(message, build_market_text(), parse_mode="Markdown", reply_markup=kb)

@bot.message_handler(commands=['buy'])
@group_only
def cmd_buy(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) < 3: return bot.reply_to(message, "Использование: `/buy [актив] [кол-во]`\nАктивы: oil gold steel aur food coal", parse_mode="Markdown")
    asset = args[1].lower()
    try: qty = int(args[2])
    except: return bot.reply_to(message, "Количество - число.")
    if qty <= 0: return bot.reply_to(message, "Количество > 0.")
    arow = db_query("SELECT display_name,price FROM market_assets WHERE name=?", (asset,), fetchone=True)
    if not arow: return bot.reply_to(message, f"Актив '{asset}' не найден. /market")
    disp, price = arow
    total = round(price * qty, 2)
    bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    if bal < total: return bot.reply_to(message, f"Нужно {total:.2f}💰, у вас {bal:,}💰")
    e = db_query("SELECT quantity,avg_buy_price FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid, asset), fetchone=True)
    if e:
        nq = e[0] + qty; na = (e[0] * e[1] + price * qty) / nq
        db_query("UPDATE user_portfolio SET quantity=?,avg_buy_price=? WHERE user_id=? AND asset_name=?", (nq, na, uid, asset))
    else:
        db_query("INSERT INTO user_portfolio VALUES (?,?,?,?)", (uid, asset, qty, price))
    db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (total, uid))
    bot.reply_to(message, f"✅ *{qty}× {disp}* за {total:.2f}💰", parse_mode="Markdown")

@bot.message_handler(commands=['sell'])
@group_only
def cmd_sell(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) < 3: return bot.reply_to(message, "Использование: `/sell [актив] [кол-во]`", parse_mode="Markdown")
    asset = args[1].lower()
    try: qty = int(args[2])
    except: return bot.reply_to(message, "Количество - число.")
    if qty <= 0: return bot.reply_to(message, "Количество > 0.")
    arow = db_query("SELECT display_name,price FROM market_assets WHERE name=?", (asset,), fetchone=True)
    if not arow: return bot.reply_to(message, f"Актив '{asset}' не найден.")
    disp, price = arow
    row = db_query("SELECT quantity,avg_buy_price FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid, asset), fetchone=True)
    if not row or row[0] < qty: return bot.reply_to(message, f"У вас только {row[0] if row else 0:.1f} {disp}")
    rev = round(price * qty, 2); profit = round((price - row[1]) * qty, 2)
    nq = row[0] - qty
    if nq <= 0: db_query("DELETE FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid, asset))
    else: db_query("UPDATE user_portfolio SET quantity=? WHERE user_id=? AND asset_name=?", (nq, uid, asset))
    db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (rev, uid))
    pstr = f"+{profit:.2f}" if profit >= 0 else f"{profit:.2f}"
    bot.reply_to(message, f"💰 *{qty}× {disp}* → {rev:.2f}💰\n{'📈' if profit>=0 else '📉'} P&L: *{pstr}💰*", parse_mode="Markdown")

@bot.message_handler(commands=['portfolio'])
@group_only
def cmd_portfolio(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📊 Биржа", callback_data="m:prices"))
    rows = db_query('''SELECT p.asset_name,p.quantity,p.avg_buy_price,m.price,m.display_name
                       FROM user_portfolio p JOIN market_assets m ON p.asset_name=m.name
                       WHERE p.user_id=? AND p.quantity>0''', (uid,))
    if not rows: return bot.reply_to(message, "Портфель пуст. /market", reply_markup=kb)
    text = "💼 *Портфель:*\n\n"
    ti = tc = 0.0
    for _, qty, avg, cur, disp in rows:
        inv = avg * qty; cv = cur * qty; pnl = cv - inv; ti += inv; tc += cv
        e = "📈" if pnl >= 0 else "📉"
        pstr = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
        text += f"{e} *{disp}* ×{qty:.1f} | avg:{avg:.2f}→{cur:.2f} | {pstr}💰\n"
    tp = tc - ti
    tstr = f"+{tp:.2f}" if tp >= 0 else f"{tp:.2f}"
    text += f"\n{'📈' if tp>=0 else '📉'} *P&L: {tstr}💰*"
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=kb)

# --- Торговля ---
@bot.message_handler(commands=['trade'])
@group_only
def cmd_trade(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 7:
        return bot.reply_to(message,
            "📋 *Создать торговое предложение:*\n"
            "`/trade [тип] [что] [кол] [тип] [что] [кол]`\n\n"
            "*Типы:* `money` или `asset`\n\n"
            "*Примеры:*\n"
            "`/trade asset steel 50 money money 5000`\n"
            "`/trade money money 10000 asset gold 15`",
            parse_mode="Markdown")
    _, ot, on, oq_s, wt, wn, wq_s = args
    ot = ot.lower(); wt = wt.lower()
    try: oq = float(oq_s); wq = float(wq_s)
    except: return bot.reply_to(message, "Количество - число.")
    if oq <= 0 or wq <= 0: return bot.reply_to(message, "Количество > 0.")

    if ot == 'money':
        on = 'money'
        bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
        if bal < int(oq): return bot.reply_to(message, f"Нужно {int(oq):,}💰, у вас {bal:,}")
        db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (int(oq), uid))
    elif ot == 'asset':
        on = on.lower()
        if not db_query("SELECT name FROM market_assets WHERE name=?", (on,), fetchone=True):
            return bot.reply_to(message, f"Актив '{on}' не найден.")
        row = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid, on), fetchone=True)
        if not row or row[0] < oq: return bot.reply_to(message, f"Недостаточно {on}")
        db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name=?", (oq, uid, on))
    else:
        return bot.reply_to(message, "Тип: 'money' или 'asset'")

    if wt == 'money': wn = 'money'
    elif wt == 'asset':
        wn = wn.lower()
        if not db_query("SELECT name FROM market_assets WHERE name=?", (wn,), fetchone=True):
            if ot == 'money': db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (int(oq), uid))
            else: db_query("UPDATE user_portfolio SET quantity=quantity+? WHERE user_id=? AND asset_name=?", (oq, uid, on))
            return bot.reply_to(message, f"Актив '{wn}' не найден.")
    else:
        if ot == 'money': db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (int(oq), uid))
        else: db_query("UPDATE user_portfolio SET quantity=quantity+? WHERE user_id=? AND asset_name=?", (oq, uid, on))
        return bot.reply_to(message, "Тип: 'money' или 'asset'")

    db_query("INSERT INTO trade_offers (seller_id,seller_username,offer_type,offer_name,offer_qty,want_type,want_name,want_qty,created_at,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
             (uid, uname, ot, on, oq, wt, wn, wq, time.time(), 'open'))
    tid = db_query("SELECT id FROM trade_offers WHERE seller_id=? ORDER BY id DESC LIMIT 1", (uid,), fetchone=True)[0]
    ostr = f"{int(oq):,}💰" if ot == 'money' else f"{oq} {on}"
    wstr = f"{int(wq):,}💰" if wt == 'money' else f"{wq} {wn}"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📋 Все сделки", callback_data="m:trade"))
    bot.reply_to(message, f"✅ *Предложение #{tid}*\nОтдаю: {ostr} → Хочу: {wstr}\n`/accept {tid}`", parse_mode="Markdown", reply_markup=kb)

@bot.message_handler(commands=['trades'])
@group_only
def cmd_trades(message):
    if is_banned(message.from_user.id): return
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔄 Обновить", callback_data="m:trade"))
    bot.reply_to(message, build_trades_text(), parse_mode="Markdown", reply_markup=kb)

@bot.message_handler(commands=['accept'])
@group_only
def cmd_accept(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 2: return bot.reply_to(message, "Использование: `/accept [ID]`", parse_mode="Markdown")
    try: tid = int(args[1])
    except: return bot.reply_to(message, "ID - число.")
    offer = db_query('''SELECT seller_id,seller_username,offer_type,offer_name,offer_qty,
                               want_type,want_name,want_qty FROM trade_offers
                        WHERE id=? AND status='open' ''', (tid,), fetchone=True)
    if not offer: return bot.reply_to(message, f"Предложение #{tid} не найдено.")
    seller_id, seller_uname, ot, on, oq, wt, wn, wq = offer
    if seller_id == uid: return bot.reply_to(message, "Нельзя принять своё предложение.")

    if wt == 'money':
        bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
        if bal < int(wq): return bot.reply_to(message, f"Нужно {int(wq):,}💰, у вас {bal:,}")
        db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (int(wq), uid))
    else:
        row = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid, wn), fetchone=True)
        if not row or row[0] < wq: return bot.reply_to(message, f"Недостаточно {wn}")
        db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name=?", (wq, uid, wn))

    if ot == 'money': db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (int(oq), uid))
    else: add_asset(uid, on, oq)
    if wt == 'money': db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (int(wq), seller_id))
    else: add_asset(seller_id, wn, wq)

    db_query("UPDATE trade_offers SET status='closed' WHERE id=?", (tid,))
    ostr = f"{int(oq):,}💰" if ot == 'money' else f"{oq} {on}"
    wstr = f"{int(wq):,}💰" if wt == 'money' else f"{wq} {wn}"
    bot.reply_to(message, f"✅ *Сделка #{tid}!*\n@{uname} купил {ostr} у @{seller_uname} за {wstr}", parse_mode="Markdown")

@bot.message_handler(commands=['canceltrade'])
@group_only
def cmd_canceltrade(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 2: return bot.reply_to(message, "Использование: `/canceltrade [ID]`", parse_mode="Markdown")
    try: tid = int(args[1])
    except: return bot.reply_to(message, "ID - число.")
    offer = db_query("SELECT seller_id,offer_type,offer_name,offer_qty FROM trade_offers WHERE id=? AND status='open'", (tid,), fetchone=True)
    if not offer: return bot.reply_to(message, f"Предложение #{tid} не найдено.")
    if offer[0] != uid and not is_admin(uid): return bot.reply_to(message, "Это не ваше предложение.")
    sid, ot, on, oq = offer
    if ot == 'money': db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (int(oq), sid))
    else: add_asset(sid, on, oq)
    db_query("UPDATE trade_offers SET status='cancelled' WHERE id=?", (tid,))
    bot.reply_to(message, f"✅ Предложение #{tid} отменено, активы возвращены.")

# --- Переводы ---
@bot.message_handler(commands=['pay'])
@group_only
def cmd_pay(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "Использование: `/pay @user [сумма]`", parse_mode="Markdown")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, f"{args[1]} не найден.")
    try: amount = int(args[2])
    except: return bot.reply_to(message, "Сумма - число.")
    if amount <= 0 or t[0] == uid: return bot.reply_to(message, "Нельзя.")
    bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    if bal < amount: return bot.reply_to(message, "Недостаточно средств.")
    db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, uid))
    db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, t[0]))
    bot.reply_to(message, f"💸 *{amount:,}💰* → @{t[1]}", parse_mode="Markdown")

@bot.message_handler(commands=['senditem'])
@group_only
def cmd_senditem(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 4: return bot.reply_to(message, "Использование: `/senditem @user [актив] [кол-во]`", parse_mode="Markdown")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, f"{args[1]} не найден.")
    asset = args[2].lower()
    try: amount = float(args[3])
    except: return bot.reply_to(message, "Количество - число.")
    if amount <= 0 or t[0] == uid: return bot.reply_to(message, "Нельзя.")
    arow = db_query("SELECT display_name FROM market_assets WHERE name=?", (asset,), fetchone=True)
    if not arow: return bot.reply_to(message, f"Актив '{asset}' не найден.")
    row = db_query("SELECT quantity,avg_buy_price FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid, asset), fetchone=True)
    if not row or row[0] < amount: return bot.reply_to(message, f"Недостаточно {arow[0]}")
    nq = row[0] - amount
    if nq <= 0: db_query("DELETE FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid, asset))
    else: db_query("UPDATE user_portfolio SET quantity=? WHERE user_id=? AND asset_name=?", (nq, uid, asset))
    te = db_query("SELECT quantity,avg_buy_price FROM user_portfolio WHERE user_id=? AND asset_name=?", (t[0], asset), fetchone=True)
    if te:
        new_avg = (te[0] * te[1] + amount * row[1]) / (te[0] + amount)
        db_query("UPDATE user_portfolio SET quantity=quantity+?, avg_buy_price=? WHERE user_id=? AND asset_name=?", (amount, new_avg, t[0], asset))
    else:
        db_query("INSERT INTO user_portfolio VALUES (?,?,?,?)", (t[0], asset, amount, row[1]))
    bot.reply_to(message, f"📦 *{amount}× {arow[0]}* → @{t[1]}", parse_mode="Markdown")

# --- Бизнес ---
@bot.message_handler(commands=['shop'])
@group_only
def cmd_shop(message):
    if is_banned(message.from_user.id): return
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🏢 Мои бизнесы", callback_data="m:mybiz"))
    rows = db_query("SELECT name,display_name,cost,income_per_hour,description,ep_per_12h FROM business_types")
    text = "🏪 *Магазин бизнесов:*\n\n"
    for name, disp, cost, iph, desc, ep12 in rows:
        ep_str = f" | 🔬+{ep12}ОЭ/12ч" if ep12 else ""
        text += f"*{disp}* - {cost:,}💰 | ~{iph}💰/ч{ep_str}\n_{desc}_\n`/buybiz {name} [кол-во]`\n\n"
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=kb)

@bot.message_handler(commands=['buybiz'])
@group_only
def cmd_buybiz(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) < 2: return bot.reply_to(message, "Использование: `/buybiz [название] [кол-во]`\nМагазин: /shop", parse_mode="Markdown")
    bname = args[1].lower()
    qty = int(args[2]) if len(args) >= 3 and args[2].isdigit() else 1
    if qty < 1: return bot.reply_to(message, "Количество >= 1.")
    biz = db_query("SELECT display_name,cost,income_per_hour,ep_per_12h FROM business_types WHERE name=?", (bname,), fetchone=True)
    if not biz: return bot.reply_to(message, f"Бизнес '{bname}' не найден. /shop")
    disp, cost, iph, ep12 = biz

    if bname == 'nps':
        energy_lv = get_tech(uid, 'energy')
        if energy_lv < 3:
            return bot.reply_to(message, f"⚛️ АЭС требует *Энергетика Ур.3* (у вас: {energy_lv}).", parse_mode="Markdown")
        existing = db_query("SELECT quantity FROM user_businesses WHERE user_id=? AND business_name='nps'", (uid,), fetchone=True)
        if existing and existing[0] >= 1:
            return bot.reply_to(message, "⚛️ У вашей страны уже есть АЭС.")
        sr = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name='steel'", (uid,), fetchone=True)
        ar = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name='aur'", (uid,), fetchone=True)
        cur_steel = int(sr[0]) if sr else 0
        cur_aur = float(ar[0]) if ar else 0.0
        bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
        if bal < cost or cur_steel < 500 or cur_aur < 20:
            return bot.reply_to(message, f"⚛️ *АЭС требует:*\n💰 {cost:,} (у вас: {bal:,})\n⚙️ 500 стали (у вас: {cur_steel})\n💎 20 аурита (у вас: {cur_aur:.1f})", parse_mode="Markdown")
        db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (cost, uid))
        db_query("UPDATE user_portfolio SET quantity=quantity-500 WHERE user_id=? AND asset_name='steel'", (uid,))
        db_query("UPDATE user_portfolio SET quantity=quantity-20 WHERE user_id=? AND asset_name='aur'", (uid,))
        db_query("INSERT INTO user_businesses (user_id,business_name,quantity) VALUES (?,?,1) ON CONFLICT(user_id,business_name) DO UPDATE SET quantity=quantity+1", (uid, bname))
        bot.reply_to(message, f"⚛️ *АЭС построена!*\n-{cost:,}💰 | -500⚙️ | -20💎\n💵 {iph:,}💰/ч | ⚡ -25% расход топлива армии", parse_mode="Markdown")
        return

    total = cost * qty
    bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    if bal < total: return bot.reply_to(message, f"Нужно {total:,}💰, у вас {bal:,}💰")
    db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (total, uid))
    db_query("INSERT INTO user_businesses (user_id,business_name,quantity) VALUES (?,?,?) ON CONFLICT(user_id,business_name) DO UPDATE SET quantity=quantity+?", (uid, bname, qty, qty))
    ep_str = f"\n🔬 +{ep12*qty}ОЭ/12ч" if ep12 else ""
    bot.reply_to(message, f"✅ *{qty}× {disp}* за {total:,}💰!\n~{iph*qty}💰/ч{ep_str}", parse_mode="Markdown")

@bot.message_handler(commands=['mybiz'])
@group_only
def cmd_mybiz(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🛒 Магазин", callback_data="m:shop"))
    rows = db_query('''SELECT bt.display_name,ub.quantity,bt.income_per_hour,bt.ep_per_12h
                       FROM user_businesses ub JOIN business_types bt ON ub.business_name=bt.name
                       WHERE ub.user_id=?''', (uid,))
    if not rows: return bot.reply_to(message, "У вас нет бизнесов.\n/shop - купить", reply_markup=kb)
    text = "🏢 *Мои бизнесы:*\n\n"
    ti = te = 0
    for disp, qty, iph, ep12 in rows:
        si = iph * qty; se = ep12 * qty; ti += si; te += se
        ep_str = f" | +{se}ОЭ" if se else ""
        text += f"*{disp}* ×{qty} - {si}💰/ч{ep_str}\n"
    text += f"\n📊 *~{ti}💰/ч | 🔬+{te}ОЭ/12ч | ~{ti*24:,}💰/сут*"
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=kb)

# --- Рейтинги ---
@bot.message_handler(commands=['top'])
@group_only
def cmd_top(message):
    args = message.text.split()
    if len(args) < 2:
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("💰 Баланс",   callback_data="m:top"),
            types.InlineKeyboardButton("⚔️ Армия",     callback_data="m:toparmy"),
        )
        return bot.reply_to(message, build_top_text(), parse_mode="Markdown", reply_markup=kb)
    cat = args[1].lower()
    if cat == 'money':
        rows = db_query("SELECT username,balance FROM users WHERE banned=0 ORDER BY balance DESC LIMIT 10")
        text = "🏆 *Топ по балансу:*\n\n"
        for i,(u,v) in enumerate(rows or [],1): text += f"{i}. @{u} - {v:,}💰\n"
    elif cat == 'ep':
        rows = db_query("SELECT username,ep FROM users WHERE banned=0 ORDER BY ep DESC LIMIT 10")
        text = "🏆 *Топ по ОЭ:*\n\n"
        for i,(u,v) in enumerate(rows or [],1): text += f"{i}. @{u} - {v:,}🔬\n"
    else:
        arow = db_query("SELECT display_name FROM market_assets WHERE name=?", (cat,), fetchone=True)
        if not arow: return bot.reply_to(message, f"Категория '{cat}' не найдена.")
        rows = db_query('''SELECT u.username,p.quantity FROM user_portfolio p
                           JOIN users u ON p.user_id=u.user_id
                           WHERE p.asset_name=? AND p.quantity>0 AND u.banned=0
                           ORDER BY p.quantity DESC LIMIT 10''', (cat,))
        text = f"🏆 *Топ по {arow[0]}:*\n\n"
        for i,(u,v) in enumerate(rows or [],1): text += f"{i}. @{u} - {v:.1f}\n"
    bot.reply_to(message, text or "Рейтинг пуст.", parse_mode="Markdown")

@bot.message_handler(commands=['toparmy'])
@group_only
def cmd_toparmy(message):
    users = db_query("SELECT user_id,username FROM users WHERE banned=0")
    powers = sorted([(uname, calc_power(uid)) for uid, uname in (users or [])], key=lambda x: x[1], reverse=True)
    powers = [(u, p) for u, p in powers if p > 0][:10]
    medals = ["🥇","🥈","🥉"]
    text = "⚔️ *Рейтинг военной мощи:*\n\n"
    for i,(u,p) in enumerate(powers,1):
        text += f"{medals[i-1] if i<=3 else str(i)+'.'} @{u} - {p:,}⚔️\n"
    if not powers: text += "Рейтинг пуст."
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['worldstats'])
@group_only
def cmd_worldstats(message):
    money  = (db_query("SELECT SUM(balance) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
    troops = (db_query("SELECT SUM(troops) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
    count  = (db_query("SELECT COUNT(*) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
    ep     = (db_query("SELECT SUM(ep) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
    oil    = (db_query("SELECT SUM(quantity) FROM user_portfolio WHERE asset_name='oil'", fetchone=True) or [0])[0] or 0
    trades = (db_query("SELECT COUNT(*) FROM trade_offers WHERE status='open'", fetchone=True) or [0])[0] or 0
    avg_m  = (db_query("SELECT AVG(morale) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
    nps    = (db_query("SELECT COUNT(*) FROM user_businesses WHERE business_name='nps' AND quantity>0", fetchone=True) or [0])[0] or 0
    miss   = (db_query("SELECT SUM(quantity) FROM user_military WHERE unit_name='missile'", fetchone=True) or [0])[0] or 0
    nsubs  = (db_query("SELECT SUM(quantity) FROM user_military WHERE unit_name='nuclear_sub'", fetchone=True) or [0])[0] or 0
    bot.reply_to(message,
        f"🌍 *Мировая статистика:*\n\n"
        f"👥 Правителей: {count}\n💰 Денег: {money:,}💰\n"
        f"🪖 Войск: {troops:,}\n🎺 Средняя мораль: {avg_m:.0f}%\n"
        f"🔬 ОЭ: {ep:,}\n🛢️ Нефти: {oil:.1f}\n"
        f"⚛️ АЭС: {nps}\n☢️ Ракет: {int(miss or 0)}\n"
        f"☢️ Атомных подлодок: {int(nsubs or 0)}\n🤝 Сделок: {trades}",
        parse_mode="Markdown")

# ==============================================================
# ADMIN КОМАНДЫ
# ==============================================================
@bot.message_handler(commands=['adminhelp'])
@admin_only
def cmd_adminhelp(message):
    bot.reply_to(message,
        "🔧 *Администрирование:*\n\n"
        "/givemoney /takemoney @u сумма\n"
        "/giveep @u кол-во\n"
        "/giveitem /takeitem @u актив кол\n"
        "/giveextractor /takeextractor @u кол\n"
        "/givebuilding /takebuilding @u [gold|steel|coal|aur] кол\n"
        "/givemilitary @u тип кол\n"
        "/setlevel /settroops /setmorale /settech @u ...\n"
        "/banuser /unbanuser /wipeuser @u\n"
        "/playerinfo @u\n"
        "/setprice /setbaseprice актив цена\n"
        "/marketevent актив %\n"
        "/marketcrash | /marketboom | /resetmarket\n"
        "/broadcast /announcement текст\n"
        "/initcountry @u страна [reset] -- инит страны\n"
        "/initbasic @u [micro|small|medium|large] -- базовый пакет\n"
        "/listcountries -- список пресетов\n"
        "/setcountry @u Название -- задать название страны",
        parse_mode="Markdown")

@bot.message_handler(commands=['givemoney'])
@admin_only
def cmd_givemoney(message):
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "/givemoney @user сумма")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    try: a = int(args[2])
    except: return bot.reply_to(message, "Сумма - число.")
    db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (a, t[0]))
    bot.reply_to(message, f"✅ @{t[1]} +{a:,}💰")

@bot.message_handler(commands=['takemoney'])
@admin_only
def cmd_takemoney(message):
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "/takemoney @user сумма")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    try: a = int(args[2])
    except: return bot.reply_to(message, "Сумма - число.")
    db_query("UPDATE users SET balance=MAX(0,balance-?) WHERE user_id=?", (a, t[0]))
    bot.reply_to(message, f"✅ @{t[1]} -{a:,}💰")

@bot.message_handler(commands=['giveep'])
@admin_only
def cmd_giveep(message):
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "/giveep @user кол-во")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    try: a = int(args[2])
    except: return bot.reply_to(message, "Количество - число.")
    db_query("UPDATE users SET ep=ep+? WHERE user_id=?", (a, t[0]))
    bot.reply_to(message, f"✅ @{t[1]} +{a}🔬ОЭ")

@bot.message_handler(commands=['giveitem'])
@admin_only
def cmd_giveitem(message):
    args = message.text.split()
    if len(args) != 4: return bot.reply_to(message, "/giveitem @user актив кол-во")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    asset = args[2].lower()
    try: a = float(args[3])
    except: return bot.reply_to(message, "Количество - число.")
    if not db_query("SELECT name FROM market_assets WHERE name=?", (asset,), fetchone=True):
        return bot.reply_to(message, f"Актив '{asset}' не найден.")
    add_asset(t[0], asset, a)
    bot.reply_to(message, f"✅ @{t[1]} +{a}×{asset}")

@bot.message_handler(commands=['takeitem'])
@admin_only
def cmd_takeitem(message):
    args = message.text.split()
    if len(args) != 4: return bot.reply_to(message, "/takeitem @user актив кол-во")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    asset = args[2].lower()
    try: a = float(args[3])
    except: return bot.reply_to(message, "Количество - число.")
    db_query("UPDATE user_portfolio SET quantity=MAX(0,quantity-?) WHERE user_id=? AND asset_name=?", (a, t[0], asset))
    bot.reply_to(message, f"✅ @{t[1]} -{a}×{asset}")

@bot.message_handler(commands=['giveextractor'])
@admin_only
def cmd_giveextractor(message):
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "/giveextractor @user кол-во")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    try: a = int(args[2])
    except: return bot.reply_to(message, "Количество - число.")
    e = db_query("SELECT quantity FROM user_extractors WHERE user_id=?", (t[0],), fetchone=True)
    if e: db_query("UPDATE user_extractors SET quantity=quantity+? WHERE user_id=?", (a, t[0]))
    else: db_query("INSERT INTO user_extractors VALUES (?,?,?)", (t[0], a, 0))
    bot.reply_to(message, f"✅ @{t[1]} +{a}🛢️")

@bot.message_handler(commands=['takeextractor'])
@admin_only
def cmd_takeextractor(message):
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "/takeextractor @user кол-во")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    try: a = int(args[2])
    except: return bot.reply_to(message, "Количество - число.")
    db_query("UPDATE user_extractors SET quantity=MAX(0,quantity-?) WHERE user_id=?", (a, t[0]))
    bot.reply_to(message, f"✅ @{t[1]} -{a}🛢️")

@bot.message_handler(commands=['givebuilding'])
@admin_only
def cmd_givebuilding(message):
    args = message.text.split()
    if len(args) != 4: return bot.reply_to(message, "/givebuilding @user [gold|steel|coal|aur] кол-во")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    res = args[2].lower()
    if res not in RESOURCE_BUILDINGS:
        return bot.reply_to(message, f"Доступно: {', '.join(RESOURCE_BUILDINGS.keys())}")
    try: a = int(args[3])
    except: return bot.reply_to(message, "Количество - число.")
    emoji, name, _, _ = RESOURCE_BUILDINGS[res]
    e = db_query("SELECT quantity FROM user_resource_buildings WHERE user_id=? AND resource=?", (t[0], res), fetchone=True)
    if e: db_query("UPDATE user_resource_buildings SET quantity=quantity+? WHERE user_id=? AND resource=?", (a, t[0], res))
    else: db_query("INSERT INTO user_resource_buildings VALUES (?,?,?,?)", (t[0], res, a, 0))
    bot.reply_to(message, f"✅ @{t[1]} +{a}×{emoji}{name}")

@bot.message_handler(commands=['takebuilding'])
@admin_only
def cmd_takebuilding(message):
    args = message.text.split()
    if len(args) != 4: return bot.reply_to(message, "/takebuilding @user [gold|steel|coal|aur] кол-во")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    res = args[2].lower()
    if res not in RESOURCE_BUILDINGS:
        return bot.reply_to(message, f"Доступно: {', '.join(RESOURCE_BUILDINGS.keys())}")
    try: a = int(args[3])
    except: return bot.reply_to(message, "Количество - число.")
    emoji, name, _, _ = RESOURCE_BUILDINGS[res]
    db_query("UPDATE user_resource_buildings SET quantity=MAX(0,quantity-?) WHERE user_id=? AND resource=?", (a, t[0], res))
    bot.reply_to(message, f"✅ @{t[1]} -{a}×{emoji}{name}")

@bot.message_handler(commands=['givemilitary'])
@admin_only
def cmd_givemilitary(message):
    args = message.text.split()
    if len(args) != 4: return bot.reply_to(message, "/givemilitary @user тип кол-во")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    unit = args[2].lower()
    try: a = int(args[3])
    except: return bot.reply_to(message, "Количество - число.")
    un = db_query("SELECT display_name FROM military_types WHERE name=?", (unit,), fetchone=True)
    if not un: return bot.reply_to(message, f"Тип '{unit}' не найден.")
    e = db_query("SELECT quantity FROM user_military WHERE user_id=? AND unit_name=?", (t[0], unit), fetchone=True)
    if e: db_query("UPDATE user_military SET quantity=quantity+? WHERE user_id=? AND unit_name=?", (a, t[0], unit))
    else: db_query("INSERT INTO user_military VALUES (?,?,?)", (t[0], unit, a))
    bot.reply_to(message, f"✅ @{t[1]} +{a}×{un[0]}")

@bot.message_handler(commands=['setlevel'])
@admin_only
def cmd_setlevel(message):
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "/setlevel @user уровень")
    t = find_user(args[1]);
    if not t: return bot.reply_to(message, "Не найден.")
    try: lv = int(args[2])
    except: return bot.reply_to(message, "Уровень - число.")
    db_query("UPDATE users SET level=? WHERE user_id=?", (lv, t[0]))
    bot.reply_to(message, f"✅ @{t[1]} уровень={lv}")

@bot.message_handler(commands=['settroops'])
@admin_only
def cmd_settroops(message):
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "/settroops @user кол-во")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    try: a = int(args[2])
    except: return bot.reply_to(message, "Количество - число.")
    db_query("UPDATE users SET troops=? WHERE user_id=?", (a, t[0]))
    bot.reply_to(message, f"✅ @{t[1]} войска={a:,}")

@bot.message_handler(commands=['setmorale'])
@admin_only
def cmd_setmorale(message):
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "/setmorale @user процент")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    try: val = max(1, min(100, int(args[2])))
    except: return bot.reply_to(message, "Процент - число.")
    db_query("UPDATE users SET morale=? WHERE user_id=?", (val, t[0]))
    bot.reply_to(message, f"✅ @{t[1]} мораль={val}%")

@bot.message_handler(commands=['settech'])
@admin_only
def cmd_settech(message):
    args = message.text.split()
    if len(args) != 4: return bot.reply_to(message, "/settech @user тех уровень")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    tech = args[2].lower()
    try: lv = int(args[3])
    except: return bot.reply_to(message, "Уровень - число.")
    td = db_query("SELECT display_name,max_level FROM tech_types WHERE name=?", (tech,), fetchone=True)
    if not td: return bot.reply_to(message, f"Технология '{tech}' не найдена.")
    lv = max(0, min(lv, td[1]))
    e = db_query("SELECT level FROM user_tech WHERE user_id=? AND tech_name=?", (t[0], tech), fetchone=True)
    if e: db_query("UPDATE user_tech SET level=? WHERE user_id=? AND tech_name=?", (lv, t[0], tech))
    else: db_query("INSERT INTO user_tech VALUES (?,?,?)", (t[0], tech, lv))
    bot.reply_to(message, f"✅ @{t[1]} {td[0]} Ур.{lv}")

@bot.message_handler(commands=['banuser'])
@admin_only
def cmd_banuser(message):
    args = message.text.split()
    if len(args) != 2: return bot.reply_to(message, "/banuser @user")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    db_query("UPDATE users SET banned=1 WHERE user_id=?", (t[0],))
    bot.reply_to(message, f"✅ @{t[1]} заблокирован🚫")

@bot.message_handler(commands=['unbanuser'])
@admin_only
def cmd_unbanuser(message):
    args = message.text.split()
    if len(args) != 2: return bot.reply_to(message, "/unbanuser @user")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    db_query("UPDATE users SET banned=0 WHERE user_id=?", (t[0],))
    bot.reply_to(message, f"✅ @{t[1]} разблокирован✅")

@bot.message_handler(commands=['wipeuser'])
@admin_only
def cmd_wipeuser(message):
    args = message.text.split()
    if len(args) != 2: return bot.reply_to(message, "/wipeuser @user")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    tid = t[0]
    db_query("UPDATE users SET balance=1000,level=1,troops=0,ep=0,last_cash=0,last_draft=0,morale=100 WHERE user_id=?", (tid,))
    for tbl in ['user_businesses','user_portfolio','user_military','user_tech','user_extractors','user_resource_buildings']:
        db_query(f"DELETE FROM {tbl} WHERE user_id=?", (tid,))
    bot.reply_to(message, f"✅ @{t[1]} сброшен.")

@bot.message_handler(commands=['playerinfo'])
@admin_only
def cmd_playerinfo(message):
    args = message.text.split()
    if len(args) != 2: return bot.reply_to(message, "/playerinfo @user")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    uid, uname = t
    user = db_query("SELECT balance,level,troops,ep,banned,morale FROM users WHERE user_id=?", (uid,), fetchone=True)
    ext = (db_query("SELECT quantity FROM user_extractors WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    power = calc_power(uid)
    techs = db_query("SELECT tech_name,level FROM user_tech WHERE user_id=? AND level>0", (uid,))
    tstr = ", ".join(f"{n}:{l}" for n,l in techs) if techs else "нет"
    bot.reply_to(message,
        f"📋 *[ADMIN] @{uname}*\n"
        f"ID: `{uid}` | Бан: {'Да' if user[4] else 'Нет'}\n"
        f"💰{user[0]:,} | 📈Ур.{user[1]} | 🪖{user[2]:,}\n"
        f"🎺Мораль:{user[5]}% | ⚔️Мощь:{power:,}\n"
        f"🔬ОЭ:{user[3]} | 🛢️Качек:{ext}\n"
        f"Тех: {tstr}",
        parse_mode="Markdown")

@bot.message_handler(commands=['setprice'])
@admin_only
def cmd_setprice(message):
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "/setprice актив цена")
    asset = args[1].lower()
    try: p = float(args[2])
    except: return bot.reply_to(message, "Цена - число.")
    if not db_query("SELECT name FROM market_assets WHERE name=?", (asset,), fetchone=True):
        return bot.reply_to(message, f"'{asset}' не найден.")
    db_query("UPDATE market_assets SET price=?,last_updated=? WHERE name=?", (p, time.time(), asset))
    bot.reply_to(message, f"✅ {asset} = {p:.2f}💰")

@bot.message_handler(commands=['setbaseprice'])
@admin_only
def cmd_setbaseprice(message):
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "/setbaseprice актив цена")
    asset = args[1].lower()
    try: p = float(args[2])
    except: return bot.reply_to(message, "Цена - число.")
    if not db_query("SELECT name FROM market_assets WHERE name=?", (asset,), fetchone=True):
        return bot.reply_to(message, f"'{asset}' не найден.")
    db_query("UPDATE market_assets SET base_price=? WHERE name=?", (p, asset))
    bot.reply_to(message, f"✅ {asset} базовая = {p:.2f}💰")

@bot.message_handler(commands=['marketevent'])
@admin_only
def cmd_marketevent(message):
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "/marketevent актив %")
    asset = args[1].lower()
    try: pct = float(args[2])
    except: return bot.reply_to(message, "% - число.")
    row = db_query("SELECT display_name,price FROM market_assets WHERE name=?", (asset,), fetchone=True)
    if not row: return bot.reply_to(message, f"'{asset}' не найден.")
    disp, old = row
    new_p = round(max(0.01, old * (1 + pct / 100)), 2)
    db_query("UPDATE market_assets SET price=?,last_updated=? WHERE name=?", (new_p, time.time(), asset))
    arr = "📈" if pct >= 0 else "📉"
    bot.reply_to(message, f"⚡ {arr} *{disp}*: {old:.2f} → *{new_p:.2f}* ({'+' if pct>=0 else ''}{pct:.1f}%)", parse_mode="Markdown")

@bot.message_handler(commands=['marketcrash'])
@admin_only
def cmd_marketcrash(message):
    assets = db_query("SELECT name,display_name,price FROM market_assets")
    text = "🔴 *ОБВАЛ РЫНКА!*\n\n"
    for name, disp, price in assets:
        drop = random.uniform(0.20, 0.50)
        new = round(price * (1 - drop), 2)
        db_query("UPDATE market_assets SET price=?,last_updated=? WHERE name=?", (new, time.time(), name))
        text += f"📉 {disp}: {price:.2f} → *{new:.2f}* (-{drop*100:.1f}%)\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['marketboom'])
@admin_only
def cmd_marketboom(message):
    assets = db_query("SELECT name,display_name,price FROM market_assets")
    text = "🟢 *БУМ НА РЫНКЕ!*\n\n"
    for name, disp, price in assets:
        rise = random.uniform(0.20, 0.50)
        new = round(price * (1 + rise), 2)
        db_query("UPDATE market_assets SET price=?,last_updated=? WHERE name=?", (new, time.time(), name))
        text += f"📈 {disp}: {price:.2f} → *{new:.2f}* (+{rise*100:.1f}%)\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['resetmarket'])
@admin_only
def cmd_resetmarket(message):
    db_query("UPDATE market_assets SET price=base_price, last_updated=?", (time.time(),))
    bot.reply_to(message, "✅ Все цены сброшены к базовым.")

@bot.message_handler(commands=['broadcast'])
@admin_only
def cmd_broadcast(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return bot.reply_to(message, "/broadcast текст")
    text = f"📢 *Объявление:*\n\n{args[1]}"
    for gid in ALLOWED_GROUP_IDS:
        try: bot.send_message(gid, text, parse_mode="Markdown")
        except Exception as e: print(f"Broadcast err {gid}: {e}")
    bot.reply_to(message, "✅ Отправлено.")

@bot.message_handler(commands=['announcement'])
@admin_only
def cmd_announcement(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return bot.reply_to(message, "/announcement текст")
    bot.send_message(message.chat.id, f"🌍 *СОБЫТИЕ В АУРЕЛИИ:*\n\n{args[1]}", parse_mode="Markdown")
    bot.reply_to(message, "✅ Готово.")

# ==============================================================
# ПРЕСЕТЫ СТРАН - НАЧАЛЬНЫЕ УСЛОВИЯ
# ==============================================================
# Структура пресета:
# balance, level, troops, ep, morale,
# techs {tech_name: level},
# assets {asset_name: qty},
# buildings {resource: qty},
# extractors (int - нефтекачки),
# military {unit_name: qty},
# businesses {biz_name: qty}

COUNTRY_PRESETS = {

    # ========== ЭНИВАРРА ==========

    'турбания': {
        'name': 'Турбанская Республика',
        'balance': 850000, 'level': 8, 'troops': 30000, 'ep': 1200, 'morale': 72,
        'techs': {
            'finance': 3, 'logistics': 4, 'metallurgy': 4, 'engineering': 4,
            'military_sc': 4, 'industry': 4, 'energy': 3, 'trading': 2,
            'espionage': 2, 'naval': 2, 'morale_tech': 2, 'nuclear': 2,
        },
        'assets': {'steel': 800, 'oil': 400, 'coal': 600, 'gold': 50, 'aur': 15, 'food': 120},
        'buildings': {'steel': 4, 'coal': 3, 'gold': 1},
        'extractors': 5,
        'military': {
            'rifle': 3000, 'machinegun': 1200, 'mortar': 600,
            'apc': 400, 'tank': 800, 'artillery': 300,
            'aa_gun': 200, 'mlrs': 80, 'missile': 20,
            'plane': 150, 'helicopter': 100,
            'corvette': 20, 'ship': 10,
        },
        'businesses': {'factory': 8, 'mine': 12, 'lab': 3, 'farm': 3},
    },

    'дервесния': {
        'name': 'Дервесния',
        'balance': 1100000, 'level': 10, 'troops': 35000, 'ep': 2500, 'morale': 80,
        'techs': {
            'finance': 4, 'logistics': 5, 'metallurgy': 5, 'engineering': 5,
            'military_sc': 5, 'industry': 5, 'energy': 4, 'trading': 3,
            'espionage': 3, 'naval': 3, 'morale_tech': 3, 'nuclear': 2,
        },
        'assets': {'steel': 1200, 'oil': 500, 'coal': 700, 'gold': 80, 'aur': 20, 'food': 150},
        'buildings': {'steel': 5, 'coal': 4, 'gold': 2, 'aur': 1},
        'extractors': 7,
        'military': {
            'rifle': 4000, 'machinegun': 1800, 'mortar': 900,
            'apc': 700, 'tank': 1200, 'artillery': 500,
            'aa_gun': 350, 'mlrs': 150,
            'plane': 250, 'bomber': 60, 'helicopter': 150,
            'corvette': 30, 'ship': 15, 'submarine': 8,
        },
        'businesses': {'factory': 10, 'mine': 14, 'lab': 5, 'nps': 1},
    },

    'вордсфалия': {
        'name': 'Вордсфалия',
        'balance': 950000, 'level': 9, 'troops': 28000, 'ep': 1800, 'morale': 78,
        'techs': {
            'finance': 5, 'logistics': 3, 'metallurgy': 3, 'engineering': 3,
            'military_sc': 3, 'industry': 4, 'energy': 3, 'trading': 5,
            'espionage': 2, 'naval': 4, 'morale_tech': 2, 'nuclear': 1,
        },
        'assets': {'steel': 600, 'oil': 350, 'coal': 400, 'gold': 200, 'aur': 20, 'food': 200},
        'buildings': {'gold': 3, 'steel': 2, 'coal': 2},
        'extractors': 4,
        'military': {
            'rifle': 2000, 'machinegun': 800, 'mortar': 400,
            'apc': 300, 'tank': 500, 'artillery': 200,
            'aa_gun': 150, 'plane': 180, 'helicopter': 80,
            'corvette': 40, 'ship': 25, 'submarine': 12, 'cruiser': 4,
        },
        'businesses': {'factory': 7, 'mine': 12, 'lab': 3, 'farm': 4},
    },

    'курбания': {
        'name': 'Курбания',
        'balance': 180000, 'level': 4, 'troops': 12000, 'ep': 300, 'morale': 60,
        'techs': {
            'finance': 1, 'logistics': 2, 'metallurgy': 1,
            'engineering': 1, 'military_sc': 2, 'industry': 1,
            'energy': 1, 'trading': 1, 'morale_tech': 1,
        },
        'assets': {'steel': 150, 'oil': 60, 'coal': 100, 'gold': 20, 'food': 80},
        'buildings': {'steel': 1, 'coal': 1},
        'extractors': 1,
        'military': {
            'rifle': 800, 'machinegun': 300, 'mortar': 120,
            'apc': 80, 'tank': 100, 'artillery': 40,
            'plane': 30, 'helicopter': 20,
        },
        'businesses': {'factory': 3, 'farm': 3, 'mine': 7},
    },

    'кефирстан': {
        'name': 'Кефирстан',
        'balance': 320000, 'level': 5, 'troops': 8000, 'ep': 600, 'morale': 82,
        'techs': {
            'finance': 3, 'logistics': 2, 'metallurgy': 1,
            'engineering': 2, 'military_sc': 1, 'industry': 2,
            'energy': 1, 'trading': 3, 'morale_tech': 2,
        },
        'assets': {'steel': 100, 'oil': 40, 'coal': 80, 'gold': 150, 'food': 400},
        'buildings': {'gold': 2, 'steel': 1},
        'extractors': 1,
        'military': {
            'rifle': 400, 'machinegun': 150, 'apc': 50,
            'tank': 80, 'plane': 20, 'helicopter': 15,
        },
        'businesses': {'farm': 8, 'factory': 3, 'mine': 3},
    },

    'веранд': {
        'name': 'Веранд',
        'balance': 420000, 'level': 6, 'troops': 15000, 'ep': 900, 'morale': 85,
        'techs': {
            'finance': 4, 'logistics': 3, 'metallurgy': 2, 'engineering': 2,
            'military_sc': 2, 'industry': 3, 'energy': 2,
            'trading': 4, 'espionage': 2, 'morale_tech': 3,
        },
        'assets': {'steel': 200, 'oil': 150, 'coal': 120, 'gold': 100, 'aur': 10, 'food': 200},
        'buildings': {'gold': 1, 'steel': 2},
        'extractors': 3,
        'military': {
            'rifle': 1000, 'machinegun': 400, 'mortar': 200,
            'apc': 150, 'tank': 250, 'artillery': 100,
            'aa_gun': 80, 'plane': 60, 'helicopter': 40,
            'corvette': 15, 'ship': 8,
        },
        'businesses': {'factory': 5, 'farm': 4, 'lab': 2, 'mine': 4},
    },

    'далестан': {
        'name': 'Далестан',
        'balance': 280000, 'level': 5, 'troops': 14000, 'ep': 500, 'morale': 70,
        'techs': {
            'finance': 2, 'logistics': 2, 'metallurgy': 2,
            'military_sc': 2, 'industry': 2, 'trading': 2,
        },
        'assets': {'steel': 180, 'oil': 200, 'coal': 100, 'gold': 40, 'food': 150},
        'buildings': {'steel': 1, 'coal': 1},
        'extractors': 3,
        'military': {
            'rifle': 1200, 'machinegun': 400, 'mortar': 150,
            'apc': 100, 'tank': 180, 'artillery': 60, 'plane': 40,
        },
        'businesses': {'factory': 4, 'farm': 3, 'mine': 8},
    },

    'дурдания': {
        'name': 'Дурдания',
        'balance': 200000, 'level': 4, 'troops': 12000, 'ep': 350, 'morale': 68,
        'techs': {
            'finance': 2, 'logistics': 1, 'metallurgy': 1,
            'military_sc': 2, 'industry': 1, 'trading': 1,
        },
        'assets': {'steel': 120, 'oil': 100, 'coal': 80, 'food': 120},
        'buildings': {'steel': 1, 'coal': 1},
        'extractors': 2,
        'military': {
            'rifle': 800, 'machinegun': 300, 'mortar': 100,
            'apc': 80, 'tank': 120, 'artillery': 40,
        },
        'businesses': {'factory': 3, 'farm': 3, 'mine': 8},
    },

    'холдосия': {
        'name': 'Холдосия',
        'balance': 600000, 'level': 7, 'troops': 22000, 'ep': 1000, 'morale': 75,
        'techs': {
            'finance': 3, 'logistics': 3, 'metallurgy': 3, 'engineering': 3,
            'military_sc': 3, 'industry': 3, 'energy': 2,
            'trading': 2, 'espionage': 3, 'naval': 2,
        },
        'assets': {'steel': 400, 'oil': 250, 'coal': 300, 'gold': 60, 'aur': 8, 'food': 100},
        'buildings': {'steel': 3, 'coal': 2, 'gold': 1},
        'extractors': 3,
        'military': {
            'rifle': 2000, 'machinegun': 700, 'mortar': 350,
            'apc': 250, 'tank': 450, 'artillery': 180,
            'aa_gun': 120, 'mlrs': 40,
            'plane': 100, 'bomber': 20, 'helicopter': 60,
            'corvette': 25, 'ship': 12,
        },
        'businesses': {'factory': 7, 'mine': 10, 'lab': 3},
    },

    'бордусния': {
        'name': 'Бордусния',
        'balance': 120000, 'level': 3, 'troops': 10000, 'ep': 200, 'morale': 55,
        'techs': {
            'finance': 1, 'logistics': 1, 'military_sc': 1, 'industry': 1,
        },
        'assets': {'steel': 80, 'oil': 30, 'coal': 60, 'food': 100},
        'buildings': {'coal': 1},
        'extractors': 1,
        'military': {
            'rifle': 600, 'machinegun': 200, 'mortar': 80,
            'apc': 40, 'tank': 60,
        },
        'businesses': {'factory': 2, 'farm': 3, 'mine': 7},
    },

    # ========== САРГАТИЯ ==========

    'сор': {
        'name': 'Северные Объединённые Республики',
        'balance': 550000, 'level': 6, 'troops': 18000, 'ep': 800, 'morale': 73,
        'techs': {
            'finance': 3, 'logistics': 3, 'metallurgy': 2, 'military_sc': 2,
            'industry': 3, 'trading': 3, 'naval': 4, 'morale_tech': 2,
        },
        'assets': {'steel': 300, 'oil': 200, 'coal': 250, 'gold': 80, 'food': 200},
        'buildings': {'gold': 1, 'coal': 2, 'steel': 1},
        'extractors': 3,
        'military': {
            'rifle': 1500, 'machinegun': 600, 'mortar': 250,
            'apc': 200, 'tank': 350, 'artillery': 120,
            'aa_gun': 80, 'plane': 80, 'helicopter': 50,
            'corvette': 35, 'ship': 20, 'submarine': 10, 'cruiser': 3,
        },
        'businesses': {'factory': 5, 'farm': 4, 'mine': 9},
    },

    'нолания': {
        'name': 'Нолания',
        'balance': 400000, 'level': 5, 'troops': 16000, 'ep': 600, 'morale': 70,
        'techs': {
            'finance': 2, 'logistics': 2, 'metallurgy': 2,
            'military_sc': 2, 'industry': 2, 'trading': 2, 'naval': 2,
        },
        'assets': {'steel': 200, 'oil': 150, 'coal': 180, 'gold': 60, 'food': 180},
        'buildings': {'steel': 1, 'coal': 1, 'gold': 1},
        'extractors': 2,
        'military': {
            'rifle': 1200, 'machinegun': 450, 'mortar': 200,
            'apc': 150, 'tank': 280, 'artillery': 100,
            'plane': 60, 'corvette': 20, 'ship': 10,
        },
        'businesses': {'factory': 4, 'farm': 4, 'mine': 9},
    },

    'саргатийская_федерация': {
        'name': 'Саргатийская Федерация',
        'balance': 250000, 'level': 4, 'troops': 13000, 'ep': 400, 'morale': 65,
        'techs': {
            'finance': 2, 'logistics': 1, 'military_sc': 1,
            'industry': 2, 'trading': 2,
        },
        'assets': {'steel': 150, 'oil': 80, 'coal': 120, 'gold': 40, 'food': 200},
        'buildings': {'coal': 1, 'steel': 1},
        'extractors': 2,
        'military': {
            'rifle': 900, 'machinegun': 300, 'mortar': 120,
            'apc': 80, 'tank': 150, 'artillery': 50,
        },
        'businesses': {'factory': 2, 'farm': 4, 'mine': 9},
    },

    'медия': {
        'name': 'Медия',
        'balance': 180000, 'level': 3, 'troops': 8000, 'ep': 250, 'morale': 65,
        'techs': {
            'finance': 1, 'logistics': 1, 'military_sc': 1, 'trading': 2,
        },
        'assets': {'steel': 80, 'oil': 50, 'coal': 60, 'food': 150},
        'buildings': {'steel': 1},
        'extractors': 1,
        'military': {
            'rifle': 500, 'machinegun': 150, 'mortar': 60,
            'apc': 40, 'tank': 70,
        },
        'businesses': {'farm': 4, 'mine': 5, 'factory': 2},
    },

    # ========== ФЕРИДИЯ ==========

    'нидросия': {
        'name': 'Нидросия',
        'balance': 500000, 'level': 6, 'troops': 17000, 'ep': 900, 'morale': 78,
        'techs': {
            'finance': 3, 'logistics': 2, 'metallurgy': 2,
            'military_sc': 2, 'industry': 3, 'trading': 3, 'naval': 4,
        },
        'assets': {'steel': 250, 'oil': 180, 'coal': 150, 'gold': 100, 'aur': 20, 'food': 180},
        'buildings': {'gold': 2, 'aur': 1, 'steel': 1},
        'extractors': 3,
        'military': {
            'rifle': 1200, 'machinegun': 500, 'mortar': 200,
            'apc': 150, 'tank': 300, 'artillery': 100,
            'plane': 80, 'helicopter': 50,
            'corvette': 30, 'ship': 18, 'submarine': 6, 'cruiser': 2,
        },
        'businesses': {'factory': 5, 'farm': 3, 'mine': 10},
    },

    'аэлион': {
        'name': 'Аэлион',
        'balance': 350000, 'level': 5, 'troops': 13000, 'ep': 600, 'morale': 75,
        'techs': {
            'finance': 2, 'logistics': 2, 'military_sc': 2,
            'industry': 2, 'trading': 3, 'naval': 3,
        },
        'assets': {'steel': 150, 'oil': 100, 'coal': 80, 'gold': 80, 'aur': 8, 'food': 150},
        'buildings': {'gold': 1, 'aur': 1},
        'extractors': 2,
        'military': {
            'rifle': 800, 'machinegun': 300, 'apc': 100,
            'tank': 180, 'plane': 50,
            'corvette': 20, 'ship': 10,
        },
        'businesses': {'farm': 3, 'factory': 4, 'mine': 7},
    },

    'хумесния': {
        'name': 'Хумесния',
        'balance': 220000, 'level': 4, 'troops': 11000, 'ep': 400, 'morale': 68,
        'techs': {
            'finance': 2, 'logistics': 1, 'military_sc': 1,
            'industry': 2, 'trading': 1,
        },
        'assets': {'steel': 120, 'oil': 60, 'coal': 80, 'food': 120},
        'buildings': {'steel': 1, 'coal': 1},
        'extractors': 1,
        'military': {
            'rifle': 700, 'machinegun': 250, 'mortar': 100,
            'apc': 60, 'tank': 100,
        },
        'businesses': {'farm': 3, 'factory': 3, 'mine': 7},
    },

    'гордатштам': {
        'name': 'Гордатштам',
        'balance': 300000, 'level': 5, 'troops': 14000, 'ep': 500, 'morale': 72,
        'techs': {
            'finance': 2, 'logistics': 2, 'metallurgy': 2,
            'military_sc': 2, 'industry': 2,
        },
        'assets': {'steel': 200, 'oil': 120, 'coal': 150, 'gold': 50, 'food': 140},
        'buildings': {'steel': 2, 'coal': 1},
        'extractors': 2,
        'military': {
            'rifle': 1000, 'machinegun': 400, 'mortar': 160,
            'apc': 120, 'tank': 200, 'artillery': 70,
        },
        'businesses': {'factory': 4, 'farm': 3, 'mine': 8},
    },

    # ========== МАЛЫЕ ==========

    'деши': {
        'name': 'Деши',
        'balance': 160000, 'level': 4, 'troops': 12000, 'ep': 300, 'morale': 65,
        'techs': {
            'finance': 1, 'logistics': 2, 'military_sc': 2,
            'industry': 1, 'energy': 1,
        },
        'assets': {'steel': 100, 'oil': 60, 'coal': 60, 'gold': 30, 'food': 100},
        'buildings': {'steel': 1, 'gold': 1},
        'extractors': 1,
        'military': {
            'rifle': 800, 'machinegun': 300, 'mortar': 120,
            'apc': 80, 'tank': 150, 'artillery': 50, 'aa_gun': 40, 'plane': 30,
        },
        'businesses': {'mine': 7, 'farm': 3, 'factory': 3},
    },

    'корментия': {
        'name': 'Корментия',
        'balance': 450000, 'level': 6, 'troops': 14000, 'ep': 700, 'morale': 80,
        'techs': {
            'finance': 3, 'trading': 4, 'naval': 3, 'logistics': 2,
            'military_sc': 2, 'industry': 2,
        },
        'assets': {'steel': 200, 'oil': 150, 'coal': 100, 'gold': 200, 'aur': 10, 'food': 200},
        'buildings': {'gold': 2, 'steel': 1},
        'extractors': 2,
        'military': {
            'rifle': 900, 'machinegun': 350, 'apc': 120,
            'tank': 200, 'plane': 70,
            'corvette': 25, 'ship': 12, 'submarine': 5,
        },
        'businesses': {'farm': 3, 'factory': 4, 'mine': 7, 'bank_biz': 1},
    },

    'йогуртстан': {
        'name': 'Йогуртстан',
        'balance': 100000, 'level': 3, 'troops': 6000, 'ep': 150, 'morale': 58,
        'techs': {
            'finance': 1, 'military_sc': 1, 'logistics': 1,
        },
        'assets': {'steel': 50, 'oil': 20, 'food': 150},
        'buildings': {},
        'extractors': 0,
        'military': {
            'rifle': 400, 'machinegun': 120, 'apc': 30, 'tank': 50,
        },
        'businesses': {'farm': 3, 'mine': 5},
    },

    'хеки': {
        'name': 'Хеки',
        'balance': 200000, 'level': 4, 'troops': 10000, 'ep': 350, 'morale': 72,
        'techs': {
            'finance': 2, 'military_sc': 2, 'logistics': 1, 'trading': 2,
        },
        'assets': {'steel': 120, 'oil': 70, 'coal': 60, 'gold': 40, 'food': 100},
        'buildings': {'steel': 1, 'gold': 1},
        'extractors': 1,
        'military': {
            'rifle': 600, 'machinegun': 220, 'mortar': 80,
            'apc': 60, 'tank': 110, 'artillery': 40,
        },
        'businesses': {'factory': 3, 'farm': 3, 'mine': 6},
    },
}


COUNTRY_ALIASES = {
    'сор': 'сор', 'cor': 'сор', 'north': 'сор',
    'турбания': 'турбания', 'turbania': 'турбания',
    'дервесния': 'дервесния', 'dervesnia': 'дервесния',
    'вордсфалия': 'вордсфалия', 'wordsfaliya': 'вордсфалия',
    'курбания': 'курбания', 'kurbania': 'курбания',
    'кефирстан': 'кефирстан', 'kefirstan': 'кефирстан',
    'веранд': 'веранд', 'verand': 'веранд',
    'далестан': 'далестан', 'dalestan': 'далестан',
    'дурдания': 'дурдания', 'durdania': 'дурдания',
    'холдосия': 'холдосия', 'holdosia': 'холдосия',
    'бордусния': 'бордусния', 'bordusnia': 'бордусния',
    'нолания': 'нолания', 'nolaniya': 'нолания',
    'нидросия': 'нидросия', 'nidrosia': 'нидросия',
    'аэлион': 'аэлион', 'aelion': 'аэлион',
    'хумесния': 'хумесния', 'humesnia': 'хумесния',
    'гордатштам': 'гордатштам', 'gordatshtam': 'гордатштам',
    'деши': 'деши', 'deshi': 'деши',
    'корментия': 'корментия', 'kormentia': 'корментия',
    'йогуртстан': 'йогуртстан', 'jogurtstan': 'йогуртстан',
    'хеки': 'хеки', 'heki': 'хеки',
    'медия': 'медия', 'media': 'медия',
    'саргатийская_федерация': 'саргатийская_федерация',
    'сарфед': 'саргатийская_федерация',
    'аэлион': 'аэлион',
}


@bot.message_handler(commands=['initcountry'])
@admin_only
def cmd_initcountry(message):
    """Выдать игроку начальные ресурсы по пресету страны.
    Синтаксис: /initcountry @user страна [reset]
    Флаг reset - полностью стереть прогресс перед применением пресета."""
    args = message.text.split()
    if len(args) < 3:
        lines = ["⚙️ *Команда:* `/initcountry @user страна [reset]`",
                 "",
                 "Доступные страны:"]
        for key, p in sorted(COUNTRY_PRESETS.items()):
            lines.append(f"  `{key}` - {p['name']}")
        return bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

    t = get_user(args[1])
    if not t:
        return bot.reply_to(message, f"Пользователь {args[1]} не найден.")

    uid, uname = t
    country_raw = args[2].lower()
    do_reset = len(args) > 3 and args[3].lower() == 'reset'

    # Поиск пресета
    country_key = COUNTRY_ALIASES.get(country_raw, country_raw)
    preset = COUNTRY_PRESETS.get(country_key)
    if not preset:
        return bot.reply_to(message, f"❌ Страна `{country_raw}` не найдена.\nДоступные: {', '.join(COUNTRY_PRESETS.keys())}", parse_mode="Markdown")

    # Убедимся что пользователь есть в БД
    if not db_query("SELECT user_id FROM users WHERE user_id=?", (uid,), fetchone=True):
        db_query("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (uid, uname))

    # Полный сброс если запрошен
    if do_reset:
        db_query("UPDATE users SET balance=0, level=1, troops=0, ep=0, morale=100 WHERE user_id=?", (uid,))
        db_query("DELETE FROM user_tech WHERE user_id=?", (uid,))
        db_query("DELETE FROM user_portfolio WHERE user_id=?", (uid,))
        db_query("DELETE FROM user_businesses WHERE user_id=?", (uid,))
        db_query("DELETE FROM user_military WHERE user_id=?", (uid,))
        db_query("DELETE FROM user_resource_buildings WHERE user_id=?", (uid,))
        db_query("DELETE FROM user_extractors WHERE user_id=?", (uid,))

    # Основные параметры
    db_query("UPDATE users SET balance=balance+?, level=?, troops=troops+?, ep=ep+?, morale=? WHERE user_id=?",
             (preset['balance'], preset['level'], preset['troops'],
              preset['ep'], preset['morale'], uid))

    # Технологии
    for tech, lv in preset.get('techs', {}).items():
        existing = db_query("SELECT level FROM user_tech WHERE user_id=? AND tech_name=?", (uid, tech), fetchone=True)
        if existing:
            db_query("UPDATE user_tech SET level=MAX(level,?) WHERE user_id=? AND tech_name=?", (lv, uid, tech))
        else:
            db_query("INSERT OR IGNORE INTO user_tech (user_id, tech_name, level) VALUES (?,?,?)", (uid, tech, lv))

    # Ресурсы (активы биржи)
    for asset, qty in preset.get('assets', {}).items():
        add_asset(uid, asset, qty)

    # Добывающие здания (resource_buildings)
    for res, qty in preset.get('buildings', {}).items():
        existing = db_query("SELECT quantity FROM user_resource_buildings WHERE user_id=? AND resource=?", (uid, res), fetchone=True)
        if existing:
            db_query("UPDATE user_resource_buildings SET quantity=quantity+? WHERE user_id=? AND resource=?", (qty, uid, res))
        else:
            db_query("INSERT INTO user_resource_buildings (user_id, resource, quantity, last_extract) VALUES (?,?,?,0)", (uid, res, qty))

    # Нефтекачки
    ext_qty = preset.get('extractors', 0)
    if ext_qty:
        existing = db_query("SELECT quantity FROM user_extractors WHERE user_id=?", (uid,), fetchone=True)
        if existing:
            db_query("UPDATE user_extractors SET quantity=quantity+? WHERE user_id=?", (ext_qty, uid))
        else:
            db_query("INSERT INTO user_extractors (user_id, quantity, last_extract) VALUES (?,?,0)", (uid, ext_qty))

    # Военные юниты
    for unit, qty in preset.get('military', {}).items():
        existing = db_query("SELECT quantity FROM user_military WHERE user_id=? AND unit_name=?", (uid, unit), fetchone=True)
        if existing:
            db_query("UPDATE user_military SET quantity=quantity+? WHERE user_id=? AND unit_name=?", (qty, uid, unit))
        else:
            db_query("INSERT INTO user_military (user_id, unit_name, quantity) VALUES (?,?,?)", (uid, unit, qty))

    # Бизнесы
    for biz, qty in preset.get('businesses', {}).items():
        existing = db_query("SELECT quantity FROM user_businesses WHERE user_id=? AND business_name=?", (uid, biz), fetchone=True)
        if existing:
            db_query("UPDATE user_businesses SET quantity=quantity+? WHERE user_id=? AND business_name=?", (qty, uid, biz))
        else:
            db_query("INSERT INTO user_businesses (user_id, business_name, quantity) VALUES (?,?,?)", (uid, biz, qty))

    reset_note = " (с полным сбросом)" if do_reset else ""
    lines_out = [
        f"✅ *@{uname}* инициализирован как *{preset['name']}*{reset_note}",
        f"💰 +{preset['balance']:,}  |  📈 Ур.{preset['level']}  |  🪖 +{preset['troops']:,}",
        f"🔬 +{preset['ep']} ОЭ  |  🎺 Мораль: {preset['morale']}%",
        f"🔧 Техи: {len(preset['techs'])} штук",
        f"🏭 Бизнесов: {sum(preset['businesses'].values())} шт.",
        f"⚔️ Юнитов типов: {len(preset['military'])}",
    ]
    bot.reply_to(message, "\n".join(lines_out), parse_mode="Markdown")


@bot.message_handler(commands=['listcountries'])
@admin_only
def cmd_listcountries(message):
    lines_out = ["🌍 *Пресеты стран Аурелии:*", ""]
    for key, p in sorted(COUNTRY_PRESETS.items()):
        lines_out.append(f"*{p['name']}* (`{key}`)")
        lines_out.append(f"  💰{p['balance']:,} | Ур.{p['level']} | 🪖{p['troops']:,} | 🔬{p['ep']} | 🎺{p['morale']}%")
    bot.reply_to(message, "\n".join(lines_out), parse_mode="Markdown")


# --- Переименование страны (сам игрок) ---
@bot.message_handler(commands=['rename'])
@group_only
def cmd_rename(message):
    uid = message.from_user.id
    ensure_user(uid, message.from_user.username or 'unknown')
    if is_banned(uid): return bot.reply_to(message, "Вы заблокированы.")
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        cur = (db_query("SELECT country_name FROM users WHERE user_id=?", (uid,), fetchone=True) or [None])[0]
        cur_str = f"Текущее: *{cur}*" if cur else "Название не задано."
        return bot.reply_to(message, f"✏️ {cur_str}\n\nИспользование: `/rename Название Страны`", parse_mode="Markdown")
    new_name = args[1].strip()
    if len(new_name) > 40:
        return bot.reply_to(message, "❌ Название слишком длинное (макс. 40 символов).")
    db_query("UPDATE users SET country_name=? WHERE user_id=?", (new_name, uid))
    bot.reply_to(message, f"✅ Страна переименована: *{new_name}*", parse_mode="Markdown")


# --- Установить название страны другому игроку (только админ) ---
@bot.message_handler(commands=['setcountry'])
@admin_only
def cmd_setcountry(message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        return bot.reply_to(message, "Использование: `/setcountry @user Название Страны`", parse_mode="Markdown")
    t = get_user(args[1])
    if not t: return bot.reply_to(message, f"Пользователь {args[1]} не найден.")
    uid, uname = t
    new_name = args[2].strip()
    if len(new_name) > 40:
        return bot.reply_to(message, "❌ Название слишком длинное (макс. 40 символов).")
    db_query("UPDATE users SET country_name=? WHERE user_id=?", (new_name, uid))
    bot.reply_to(message, f"✅ @{uname} - страна: *{new_name}*", parse_mode="Markdown")


# --- Базовый стартовый пакет для непрописанных стран ---
@bot.message_handler(commands=['initbasic'])
@admin_only
def cmd_initbasic(message):
    """Базовый стартовый пакет для стран которых нет в пресетах.
    Синтаксис: /initbasic @user [уровень: micro|small|medium|large]
    micro  - деревня/остров, ур.2
    small  - малое государство, ур.3
    medium - среднее государство, ур.4 (по умолчанию)
    large  - крупное но непрописанное, ур.5"""
    args = message.text.split()
    if len(args) < 2:
        return bot.reply_to(message,
            "Использование: `/initbasic @user [micro|small|medium|large]`\n\n"
            "micro - деревня/остров (ур.2)\n"
            "small - малое государство (ур.3)\n"
            "medium - среднее государство (ур.4, по умолчанию)\n"
            "large - крупное непрописанное (ур.5)", parse_mode="Markdown")

    t = get_user(args[1])
    if not t: return bot.reply_to(message, f"Пользователь {args[1]} не найден.")
    uid, uname = t

    tier = args[2].lower() if len(args) > 2 else 'medium'

    tiers = {
        'micro':  {'balance': 50000,  'level': 2, 'troops': 8000,  'ep': 80,  'morale': 65,
                   'assets': {'steel': 30, 'oil': 10, 'food': 60},
                   'military': {'rifle': 200, 'machinegun': 50},
                   'businesses': {'farm': 1}},
        'small':  {'balance': 90000,  'level': 3, 'troops': 18000, 'ep': 150, 'morale': 65,
                   'assets': {'steel': 60, 'oil': 25, 'coal': 40, 'food': 80},
                   'military': {'rifle': 400, 'machinegun': 120, 'apc': 20, 'tank': 30},
                   'businesses': {'farm': 1, 'factory': 1}},
        'medium': {'balance': 160000, 'level': 4, 'troops': 35000, 'ep': 280, 'morale': 67,
                   'assets': {'steel': 100, 'oil': 50, 'coal': 60, 'gold': 20, 'food': 100},
                   'military': {'rifle': 700, 'machinegun': 250, 'mortar': 80,
                                'apc': 50, 'tank': 90, 'artillery': 30},
                   'businesses': {'farm': 2, 'factory': 1, 'mine': 1}},
        'large':  {'balance': 270000, 'level': 5, 'troops': 60000, 'ep': 450, 'morale': 70,
                   'assets': {'steel': 180, 'oil': 90, 'coal': 100, 'gold': 40, 'food': 130},
                   'military': {'rifle': 1000, 'machinegun': 380, 'mortar': 140,
                                'apc': 90, 'tank': 160, 'artillery': 55, 'plane': 25},
                   'businesses': {'farm': 2, 'factory': 2, 'mine': 1},
                   'extractors': 1},
    }

    if tier not in tiers:
        return bot.reply_to(message, f"❌ Уровень `{tier}` не найден. Используй: micro, small, medium, large", parse_mode="Markdown")

    p = tiers[tier]

    if not db_query("SELECT user_id FROM users WHERE user_id=?", (uid,), fetchone=True):
        db_query("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (uid, uname))

    db_query("UPDATE users SET balance=balance+?, level=?, troops=troops+?, ep=ep+?, morale=? WHERE user_id=?",
             (p['balance'], p['level'], p['troops'], p['ep'], p['morale'], uid))

    for asset, qty in p.get('assets', {}).items():
        add_asset(uid, asset, qty)

    for unit, qty in p.get('military', {}).items():
        existing = db_query("SELECT quantity FROM user_military WHERE user_id=? AND unit_name=?", (uid, unit), fetchone=True)
        if existing:
            db_query("UPDATE user_military SET quantity=quantity+? WHERE user_id=? AND unit_name=?", (qty, uid, unit))
        else:
            db_query("INSERT INTO user_military (user_id, unit_name, quantity) VALUES (?,?,?)", (uid, unit, qty))

    for biz, qty in p.get('businesses', {}).items():
        existing = db_query("SELECT quantity FROM user_businesses WHERE user_id=? AND business_name=?", (uid, biz), fetchone=True)
        if existing:
            db_query("UPDATE user_businesses SET quantity=quantity+? WHERE user_id=? AND business_name=?", (qty, uid, biz))
        else:
            db_query("INSERT INTO user_businesses (user_id, business_name, quantity) VALUES (?,?,?)", (uid, biz, qty))

    ext_qty = p.get('extractors', 0)
    if ext_qty:
        existing = db_query("SELECT quantity FROM user_extractors WHERE user_id=?", (uid,), fetchone=True)
        if existing:
            db_query("UPDATE user_extractors SET quantity=quantity+? WHERE user_id=?", (ext_qty, uid))
        else:
            db_query("INSERT INTO user_extractors (user_id, quantity, last_extract) VALUES (?,?,0)", (uid, ext_qty))

    tier_names = {'micro': 'Микро-государство', 'small': 'Малое государство',
                  'medium': 'Среднее государство', 'large': 'Крупное государство'}
    bot.reply_to(message,
        f"✅ *@{uname}* - базовый пакет *{tier_names[tier]}*\n"
        f"💰 +{p['balance']:,} | Ур.{p['level']} | 🪖 +{p['troops']:,} | 🔬 +{p['ep']} ОЭ",
        parse_mode="Markdown")


# ==============================================================
# ЗАПУСК
# ==============================================================
print("🌍 Aurelia Bot v5 запускается...")
try:
    set_commands()
    print("✅ Команды зарегистрированы в Telegram")
except Exception as e:
    print(f"⚠️ Не удалось зарегистрировать команды: {e}")

print("🚀 Бот запущен!")
bot.polling(none_stop=True, timeout=30)
