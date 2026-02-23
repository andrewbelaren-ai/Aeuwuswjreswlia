import telebot
import sqlite3
import time
import random
import threading
import math
import functools

TOKEN = '8539716689:AAGMlLbxq7lAlS2t51iZvm_r2UIjCfxJStE'
ADMIN_IDS = [6115517123, 2046462689, 7787565361]
ALLOWED_GROUP_IDS = [-1003880025896, -1003790960557]

bot = telebot.TeleBot(TOKEN)

# ==============================================================
# КРИТИЧНО: functools.wraps — без него telebot видит все хендлеры
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
        if message.chat.id not in ALLOWED_GROUP_IDS:
            return
        if not is_admin(message.from_user.id):
            return bot.reply_to(message, "No access.")
        func(message)
    return wrapper

# ==============================================================
# --- ИНИЦИАЛИЗАЦИЯ БД ---
# ==============================================================
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

    # Добыча других ресурсов (аналог нефтекачек)
    c.execute('''CREATE TABLE IF NOT EXISTS user_resource_buildings (
        user_id INTEGER,
        resource TEXT,
        quantity INTEGER DEFAULT 0,
        last_extract REAL DEFAULT 0,
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
        user_id INTEGER, event_type TEXT, description TEXT,
        created_at REAL DEFAULT 0
    )''')

    conn.commit()

    # --- Бизнесы (без порта, цены x2) ---
    # oil_per_unit и coal_per_unit - расход топлива каждые 3 часа на ЕДИНИЦУ техники
    businesses = [
        ('farm',      '🌾 Ферма',            4000,   40,  'Надежный базовый доход',                0),
        ('factory',   '🏭 Завод',            10000,  120, 'Производство товаров + ОЭ',             50),
        ('mine',      '⛏️ Шахта',            16000,  220, 'Добыча ресурсов + ОЭ',                 50),
        ('casino',    '🎰 Казино',           30000,  450, 'Большой доход, большие вложения',       20),
        ('bank_biz',  '🏦 Частный банк',     60000,  950, 'Максимальный пассивный доход',          30),
        ('lab',       '🔬 Лаборатория',      45000,  300, 'Исследования: много ОЭ',               100),
        ('nps',       '⚛️ АЭС',             500000, 1200, 'Требует Энергетика Ур.3. Снижает расход топлива армии на 25%. Огромный доход.', 80),
    ]
    c.executemany('INSERT OR IGNORE INTO business_types VALUES (?,?,?,?,?,?)', businesses)
    for name, _, _, _, _, ep in businesses:
        c.execute("UPDATE business_types SET ep_per_12h=? WHERE name=?", (ep, name))

    # --- Активы ---
    assets = [
        ('oil',   '🛢️ Нефть',            100.0, 100.0, '🛢️'),
        ('gold',  '🥇 Золото',           500.0, 500.0, '🥇'),
        ('steel', '⚙️ Сталь',             80.0,  80.0, '⚙️'),
        ('aur',   '💎 Аурит',            300.0, 300.0, '💎'),
        ('food',  '🌽 Продовольствие',    50.0,  50.0, '🌽'),
        ('coal',  '🪨 Уголь',             60.0,  60.0, '🪨'),
    ]
    c.executemany(
        'INSERT OR IGNORE INTO market_assets (name,display_name,price,base_price,emoji) VALUES (?,?,?,?,?)',
        assets)

    # --- Военная техника эпохи 1960-х ---
    # (name, display, steel, money, desc, power, category, oil_per_unit/3h, coal_per_unit/3h)
    # oil_per_unit: нефть на 1 единицу за 3 часа
    # coal_per_unit: уголь на 1 единицу за 3 часа
    military = [
        # Наземные - не тратят топливо (только деньги на содержание)
        ('rifle',      '🔫 Винтовки',         2,    200,    'Базовое вооружение пехоты',       1,   'ground', 0,      0),
        ('machinegun', '🔥 Пулемёты',         5,    500,    'Пулемётная поддержка пехоты',     3,   'ground', 0,      0),
        ('mortar',     '💣 Миномёты',         15,   2000,   'Полевая огневая поддержка',       8,   'ground', 0,      0),
        ('apc',        '🚗 БТР',              25,   4000,   'Бронетранспортёр для пехоты',     20,  'ground', 0,      0),
        ('tank',       '🛡️ Танки',            50,   10000,  'Основная боевая машина',          50,  'ground', 0.002,  0),
        ('artillery',  '💥 Артиллерия',       80,   16000,  'Дальнобойная огневая поддержка',  40,  'ground', 0,      0),
        ('aa_gun',     '🎯 ПВО',              60,   14000,  'Зенитные орудия и ракеты',        30,  'ground', 0,      0),
        ('mlrs',       '🚀 РСЗО',             120,  25000,  'Реактивная система залпового огня', 80, 'ground', 0,      0),
        ('missile',    '☢️ Баллистические ракеты', 200, 50000, 'Стратегические и тактические ракеты', 150, 'ground', 0, 0),
        # Авиация - тратят нефть
        ('plane',      '✈️ Истребители',      120,  30000,  'Реактивные истребители-перехватчики', 80, 'air',   0.003,  0),
        ('bomber',     '💣 Бомбардировщики',  180,  50000,  'Стратегические бомбардировщики',  100, 'air',    0.005,  0),
        ('helicopter', '🚁 Вертолёты',        80,   20000,  'Военные вертолёты поддержки',     50,  'air',    0.002,  0),
        ('bomb',       '💥 Авиабомбы',        20,   3000,   'Боеприпасы для авиации',         5,   'air',    0,      0),
        # Флот - тратит уголь
        ('corvette',   '🚤 Корветы',          80,   15000,  'Легкие боевые корабли',          40,  'navy',   0,      0.003),
        ('ship',       '🚢 Эсминцы',          200,  50000,  'Основа военно-морского флота',   120, 'navy',   0,      0.008),
        ('submarine',  '🛥️ Подлодки',         150,  40000,  'Скрытые морские удары',          100, 'navy',   0,      0.005),
        ('cruiser',    '⛵ Крейсеры',         400,  90000,  'Тяжелые боевые корабли',         250, 'navy',   0,      0.015),
        ('carrier',    '⛴️ Авианосцы',        1000, 300000, 'Господство в океане',            500, 'navy',   0,      0.05),
        ('nuclear_sub','☢️ Атомные подлодки', 2000, 600000, 'Ядерное сдерживание на море',    1000,'navy',   0,      0.02),
    ]
    c.executemany('INSERT OR IGNORE INTO military_types VALUES (?,?,?,?,?,?,?,?,?)', military)
    for row in military:
        c.execute("UPDATE military_types SET power_value=?,category=?,oil_per_unit=?,coal_per_unit=? WHERE name=?",
                  (row[5], row[6], row[7], row[8], row[0]))

    # --- Технологии ---
    techs = [
        ('finance',    '💹 Финансы',          5, 300,  '+10% к доходу /cash за уровень',          '+10%cash'),
        ('logistics',  '🚛 Логистика',        5, 450,  '-10% к содержанию армии за уровень',      '-10%maint'),
        ('metallurgy', '🔩 Металлургия',       5, 600,  '-8% к расходу Стали при крафте',          '-8%steel'),
        ('engineering','⚙️ Инженерия',        5, 600,  '-8% к денежному расходу при крафте',      '-8%money'),
        ('military_sc','🎖️ Военная наука',    5, 750,  '+15% к боевой мощи за уровень',           '+15%power'),
        ('industry',   '🏗️ Индустриализация', 5, 540,  '+20% к генерации ОЭ за уровень',          '+20%EP'),
        ('energy',     '⚡ Энергетика',       5, 660,  '-10% к расходу топлива за уровень',       '-10%fuel'),
        ('trading',    '🤝 Торговля',         3, 450,  '-1% комиссия на бирже за уровень',         '-1%fee'),
        ('espionage',  '🕵️ Разведка',         3, 900,  'Расширенные возможности разведки',        'spy'),
        ('naval',      '⚓ Морское дело',      5, 750,  '+20% к мощи флота за уровень',            '+20%navy'),
        ('morale_tech','🎺 Политработа',      5, 540,  '+5% морали за уровень, -5% дезертирства', '+morale'),
        ('nuclear',    '☢️ Ядерная программа',5, 1200, 'Открывает производство ядерного оружия',  'nuclear'),
    ]
    c.executemany('INSERT OR IGNORE INTO tech_types VALUES (?,?,?,?,?,?)', techs)

    # Обновить цены технологий если они изменились
    for row in techs:
        c.execute("UPDATE tech_types SET ep_cost_per_level=? WHERE name=?", (row[3], row[0]))

    conn.commit()
    conn.close()

init_db()

# Требования технологий для производства юнитов
# формат: unit_name -> [(tech_name, min_level), ...]
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

# Доп. ресурсные требования для ядерного оружия (на 1 единицу)
UNIT_RESOURCE_REQUIREMENTS = {
    'missile':    {'aur': 10, 'oil': 5},
    'nuclear_sub':{'aur': 80},
}

# Конфигурация ресурсных зданий
# resource -> (emoji, display_name, yield_per_building, cooldown_seconds)
RESOURCE_BUILDINGS = {
    'gold':  ('🥇', 'Золотой рудник',       1, 14400),  # 4ч
    'steel': ('⚙️', 'Сталелитейный завод',  2, 10800),  # 3ч
    'coal':  ('🪨', 'Угольная шахта',        3, 7200),   # 2ч
    'aur':   ('💎', 'Аурит-шахта',           1, 21600),  # 6ч
}

# ==============================================================
# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
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

def is_admin(uid): return uid in ADMIN_IDS
def is_banned(uid):
    r = db_query("SELECT banned FROM users WHERE user_id=?", (uid,), fetchone=True)
    return r and r[0] == 1

def get_tech(uid, name):
    r = db_query("SELECT level FROM user_tech WHERE user_id=? AND tech_name=?", (uid,name), fetchone=True)
    return r[0] if r else 0

def get_price_arrow(price, base):
    if price > base * 1.1: return "📈"
    elif price < base * 0.9: return "📉"
    return "➡️"

def calc_power(uid):
    units = db_query('''SELECT um.unit_name, um.quantity, mt.power_value, mt.category
                        FROM user_military um JOIN military_types mt ON um.unit_name=mt.name
                        WHERE um.user_id=? AND um.quantity>0''', (uid,))
    troops = (db_query("SELECT troops FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    morale = (db_query("SELECT morale FROM users WHERE user_id=?", (uid,), fetchone=True) or [100])[0]
    morale_mult = max(0.1, morale / 100)
    power = troops
    naval_bonus = 1 + get_tech(uid, 'naval') * 0.20
    for _, qty, pv, cat in (units or []):
        b = naval_bonus if cat == 'navy' else 1.0
        power += int(qty * pv * b)
    mil_bonus = 1 + get_tech(uid, 'military_sc') * 0.15
    return int(power * mil_bonus * morale_mult)

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
    e = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?",
                 (uid, asset_name), fetchone=True)
    if e:
        db_query("UPDATE user_portfolio SET quantity=quantity+? WHERE user_id=? AND asset_name=?",
                 (amount, uid, asset_name))
    else:
        db_query("INSERT INTO user_portfolio VALUES (?,?,?,?)", (uid, asset_name, amount, 0))

GROUND = {'rifle','machinegun','mortar','apc','tank','artillery','aa_gun','mlrs','missile'}
AIR    = {'plane','bomber','helicopter','bomb'}
NAVY   = {'corvette','ship','submarine','cruiser','carrier','nuclear_sub'}

# ==============================================================
# --- ФОНОВЫЕ ПОТОКИ ---
# ==============================================================
def market_updater():
    while True:
        time.sleep(3600)
        for name, price, base in db_query("SELECT name,price,base_price FROM market_assets"):
            change = random.uniform(-0.20, 0.20)
            new_p = max(base*0.4, min(base*2.5, price*(1+change)))
            db_query("UPDATE market_assets SET price=?,last_updated=? WHERE name=?",
                     (round(new_p,2), time.time(), name))

def passive_income():
    while True:
        time.sleep(600)
        rows = db_query('''SELECT ub.user_id, SUM(ub.quantity*bt.income_per_hour)
                           FROM user_businesses ub
                           JOIN business_types bt ON ub.business_name=bt.name
                           GROUP BY ub.user_id''')
        for uid, total in (rows or []):
            income = int(total * (600/3600))
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
                base_gain = ep_map[uid] * bonus
                # Случайное отклонение ±10%
                gain = int(base_gain * random.uniform(0.90, 1.10))
                if gain > 0:
                    db_query("UPDATE users SET ep=ep+?, last_ep=? WHERE user_id=?", (gain, now, uid))

def army_upkeep():
    """
    Каждый час:
    - Содержание пехоты: каждые 5 солдат = 1 /ч
    - Прогрессивный налог на богатство (с 50к)
    - Дезертирство при нехватке денег на содержание
    - Падение морали при дезертирстве
    Каждые 3 часа:
    - Расход нефти: танки + авиация
    - Расход угля: флот
    """
    fuel_acc = {}   # накопитель для дробного расхода топлива
    tick = 0
    while True:
        time.sleep(3600)
        tick += 1

        users = db_query("SELECT user_id,troops,balance,morale FROM users WHERE banned=0")
        for uid, troops, bal, morale in (users or []):
            morale = morale or 100

            # Содержание пехоты
            logi = get_tech(uid, 'logistics')
            reduction = max(0.1, 1 - logi * 0.10)
            maint = int((troops / 5) * reduction)

            # Прогрессивный налог (начинается с 50к)
            if   bal >= 2_000_000: tax = int(bal * 0.035)
            elif bal >= 1_000_000: tax = int(bal * 0.030)
            elif bal >= 500_000:   tax = int(bal * 0.025)
            elif bal >= 200_000:   tax = int(bal * 0.020)
            elif bal >= 150_000:   tax = int(bal * 0.015)
            elif bal >= 100_000:   tax = int(bal * 0.010)
            elif bal >= 50_000:    tax = int(bal * 0.005)
            else:                  tax = 0

            total_deduct = maint + tax

            if total_deduct == 0:
                continue

            if bal >= total_deduct:
                db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (total_deduct, uid))
            else:
                # Не хватает денег - дезертирство
                unpaid_maint = max(0, maint - bal)
                db_query("UPDATE users SET balance=0 WHERE user_id=?", (uid,))

                if troops > 0 and unpaid_maint > 0:
                    morale_tech = get_tech(uid, 'morale_tech')
                    # Базовое дезертирство 3%/ч, снижается технологией
                    base_rate = max(0.005, 0.03 - morale_tech * 0.005)
                    # Чем ниже мораль, тем больше дезертирство
                    morale_factor = max(1.0, (100 - morale) / 50 + 1)
                    rate = min(0.15, base_rate * morale_factor)
                    lost = max(10, int(troops * rate))
                    lost = min(lost, troops)

                    db_query("UPDATE users SET troops=MAX(0,troops-?) WHERE user_id=?", (lost, uid))
                    # Мораль падает
                    morale_drop = random.randint(3, 8)
                    new_morale = max(10, morale - morale_drop)
                    db_query("UPDATE users SET morale=? WHERE user_id=?", (new_morale, uid))
                    log_event(uid, 'desertion',
                              f"Дезертировало {lost} солдат (нет денег на содержание). Мораль: {new_morale}")

            # Восстановление морали при достатке
            if bal >= total_deduct * 2 and morale < 100:
                recovery = random.randint(1, 3) + get_tech(uid, 'morale_tech')
                new_morale = min(100, morale + recovery)
                db_query("UPDATE users SET morale=? WHERE user_id=?", (new_morale, uid))

        # --- Расход топлива каждые 3 часа ---
        if tick % 3 == 0:
            energy_units = db_query('''SELECT user_id, unit_name, quantity, oil_per_unit, coal_per_unit
                                       FROM user_military um
                                       JOIN military_types mt ON um.unit_name=mt.name
                                       WHERE (mt.oil_per_unit > 0 OR mt.coal_per_unit > 0) AND um.quantity > 0''')

            # Группируем расход по пользователям
            fuel_needs = {}
            for uid, unit_name, qty, oil_pu, coal_pu in (energy_units or []):
                if uid not in fuel_needs:
                    fuel_needs[uid] = {'oil': 0.0, 'coal': 0.0}
                energy_tech = get_tech(uid, 'energy')
                has_aes = db_query("SELECT quantity FROM user_businesses WHERE user_id=? AND business_name='nps'",
                                   (uid,), fetchone=True)
                nps_bonus = 0.25 if (has_aes and has_aes[0] > 0) else 0.0
                fuel_mult = max(0.05, 1 - energy_tech * 0.10 - nps_bonus)
                fuel_needs[uid]['oil']  += oil_pu  * qty * fuel_mult
                fuel_needs[uid]['coal'] += coal_pu * qty * fuel_mult

            for uid, needs in fuel_needs.items():
                if uid not in fuel_acc:
                    fuel_acc[uid] = {'oil': 0.0, 'coal': 0.0}

                for res in ('oil', 'coal'):
                    fuel_acc[uid][res] += needs[res]
                    to_ded = int(fuel_acc[uid][res])
                    if to_ded > 0:
                        fuel_acc[uid][res] -= to_ded
                        row = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?",
                                       (uid, res), fetchone=True)
                        current = row[0] if row else 0
                        actual = min(to_ded, int(current))
                        if actual > 0:
                            db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name=?",
                                     (actual, uid, res))
                        # Если нефти/угля нет и есть авиация/флот, падает мораль
                        if actual < to_ded:
                            morale_row = db_query("SELECT morale FROM users WHERE user_id=?", (uid,), fetchone=True)
                            if morale_row:
                                new_morale = max(20, (morale_row[0] or 100) - random.randint(1, 3))
                                db_query("UPDATE users SET morale=? WHERE user_id=?", (new_morale, uid))

def food_consumption():
    """
    Каждые 6 часов войска потребляют продовольствие.
    Нехватка еды - падение морали и небольшое дезертирство.
    """
    while True:
        time.sleep(21600)
        users = db_query("SELECT user_id, troops, morale FROM users WHERE troops > 0 AND banned=0")
        for uid, troops, morale in (users or []):
            morale = morale or 100
            # 1 еда на 1000 солдат каждые 6 часов
            food_needed = max(1, troops // 1000)
            food_row = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name='food'",
                                (uid,), fetchone=True)
            food_have = int(food_row[0]) if food_row else 0

            if food_have >= food_needed:
                db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name='food'",
                         (food_needed, uid))
                # Мораль немного растет при наличии еды
                if morale < 100:
                    db_query("UPDATE users SET morale=MIN(100,morale+1) WHERE user_id=?", (uid,))
            else:
                # Нет еды - мораль падает, небольшое дезертирство
                if food_have > 0:
                    db_query("DELETE FROM user_portfolio WHERE user_id=? AND asset_name='food'", (uid,))
                morale_drop = random.randint(2, 5)
                new_morale = max(5, morale - morale_drop)
                db_query("UPDATE users SET morale=? WHERE user_id=?", (new_morale, uid))

                if troops > 0:
                    hunger_desertion = max(5, int(troops * 0.01))
                    db_query("UPDATE users SET troops=MAX(0,troops-?) WHERE user_id=?", (hunger_desertion, uid))
                    log_event(uid, 'hunger', f"Нехватка продовольствия! -{hunger_desertion} солдат, мораль: {new_morale}")

for fn in [market_updater, passive_income, ep_gen, army_upkeep, food_consumption]:
    threading.Thread(target=fn, daemon=True).start()

# ==============================================================
# --- ОСНОВНЫЕ КОМАНДЫ ---
# ==============================================================

@bot.message_handler(commands=['start'])
@group_only
def cmd_start(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return bot.reply_to(message, "Вы заблокированы.")
    bot.reply_to(message,
        "🌍 *Добро пожаловать в Аурелию!*\n\n"
        "💰 Стартовый капитал: 1000\n\n"
        "Введите /help для полного списка команд.\n\n"
        "📋 *Быстрый старт:*\n"
        "/profile - ваш профиль\n"
        "/cash - собрать налоги\n"
        "/shop - купить бизнес\n"
        "/draft - призвать армию\n"
        "/market - биржа ресурсов",
        parse_mode="Markdown")

@bot.message_handler(commands=['help'])
@group_only
def cmd_help(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    bot.reply_to(message,
        "📋 *Все команды Аурелии:*\n\n"
        "👤 *Основные:*\n"
        "/profile - профиль и статус\n"
        "/cash - сбор налогов (30 мин)\n"
        "/upgrade - улучшить уровень экономики\n"
        "/pay @user сумма - перевести деньги\n"
        "/senditem @user актив кол-во - передать ресурс\n"
        "/events - лог событий\n\n"
        "🏢 *Бизнес:*\n"
        "/shop - магазин бизнесов\n"
        "/buybiz название [кол-во] - купить бизнес\n"
        "/mybiz - ваши бизнесы и доход\n\n"
        "📊 *Биржа:*\n"
        "/market - цены на ресурсы\n"
        "/buy актив кол-во - купить\n"
        "/sell актив кол-во - продать\n"
        "/portfolio - ваш портфель\n\n"
        "⚔️ *Военное дело:*\n"
        "/army - состав армии и расходы\n"
        "/draft - призыв пехоты (2ч)\n"
        "/craft [тип] [кол-во] - производство техники\n"
        "/giftunit @user тип кол-во - подарить технику\n"
        "/morale - мораль армии\n\n"
        "🔬 *Технологии:*\n"
        "/tech - дерево технологий\n"
        "/researchtech название - исследовать\n\n"
        "⛏️ *Добыча:*\n"
        "/extractoil - добыть нефть\n"
        "/extract [gold|steel|coal|aur] - добыть ресурс\n\n"
        "🤝 *Торговля:*\n"
        "/trade тип что кол-во тип что кол-во\n"
        "/trades - открытые предложения\n"
        "/accept ID - принять сделку\n"
        "/canceltrade ID - отменить сделку\n\n"
        "🏆 *Рейтинги:*\n"
        "/top - рейтинги по категориям\n"
        "/toparmy - военная мощь\n"
        "/worldstats - мировая статистика",
        parse_mode="Markdown")

@bot.message_handler(commands=['profile'])
@group_only
def cmd_profile(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    user = db_query("SELECT balance,level,troops,ep,morale FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return bot.reply_to(message, "Введите /start")
    bal, lv, troops, ep, morale = user
    morale = morale or 100
    iph = (db_query('''SELECT SUM(ub.quantity*bt.income_per_hour) FROM user_businesses ub
                        JOIN business_types bt ON ub.business_name=bt.name WHERE ub.user_id=?''',
                    (uid,), fetchone=True) or [0])[0] or 0
    ext = (db_query("SELECT quantity FROM user_extractors WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    power = calc_power(uid)
    if bal >= 2_000_000:   tax_str = "3.5%/ч 🔴"
    elif bal >= 1_000_000: tax_str = "3.0%/ч 🔴"
    elif bal >= 500_000:   tax_str = "2.5%/ч 🟠"
    elif bal >= 200_000:   tax_str = "2.0%/ч 🟠"
    elif bal >= 150_000:   tax_str = "1.5%/ч 🟡"
    elif bal >= 100_000:   tax_str = "1.0%/ч 🟡"
    elif bal >= 50_000:    tax_str = "0.5%/ч 🟡"
    else:                  tax_str = "нет ✅"

    if morale >= 80:   morale_str = f"{morale}% 💚"
    elif morale >= 50: morale_str = f"{morale}% 🟡"
    elif morale >= 25: morale_str = f"{morale}% 🟠 (угроза дезертирства)"
    else:              morale_str = f"{morale}% 🔴 (КРИЗИС)"

    bot.reply_to(message,
        f"👤 *@{uname}*\n\n"
        f"💰 Баланс: {bal:,}\n"
        f"💸 Налог: {tax_str}\n"
        f"📈 Уровень экономики: {lv}\n"
        f"🪖 Пехота: {troops:,}\n"
        f"🎺 Мораль армии: {morale_str}\n"
        f"⚔️ Военная мощь: {power:,}\n"
        f"🏭 Пассивный доход: ~{iph} 💰/ч\n"
        f"🔬 ОЭ: {ep}\n"
        f"🛢️ Нефтекачек: {ext}\n\n"
        f"Мораль влияет на военную мощь!",
        parse_mode="Markdown")

@bot.message_handler(commands=['morale'])
@group_only
def cmd_morale(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    user = db_query("SELECT morale, troops, balance FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return bot.reply_to(message, "Введите /start")
    morale, troops, bal = user
    morale = morale or 100
    logi = get_tech(uid, 'logistics')
    maint = int((troops / 5) * max(0.1, 1 - logi * 0.10))

    if   morale >= 90: status = "Элитный дух - армия непобедима 💚"
    elif morale >= 70: status = "Высокий дух - хорошая боеспособность 🟢"
    elif morale >= 50: status = "Нормальный дух 🟡"
    elif morale >= 30: status = "Низкий дух - начинается дезертирство 🟠"
    elif morale >= 15: status = "Кризис морали - массовое дезертирство 🔴"
    else:              status = "Коллапс - армия распадается ☠️"

    morale_tech = get_tech(uid, 'morale_tech')
    desertion_rate = max(0.5, 3.0 - morale_tech * 0.5)

    text = (
        f"🎺 *Состояние вашей армии:*\n\n"
        f"Мораль: *{morale}%*\n"
        f"Статус: {status}\n\n"
        f"🪖 Пехота: {troops:,}\n"
        f"💸 Содержание: ~{maint} 💰/ч\n"
        f"💰 Ваш баланс: {bal:,}\n\n"
        f"*Как поднять мораль:*\n"
        f"- Платить за содержание армии\n"
        f"- Снабжать едой (/buy food)\n"
        f"- Технология Политработа (/tech)\n"
        f"  Текущий уровень: {morale_tech}/5\n\n"
        f"*При нехватке денег:* -{desertion_rate:.1f}% войск/ч"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['events'])
@group_only
def cmd_events(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    rows = db_query('''SELECT event_type, description, created_at FROM event_log
                       WHERE user_id=? ORDER BY created_at DESC LIMIT 10''', (uid,))
    if not rows:
        return bot.reply_to(message, "У вас нет зарегистрированных событий.")
    text = "📋 *Последние события:*\n\n"
    for etype, desc, ts in rows:
        dt = time.strftime('%d.%m %H:%M', time.localtime(ts))
        icon = {'desertion': '🏃', 'hunger': '🍽️', 'crisis': '💥'}.get(etype, '📌')
        text += f"{icon} [{dt}] {desc}\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['cash'])
@group_only
def cmd_cash(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    user = db_query("SELECT balance,level,last_cash FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return bot.reply_to(message, "Введите /start")
    bal, lv, last = user
    now = time.time()
    if now - (last or 0) < 1800:
        left = int(1800 - (now - last))
        return bot.reply_to(message, f"Казна пуста. Через {left//60} мин. {left%60} сек.")
    earned = int(500 * (1 + lv*0.2) * (1 + get_tech(uid,'finance')*0.10) * random.uniform(0.8, 1.2))
    db_query("UPDATE users SET balance=balance+?, last_cash=? WHERE user_id=?", (earned, now, uid))
    bot.reply_to(message, f"💵 Налоги: *+{earned}* 💰\nБаланс: {bal+earned:,}", parse_mode="Markdown")

@bot.message_handler(commands=['upgrade'])
@group_only
def cmd_upgrade(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    user = db_query("SELECT balance,level FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return bot.reply_to(message, "Введите /start")
    bal, lv = user
    cost = lv * 3000
    if bal < cost: return bot.reply_to(message, f"Нужно {cost:,} 💰, у вас {bal:,}")
    db_query("UPDATE users SET balance=balance-?, level=level+1 WHERE user_id=?", (cost, uid))
    bot.reply_to(message, f"✅ Экономика - уровень *{lv+1}* за {cost:,} 💰!", parse_mode="Markdown")

# --- Нефтедобыча ---
@bot.message_handler(commands=['extractoil'])
@group_only
def cmd_extractoil(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    ext = db_query("SELECT quantity,last_extract FROM user_extractors WHERE user_id=?", (uid,), fetchone=True)
    if not ext or ext[0] <= 0:
        return bot.reply_to(message, "В вашей стране нет источника нефти.")
    qty, last = ext
    now = time.time()
    if now - (last or 0) < 3600:
        left = int(3600 - (now - last))
        return bot.reply_to(message, f"Следующая добыча через {left//60} мин. {left%60} сек.")
    db_query("UPDATE user_extractors SET last_extract=? WHERE user_id=?", (now, uid))
    add_asset(uid, 'oil', qty)
    total = (db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name='oil'",
                      (uid,), fetchone=True) or [0])[0]
    bot.reply_to(message,
        f"🛢️ Добыто *{qty}* нефти ({qty} качек x 1)\nВсего нефти: {total:.1f}",
        parse_mode="Markdown")

@bot.message_handler(commands=['extract'])
@group_only
def cmd_extract(message):
    """Добыча ресурсов из зданий: /extract gold|steel|coal|aur"""
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()

    if len(args) < 2:
        text = "⛏️ *Добыча ресурсов:*\n\n"
        for res, (emoji, name, yld, cd) in RESOURCE_BUILDINGS.items():
            row = db_query("SELECT quantity,last_extract FROM user_resource_buildings WHERE user_id=? AND resource=?",
                           (uid, res), fetchone=True)
            qty = row[0] if row else 0
            last = row[1] if row else 0
            now = time.time()
            if qty > 0:
                if now - (last or 0) < cd:
                    left = int(cd - (now - last))
                    cd_str = f"{left//3600}ч {(left%3600)//60}м" if left >= 3600 else f"{left//60}м {left%60}с"
                    ready = f"готово через {cd_str}"
                else:
                    ready = f"✅ готово! +{qty*yld} {emoji}"
                text += f"{emoji} *{name}*: {qty} шт. - {ready}\n"
            else:
                text += f"{emoji} *{name}* (`/extract {res}`): нет зданий\n"
        text += "\nИспользование: `/extract [ресурс]`"
        return bot.reply_to(message, text, parse_mode="Markdown")

    res = args[1].lower()
    if res not in RESOURCE_BUILDINGS:
        return bot.reply_to(message,
            f"Неизвестный ресурс. Доступно: {', '.join(RESOURCE_BUILDINGS.keys())}")

    emoji, name, yld, cd = RESOURCE_BUILDINGS[res]
    row = db_query("SELECT quantity,last_extract FROM user_resource_buildings WHERE user_id=? AND resource=?",
                   (uid, res), fetchone=True)
    if not row or row[0] <= 0:
        return bot.reply_to(message, f"В вашей стране нет источника {name.lower()}.")

    qty, last = row
    now = time.time()
    if now - (last or 0) < cd:
        left = int(cd - (now - last))
        cd_str = f"{left//3600}ч {(left%3600)//60}м" if left >= 3600 else f"{left//60}м {left%60}с"
        return bot.reply_to(message, f"Следующая добыча через {cd_str}.")

    gained = qty * yld
    db_query("UPDATE user_resource_buildings SET last_extract=? WHERE user_id=? AND resource=?",
             (now, uid, res))
    add_asset(uid, res, gained)
    total = (db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?",
                      (uid, res), fetchone=True) or [0])[0]
    bot.reply_to(message,
        f"{emoji} Добыто *{gained}* ({qty} зданий x {yld})\nВсего {name.split()[0].lower()}: {total:.1f}",
        parse_mode="Markdown")

# --- Технологии ---
@bot.message_handler(commands=['tech'])
@group_only
def cmd_tech(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    techs = db_query("SELECT name,display_name,max_level,ep_cost_per_level,description FROM tech_types")
    ep = (db_query("SELECT ep FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    text = f"🔬 *Дерево технологий*\n💡 Ваши ОЭ: {ep}\n\n"
    for name, disp, maxlv, cost, desc in techs:
        lv = get_tech(uid, name)
        status = "✅ МАКС" if lv >= maxlv else f"Ур.{lv}/{maxlv} - {cost} ОЭ"
        text += f"*{disp}* (`{name}`)\n_{desc}_\n{status}\n\n"
    text += "- `/researchtech [название]`"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['researchtech'])
@group_only
def cmd_researchtech(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) < 2: return bot.reply_to(message, "Использование: /researchtech [название]")
    tech_name = args[1].lower()
    tech = db_query("SELECT display_name,max_level,ep_cost_per_level FROM tech_types WHERE name=?",
                    (tech_name,), fetchone=True)
    if not tech: return bot.reply_to(message, f"Технология '{tech_name}' не найдена. /tech")
    disp, maxlv, cost = tech
    lv = get_tech(uid, tech_name)
    if lv >= maxlv: return bot.reply_to(message, f"✅ *{disp}* уже максимальна.", parse_mode="Markdown")
    ep = (db_query("SELECT ep FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    if ep < cost: return bot.reply_to(message, f"Нужно {cost} ОЭ, у вас {ep}")
    db_query("UPDATE users SET ep=ep-? WHERE user_id=?", (cost, uid))
    if lv == 0:
        db_query("INSERT INTO user_tech VALUES (?,?,1)", (uid, tech_name))
    else:
        db_query("UPDATE user_tech SET level=level+1 WHERE user_id=? AND tech_name=?", (uid, tech_name))
    bot.reply_to(message, f"🔬 *{disp}* - Ур. *{lv+1}/{maxlv}*\nПотрачено: {cost} ОЭ",
                 parse_mode="Markdown")

# --- Армия ---
@bot.message_handler(commands=['draft'])
@group_only
def cmd_draft(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    user = db_query("SELECT troops,last_draft,morale FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return bot.reply_to(message, "Введите /start")
    troops, last, morale = user
    now = time.time()
    if now - (last or 0) < 7200:
        left = int(7200 - (now - last))
        return bot.reply_to(message, f"Следующий призыв через {left//3600} ч. {(left%3600)//60} мин.")

    morale = morale or 100
    # Низкая мораль = меньше призывников
    morale_factor = max(0.3, morale / 100)
    base_recruits = random.randint(1000, 2000)
    new_recruits = int(base_recruits * morale_factor)

    db_query("UPDATE users SET troops=troops+?, last_draft=? WHERE user_id=?", (new_recruits, now, uid))
    morale_note = ""
    if morale < 60:
        morale_note = f"\n⚠️ Низкая мораль ({morale}%) сократила призыв!"
    bot.reply_to(message,
        f"🪖 *Призыв!*\n+*{new_recruits}* новобранцев\nВсего: {troops+new_recruits:,}{morale_note}",
        parse_mode="Markdown")

@bot.message_handler(commands=['craft'])
@group_only
def cmd_craft(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()

    if len(args) < 3:
        types = db_query("SELECT name,display_name,steel_cost,money_cost,category,oil_per_unit,coal_per_unit FROM military_types")
        cats = {'ground': '🪖 Наземные силы', 'air': '✈️ Авиация', 'navy': '🚢 Флот'}
        text = "⚙️ *Производство военной техники:* `/craft [тип] [кол-во]`\n\n"
        for ck, cn in cats.items():
            text += f"*{cn}:*\n"
            for name, disp, steel, money, cat, oil_pu, coal_pu in types:
                if cat != ck: continue
                fuel_str = ""
                if oil_pu > 0:  fuel_str = f" | 🛢️{oil_pu}/3ч"
                if coal_pu > 0: fuel_str = f" | 🪨{coal_pu}/3ч"
                req_str = ""
                if name in UNIT_TECH_REQUIREMENTS:
                    reqs = []
                    for tname, tlv in UNIT_TECH_REQUIREMENTS[name]:
                        trow = db_query("SELECT display_name FROM tech_types WHERE name=?", (tname,), fetchone=True)
                        tdisp = trow[0].split()[-1] if trow else tname
                        cur = get_tech(uid, tname)
                        ok = "✅" if cur >= tlv else "❌"
                        reqs.append(f"{ok}{tdisp}Ур.{tlv}")
                    req_str = f" [{', '.join(reqs)}]"
                extra_str = ""
                if name in UNIT_RESOURCE_REQUIREMENTS:
                    parts = [f"{v}{k}" for k, v in UNIT_RESOURCE_REQUIREMENTS[name].items()]
                    extra_str = f" +{'/'.join(parts)}/ед."
                text += f"  {disp} (`{name}`) - {steel}⚙️ + {money:,}💰{fuel_str}{extra_str}{req_str}\n"
            text += "\n"
        return bot.reply_to(message, text, parse_mode="Markdown")

    unit_name = args[1].lower()
    try: qty = int(args[2])
    except: return bot.reply_to(message, "Количество - число.")
    if qty <= 0: return bot.reply_to(message, "Количество > 0.")
    unit = db_query("SELECT display_name,steel_cost,money_cost FROM military_types WHERE name=?",
                    (unit_name,), fetchone=True)
    if not unit: return bot.reply_to(message, f"Тип '{unit_name}' не найден.")
    disp, steel_c, money_c = unit

    # Проверка требований технологий
    if unit_name in UNIT_TECH_REQUIREMENTS:
        missing = []
        for tech_name, min_lv in UNIT_TECH_REQUIREMENTS[unit_name]:
            cur_lv = get_tech(uid, tech_name)
            if cur_lv < min_lv:
                tech_row = db_query("SELECT display_name FROM tech_types WHERE name=?", (tech_name,), fetchone=True)
                tech_disp = tech_row[0] if tech_row else tech_name
                missing.append(f"{tech_disp} Ур.{min_lv} (у вас: {cur_lv})")
        if missing:
            return bot.reply_to(message,
                f"❌ Для производства *{disp}* нужно:\n" + "\n".join(f"- {m}" for m in missing),
                parse_mode="Markdown")
    total_steel = int(steel_c * qty * max(0.2, 1 - get_tech(uid,'metallurgy')*0.08))
    total_money = int(money_c * qty * max(0.2, 1 - get_tech(uid,'engineering')*0.08))
    bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    sr = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name='steel'",
                  (uid,), fetchone=True)
    cur_steel = int(sr[0]) if sr else 0
    if bal < total_money or cur_steel < total_steel:
        return bot.reply_to(message,
            f"Нужно: {total_steel}⚙️ и {total_money:,}💰\nЕсть: {cur_steel}⚙️ и {bal:,}💰")

    # Проверка доп. ресурсов для ядерного оружия
    extra_needed = {}
    if unit_name in UNIT_RESOURCE_REQUIREMENTS:
        for asset, per_unit in UNIT_RESOURCE_REQUIREMENTS[unit_name].items():
            needed = per_unit * qty
            row = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?",
                           (uid, asset), fetchone=True)
            have = row[0] if row else 0
            if have < needed:
                arow = db_query("SELECT display_name FROM market_assets WHERE name=?", (asset,), fetchone=True)
                aname = arow[0] if arow else asset
                return bot.reply_to(message,
                    f"❌ Ядерное производство: нужно *{needed}x {aname}*, у вас {have:.1f}",
                    parse_mode="Markdown")
            extra_needed[asset] = needed

    db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (total_money, uid))
    db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name='steel'",
             (total_steel, uid))
    for asset, needed in extra_needed.items():
        db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name=?",
                 (needed, uid, asset))
    db_query("INSERT INTO user_military VALUES (?,?,?) ON CONFLICT(user_id,unit_name) DO UPDATE SET quantity=quantity+?",
             (uid, unit_name, qty, qty))
    extra_str = ""
    for asset, needed in extra_needed.items():
        arow = db_query("SELECT display_name FROM market_assets WHERE name=?", (asset,), fetchone=True)
        extra_str += f" | -{needed}x{arow[0] if arow else asset}"
    bot.reply_to(message, f"🏭 *{qty}x {disp}* произведено!\n-{total_steel}⚙️ | -{total_money:,}💰{extra_str}",
                 parse_mode="Markdown")

@bot.message_handler(commands=['army'])
@group_only
def cmd_army(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    user = db_query("SELECT troops, morale FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return bot.reply_to(message, "Введите /start")
    troops, morale = user
    morale = morale or 100

    units = db_query('''SELECT u.unit_name, m.display_name, u.quantity, m.category,
                               m.oil_per_unit, m.coal_per_unit
                        FROM user_military u JOIN military_types m ON u.unit_name=m.name
                        WHERE u.user_id=? AND u.quantity>0''', (uid,))
    secs = {'ground':[], 'air':[], 'navy':[]}
    total_oil_3h = 0.0
    total_coal_3h = 0.0
    energy_mult = max(0.1, 1 - get_tech(uid,'energy') * 0.10)
    has_aes = db_query("SELECT quantity FROM user_businesses WHERE user_id=? AND business_name='nps'",
                       (uid,), fetchone=True)
    nps_bonus = 0.25 if (has_aes and has_aes[0] > 0) else 0.0
    fuel_mult = max(0.05, energy_mult - nps_bonus)

    for uname, disp, qty, cat, oil_pu, coal_pu in (units or []):
        secs.get(cat, secs['ground']).append(f"  {disp}: {qty:,}")
        total_oil_3h  += oil_pu  * qty * fuel_mult
        total_coal_3h += coal_pu * qty * fuel_mult

    logi = get_tech(uid, 'logistics')
    maint = int((troops/5) * max(0.1, 1 - logi * 0.10))
    power = calc_power(uid)

    text = f"⚔️ *Ваши вооруженные силы:*\n\n"
    text += f"🪖 *Наземные:*\n  Пехота: {troops:,}\n"
    text += ("\n".join(secs['ground'])+"\n") if secs['ground'] else "  Техника отсутствует\n"
    text += "\n✈️ *Авиация:*\n"
    text += ("\n".join(secs['air'])+"\n") if secs['air'] else "  Авиация отсутствует\n"
    text += "\n🚢 *Флот:*\n"
    text += ("\n".join(secs['navy'])+"\n") if secs['navy'] else "  Флот отсутствует\n"
    text += f"\n⚔️ *Мощь: {power:,}*"
    text += f" (мораль: {morale}%)\n"
    text += f"💸 Содержание пехоты: ~{maint} 💰/ч\n"
    if total_oil_3h > 0:
        aes_note = " (⚛️ АЭС: -25%)" if nps_bonus > 0 else ""
        text += f"🛢️ Расход нефти (авиация+танки): {total_oil_3h:.2f}/3ч{aes_note}\n"
    if total_coal_3h > 0:
        aes_note = " (⚛️ АЭС: -25%)" if nps_bonus > 0 else ""
        text += f"🪨 Расход угля (флот): {total_coal_3h:.2f}/3ч{aes_note}\n"
    text += "\n💡 /craft - производство | /giftunit - подарить | /morale - мораль"
    bot.reply_to(message, text, parse_mode="Markdown")

# --- Подарить оружие ---
@bot.message_handler(commands=['giftunit'])
@group_only
def cmd_giftunit(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 4:
        return bot.reply_to(message,
            "Использование: `/giftunit @user [тип] [кол-во]`\nПример: `/giftunit @ivan tank 5`",
            parse_mode="Markdown")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, f"{args[1]} не найден.")
    unit_name = args[2].lower()
    try: qty = int(args[3])
    except: return bot.reply_to(message, "Количество - число.")
    if qty <= 0: return bot.reply_to(message, "Количество > 0.")
    if t[0] == uid: return bot.reply_to(message, "Нельзя дарить себе.")
    unit = db_query("SELECT display_name FROM military_types WHERE name=?", (unit_name,), fetchone=True)
    if not unit: return bot.reply_to(message, f"Тип '{unit_name}' не найден. /craft")
    row = db_query("SELECT quantity FROM user_military WHERE user_id=? AND unit_name=?", (uid,unit_name), fetchone=True)
    if not row or row[0] < qty:
        return bot.reply_to(message, f"У вас только {row[0] if row else 0} {unit[0]}")
    db_query("UPDATE user_military SET quantity=quantity-? WHERE user_id=? AND unit_name=?", (qty,uid,unit_name))
    e = db_query("SELECT quantity FROM user_military WHERE user_id=? AND unit_name=?", (t[0],unit_name), fetchone=True)
    if e:
        db_query("UPDATE user_military SET quantity=quantity+? WHERE user_id=? AND unit_name=?", (qty,t[0],unit_name))
    else:
        db_query("INSERT INTO user_military VALUES (?,?,?)", (t[0],unit_name,qty))
    bot.reply_to(message, f"🎁 *{qty}x {unit[0]}* подарено @{t[1]}!", parse_mode="Markdown")

# ==============================================================
# --- ТОРГОВАЯ СИСТЕМА ---
# ==============================================================
@bot.message_handler(commands=['trade'])
@group_only
def cmd_trade(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 7:
        return bot.reply_to(message,
            "📋 *Создать торговое предложение:*\n"
            "`/trade [тип] [что] [кол-во] [тип] [что] [кол-во]`\n\n"
            "*Типы:* `money` или `asset`\n"
            "*Активы:* oil gold steel aur food coal\n\n"
            "*Примеры:*\n"
            "`/trade asset steel 50 money money 5000`\n"
            "`/trade money money 10000 asset gold 15`\n"
            "`/trade asset oil 20 asset steel 100`",
            parse_mode="Markdown")
    _, ot, on, oq_s, wt, wn, wq_s = args
    ot = ot.lower(); wt = wt.lower()
    try: oq = float(oq_s); wq = float(wq_s)
    except: return bot.reply_to(message, "Количество - число.")
    if oq <= 0 or wq <= 0: return bot.reply_to(message, "Количество > 0.")

    if ot == 'money':
        on = 'money'
        bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
        if bal < int(oq): return bot.reply_to(message, f"Нужно {int(oq):,} 💰, у вас {bal:,}")
        db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (int(oq), uid))
    elif ot == 'asset':
        on = on.lower()
        if not db_query("SELECT name FROM market_assets WHERE name=?", (on,), fetchone=True):
            return bot.reply_to(message, f"Актив '{on}' не найден.")
        row = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid,on), fetchone=True)
        if not row or row[0] < oq: return bot.reply_to(message, f"Недостаточно {on}")
        db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name=?", (oq,uid,on))
    else:
        return bot.reply_to(message, "Тип: 'money' или 'asset'")

    if wt == 'money':
        wn = 'money'
    elif wt == 'asset':
        wn = wn.lower()
        if not db_query("SELECT name FROM market_assets WHERE name=?", (wn,), fetchone=True):
            if ot == 'money': db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (int(oq),uid))
            else: db_query("UPDATE user_portfolio SET quantity=quantity+? WHERE user_id=? AND asset_name=?", (oq,uid,on))
            return bot.reply_to(message, f"Актив '{wn}' не найден.")
    else:
        if ot == 'money': db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (int(oq),uid))
        else: db_query("UPDATE user_portfolio SET quantity=quantity+? WHERE user_id=? AND asset_name=?", (oq,uid,on))
        return bot.reply_to(message, "Тип: 'money' или 'asset'")

    db_query("INSERT INTO trade_offers (seller_id,seller_username,offer_type,offer_name,offer_qty,want_type,want_name,want_qty,created_at,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
             (uid, uname, ot, on, oq, wt, wn, wq, time.time(), 'open'))
    tid = db_query("SELECT id FROM trade_offers WHERE seller_id=? ORDER BY id DESC LIMIT 1",
                   (uid,), fetchone=True)[0]
    ostr = f"{int(oq):,} 💰" if ot=='money' else f"{oq} {on}"
    wstr = f"{int(wq):,} 💰" if wt=='money' else f"{wq} {wn}"
    bot.reply_to(message,
        f"✅ *Предложение #{tid}*\nОтдаю: {ostr}\nХочу: {wstr}\n"
        f"Все: /trades | Принять: `/accept {tid}`",
        parse_mode="Markdown")

@bot.message_handler(commands=['trades'])
@group_only
def cmd_trades(message):
    if is_banned(message.from_user.id): return
    offers = db_query('''SELECT id,seller_username,offer_type,offer_name,offer_qty,
                                want_type,want_name,want_qty FROM trade_offers
                         WHERE status='open' ORDER BY id DESC LIMIT 20''')
    if not offers: return bot.reply_to(message, "Открытых предложений нет.")
    text = "🤝 *Открытые торговые предложения:*\n\n"
    for tid, seller, ot, on, oq, wt, wn, wq in offers:
        ostr = f"{int(oq):,}💰" if ot=='money' else f"{oq} {on}"
        wstr = f"{int(wq):,}💰" if wt=='money' else f"{wq} {wn}"
        text += f"*#{tid}* @{seller}: {ostr} -> {wstr} `/accept {tid}`\n"
    text += "\nОтменить: `/canceltrade ID`"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['accept'])
@group_only
def cmd_accept(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 2: return bot.reply_to(message, "Использование: /accept [ID]")
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
        if bal < int(wq): return bot.reply_to(message, f"Нужно {int(wq):,} 💰, у вас {bal:,}")
        db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (int(wq), uid))
    else:
        row = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid,wn), fetchone=True)
        if not row or row[0] < wq: return bot.reply_to(message, f"Недостаточно {wn}")
        db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name=?", (wq,uid,wn))

    if ot == 'money':
        db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (int(oq), uid))
    else:
        add_asset(uid, on, oq)

    if wt == 'money':
        db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (int(wq), seller_id))
    else:
        add_asset(seller_id, wn, wq)

    db_query("UPDATE trade_offers SET status='closed' WHERE id=?", (tid,))
    ostr = f"{int(oq):,}💰" if ot=='money' else f"{oq} {on}"
    wstr = f"{int(wq):,}💰" if wt=='money' else f"{wq} {wn}"
    bot.reply_to(message,
        f"✅ *Сделка #{tid} завершена!*\n@{uname} купил {ostr} у @{seller_uname} за {wstr}",
        parse_mode="Markdown")

@bot.message_handler(commands=['canceltrade'])
@group_only
def cmd_canceltrade(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 2: return bot.reply_to(message, "Использование: /canceltrade [ID]")
    try: tid = int(args[1])
    except: return bot.reply_to(message, "ID - число.")
    offer = db_query("SELECT seller_id,offer_type,offer_name,offer_qty FROM trade_offers WHERE id=? AND status='open'",
                     (tid,), fetchone=True)
    if not offer: return bot.reply_to(message, f"Предложение #{tid} не найдено.")
    if offer[0] != uid and not is_admin(uid):
        return bot.reply_to(message, "Это не ваше предложение.")
    seller_id, ot, on, oq = offer
    if ot == 'money':
        db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (int(oq), seller_id))
    else:
        add_asset(seller_id, on, oq)
    db_query("UPDATE trade_offers SET status='cancelled' WHERE id=?", (tid,))
    bot.reply_to(message, f"✅ Предложение #{tid} отменено, активы возвращены.")

# ==============================================================
# --- ПЕРЕВОДЫ ---
# ==============================================================
@bot.message_handler(commands=['pay'])
@group_only
def cmd_pay(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "Использование: /pay @user [сумма]")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, f"{args[1]} не найден.")
    try: amount = int(args[2])
    except: return bot.reply_to(message, "Сумма - число.")
    if amount <= 0: return bot.reply_to(message, "Сумма > 0.")
    if t[0] == uid: return bot.reply_to(message, "Нельзя себе.")
    bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    if bal < amount: return bot.reply_to(message, "Недостаточно средств.")
    db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, uid))
    db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, t[0]))
    bot.reply_to(message, f"💸 *{amount:,}* 💰 -> @{t[1]}", parse_mode="Markdown")

@bot.message_handler(commands=['senditem'])
@group_only
def cmd_senditem(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 4:
        return bot.reply_to(message, "Использование: `/senditem @user [актив] [кол-во]`", parse_mode="Markdown")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, f"{args[1]} не найден.")
    asset = args[2].lower()
    try: amount = float(args[3])
    except: return bot.reply_to(message, "Количество - число.")
    if amount <= 0: return bot.reply_to(message, "Количество > 0.")
    if t[0] == uid: return bot.reply_to(message, "Нельзя себе.")
    arow = db_query("SELECT display_name FROM market_assets WHERE name=?", (asset,), fetchone=True)
    if not arow: return bot.reply_to(message, f"Актив '{asset}' не найден.")
    row = db_query("SELECT quantity,avg_buy_price FROM user_portfolio WHERE user_id=? AND asset_name=?",
                   (uid,asset), fetchone=True)
    if not row or row[0] < amount: return bot.reply_to(message, f"Недостаточно {arow[0]}")
    new_qty = row[0] - amount
    if new_qty <= 0: db_query("DELETE FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid,asset))
    else: db_query("UPDATE user_portfolio SET quantity=? WHERE user_id=? AND asset_name=?", (new_qty,uid,asset))
    te = db_query("SELECT quantity,avg_buy_price FROM user_portfolio WHERE user_id=? AND asset_name=?",
                  (t[0],asset), fetchone=True)
    if te:
        new_avg = (te[0]*te[1] + amount*row[1]) / (te[0]+amount)
        db_query("UPDATE user_portfolio SET quantity=quantity+?, avg_buy_price=? WHERE user_id=? AND asset_name=?",
                 (amount, new_avg, t[0], asset))
    else:
        db_query("INSERT INTO user_portfolio VALUES (?,?,?,?)", (t[0],asset,amount,row[1]))
    bot.reply_to(message, f"📦 *{amount}x {arow[0]}* -> @{t[1]}", parse_mode="Markdown")

# ==============================================================
# --- БИЗНЕС ---
# ==============================================================
@bot.message_handler(commands=['shop'])
@group_only
def cmd_shop(message):
    if is_banned(message.from_user.id): return
    rows = db_query("SELECT name,display_name,cost,income_per_hour,description,ep_per_12h FROM business_types")
    text = "🏪 *Магазин бизнесов:*\n\n"
    for name, disp, cost, iph, desc, ep12 in rows:
        ep_str = f" | 🔬+{ep12}ОЭ/12ч" if ep12 else ""
        text += f"{disp}\n💵 {cost:,}💰 | ~{iph}💰/ч{ep_str}\n_{desc}_\n`/buybiz {name}`\n\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['buybiz'])
@group_only
def cmd_buybiz(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) < 2: return bot.reply_to(message, "Использование: /buybiz [название] [кол-во]")
    bname = args[1].lower()
    qty = int(args[2]) if len(args) >= 3 and args[2].isdigit() else 1
    if qty < 1: return bot.reply_to(message, "Количество >= 1.")
    biz = db_query("SELECT display_name,cost,income_per_hour,ep_per_12h FROM business_types WHERE name=?",
                   (bname,), fetchone=True)
    if not biz: return bot.reply_to(message, f"Бизнес '{bname}' не найден. /shop")
    disp, cost, iph, ep12 = biz

    # Особая обработка АЭС
    if bname == 'nps':
        energy_lv = get_tech(uid, 'energy')
        if energy_lv < 3:
            return bot.reply_to(message,
                f"⚛️ АЭС требует технологию *Энергетика Ур.3* (у вас: {energy_lv}).\n"
                f"Исследуйте: /tech -> /researchtech energy",
                parse_mode="Markdown")
        existing = db_query("SELECT quantity FROM user_businesses WHERE user_id=? AND business_name='nps'",
                            (uid,), fetchone=True)
        if existing and existing[0] >= 1:
            return bot.reply_to(message, "⚛️ У вашей страны уже есть АЭС. Только одна на государство.")
        steel_needed, aur_needed = 500, 20
        sr = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name='steel'", (uid,), fetchone=True)
        ar = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name='aur'", (uid,), fetchone=True)
        cur_steel = int(sr[0]) if sr else 0
        cur_aur = float(ar[0]) if ar else 0.0
        bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
        if bal < cost or cur_steel < steel_needed or cur_aur < aur_needed:
            return bot.reply_to(message,
                f"⚛️ *Строительство АЭС требует:*\n"
                f"💰 {cost:,} (у вас: {bal:,})\n"
                f"⚙️ {steel_needed} стали (у вас: {cur_steel})\n"
                f"💎 {aur_needed} аурита (у вас: {cur_aur:.1f})",
                parse_mode="Markdown")
        db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (cost, uid))
        db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name='steel'", (steel_needed, uid))
        db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name='aur'", (aur_needed, uid))
        db_query("INSERT INTO user_businesses (user_id,business_name,quantity) VALUES (?,?,1) "
                 "ON CONFLICT(user_id,business_name) DO UPDATE SET quantity=quantity+1", (uid, bname))
        bot.reply_to(message,
            f"⚛️ *АЭС построена!*\n"
            f"-{cost:,}💰 | -{steel_needed}⚙️ | -{aur_needed}💎\n\n"
            f"💵 Доход: ~{iph:,}💰/ч\n"
            f"⚡ Расход топлива армии снижен на 25%",
            parse_mode="Markdown")
        return
    total = cost * qty
    bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    if bal < total: return bot.reply_to(message, f"Нужно {total:,}💰, у вас {bal:,}💰")
    db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (total, uid))
    db_query("INSERT INTO user_businesses (user_id,business_name,quantity) VALUES (?,?,?) ON CONFLICT(user_id,business_name) DO UPDATE SET quantity=quantity+?",
             (uid, bname, qty, qty))
    ep_str = f"\n🔬 +{ep12*qty} ОЭ/12ч" if ep12 else ""
    bot.reply_to(message, f"✅ *{qty}x {disp}* за {total:,}💰!\n~{iph*qty}💰/ч{ep_str}",
                 parse_mode="Markdown")

@bot.message_handler(commands=['mybiz'])
@group_only
def cmd_mybiz(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    rows = db_query('''SELECT bt.display_name,ub.quantity,bt.income_per_hour,bt.ep_per_12h
                       FROM user_businesses ub JOIN business_types bt ON ub.business_name=bt.name
                       WHERE ub.user_id=?''', (uid,))
    if not rows: return bot.reply_to(message, "У вас нет бизнесов. /shop")
    text = "🏢 *Ваши бизнесы:*\n\n"
    ti = te = 0
    for disp, qty, iph, ep12 in rows:
        si=iph*qty; se=ep12*qty; ti+=si; te+=se
        ep_str = f" | +{se}ОЭ" if se else ""
        text += f"{disp} x{qty} - {si}💰/ч{ep_str}\n"
    text += f"\n📊 *~{ti}💰/ч | 🔬+{te}ОЭ/12ч | ~{ti*24:,}💰/сутки*"
    bot.reply_to(message, text, parse_mode="Markdown")

# ==============================================================
# --- БИРЖА ---
# ==============================================================
@bot.message_handler(commands=['market'])
@group_only
def cmd_market(message):
    if is_banned(message.from_user.id): return
    assets = db_query("SELECT name,display_name,price,base_price FROM market_assets")
    text = "📊 *Мировая биржа:*\n\n"
    for name, disp, price, base in assets:
        arr = get_price_arrow(price, base)
        pct = ((price-base)/base)*100
        sign = "+" if pct >= 0 else ""
        text += f"{arr} *{disp}*: {price:.2f}💰 ({sign}{pct:.1f}%)\n"
        text += f"   `/buy {name} [кол]`  `/sell {name} [кол]`\n\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['buy'])
@group_only
def cmd_buy(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) < 3: return bot.reply_to(message, "Использование: /buy [актив] [кол-во]")
    asset = args[1].lower()
    try: qty = int(args[2])
    except: return bot.reply_to(message, "Количество - число.")
    if qty <= 0: return bot.reply_to(message, "Количество > 0.")
    arow = db_query("SELECT display_name,price FROM market_assets WHERE name=?", (asset,), fetchone=True)
    if not arow: return bot.reply_to(message, f"Актив '{asset}' не найден.")
    disp, price = arow
    total = round(price * qty, 2)
    bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    if bal < total: return bot.reply_to(message, f"Нужно {total:.2f}💰, у вас {bal:,}💰")
    e = db_query("SELECT quantity,avg_buy_price FROM user_portfolio WHERE user_id=? AND asset_name=?",
                 (uid,asset), fetchone=True)
    if e:
        nq = e[0]+qty; na = (e[0]*e[1]+price*qty)/nq
        db_query("UPDATE user_portfolio SET quantity=?,avg_buy_price=? WHERE user_id=? AND asset_name=?",
                 (nq,na,uid,asset))
    else:
        db_query("INSERT INTO user_portfolio VALUES (?,?,?,?)", (uid,asset,qty,price))
    db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (total, uid))
    bot.reply_to(message, f"✅ *{qty}x {disp}* за {total:.2f}💰", parse_mode="Markdown")

@bot.message_handler(commands=['sell'])
@group_only
def cmd_sell(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) < 3: return bot.reply_to(message, "Использование: /sell [актив] [кол-во]")
    asset = args[1].lower()
    try: qty = int(args[2])
    except: return bot.reply_to(message, "Количество - число.")
    if qty <= 0: return bot.reply_to(message, "Количество > 0.")
    arow = db_query("SELECT display_name,price FROM market_assets WHERE name=?", (asset,), fetchone=True)
    if not arow: return bot.reply_to(message, f"Актив '{asset}' не найден.")
    disp, price = arow
    row = db_query("SELECT quantity,avg_buy_price FROM user_portfolio WHERE user_id=? AND asset_name=?",
                   (uid,asset), fetchone=True)
    if not row or row[0] < qty:
        return bot.reply_to(message, f"У вас только {row[0] if row else 0:.1f} {disp}")
    rev = round(price*qty, 2); profit = round((price-row[1])*qty, 2)
    nq = row[0]-qty
    if nq <= 0: db_query("DELETE FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid,asset))
    else: db_query("UPDATE user_portfolio SET quantity=? WHERE user_id=? AND asset_name=?", (nq,uid,asset))
    db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (rev, uid))
    emoji = "📈" if profit >= 0 else "📉"
    pstr = f"+{profit:.2f}" if profit >= 0 else f"{profit:.2f}"
    bot.reply_to(message, f"💰 *{qty}x {disp}* за {rev:.2f}💰\n{emoji} P&L: *{pstr}💰*",
                 parse_mode="Markdown")

@bot.message_handler(commands=['portfolio'])
@group_only
def cmd_portfolio(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    rows = db_query('''SELECT p.asset_name,p.quantity,p.avg_buy_price,m.price,m.display_name
                       FROM user_portfolio p JOIN market_assets m ON p.asset_name=m.name
                       WHERE p.user_id=? AND p.quantity>0''', (uid,))
    if not rows: return bot.reply_to(message, "Портфель пуст. /market")
    text = "💼 *Портфель:*\n\n"
    ti = tc = 0.0
    for _, qty, avg, cur, disp in rows:
        inv=avg*qty; cv=cur*qty; pnl=cv-inv; ti+=inv; tc+=cv
        e = "📈" if pnl>=0 else "📉"
        pstr = f"+{pnl:.2f}" if pnl>=0 else f"{pnl:.2f}"
        text += f"{e} *{disp}* x{qty:.1f} | avg:{avg:.2f}->{cur:.2f} | {pstr}💰\n"
    tp=tc-ti; tstr=f"+{tp:.2f}" if tp>=0 else f"{tp:.2f}"
    text += f"\n💰 Вложено: {ti:.2f} | Сейчас: {tc:.2f}\n{'📈' if tp>=0 else '📉'} *P&L: {tstr}💰*"
    bot.reply_to(message, text, parse_mode="Markdown")

# ==============================================================
# --- РЕЙТИНГИ ---
# ==============================================================
@bot.message_handler(commands=['toparmy'])
@group_only
def cmd_toparmy(message):
    users = db_query("SELECT user_id,username FROM users WHERE banned=0")
    powers = sorted([(uname, calc_power(uid)) for uid,uname in (users or [])],
                    key=lambda x: x[1], reverse=True)
    powers = [(u,p) for u,p in powers if p > 0][:10]
    if not powers: return bot.reply_to(message, "Рейтинг пуст.")
    medals = ["🥇","🥈","🥉"]
    text = "⚔️ *Рейтинг военной мощи:*\n\n"
    for i,(u,p) in enumerate(powers,1):
        text += f"{medals[i-1] if i<=3 else str(i)+'.'} @{u} - {p:,}⚔️\n"
    text += "\n💡 Мощь = войска + техника x коэффициент x мораль x технологии"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['top'])
@group_only
def cmd_top(message):
    args = message.text.split()
    if len(args) < 2:
        assets = db_query("SELECT name,display_name FROM market_assets")
        text = "🏆 *Рейтинги:*\n`/top money` `/top ep`\n"
        for name, disp in assets: text += f"`/top {name}` - {disp}\n"
        text += "\n⚔️ /toparmy"
        return bot.reply_to(message, text, parse_mode="Markdown")
    cat = args[1].lower()
    if cat == 'money':
        rows = db_query("SELECT username,balance FROM users WHERE banned=0 ORDER BY balance DESC LIMIT 10")
        text = "🏆 *Топ по балансу:*\n\n"
        for i,(u,v) in enumerate(rows or [],1): text += f"{i}. @{u} - {v:,}💰\n"
    elif cat == 'ep':
        rows = db_query("SELECT username,ep FROM users WHERE banned=0 ORDER BY ep DESC LIMIT 10")
        text = "🏆 *Топ по ОЭ:*\n\n"
        for i,(u,v) in enumerate(rows or [],1): text += f"{i}. @{u} - {v:,}ОЭ🔬\n"
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

@bot.message_handler(commands=['worldstats'])
@group_only
def cmd_worldstats(message):
    money  = (db_query("SELECT SUM(balance) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
    troops = (db_query("SELECT SUM(troops) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
    count  = (db_query("SELECT COUNT(*) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
    ep     = (db_query("SELECT SUM(ep) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
    oil    = (db_query("SELECT SUM(quantity) FROM user_portfolio WHERE asset_name='oil'", fetchone=True) or [0])[0] or 0
    trades = (db_query("SELECT COUNT(*) FROM trade_offers WHERE status='open'", fetchone=True) or [0])[0] or 0
    avg_morale = (db_query("SELECT AVG(morale) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
    nps_count = (db_query("SELECT COUNT(*) FROM user_businesses WHERE business_name='nps' AND quantity>0", fetchone=True) or [0])[0] or 0
    missiles = (db_query("SELECT SUM(quantity) FROM user_military WHERE unit_name='missile'", fetchone=True) or [0])[0] or 0
    nucsubs  = (db_query("SELECT SUM(quantity) FROM user_military WHERE unit_name='nuclear_sub'", fetchone=True) or [0])[0] or 0
    bot.reply_to(message,
        f"🌍 *Мировая статистика Аурелии:*\n\n"
        f"👥 Правителей: {count}\n"
        f"💰 Денег в мире: {money:,}💰\n"
        f"🪖 Войск: {troops:,}\n"
        f"🎺 Средняя мораль: {avg_morale:.0f}%\n"
        f"🔬 ОЭ: {ep:,}\n"
        f"🛢️ Нефти: {oil:.1f}\n"
        f"⚛️ АЭС в мире: {nps_count}\n"
        f"☢️ Баллистических ракет: {int(missiles or 0)}\n"
        f"☢️ Атомных подлодок: {int(nucsubs or 0)}\n"
        f"🤝 Открытых сделок: {trades}",
        parse_mode="Markdown")

# ==============================================================
# --- ADMIN ---
# ==============================================================
@bot.message_handler(commands=['adminhelp'])
@admin_only
def cmd_adminhelp(message):
    bot.reply_to(message,
        "🔧 *Команды администратора:*\n\n"
        "💰 /givemoney @u сумма\n"
        "💰 /takemoney @u сумма\n"
        "🔬 /giveep @u кол-во\n"
        "📦 /giveitem @u актив кол-во\n"
        "📦 /takeitem @u актив кол-во\n"
        "🛢️ /giveextractor @u кол-во\n"
        "🛢️ /takeextractor @u кол-во\n"
        "⛏️ /givebuilding @u [gold|steel|coal|aur] кол-во\n"
        "⛏️ /takebuilding @u [gold|steel|coal|aur] кол-во\n"
        "⚔️ /givemilitary @u тип кол-во\n"
        "📈 /setlevel @u уровень\n"
        "🪖 /settroops @u кол-во\n"
        "🎺 /setmorale @u процент\n"
        "🔬 /settech @u тех уровень\n"
        "🚫 /banuser @u | /unbanuser @u\n"
        "🗑️ /wipeuser @u\n"
        "📋 /playerinfo @u\n"
        "📊 /setprice актив цена\n"
        "📊 /setbaseprice актив цена\n"
        "⚡ /marketevent актив %\n"
        "📉 /marketcrash | 📈 /marketboom | 🔄 /resetmarket\n"
        "🤝 /canceltrade ID\n"
        "📢 /broadcast текст\n"
        "📢 /announcement текст\n\n"
        "*Активы:* oil gold steel aur food coal\n"
        "*Техника:* rifle machinegun mortar apc tank\n"
        "artillery aa\\_gun mlrs missile\n"
        "plane bomber helicopter bomb\n"
        "corvette ship submarine cruiser carrier nuclear\\_sub",
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
    bot.reply_to(message, f"✅ @{t[1]} +{a}ОЭ🔬")

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
    bot.reply_to(message, f"✅ @{t[1]} +{a}x{asset}")

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
    db_query("UPDATE user_portfolio SET quantity=MAX(0,quantity-?) WHERE user_id=? AND asset_name=?",
             (a, t[0], asset))
    bot.reply_to(message, f"✅ @{t[1]} -{a}x{asset}")

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
    bot.reply_to(message, f"✅ @{t[1]} +{a}🛢️качек")

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
    bot.reply_to(message, f"✅ @{t[1]} -{a}🛢️качек")

@bot.message_handler(commands=['givebuilding'])
@admin_only
def cmd_givebuilding(message):
    """Выдать ресурсное здание: /givebuilding @user [gold|steel|coal|aur] кол-во"""
    args = message.text.split()
    if len(args) != 4: return bot.reply_to(message, "/givebuilding @user [gold|steel|coal|aur] кол-во")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    res = args[2].lower()
    if res not in RESOURCE_BUILDINGS:
        return bot.reply_to(message, f"Ресурс '{res}' не поддерживается. Доступно: {', '.join(RESOURCE_BUILDINGS.keys())}")
    try: a = int(args[3])
    except: return bot.reply_to(message, "Количество - число.")
    emoji, name, _, _ = RESOURCE_BUILDINGS[res]
    e = db_query("SELECT quantity FROM user_resource_buildings WHERE user_id=? AND resource=?", (t[0],res), fetchone=True)
    if e:
        db_query("UPDATE user_resource_buildings SET quantity=quantity+? WHERE user_id=? AND resource=?", (a,t[0],res))
    else:
        db_query("INSERT INTO user_resource_buildings VALUES (?,?,?,?)", (t[0],res,a,0))
    bot.reply_to(message, f"✅ @{t[1]} +{a}x {emoji}{name}")

@bot.message_handler(commands=['takebuilding'])
@admin_only
def cmd_takebuilding(message):
    """Забрать ресурсное здание: /takebuilding @user [gold|steel|coal|aur] кол-во"""
    args = message.text.split()
    if len(args) != 4: return bot.reply_to(message, "/takebuilding @user [gold|steel|coal|aur] кол-во")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    res = args[2].lower()
    if res not in RESOURCE_BUILDINGS:
        return bot.reply_to(message, f"Ресурс '{res}' не поддерживается.")
    try: a = int(args[3])
    except: return bot.reply_to(message, "Количество - число.")
    emoji, name, _, _ = RESOURCE_BUILDINGS[res]
    db_query("UPDATE user_resource_buildings SET quantity=MAX(0,quantity-?) WHERE user_id=? AND resource=?",
             (a, t[0], res))
    bot.reply_to(message, f"✅ @{t[1]} -{a}x {emoji}{name}")

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
    e = db_query("SELECT quantity FROM user_military WHERE user_id=? AND unit_name=?", (t[0],unit), fetchone=True)
    if e: db_query("UPDATE user_military SET quantity=quantity+? WHERE user_id=? AND unit_name=?", (a,t[0],unit))
    else: db_query("INSERT INTO user_military VALUES (?,?,?)", (t[0],unit,a))
    bot.reply_to(message, f"✅ @{t[1]} +{a}x{un[0]}")

@bot.message_handler(commands=['setlevel'])
@admin_only
def cmd_setlevel(message):
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "/setlevel @user уровень")
    t = find_user(args[1])
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
    if len(args) != 3: return bot.reply_to(message, "/setmorale @user процент (1-100)")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    try: val = int(args[2])
    except: return bot.reply_to(message, "Процент - число.")
    val = max(1, min(100, val))
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
    e = db_query("SELECT level FROM user_tech WHERE user_id=? AND tech_name=?", (t[0],tech), fetchone=True)
    if e: db_query("UPDATE user_tech SET level=? WHERE user_id=? AND tech_name=?", (lv,t[0],tech))
    else: db_query("INSERT INTO user_tech VALUES (?,?,?)", (t[0],tech,lv))
    bot.reply_to(message, f"✅ @{t[1]} {td[0]} - Ур.{lv}")

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
    for tbl in ['user_businesses','user_portfolio','user_military','user_tech','user_extractors']:
        db_query(f"DELETE FROM {tbl} WHERE user_id=?", (tid,))
    bot.reply_to(message, f"✅ @{t[1]} полностью сброшен.")

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
        f"ID:`{uid}` | Бан:{'Да' if user[4] else 'Нет'}\n"
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
    bot.reply_to(message, f"✅ {asset} - {p:.2f}💰")

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
    bot.reply_to(message, f"✅ {asset} базовая - {p:.2f}💰")

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
    new_p = round(max(0.01, old*(1+pct/100)), 2)
    db_query("UPDATE market_assets SET price=?,last_updated=? WHERE name=?", (new_p, time.time(), asset))
    arr = "📈" if pct >= 0 else "📉"
    bot.reply_to(message,
        f"⚡ *{arr} {disp}*: {old:.2f} -> *{new_p:.2f}* ({'+' if pct>=0 else ''}{pct:.1f}%)",
        parse_mode="Markdown")

@bot.message_handler(commands=['marketcrash'])
@admin_only
def cmd_marketcrash(message):
    assets = db_query("SELECT name,display_name,price FROM market_assets")
    text = "🔴 *ОБВАЛ РЫНКА!*\n\n"
    for name, disp, price in assets:
        drop = random.uniform(0.20, 0.50)
        new = round(price*(1-drop), 2)
        db_query("UPDATE market_assets SET price=?,last_updated=? WHERE name=?", (new,time.time(),name))
        text += f"📉 {disp}: {price:.2f} -> *{new:.2f}* (-{drop*100:.1f}%)\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['marketboom'])
@admin_only
def cmd_marketboom(message):
    assets = db_query("SELECT name,display_name,price FROM market_assets")
    text = "🟢 *БУМ НА РЫНКЕ!*\n\n"
    for name, disp, price in assets:
        rise = random.uniform(0.20, 0.50)
        new = round(price*(1+rise), 2)
        db_query("UPDATE market_assets SET price=?,last_updated=? WHERE name=?", (new,time.time(),name))
        text += f"📈 {disp}: {price:.2f} -> *{new:.2f}* (+{rise*100:.1f}%)\n"
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
    text = f"📢 *Объявление от Администрации:*\n\n{args[1]}"
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
print("🌍 Aurelia Bot v4 запущен!")
bot.polling(none_stop=True)        last_extract REAL DEFAULT 0,
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
        user_id INTEGER, event_type TEXT, description TEXT,
        created_at REAL DEFAULT 0
    )''')

    conn.commit()

    # --- Бизнесы (без порта, цены x2) ---
    # oil_per_unit и coal_per_unit - расход топлива каждые 3 часа на ЕДИНИЦУ техники
    businesses = [
        ('farm',      '🌾 Ферма',        4000,  40,  'Надежный базовый доход',          0),
        ('factory',   '🏭 Завод',        10000, 120, 'Производство товаров + ОЭ',       50),
        ('mine',      '⛏️ Шахта',        16000, 220, 'Добыча ресурсов + ОЭ',           50),
        ('casino',    '🎰 Казино',       30000, 450, 'Большой доход, большие вложения', 20),
        ('bank_biz',  '🏦 Частный банк', 60000, 950, 'Максимальный пассивный доход',    30),
        ('lab',       '🔬 Лаборатория',  45000, 300, 'Исследования: много ОЭ',         100),
    ]
    c.executemany('INSERT OR IGNORE INTO business_types VALUES (?,?,?,?,?,?)', businesses)
    for name, _, _, _, _, ep in businesses:
        c.execute("UPDATE business_types SET ep_per_12h=? WHERE name=?", (ep, name))

    # --- Активы ---
    assets = [
        ('oil',   '🛢️ Нефть',            100.0, 100.0, '🛢️'),
        ('gold',  '🥇 Золото',           500.0, 500.0, '🥇'),
        ('steel', '⚙️ Сталь',             80.0,  80.0, '⚙️'),
        ('aur',   '💎 Аурит',            300.0, 300.0, '💎'),
        ('food',  '🌽 Продовольствие',    50.0,  50.0, '🌽'),
        ('coal',  '🪨 Уголь',             60.0,  60.0, '🪨'),
    ]
    c.executemany(
        'INSERT OR IGNORE INTO market_assets (name,display_name,price,base_price,emoji) VALUES (?,?,?,?,?)',
        assets)

    # --- Военная техника эпохи 1960-х ---
    # (name, display, steel, money, desc, power, category, oil_per_unit/3h, coal_per_unit/3h)
    # oil_per_unit: нефть на 1 единицу за 3 часа
    # coal_per_unit: уголь на 1 единицу за 3 часа
    military = [
        # Наземные - не тратят топливо (только деньги на содержание)
        ('rifle',      '🔫 Винтовки',         2,    200,    'Базовое вооружение пехоты',       1,   'ground', 0,      0),
        ('machinegun', '🔥 Пулемёты',         5,    500,    'Пулемётная поддержка пехоты',     3,   'ground', 0,      0),
        ('mortar',     '💣 Миномёты',         15,   2000,   'Полевая огневая поддержка',       8,   'ground', 0,      0),
        ('apc',        '🚗 БТР',              25,   4000,   'Бронетранспортёр для пехоты',     20,  'ground', 0,      0),
        ('tank',       '🛡️ Танки',            50,   10000,  'Основная боевая машина',          50,  'ground', 0.002,  0),
        ('artillery',  '💥 Артиллерия',       80,   16000,  'Дальнобойная огневая поддержка',  40,  'ground', 0,      0),
        ('aa_gun',     '🎯 ПВО',              60,   14000,  'Зенитные орудия и ракеты',        30,  'ground', 0,      0),
        ('mlrs',       '🚀 РСЗО',             120,  25000,  'Реактивная система залпового огня', 80, 'ground', 0,      0),
        ('missile',    '☢️ Баллистические ракеты', 200, 50000, 'Стратегические и тактические ракеты', 150, 'ground', 0, 0),
        # Авиация - тратят нефть
        ('plane',      '✈️ Истребители',      120,  30000,  'Реактивные истребители-перехватчики', 80, 'air',   0.003,  0),
        ('bomber',     '💣 Бомбардировщики',  180,  50000,  'Стратегические бомбардировщики',  100, 'air',    0.005,  0),
        ('helicopter', '🚁 Вертолёты',        80,   20000,  'Военные вертолёты поддержки',     50,  'air',    0.002,  0),
        ('bomb',       '💥 Авиабомбы',        20,   3000,   'Боеприпасы для авиации',         5,   'air',    0,      0),
        # Флот - тратит уголь
        ('corvette',   '🚤 Корветы',          80,   15000,  'Легкие боевые корабли',          40,  'navy',   0,      0.003),
        ('ship',       '🚢 Эсминцы',          200,  50000,  'Основа военно-морского флота',   120, 'navy',   0,      0.008),
        ('submarine',  '🛥️ Подлодки',         150,  40000,  'Скрытые морские удары',          100, 'navy',   0,      0.005),
        ('cruiser',    '⛵ Крейсеры',         400,  90000,  'Тяжелые боевые корабли',         250, 'navy',   0,      0.015),
        ('carrier',    '⛴️ Авианосцы',        1000, 300000, 'Господство в океане',            500, 'navy',   0,      0.05),
        ('nuclear_sub','☢️ Атомные подлодки', 2000, 600000, 'Ядерное сдерживание на море',    1000,'navy',   0,      0.02),
    ]
    c.executemany('INSERT OR IGNORE INTO military_types VALUES (?,?,?,?,?,?,?,?,?)', military)
    for row in military:
        c.execute("UPDATE military_types SET power_value=?,category=?,oil_per_unit=?,coal_per_unit=? WHERE name=?",
                  (row[5], row[6], row[7], row[8], row[0]))

    # --- Технологии ---
    techs = [
        ('finance',    '💹 Финансы',          5, 300,  '+10% к доходу /cash за уровень',          '+10%cash'),
        ('logistics',  '🚛 Логистика',        5, 450,  '-10% к содержанию армии за уровень',      '-10%maint'),
        ('metallurgy', '🔩 Металлургия',       5, 600,  '-8% к расходу Стали при крафте',          '-8%steel'),
        ('engineering','⚙️ Инженерия',        5, 600,  '-8% к денежному расходу при крафте',      '-8%money'),
        ('military_sc','🎖️ Военная наука',    5, 750,  '+15% к боевой мощи за уровень',           '+15%power'),
        ('industry',   '🏗️ Индустриализация', 5, 540,  '+20% к генерации ОЭ за уровень',          '+20%EP'),
        ('energy',     '⚡ Энергетика',       5, 660,  '-10% к расходу топлива за уровень',       '-10%fuel'),
        ('trading',    '🤝 Торговля',         3, 450,  '-1% комиссия на бирже за уровень',         '-1%fee'),
        ('espionage',  '🕵️ Разведка',         3, 900,  'Расширенные возможности разведки',        'spy'),
        ('naval',      '⚓ Морское дело',      5, 750,  '+20% к мощи флота за уровень',            '+20%navy'),
        ('morale_tech','🎺 Политработа',      5, 540,  '+5% морали за уровень, -5% дезертирства', '+morale'),
    ]
    c.executemany('INSERT OR IGNORE INTO tech_types VALUES (?,?,?,?,?,?)', techs)

    # Обновить цены технологий если они изменились
    for row in techs:
        c.execute("UPDATE tech_types SET ep_cost_per_level=? WHERE name=?", (row[3], row[0]))

    conn.commit()
    conn.close()

init_db()

# Требования технологий для производства юнитов
# формат: unit_name -> [(tech_name, min_level), ...]
UNIT_TECH_REQUIREMENTS = {
    'artillery':  [('military_sc', 1)],
    'aa_gun':     [('military_sc', 1)],
    'mlrs':       [('military_sc', 2)],
    'missile':    [('military_sc', 4)],
    'bomber':     [('military_sc', 1)],
    'submarine':  [('naval', 2)],
    'cruiser':    [('naval', 3)],
    'carrier':    [('naval', 4)],
    'nuclear_sub':[('naval', 5), ('military_sc', 3)],
}

# Конфигурация ресурсных зданий
# resource -> (emoji, display_name, yield_per_building, cooldown_seconds)
RESOURCE_BUILDINGS = {
    'gold':  ('🥇', 'Золотой рудник',       1, 14400),  # 4ч
    'steel': ('⚙️', 'Сталелитейный завод',  2, 10800),  # 3ч
    'coal':  ('🪨', 'Угольная шахта',        3, 7200),   # 2ч
    'aur':   ('💎', 'Аурит-шахта',           1, 21600),  # 6ч
}

# ==============================================================
# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
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

def is_admin(uid): return uid in ADMIN_IDS
def is_banned(uid):
    r = db_query("SELECT banned FROM users WHERE user_id=?", (uid,), fetchone=True)
    return r and r[0] == 1

def get_tech(uid, name):
    r = db_query("SELECT level FROM user_tech WHERE user_id=? AND tech_name=?", (uid,name), fetchone=True)
    return r[0] if r else 0

def get_price_arrow(price, base):
    if price > base * 1.1: return "📈"
    elif price < base * 0.9: return "📉"
    return "➡️"

def calc_power(uid):
    units = db_query('''SELECT um.unit_name, um.quantity, mt.power_value, mt.category
                        FROM user_military um JOIN military_types mt ON um.unit_name=mt.name
                        WHERE um.user_id=? AND um.quantity>0''', (uid,))
    troops = (db_query("SELECT troops FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    morale = (db_query("SELECT morale FROM users WHERE user_id=?", (uid,), fetchone=True) or [100])[0]
    morale_mult = max(0.1, morale / 100)
    power = troops
    naval_bonus = 1 + get_tech(uid, 'naval') * 0.20
    for _, qty, pv, cat in (units or []):
        b = naval_bonus if cat == 'navy' else 1.0
        power += int(qty * pv * b)
    mil_bonus = 1 + get_tech(uid, 'military_sc') * 0.15
    return int(power * mil_bonus * morale_mult)

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
    e = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?",
                 (uid, asset_name), fetchone=True)
    if e:
        db_query("UPDATE user_portfolio SET quantity=quantity+? WHERE user_id=? AND asset_name=?",
                 (amount, uid, asset_name))
    else:
        db_query("INSERT INTO user_portfolio VALUES (?,?,?,?)", (uid, asset_name, amount, 0))

GROUND = {'rifle','machinegun','mortar','apc','tank','artillery','aa_gun','mlrs','missile'}
AIR    = {'plane','bomber','helicopter','bomb'}
NAVY   = {'corvette','ship','submarine','cruiser','carrier','nuclear_sub'}

# ==============================================================
# --- ФОНОВЫЕ ПОТОКИ ---
# ==============================================================
def market_updater():
    while True:
        time.sleep(3600)
        for name, price, base in db_query("SELECT name,price,base_price FROM market_assets"):
            change = random.uniform(-0.20, 0.20)
            new_p = max(base*0.4, min(base*2.5, price*(1+change)))
            db_query("UPDATE market_assets SET price=?,last_updated=? WHERE name=?",
                     (round(new_p,2), time.time(), name))

def passive_income():
    while True:
        time.sleep(600)
        rows = db_query('''SELECT ub.user_id, SUM(ub.quantity*bt.income_per_hour)
                           FROM user_businesses ub
                           JOIN business_types bt ON ub.business_name=bt.name
                           GROUP BY ub.user_id''')
        for uid, total in (rows or []):
            income = int(total * (600/3600))
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
                base_gain = ep_map[uid] * bonus
                # Случайное отклонение ±10%
                gain = int(base_gain * random.uniform(0.90, 1.10))
                if gain > 0:
                    db_query("UPDATE users SET ep=ep+?, last_ep=? WHERE user_id=?", (gain, now, uid))

def army_upkeep():
    """
    Каждый час:
    - Содержание пехоты: каждые 5 солдат = 1 /ч
    - Прогрессивный налог на богатство (с 50к)
    - Дезертирство при нехватке денег на содержание
    - Падение морали при дезертирстве
    Каждые 3 часа:
    - Расход нефти: танки + авиация
    - Расход угля: флот
    """
    fuel_acc = {}   # накопитель для дробного расхода топлива
    tick = 0
    while True:
        time.sleep(3600)
        tick += 1

        users = db_query("SELECT user_id,troops,balance,morale FROM users WHERE banned=0")
        for uid, troops, bal, morale in (users or []):
            morale = morale or 100

            # Содержание пехоты
            logi = get_tech(uid, 'logistics')
            reduction = max(0.1, 1 - logi * 0.10)
            maint = int((troops / 5) * reduction)

            # Прогрессивный налог (начинается с 50к)
            if   bal >= 2_000_000: tax = int(bal * 0.03)
            elif bal >= 500_000:   tax = int(bal * 0.02)
            elif bal >= 50_000:    tax = int(bal * 0.01)
            else:                  tax = 0

            total_deduct = maint + tax

            if total_deduct == 0:
                continue

            if bal >= total_deduct:
                db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (total_deduct, uid))
            else:
                # Не хватает денег - дезертирство
                unpaid_maint = max(0, maint - bal)
                db_query("UPDATE users SET balance=0 WHERE user_id=?", (uid,))

                if troops > 0 and unpaid_maint > 0:
                    morale_tech = get_tech(uid, 'morale_tech')
                    # Базовое дезертирство 3%/ч, снижается технологией
                    base_rate = max(0.005, 0.03 - morale_tech * 0.005)
                    # Чем ниже мораль, тем больше дезертирство
                    morale_factor = max(1.0, (100 - morale) / 50 + 1)
                    rate = min(0.15, base_rate * morale_factor)
                    lost = max(10, int(troops * rate))
                    lost = min(lost, troops)

                    db_query("UPDATE users SET troops=MAX(0,troops-?) WHERE user_id=?", (lost, uid))
                    # Мораль падает
                    morale_drop = random.randint(3, 8)
                    new_morale = max(10, morale - morale_drop)
                    db_query("UPDATE users SET morale=? WHERE user_id=?", (new_morale, uid))
                    log_event(uid, 'desertion',
                              f"Дезертировало {lost} солдат (нет денег на содержание). Мораль: {new_morale}")

            # Восстановление морали при достатке
            if bal >= total_deduct * 2 and morale < 100:
                recovery = random.randint(1, 3) + get_tech(uid, 'morale_tech')
                new_morale = min(100, morale + recovery)
                db_query("UPDATE users SET morale=? WHERE user_id=?", (new_morale, uid))

        # --- Расход топлива каждые 3 часа ---
        if tick % 3 == 0:
            energy_units = db_query('''SELECT user_id, unit_name, quantity, oil_per_unit, coal_per_unit
                                       FROM user_military um
                                       JOIN military_types mt ON um.unit_name=mt.name
                                       WHERE (mt.oil_per_unit > 0 OR mt.coal_per_unit > 0) AND um.quantity > 0''')

            # Группируем расход по пользователям
            fuel_needs = {}
            for uid, unit_name, qty, oil_pu, coal_pu in (energy_units or []):
                if uid not in fuel_needs:
                    fuel_needs[uid] = {'oil': 0.0, 'coal': 0.0}
                energy_tech = get_tech(uid, 'energy')
                fuel_mult = max(0.1, 1 - energy_tech * 0.10)
                fuel_needs[uid]['oil']  += oil_pu  * qty * fuel_mult
                fuel_needs[uid]['coal'] += coal_pu * qty * fuel_mult

            for uid, needs in fuel_needs.items():
                if uid not in fuel_acc:
                    fuel_acc[uid] = {'oil': 0.0, 'coal': 0.0}

                for res in ('oil', 'coal'):
                    fuel_acc[uid][res] += needs[res]
                    to_ded = int(fuel_acc[uid][res])
                    if to_ded > 0:
                        fuel_acc[uid][res] -= to_ded
                        row = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?",
                                       (uid, res), fetchone=True)
                        current = row[0] if row else 0
                        actual = min(to_ded, int(current))
                        if actual > 0:
                            db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name=?",
                                     (actual, uid, res))
                        # Если нефти/угля нет и есть авиация/флот, падает мораль
                        if actual < to_ded:
                            morale_row = db_query("SELECT morale FROM users WHERE user_id=?", (uid,), fetchone=True)
                            if morale_row:
                                new_morale = max(20, (morale_row[0] or 100) - random.randint(1, 3))
                                db_query("UPDATE users SET morale=? WHERE user_id=?", (new_morale, uid))

def food_consumption():
    """
    Каждые 6 часов войска потребляют продовольствие.
    Нехватка еды - падение морали и небольшое дезертирство.
    """
    while True:
        time.sleep(21600)
        users = db_query("SELECT user_id, troops, morale FROM users WHERE troops > 0 AND banned=0")
        for uid, troops, morale in (users or []):
            morale = morale or 100
            # 1 еда на 1000 солдат каждые 6 часов
            food_needed = max(1, troops // 1000)
            food_row = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name='food'",
                                (uid,), fetchone=True)
            food_have = int(food_row[0]) if food_row else 0

            if food_have >= food_needed:
                db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name='food'",
                         (food_needed, uid))
                # Мораль немного растет при наличии еды
                if morale < 100:
                    db_query("UPDATE users SET morale=MIN(100,morale+1) WHERE user_id=?", (uid,))
            else:
                # Нет еды - мораль падает, небольшое дезертирство
                if food_have > 0:
                    db_query("DELETE FROM user_portfolio WHERE user_id=? AND asset_name='food'", (uid,))
                morale_drop = random.randint(2, 5)
                new_morale = max(5, morale - morale_drop)
                db_query("UPDATE users SET morale=? WHERE user_id=?", (new_morale, uid))

                if troops > 0:
                    hunger_desertion = max(5, int(troops * 0.01))
                    db_query("UPDATE users SET troops=MAX(0,troops-?) WHERE user_id=?", (hunger_desertion, uid))
                    log_event(uid, 'hunger', f"Нехватка продовольствия! -{hunger_desertion} солдат, мораль: {new_morale}")

for fn in [market_updater, passive_income, ep_gen, army_upkeep, food_consumption]:
    threading.Thread(target=fn, daemon=True).start()

# ==============================================================
# --- ОСНОВНЫЕ КОМАНДЫ ---
# ==============================================================

@bot.message_handler(commands=['start'])
@group_only
def cmd_start(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return bot.reply_to(message, "Вы заблокированы.")
    bot.reply_to(message,
        "🌍 *Добро пожаловать в Аурелию!*\n\n"
        "💰 Стартовый капитал: 1000\n\n"
        "📋 *Базовые:*\n"
        "/profile - профиль и статус\n"
        "/cash - сбор налогов (30 мин)\n"
        "/upgrade - улучшить экономику\n"
        "/pay @user сумма - перевод\n"
        "/senditem @user актив кол-во\n\n"
        "🏢 *Бизнес:* /shop /buybiz /mybiz\n"
        "📊 *Биржа:* /market /buy /sell /portfolio\n\n"
        "⚔️ *Армия эпохи 60-х:*\n"
        "/draft - призыв войск (2ч)\n"
        "/craft - производство техники\n"
        "/army - состав и расходы армии\n"
        "/giftunit @user тип кол-во - подарить оружие\n"
        "/morale - текущая мораль армии\n\n"
        "🤝 *Торговля:*\n"
        "/trade - создать предложение\n"
        "/trades - открытые сделки\n"
        "/accept ID - принять сделку\n"
        "/canceltrade ID - отменить сделку\n\n"
        "🛢️ /extractoil - добыть нефть\n"
        "⛏️ /extract [gold|steel|coal|aur] - добыть ресурс\n"
        "🔬 /tech | /researchtech\n"
        "📋 /events - последние события\n"
        "🏆 /top | /toparmy | /worldstats",
        parse_mode="Markdown")

@bot.message_handler(commands=['profile'])
@group_only
def cmd_profile(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    user = db_query("SELECT balance,level,troops,ep,morale FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return bot.reply_to(message, "Введите /start")
    bal, lv, troops, ep, morale = user
    morale = morale or 100
    iph = (db_query('''SELECT SUM(ub.quantity*bt.income_per_hour) FROM user_businesses ub
                        JOIN business_types bt ON ub.business_name=bt.name WHERE ub.user_id=?''',
                    (uid,), fetchone=True) or [0])[0] or 0
    ext = (db_query("SELECT quantity FROM user_extractors WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    power = calc_power(uid)
    if bal >= 2_000_000:   tax_str = "3%/ч 🔴"
    elif bal >= 500_000:   tax_str = "2%/ч 🟠"
    elif bal >= 50_000:    tax_str = "1%/ч 🟡"
    else:                  tax_str = "нет ✅"

    if morale >= 80:   morale_str = f"{morale}% 💚"
    elif morale >= 50: morale_str = f"{morale}% 🟡"
    elif morale >= 25: morale_str = f"{morale}% 🟠 (угроза дезертирства)"
    else:              morale_str = f"{morale}% 🔴 (КРИЗИС)"

    bot.reply_to(message,
        f"👤 *@{uname}*\n\n"
        f"💰 Баланс: {bal:,}\n"
        f"💸 Налог: {tax_str}\n"
        f"📈 Уровень экономики: {lv}\n"
        f"🪖 Пехота: {troops:,}\n"
        f"🎺 Мораль армии: {morale_str}\n"
        f"⚔️ Военная мощь: {power:,}\n"
        f"🏭 Пассивный доход: ~{iph} 💰/ч\n"
        f"🔬 ОЭ: {ep}\n"
        f"🛢️ Нефтекачек: {ext}\n\n"
        f"Мораль влияет на военную мощь!",
        parse_mode="Markdown")

@bot.message_handler(commands=['morale'])
@group_only
def cmd_morale(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    user = db_query("SELECT morale, troops, balance FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return bot.reply_to(message, "Введите /start")
    morale, troops, bal = user
    morale = morale or 100
    logi = get_tech(uid, 'logistics')
    maint = int((troops / 5) * max(0.1, 1 - logi * 0.10))

    if   morale >= 90: status = "Элитный дух - армия непобедима 💚"
    elif morale >= 70: status = "Высокий дух - хорошая боеспособность 🟢"
    elif morale >= 50: status = "Нормальный дух 🟡"
    elif morale >= 30: status = "Низкий дух - начинается дезертирство 🟠"
    elif morale >= 15: status = "Кризис морали - массовое дезертирство 🔴"
    else:              status = "Коллапс - армия распадается ☠️"

    morale_tech = get_tech(uid, 'morale_tech')
    desertion_rate = max(0.5, 3.0 - morale_tech * 0.5)

    text = (
        f"🎺 *Состояние вашей армии:*\n\n"
        f"Мораль: *{morale}%*\n"
        f"Статус: {status}\n\n"
        f"🪖 Пехота: {troops:,}\n"
        f"💸 Содержание: ~{maint} 💰/ч\n"
        f"💰 Ваш баланс: {bal:,}\n\n"
        f"*Как поднять мораль:*\n"
        f"- Платить за содержание армии\n"
        f"- Снабжать едой (/buy food)\n"
        f"- Технология Политработа (/tech)\n"
        f"  Текущий уровень: {morale_tech}/5\n\n"
        f"*При нехватке денег:* -{desertion_rate:.1f}% войск/ч"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['events'])
@group_only
def cmd_events(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    rows = db_query('''SELECT event_type, description, created_at FROM event_log
                       WHERE user_id=? ORDER BY created_at DESC LIMIT 10''', (uid,))
    if not rows:
        return bot.reply_to(message, "У вас нет зарегистрированных событий.")
    text = "📋 *Последние события:*\n\n"
    for etype, desc, ts in rows:
        dt = time.strftime('%d.%m %H:%M', time.localtime(ts))
        icon = {'desertion': '🏃', 'hunger': '🍽️', 'crisis': '💥'}.get(etype, '📌')
        text += f"{icon} [{dt}] {desc}\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['cash'])
@group_only
def cmd_cash(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    user = db_query("SELECT balance,level,last_cash FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return bot.reply_to(message, "Введите /start")
    bal, lv, last = user
    now = time.time()
    if now - (last or 0) < 1800:
        left = int(1800 - (now - last))
        return bot.reply_to(message, f"Казна пуста. Через {left//60} мин. {left%60} сек.")
    earned = int(500 * (1 + lv*0.2) * (1 + get_tech(uid,'finance')*0.10) * random.uniform(0.8, 1.2))
    db_query("UPDATE users SET balance=balance+?, last_cash=? WHERE user_id=?", (earned, now, uid))
    bot.reply_to(message, f"💵 Налоги: *+{earned}* 💰\nБаланс: {bal+earned:,}", parse_mode="Markdown")

@bot.message_handler(commands=['upgrade'])
@group_only
def cmd_upgrade(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    user = db_query("SELECT balance,level FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return bot.reply_to(message, "Введите /start")
    bal, lv = user
    cost = lv * 3000
    if bal < cost: return bot.reply_to(message, f"Нужно {cost:,} 💰, у вас {bal:,}")
    db_query("UPDATE users SET balance=balance-?, level=level+1 WHERE user_id=?", (cost, uid))
    bot.reply_to(message, f"✅ Экономика - уровень *{lv+1}* за {cost:,} 💰!", parse_mode="Markdown")

# --- Нефтедобыча ---
@bot.message_handler(commands=['extractoil'])
@group_only
def cmd_extractoil(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    ext = db_query("SELECT quantity,last_extract FROM user_extractors WHERE user_id=?", (uid,), fetchone=True)
    if not ext or ext[0] <= 0:
        return bot.reply_to(message, "В вашей стране нет источника нефти.")
    qty, last = ext
    now = time.time()
    if now - (last or 0) < 3600:
        left = int(3600 - (now - last))
        return bot.reply_to(message, f"Следующая добыча через {left//60} мин. {left%60} сек.")
    db_query("UPDATE user_extractors SET last_extract=? WHERE user_id=?", (now, uid))
    add_asset(uid, 'oil', qty)
    total = (db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name='oil'",
                      (uid,), fetchone=True) or [0])[0]
    bot.reply_to(message,
        f"🛢️ Добыто *{qty}* нефти ({qty} качек x 1)\nВсего нефти: {total:.1f}",
        parse_mode="Markdown")

@bot.message_handler(commands=['extract'])
@group_only
def cmd_extract(message):
    """Добыча ресурсов из зданий: /extract gold|steel|coal|aur"""
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()

    if len(args) < 2:
        text = "⛏️ *Добыча ресурсов:*\n\n"
        for res, (emoji, name, yld, cd) in RESOURCE_BUILDINGS.items():
            row = db_query("SELECT quantity,last_extract FROM user_resource_buildings WHERE user_id=? AND resource=?",
                           (uid, res), fetchone=True)
            qty = row[0] if row else 0
            last = row[1] if row else 0
            now = time.time()
            if qty > 0:
                if now - (last or 0) < cd:
                    left = int(cd - (now - last))
                    cd_str = f"{left//3600}ч {(left%3600)//60}м" if left >= 3600 else f"{left//60}м {left%60}с"
                    ready = f"готово через {cd_str}"
                else:
                    ready = f"✅ готово! +{qty*yld} {emoji}"
                text += f"{emoji} *{name}*: {qty} шт. - {ready}\n"
            else:
                text += f"{emoji} *{name}* (`/extract {res}`): нет зданий\n"
        text += "\nИспользование: `/extract [ресурс]`"
        return bot.reply_to(message, text, parse_mode="Markdown")

    res = args[1].lower()
    if res not in RESOURCE_BUILDINGS:
        return bot.reply_to(message,
            f"Неизвестный ресурс. Доступно: {', '.join(RESOURCE_BUILDINGS.keys())}")

    emoji, name, yld, cd = RESOURCE_BUILDINGS[res]
    row = db_query("SELECT quantity,last_extract FROM user_resource_buildings WHERE user_id=? AND resource=?",
                   (uid, res), fetchone=True)
    if not row or row[0] <= 0:
        return bot.reply_to(message, f"В вашей стране нет источника {name.lower()}.")

    qty, last = row
    now = time.time()
    if now - (last or 0) < cd:
        left = int(cd - (now - last))
        cd_str = f"{left//3600}ч {(left%3600)//60}м" if left >= 3600 else f"{left//60}м {left%60}с"
        return bot.reply_to(message, f"Следующая добыча через {cd_str}.")

    gained = qty * yld
    db_query("UPDATE user_resource_buildings SET last_extract=? WHERE user_id=? AND resource=?",
             (now, uid, res))
    add_asset(uid, res, gained)
    total = (db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?",
                      (uid, res), fetchone=True) or [0])[0]
    bot.reply_to(message,
        f"{emoji} Добыто *{gained}* ({qty} зданий x {yld})\nВсего {name.split()[0].lower()}: {total:.1f}",
        parse_mode="Markdown")

# --- Технологии ---
@bot.message_handler(commands=['tech'])
@group_only
def cmd_tech(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    techs = db_query("SELECT name,display_name,max_level,ep_cost_per_level,description FROM tech_types")
    ep = (db_query("SELECT ep FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    text = f"🔬 *Дерево технологий*\n💡 Ваши ОЭ: {ep}\n\n"
    for name, disp, maxlv, cost, desc in techs:
        lv = get_tech(uid, name)
        status = "✅ МАКС" if lv >= maxlv else f"Ур.{lv}/{maxlv} - {cost} ОЭ"
        text += f"*{disp}* (`{name}`)\n_{desc}_\n{status}\n\n"
    text += "- `/researchtech [название]`"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['researchtech'])
@group_only
def cmd_researchtech(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) < 2: return bot.reply_to(message, "Использование: /researchtech [название]")
    tech_name = args[1].lower()
    tech = db_query("SELECT display_name,max_level,ep_cost_per_level FROM tech_types WHERE name=?",
                    (tech_name,), fetchone=True)
    if not tech: return bot.reply_to(message, f"Технология '{tech_name}' не найдена. /tech")
    disp, maxlv, cost = tech
    lv = get_tech(uid, tech_name)
    if lv >= maxlv: return bot.reply_to(message, f"✅ *{disp}* уже максимальна.", parse_mode="Markdown")
    ep = (db_query("SELECT ep FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    if ep < cost: return bot.reply_to(message, f"Нужно {cost} ОЭ, у вас {ep}")
    db_query("UPDATE users SET ep=ep-? WHERE user_id=?", (cost, uid))
    if lv == 0:
        db_query("INSERT INTO user_tech VALUES (?,?,1)", (uid, tech_name))
    else:
        db_query("UPDATE user_tech SET level=level+1 WHERE user_id=? AND tech_name=?", (uid, tech_name))
    bot.reply_to(message, f"🔬 *{disp}* - Ур. *{lv+1}/{maxlv}*\nПотрачено: {cost} ОЭ",
                 parse_mode="Markdown")

# --- Армия ---
@bot.message_handler(commands=['draft'])
@group_only
def cmd_draft(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    user = db_query("SELECT troops,last_draft,morale FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return bot.reply_to(message, "Введите /start")
    troops, last, morale = user
    now = time.time()
    if now - (last or 0) < 7200:
        left = int(7200 - (now - last))
        return bot.reply_to(message, f"Следующий призыв через {left//3600} ч. {(left%3600)//60} мин.")

    morale = morale or 100
    # Низкая мораль = меньше призывников
    morale_factor = max(0.3, morale / 100)
    base_recruits = random.randint(1000, 2000)
    new_recruits = int(base_recruits * morale_factor)

    db_query("UPDATE users SET troops=troops+?, last_draft=? WHERE user_id=?", (new_recruits, now, uid))
    morale_note = ""
    if morale < 60:
        morale_note = f"\n⚠️ Низкая мораль ({morale}%) сократила призыв!"
    bot.reply_to(message,
        f"🪖 *Призыв!*\n+*{new_recruits}* новобранцев\nВсего: {troops+new_recruits:,}{morale_note}",
        parse_mode="Markdown")

@bot.message_handler(commands=['craft'])
@group_only
def cmd_craft(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()

    if len(args) < 3:
        types = db_query("SELECT name,display_name,steel_cost,money_cost,category,oil_per_unit,coal_per_unit FROM military_types")
        cats = {'ground': '🪖 Наземные силы', 'air': '✈️ Авиация', 'navy': '🚢 Флот'}
        text = "⚙️ *Производство военной техники:* `/craft [тип] [кол-во]`\n\n"
        for ck, cn in cats.items():
            text += f"*{cn}:*\n"
            for name, disp, steel, money, cat, oil_pu, coal_pu in types:
                if cat != ck: continue
                fuel_str = ""
                if oil_pu > 0:  fuel_str = f" | 🛢️{oil_pu}/3ч"
                if coal_pu > 0: fuel_str = f" | 🪨{coal_pu}/3ч"
                req_str = ""
                if name in UNIT_TECH_REQUIREMENTS:
                    reqs = []
                    for tname, tlv in UNIT_TECH_REQUIREMENTS[name]:
                        trow = db_query("SELECT display_name FROM tech_types WHERE name=?", (tname,), fetchone=True)
                        tdisp = trow[0].split()[-1] if trow else tname
                        cur = get_tech(uid, tname)
                        ok = "✅" if cur >= tlv else "❌"
                        reqs.append(f"{ok}{tdisp}Ур.{tlv}")
                    req_str = f" [{', '.join(reqs)}]"
                text += f"  {disp} (`{name}`) - {steel}⚙️ + {money:,}💰{fuel_str}{req_str}\n"
            text += "\n"
        return bot.reply_to(message, text, parse_mode="Markdown")

    unit_name = args[1].lower()
    try: qty = int(args[2])
    except: return bot.reply_to(message, "Количество - число.")
    if qty <= 0: return bot.reply_to(message, "Количество > 0.")
    unit = db_query("SELECT display_name,steel_cost,money_cost FROM military_types WHERE name=?",
                    (unit_name,), fetchone=True)
    if not unit: return bot.reply_to(message, f"Тип '{unit_name}' не найден.")
    disp, steel_c, money_c = unit

    # Проверка требований технологий
    if unit_name in UNIT_TECH_REQUIREMENTS:
        missing = []
        for tech_name, min_lv in UNIT_TECH_REQUIREMENTS[unit_name]:
            cur_lv = get_tech(uid, tech_name)
            if cur_lv < min_lv:
                tech_row = db_query("SELECT display_name FROM tech_types WHERE name=?", (tech_name,), fetchone=True)
                tech_disp = tech_row[0] if tech_row else tech_name
                missing.append(f"{tech_disp} Ур.{min_lv} (у вас: {cur_lv})")
        if missing:
            return bot.reply_to(message,
                f"❌ Для производства *{disp}* нужно:\n" + "\n".join(f"- {m}" for m in missing),
                parse_mode="Markdown")
    total_steel = int(steel_c * qty * max(0.2, 1 - get_tech(uid,'metallurgy')*0.08))
    total_money = int(money_c * qty * max(0.2, 1 - get_tech(uid,'engineering')*0.08))
    bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    sr = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name='steel'",
                  (uid,), fetchone=True)
    cur_steel = int(sr[0]) if sr else 0
    if bal < total_money or cur_steel < total_steel:
        return bot.reply_to(message,
            f"Нужно: {total_steel}⚙️ и {total_money:,}💰\nЕсть: {cur_steel}⚙️ и {bal:,}💰")
    db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (total_money, uid))
    db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name='steel'",
             (total_steel, uid))
    db_query("INSERT INTO user_military VALUES (?,?,?) ON CONFLICT(user_id,unit_name) DO UPDATE SET quantity=quantity+?",
             (uid, unit_name, qty, qty))
    bot.reply_to(message, f"🏭 *{qty}x {disp}* произведено!\n-{total_steel}⚙️ | -{total_money:,}💰",
                 parse_mode="Markdown")

@bot.message_handler(commands=['army'])
@group_only
def cmd_army(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    user = db_query("SELECT troops, morale FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not user: return bot.reply_to(message, "Введите /start")
    troops, morale = user
    morale = morale or 100

    units = db_query('''SELECT u.unit_name, m.display_name, u.quantity, m.category,
                               m.oil_per_unit, m.coal_per_unit
                        FROM user_military u JOIN military_types m ON u.unit_name=m.name
                        WHERE u.user_id=? AND u.quantity>0''', (uid,))
    secs = {'ground':[], 'air':[], 'navy':[]}
    total_oil_3h = 0.0
    total_coal_3h = 0.0
    energy_mult = max(0.1, 1 - get_tech(uid,'energy') * 0.10)

    for uname, disp, qty, cat, oil_pu, coal_pu in (units or []):
        secs.get(cat, secs['ground']).append(f"  {disp}: {qty:,}")
        total_oil_3h  += oil_pu  * qty * energy_mult
        total_coal_3h += coal_pu * qty * energy_mult

    logi = get_tech(uid, 'logistics')
    maint = int((troops/5) * max(0.1, 1 - logi * 0.10))
    power = calc_power(uid)

    text = f"⚔️ *Ваши вооруженные силы:*\n\n"
    text += f"🪖 *Наземные:*\n  Пехота: {troops:,}\n"
    text += ("\n".join(secs['ground'])+"\n") if secs['ground'] else "  Техника отсутствует\n"
    text += "\n✈️ *Авиация:*\n"
    text += ("\n".join(secs['air'])+"\n") if secs['air'] else "  Авиация отсутствует\n"
    text += "\n🚢 *Флот:*\n"
    text += ("\n".join(secs['navy'])+"\n") if secs['navy'] else "  Флот отсутствует\n"
    text += f"\n⚔️ *Мощь: {power:,}*"
    text += f" (мораль: {morale}%)\n"
    text += f"💸 Содержание пехоты: ~{maint} 💰/ч\n"
    if total_oil_3h > 0:
        text += f"🛢️ Расход нефти (авиация+танки): {total_oil_3h:.2f}/3ч\n"
    if total_coal_3h > 0:
        text += f"🪨 Расход угля (флот): {total_coal_3h:.2f}/3ч\n"
    text += "\n💡 /craft - производство | /giftunit - подарить | /morale - мораль"
    bot.reply_to(message, text, parse_mode="Markdown")

# --- Подарить оружие ---
@bot.message_handler(commands=['giftunit'])
@group_only
def cmd_giftunit(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 4:
        return bot.reply_to(message,
            "Использование: `/giftunit @user [тип] [кол-во]`\nПример: `/giftunit @ivan tank 5`",
            parse_mode="Markdown")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, f"{args[1]} не найден.")
    unit_name = args[2].lower()
    try: qty = int(args[3])
    except: return bot.reply_to(message, "Количество - число.")
    if qty <= 0: return bot.reply_to(message, "Количество > 0.")
    if t[0] == uid: return bot.reply_to(message, "Нельзя дарить себе.")
    unit = db_query("SELECT display_name FROM military_types WHERE name=?", (unit_name,), fetchone=True)
    if not unit: return bot.reply_to(message, f"Тип '{unit_name}' не найден. /craft")
    row = db_query("SELECT quantity FROM user_military WHERE user_id=? AND unit_name=?", (uid,unit_name), fetchone=True)
    if not row or row[0] < qty:
        return bot.reply_to(message, f"У вас только {row[0] if row else 0} {unit[0]}")
    db_query("UPDATE user_military SET quantity=quantity-? WHERE user_id=? AND unit_name=?", (qty,uid,unit_name))
    e = db_query("SELECT quantity FROM user_military WHERE user_id=? AND unit_name=?", (t[0],unit_name), fetchone=True)
    if e:
        db_query("UPDATE user_military SET quantity=quantity+? WHERE user_id=? AND unit_name=?", (qty,t[0],unit_name))
    else:
        db_query("INSERT INTO user_military VALUES (?,?,?)", (t[0],unit_name,qty))
    bot.reply_to(message, f"🎁 *{qty}x {unit[0]}* подарено @{t[1]}!", parse_mode="Markdown")

# ==============================================================
# --- ТОРГОВАЯ СИСТЕМА ---
# ==============================================================
@bot.message_handler(commands=['trade'])
@group_only
def cmd_trade(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 7:
        return bot.reply_to(message,
            "📋 *Создать торговое предложение:*\n"
            "`/trade [тип] [что] [кол-во] [тип] [что] [кол-во]`\n\n"
            "*Типы:* `money` или `asset`\n"
            "*Активы:* oil gold steel aur food coal\n\n"
            "*Примеры:*\n"
            "`/trade asset steel 50 money money 5000`\n"
            "`/trade money money 10000 asset gold 15`\n"
            "`/trade asset oil 20 asset steel 100`",
            parse_mode="Markdown")
    _, ot, on, oq_s, wt, wn, wq_s = args
    ot = ot.lower(); wt = wt.lower()
    try: oq = float(oq_s); wq = float(wq_s)
    except: return bot.reply_to(message, "Количество - число.")
    if oq <= 0 or wq <= 0: return bot.reply_to(message, "Количество > 0.")

    if ot == 'money':
        on = 'money'
        bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
        if bal < int(oq): return bot.reply_to(message, f"Нужно {int(oq):,} 💰, у вас {bal:,}")
        db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (int(oq), uid))
    elif ot == 'asset':
        on = on.lower()
        if not db_query("SELECT name FROM market_assets WHERE name=?", (on,), fetchone=True):
            return bot.reply_to(message, f"Актив '{on}' не найден.")
        row = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid,on), fetchone=True)
        if not row or row[0] < oq: return bot.reply_to(message, f"Недостаточно {on}")
        db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name=?", (oq,uid,on))
    else:
        return bot.reply_to(message, "Тип: 'money' или 'asset'")

    if wt == 'money':
        wn = 'money'
    elif wt == 'asset':
        wn = wn.lower()
        if not db_query("SELECT name FROM market_assets WHERE name=?", (wn,), fetchone=True):
            if ot == 'money': db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (int(oq),uid))
            else: db_query("UPDATE user_portfolio SET quantity=quantity+? WHERE user_id=? AND asset_name=?", (oq,uid,on))
            return bot.reply_to(message, f"Актив '{wn}' не найден.")
    else:
        if ot == 'money': db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (int(oq),uid))
        else: db_query("UPDATE user_portfolio SET quantity=quantity+? WHERE user_id=? AND asset_name=?", (oq,uid,on))
        return bot.reply_to(message, "Тип: 'money' или 'asset'")

    db_query("INSERT INTO trade_offers (seller_id,seller_username,offer_type,offer_name,offer_qty,want_type,want_name,want_qty,created_at,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
             (uid, uname, ot, on, oq, wt, wn, wq, time.time(), 'open'))
    tid = db_query("SELECT id FROM trade_offers WHERE seller_id=? ORDER BY id DESC LIMIT 1",
                   (uid,), fetchone=True)[0]
    ostr = f"{int(oq):,} 💰" if ot=='money' else f"{oq} {on}"
    wstr = f"{int(wq):,} 💰" if wt=='money' else f"{wq} {wn}"
    bot.reply_to(message,
        f"✅ *Предложение #{tid}*\nОтдаю: {ostr}\nХочу: {wstr}\n"
        f"Все: /trades | Принять: `/accept {tid}`",
        parse_mode="Markdown")

@bot.message_handler(commands=['trades'])
@group_only
def cmd_trades(message):
    if is_banned(message.from_user.id): return
    offers = db_query('''SELECT id,seller_username,offer_type,offer_name,offer_qty,
                                want_type,want_name,want_qty FROM trade_offers
                         WHERE status='open' ORDER BY id DESC LIMIT 20''')
    if not offers: return bot.reply_to(message, "Открытых предложений нет.")
    text = "🤝 *Открытые торговые предложения:*\n\n"
    for tid, seller, ot, on, oq, wt, wn, wq in offers:
        ostr = f"{int(oq):,}💰" if ot=='money' else f"{oq} {on}"
        wstr = f"{int(wq):,}💰" if wt=='money' else f"{wq} {wn}"
        text += f"*#{tid}* @{seller}: {ostr} -> {wstr} `/accept {tid}`\n"
    text += "\nОтменить: `/canceltrade ID`"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['accept'])
@group_only
def cmd_accept(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 2: return bot.reply_to(message, "Использование: /accept [ID]")
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
        if bal < int(wq): return bot.reply_to(message, f"Нужно {int(wq):,} 💰, у вас {bal:,}")
        db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (int(wq), uid))
    else:
        row = db_query("SELECT quantity FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid,wn), fetchone=True)
        if not row or row[0] < wq: return bot.reply_to(message, f"Недостаточно {wn}")
        db_query("UPDATE user_portfolio SET quantity=quantity-? WHERE user_id=? AND asset_name=?", (wq,uid,wn))

    if ot == 'money':
        db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (int(oq), uid))
    else:
        add_asset(uid, on, oq)

    if wt == 'money':
        db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (int(wq), seller_id))
    else:
        add_asset(seller_id, wn, wq)

    db_query("UPDATE trade_offers SET status='closed' WHERE id=?", (tid,))
    ostr = f"{int(oq):,}💰" if ot=='money' else f"{oq} {on}"
    wstr = f"{int(wq):,}💰" if wt=='money' else f"{wq} {wn}"
    bot.reply_to(message,
        f"✅ *Сделка #{tid} завершена!*\n@{uname} купил {ostr} у @{seller_uname} за {wstr}",
        parse_mode="Markdown")

@bot.message_handler(commands=['canceltrade'])
@group_only
def cmd_canceltrade(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 2: return bot.reply_to(message, "Использование: /canceltrade [ID]")
    try: tid = int(args[1])
    except: return bot.reply_to(message, "ID - число.")
    offer = db_query("SELECT seller_id,offer_type,offer_name,offer_qty FROM trade_offers WHERE id=? AND status='open'",
                     (tid,), fetchone=True)
    if not offer: return bot.reply_to(message, f"Предложение #{tid} не найдено.")
    if offer[0] != uid and not is_admin(uid):
        return bot.reply_to(message, "Это не ваше предложение.")
    seller_id, ot, on, oq = offer
    if ot == 'money':
        db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (int(oq), seller_id))
    else:
        add_asset(seller_id, on, oq)
    db_query("UPDATE trade_offers SET status='cancelled' WHERE id=?", (tid,))
    bot.reply_to(message, f"✅ Предложение #{tid} отменено, активы возвращены.")

# ==============================================================
# --- ПЕРЕВОДЫ ---
# ==============================================================
@bot.message_handler(commands=['pay'])
@group_only
def cmd_pay(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "Использование: /pay @user [сумма]")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, f"{args[1]} не найден.")
    try: amount = int(args[2])
    except: return bot.reply_to(message, "Сумма - число.")
    if amount <= 0: return bot.reply_to(message, "Сумма > 0.")
    if t[0] == uid: return bot.reply_to(message, "Нельзя себе.")
    bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    if bal < amount: return bot.reply_to(message, "Недостаточно средств.")
    db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, uid))
    db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, t[0]))
    bot.reply_to(message, f"💸 *{amount:,}* 💰 -> @{t[1]}", parse_mode="Markdown")

@bot.message_handler(commands=['senditem'])
@group_only
def cmd_senditem(message):
    uid, uname = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) != 4:
        return bot.reply_to(message, "Использование: `/senditem @user [актив] [кол-во]`", parse_mode="Markdown")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, f"{args[1]} не найден.")
    asset = args[2].lower()
    try: amount = float(args[3])
    except: return bot.reply_to(message, "Количество - число.")
    if amount <= 0: return bot.reply_to(message, "Количество > 0.")
    if t[0] == uid: return bot.reply_to(message, "Нельзя себе.")
    arow = db_query("SELECT display_name FROM market_assets WHERE name=?", (asset,), fetchone=True)
    if not arow: return bot.reply_to(message, f"Актив '{asset}' не найден.")
    row = db_query("SELECT quantity,avg_buy_price FROM user_portfolio WHERE user_id=? AND asset_name=?",
                   (uid,asset), fetchone=True)
    if not row or row[0] < amount: return bot.reply_to(message, f"Недостаточно {arow[0]}")
    new_qty = row[0] - amount
    if new_qty <= 0: db_query("DELETE FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid,asset))
    else: db_query("UPDATE user_portfolio SET quantity=? WHERE user_id=? AND asset_name=?", (new_qty,uid,asset))
    te = db_query("SELECT quantity,avg_buy_price FROM user_portfolio WHERE user_id=? AND asset_name=?",
                  (t[0],asset), fetchone=True)
    if te:
        new_avg = (te[0]*te[1] + amount*row[1]) / (te[0]+amount)
        db_query("UPDATE user_portfolio SET quantity=quantity+?, avg_buy_price=? WHERE user_id=? AND asset_name=?",
                 (amount, new_avg, t[0], asset))
    else:
        db_query("INSERT INTO user_portfolio VALUES (?,?,?,?)", (t[0],asset,amount,row[1]))
    bot.reply_to(message, f"📦 *{amount}x {arow[0]}* -> @{t[1]}", parse_mode="Markdown")

# ==============================================================
# --- БИЗНЕС ---
# ==============================================================
@bot.message_handler(commands=['shop'])
@group_only
def cmd_shop(message):
    if is_banned(message.from_user.id): return
    rows = db_query("SELECT name,display_name,cost,income_per_hour,description,ep_per_12h FROM business_types")
    text = "🏪 *Магазин бизнесов:*\n\n"
    for name, disp, cost, iph, desc, ep12 in rows:
        ep_str = f" | 🔬+{ep12}ОЭ/12ч" if ep12 else ""
        text += f"{disp}\n💵 {cost:,}💰 | ~{iph}💰/ч{ep_str}\n_{desc}_\n`/buybiz {name}`\n\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['buybiz'])
@group_only
def cmd_buybiz(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) < 2: return bot.reply_to(message, "Использование: /buybiz [название] [кол-во]")
    bname = args[1].lower()
    qty = int(args[2]) if len(args) >= 3 and args[2].isdigit() else 1
    if qty < 1: return bot.reply_to(message, "Количество >= 1.")
    biz = db_query("SELECT display_name,cost,income_per_hour,ep_per_12h FROM business_types WHERE name=?",
                   (bname,), fetchone=True)
    if not biz: return bot.reply_to(message, f"Бизнес '{bname}' не найден. /shop")
    disp, cost, iph, ep12 = biz
    total = cost * qty
    bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    if bal < total: return bot.reply_to(message, f"Нужно {total:,}💰, у вас {bal:,}💰")
    db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (total, uid))
    db_query("INSERT INTO user_businesses (user_id,business_name,quantity) VALUES (?,?,?) ON CONFLICT(user_id,business_name) DO UPDATE SET quantity=quantity+?",
             (uid, bname, qty, qty))
    ep_str = f"\n🔬 +{ep12*qty} ОЭ/12ч" if ep12 else ""
    bot.reply_to(message, f"✅ *{qty}x {disp}* за {total:,}💰!\n~{iph*qty}💰/ч{ep_str}",
                 parse_mode="Markdown")

@bot.message_handler(commands=['mybiz'])
@group_only
def cmd_mybiz(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    rows = db_query('''SELECT bt.display_name,ub.quantity,bt.income_per_hour,bt.ep_per_12h
                       FROM user_businesses ub JOIN business_types bt ON ub.business_name=bt.name
                       WHERE ub.user_id=?''', (uid,))
    if not rows: return bot.reply_to(message, "У вас нет бизнесов. /shop")
    text = "🏢 *Ваши бизнесы:*\n\n"
    ti = te = 0
    for disp, qty, iph, ep12 in rows:
        si=iph*qty; se=ep12*qty; ti+=si; te+=se
        ep_str = f" | +{se}ОЭ" if se else ""
        text += f"{disp} x{qty} - {si}💰/ч{ep_str}\n"
    text += f"\n📊 *~{ti}💰/ч | 🔬+{te}ОЭ/12ч | ~{ti*24:,}💰/сутки*"
    bot.reply_to(message, text, parse_mode="Markdown")

# ==============================================================
# --- БИРЖА ---
# ==============================================================
@bot.message_handler(commands=['market'])
@group_only
def cmd_market(message):
    if is_banned(message.from_user.id): return
    assets = db_query("SELECT name,display_name,price,base_price FROM market_assets")
    text = "📊 *Мировая биржа:*\n\n"
    for name, disp, price, base in assets:
        arr = get_price_arrow(price, base)
        pct = ((price-base)/base)*100
        sign = "+" if pct >= 0 else ""
        text += f"{arr} *{disp}*: {price:.2f}💰 ({sign}{pct:.1f}%)\n"
        text += f"   `/buy {name} [кол]`  `/sell {name} [кол]`\n\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['buy'])
@group_only
def cmd_buy(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) < 3: return bot.reply_to(message, "Использование: /buy [актив] [кол-во]")
    asset = args[1].lower()
    try: qty = int(args[2])
    except: return bot.reply_to(message, "Количество - число.")
    if qty <= 0: return bot.reply_to(message, "Количество > 0.")
    arow = db_query("SELECT display_name,price FROM market_assets WHERE name=?", (asset,), fetchone=True)
    if not arow: return bot.reply_to(message, f"Актив '{asset}' не найден.")
    disp, price = arow
    total = round(price * qty, 2)
    bal = (db_query("SELECT balance FROM users WHERE user_id=?", (uid,), fetchone=True) or [0])[0]
    if bal < total: return bot.reply_to(message, f"Нужно {total:.2f}💰, у вас {bal:,}💰")
    e = db_query("SELECT quantity,avg_buy_price FROM user_portfolio WHERE user_id=? AND asset_name=?",
                 (uid,asset), fetchone=True)
    if e:
        nq = e[0]+qty; na = (e[0]*e[1]+price*qty)/nq
        db_query("UPDATE user_portfolio SET quantity=?,avg_buy_price=? WHERE user_id=? AND asset_name=?",
                 (nq,na,uid,asset))
    else:
        db_query("INSERT INTO user_portfolio VALUES (?,?,?,?)", (uid,asset,qty,price))
    db_query("UPDATE users SET balance=balance-? WHERE user_id=?", (total, uid))
    bot.reply_to(message, f"✅ *{qty}x {disp}* за {total:.2f}💰", parse_mode="Markdown")

@bot.message_handler(commands=['sell'])
@group_only
def cmd_sell(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    args = message.text.split()
    if len(args) < 3: return bot.reply_to(message, "Использование: /sell [актив] [кол-во]")
    asset = args[1].lower()
    try: qty = int(args[2])
    except: return bot.reply_to(message, "Количество - число.")
    if qty <= 0: return bot.reply_to(message, "Количество > 0.")
    arow = db_query("SELECT display_name,price FROM market_assets WHERE name=?", (asset,), fetchone=True)
    if not arow: return bot.reply_to(message, f"Актив '{asset}' не найден.")
    disp, price = arow
    row = db_query("SELECT quantity,avg_buy_price FROM user_portfolio WHERE user_id=? AND asset_name=?",
                   (uid,asset), fetchone=True)
    if not row or row[0] < qty:
        return bot.reply_to(message, f"У вас только {row[0] if row else 0:.1f} {disp}")
    rev = round(price*qty, 2); profit = round((price-row[1])*qty, 2)
    nq = row[0]-qty
    if nq <= 0: db_query("DELETE FROM user_portfolio WHERE user_id=? AND asset_name=?", (uid,asset))
    else: db_query("UPDATE user_portfolio SET quantity=? WHERE user_id=? AND asset_name=?", (nq,uid,asset))
    db_query("UPDATE users SET balance=balance+? WHERE user_id=?", (rev, uid))
    emoji = "📈" if profit >= 0 else "📉"
    pstr = f"+{profit:.2f}" if profit >= 0 else f"{profit:.2f}"
    bot.reply_to(message, f"💰 *{qty}x {disp}* за {rev:.2f}💰\n{emoji} P&L: *{pstr}💰*",
                 parse_mode="Markdown")

@bot.message_handler(commands=['portfolio'])
@group_only
def cmd_portfolio(message):
    uid, _ = ensure_user(message)
    if is_banned(uid): return
    rows = db_query('''SELECT p.asset_name,p.quantity,p.avg_buy_price,m.price,m.display_name
                       FROM user_portfolio p JOIN market_assets m ON p.asset_name=m.name
                       WHERE p.user_id=? AND p.quantity>0''', (uid,))
    if not rows: return bot.reply_to(message, "Портфель пуст. /market")
    text = "💼 *Портфель:*\n\n"
    ti = tc = 0.0
    for _, qty, avg, cur, disp in rows:
        inv=avg*qty; cv=cur*qty; pnl=cv-inv; ti+=inv; tc+=cv
        e = "📈" if pnl>=0 else "📉"
        pstr = f"+{pnl:.2f}" if pnl>=0 else f"{pnl:.2f}"
        text += f"{e} *{disp}* x{qty:.1f} | avg:{avg:.2f}->{cur:.2f} | {pstr}💰\n"
    tp=tc-ti; tstr=f"+{tp:.2f}" if tp>=0 else f"{tp:.2f}"
    text += f"\n💰 Вложено: {ti:.2f} | Сейчас: {tc:.2f}\n{'📈' if tp>=0 else '📉'} *P&L: {tstr}💰*"
    bot.reply_to(message, text, parse_mode="Markdown")

# ==============================================================
# --- РЕЙТИНГИ ---
# ==============================================================
@bot.message_handler(commands=['toparmy'])
@group_only
def cmd_toparmy(message):
    users = db_query("SELECT user_id,username FROM users WHERE banned=0")
    powers = sorted([(uname, calc_power(uid)) for uid,uname in (users or [])],
                    key=lambda x: x[1], reverse=True)
    powers = [(u,p) for u,p in powers if p > 0][:10]
    if not powers: return bot.reply_to(message, "Рейтинг пуст.")
    medals = ["🥇","🥈","🥉"]
    text = "⚔️ *Рейтинг военной мощи:*\n\n"
    for i,(u,p) in enumerate(powers,1):
        text += f"{medals[i-1] if i<=3 else str(i)+'.'} @{u} - {p:,}⚔️\n"
    text += "\n💡 Мощь = войска + техника x коэффициент x мораль x технологии"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['top'])
@group_only
def cmd_top(message):
    args = message.text.split()
    if len(args) < 2:
        assets = db_query("SELECT name,display_name FROM market_assets")
        text = "🏆 *Рейтинги:*\n`/top money` `/top ep`\n"
        for name, disp in assets: text += f"`/top {name}` - {disp}\n"
        text += "\n⚔️ /toparmy"
        return bot.reply_to(message, text, parse_mode="Markdown")
    cat = args[1].lower()
    if cat == 'money':
        rows = db_query("SELECT username,balance FROM users WHERE banned=0 ORDER BY balance DESC LIMIT 10")
        text = "🏆 *Топ по балансу:*\n\n"
        for i,(u,v) in enumerate(rows or [],1): text += f"{i}. @{u} - {v:,}💰\n"
    elif cat == 'ep':
        rows = db_query("SELECT username,ep FROM users WHERE banned=0 ORDER BY ep DESC LIMIT 10")
        text = "🏆 *Топ по ОЭ:*\n\n"
        for i,(u,v) in enumerate(rows or [],1): text += f"{i}. @{u} - {v:,}ОЭ🔬\n"
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

@bot.message_handler(commands=['worldstats'])
@group_only
def cmd_worldstats(message):
    money = (db_query("SELECT SUM(balance) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
    troops = (db_query("SELECT SUM(troops) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
    count = (db_query("SELECT COUNT(*) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
    ep = (db_query("SELECT SUM(ep) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
    oil = (db_query("SELECT SUM(quantity) FROM user_portfolio WHERE asset_name='oil'", fetchone=True) or [0])[0] or 0
    trades = (db_query("SELECT COUNT(*) FROM trade_offers WHERE status='open'", fetchone=True) or [0])[0] or 0
    avg_morale = (db_query("SELECT AVG(morale) FROM users WHERE banned=0", fetchone=True) or [0])[0] or 0
    bot.reply_to(message,
        f"🌍 *Мировая статистика Аурелии:*\n\n"
        f"👥 Правителей: {count}\n"
        f"💰 Денег: {money:,}💰\n"
        f"🪖 Войск: {troops:,}\n"
        f"🎺 Средняя мораль: {avg_morale:.0f}%\n"
        f"🔬 ОЭ: {ep:,}\n"
        f"🛢️ Нефти: {oil:.1f}\n"
        f"🤝 Открытых сделок: {trades}",
        parse_mode="Markdown")

# ==============================================================
# --- ADMIN ---
# ==============================================================
@bot.message_handler(commands=['adminhelp'])
@admin_only
def cmd_adminhelp(message):
    bot.reply_to(message,
        "🔧 *Команды администратора:*\n\n"
        "💰 /givemoney @u сумма\n"
        "💰 /takemoney @u сумма\n"
        "🔬 /giveep @u кол-во\n"
        "📦 /giveitem @u актив кол-во\n"
        "📦 /takeitem @u актив кол-во\n"
        "🛢️ /giveextractor @u кол-во\n"
        "🛢️ /takeextractor @u кол-во\n"
        "⛏️ /givebuilding @u [gold|steel|coal|aur] кол-во\n"
        "⛏️ /takebuilding @u [gold|steel|coal|aur] кол-во\n"
        "⚔️ /givemilitary @u тип кол-во\n"
        "📈 /setlevel @u уровень\n"
        "🪖 /settroops @u кол-во\n"
        "🎺 /setmorale @u процент\n"
        "🔬 /settech @u тех уровень\n"
        "🚫 /banuser @u | /unbanuser @u\n"
        "🗑️ /wipeuser @u\n"
        "📋 /playerinfo @u\n"
        "📊 /setprice актив цена\n"
        "📊 /setbaseprice актив цена\n"
        "⚡ /marketevent актив %\n"
        "📉 /marketcrash | 📈 /marketboom | 🔄 /resetmarket\n"
        "🤝 /canceltrade ID\n"
        "📢 /broadcast текст\n"
        "📢 /announcement текст\n\n"
        "*Активы:* oil gold steel aur food coal\n"
        "*Техника:* rifle machinegun mortar apc tank\n"
        "artillery aa\\_gun mlrs missile\n"
        "plane bomber helicopter bomb\n"
        "corvette ship submarine cruiser carrier nuclear\\_sub",
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
    bot.reply_to(message, f"✅ @{t[1]} +{a}ОЭ🔬")

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
    bot.reply_to(message, f"✅ @{t[1]} +{a}x{asset}")

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
    db_query("UPDATE user_portfolio SET quantity=MAX(0,quantity-?) WHERE user_id=? AND asset_name=?",
             (a, t[0], asset))
    bot.reply_to(message, f"✅ @{t[1]} -{a}x{asset}")

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
    bot.reply_to(message, f"✅ @{t[1]} +{a}🛢️качек")

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
    bot.reply_to(message, f"✅ @{t[1]} -{a}🛢️качек")

@bot.message_handler(commands=['givebuilding'])
@admin_only
def cmd_givebuilding(message):
    """Выдать ресурсное здание: /givebuilding @user [gold|steel|coal|aur] кол-во"""
    args = message.text.split()
    if len(args) != 4: return bot.reply_to(message, "/givebuilding @user [gold|steel|coal|aur] кол-во")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    res = args[2].lower()
    if res not in RESOURCE_BUILDINGS:
        return bot.reply_to(message, f"Ресурс '{res}' не поддерживается. Доступно: {', '.join(RESOURCE_BUILDINGS.keys())}")
    try: a = int(args[3])
    except: return bot.reply_to(message, "Количество - число.")
    emoji, name, _, _ = RESOURCE_BUILDINGS[res]
    e = db_query("SELECT quantity FROM user_resource_buildings WHERE user_id=? AND resource=?", (t[0],res), fetchone=True)
    if e:
        db_query("UPDATE user_resource_buildings SET quantity=quantity+? WHERE user_id=? AND resource=?", (a,t[0],res))
    else:
        db_query("INSERT INTO user_resource_buildings VALUES (?,?,?,?)", (t[0],res,a,0))
    bot.reply_to(message, f"✅ @{t[1]} +{a}x {emoji}{name}")

@bot.message_handler(commands=['takebuilding'])
@admin_only
def cmd_takebuilding(message):
    """Забрать ресурсное здание: /takebuilding @user [gold|steel|coal|aur] кол-во"""
    args = message.text.split()
    if len(args) != 4: return bot.reply_to(message, "/takebuilding @user [gold|steel|coal|aur] кол-во")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    res = args[2].lower()
    if res not in RESOURCE_BUILDINGS:
        return bot.reply_to(message, f"Ресурс '{res}' не поддерживается.")
    try: a = int(args[3])
    except: return bot.reply_to(message, "Количество - число.")
    emoji, name, _, _ = RESOURCE_BUILDINGS[res]
    db_query("UPDATE user_resource_buildings SET quantity=MAX(0,quantity-?) WHERE user_id=? AND resource=?",
             (a, t[0], res))
    bot.reply_to(message, f"✅ @{t[1]} -{a}x {emoji}{name}")

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
    e = db_query("SELECT quantity FROM user_military WHERE user_id=? AND unit_name=?", (t[0],unit), fetchone=True)
    if e: db_query("UPDATE user_military SET quantity=quantity+? WHERE user_id=? AND unit_name=?", (a,t[0],unit))
    else: db_query("INSERT INTO user_military VALUES (?,?,?)", (t[0],unit,a))
    bot.reply_to(message, f"✅ @{t[1]} +{a}x{un[0]}")

@bot.message_handler(commands=['setlevel'])
@admin_only
def cmd_setlevel(message):
    args = message.text.split()
    if len(args) != 3: return bot.reply_to(message, "/setlevel @user уровень")
    t = find_user(args[1])
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
    if len(args) != 3: return bot.reply_to(message, "/setmorale @user процент (1-100)")
    t = find_user(args[1])
    if not t: return bot.reply_to(message, "Не найден.")
    try: val = int(args[2])
    except: return bot.reply_to(message, "Процент - число.")
    val = max(1, min(100, val))
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
    e = db_query("SELECT level FROM user_tech WHERE user_id=? AND tech_name=?", (t[0],tech), fetchone=True)
    if e: db_query("UPDATE user_tech SET level=? WHERE user_id=? AND tech_name=?", (lv,t[0],tech))
    else: db_query("INSERT INTO user_tech VALUES (?,?,?)", (t[0],tech,lv))
    bot.reply_to(message, f"✅ @{t[1]} {td[0]} - Ур.{lv}")

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
    for tbl in ['user_businesses','user_portfolio','user_military','user_tech','user_extractors']:
        db_query(f"DELETE FROM {tbl} WHERE user_id=?", (tid,))
    bot.reply_to(message, f"✅ @{t[1]} полностью сброшен.")

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
        f"ID:`{uid}` | Бан:{'Да' if user[4] else 'Нет'}\n"
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
    bot.reply_to(message, f"✅ {asset} - {p:.2f}💰")

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
    bot.reply_to(message, f"✅ {asset} базовая - {p:.2f}💰")

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
    new_p = round(max(0.01, old*(1+pct/100)), 2)
    db_query("UPDATE market_assets SET price=?,last_updated=? WHERE name=?", (new_p, time.time(), asset))
    arr = "📈" if pct >= 0 else "📉"
    bot.reply_to(message,
        f"⚡ *{arr} {disp}*: {old:.2f} -> *{new_p:.2f}* ({'+' if pct>=0 else ''}{pct:.1f}%)",
        parse_mode="Markdown")

@bot.message_handler(commands=['marketcrash'])
@admin_only
def cmd_marketcrash(message):
    assets = db_query("SELECT name,display_name,price FROM market_assets")
    text = "🔴 *ОБВАЛ РЫНКА!*\n\n"
    for name, disp, price in assets:
        drop = random.uniform(0.20, 0.50)
        new = round(price*(1-drop), 2)
        db_query("UPDATE market_assets SET price=?,last_updated=? WHERE name=?", (new,time.time(),name))
        text += f"📉 {disp}: {price:.2f} -> *{new:.2f}* (-{drop*100:.1f}%)\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['marketboom'])
@admin_only
def cmd_marketboom(message):
    assets = db_query("SELECT name,display_name,price FROM market_assets")
    text = "🟢 *БУМ НА РЫНКЕ!*\n\n"
    for name, disp, price in assets:
        rise = random.uniform(0.20, 0.50)
        new = round(price*(1+rise), 2)
        db_query("UPDATE market_assets SET price=?,last_updated=? WHERE name=?", (new,time.time(),name))
        text += f"📈 {disp}: {price:.2f} -> *{new:.2f}* (+{rise*100:.1f}%)\n"
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
    text = f"📢 *Объявление от Администрации:*\n\n{args[1]}"
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

# пенис
print("🌍 Aurelia Bot запущен!")
bot.polling(none_stop=True)
