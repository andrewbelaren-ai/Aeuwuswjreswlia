# -*- coding: utf-8 -*-
# ================================================================
# БОЕВОЙ МОДУЛЬ — combat.py
# Подключается к основному боту: from combat import register_combat
# Вызвать в конце bot__2__.py: register_combat(bot)
# ================================================================

import re
import json
import time
import sqlite3
import functools

# ================================================================
# КОНСТАНТЫ
# ================================================================

# Юниты которые считаются "техникой" — в заморозку ×0.7
TECH_UNITS = {'apc', 'tank', 'artillery', 'mlrs', 'missile'}

# Категории юнитов (берём из military_types, но дублируем для быстрого доступа)
UNIT_CATEGORIES = {
    'rifle': 'ground', 'machinegun': 'ground', 'mortar': 'ground',
    'apc': 'ground', 'tank': 'ground', 'artillery': 'ground',
    'aa_gun': 'ground', 'mlrs': 'ground', 'missile': 'ground',
    'plane': 'air', 'bomber': 'air', 'helicopter': 'air', 'bomb': 'air',
    'corvette': 'navy', 'ship': 'navy', 'submarine': 'navy',
    'cruiser': 'navy', 'carrier': 'navy', 'nuclear_sub': 'navy',
}

# Штрафы атаки по рельефу (на 1%)
TERRAIN_ATK_PENALTY = {
    'plains':    0.00,
    'hills':     0.10,
    'plateau':   0.15,
    'mountains': 0.25,
    'peaks':     0.35,
}

# Бонус обороны по рельефу (на 1%)
TERRAIN_DEF_BONUS = {
    'plains':    0.00,
    'hills':     0.15,
    'plateau':   0.20,
    'mountains': 0.30,
    'peaks':     0.45,
}

TERRAIN_NAMES = {
    'plains': 'Равнина', 'hills': 'Холмы',
    'plateau': 'Плато', 'mountains': 'Горы', 'peaks': 'Вершины',
}

# ================================================================
# БД ХЕЛПЕРЫ (локальные, не зависят от основного бота)
# ================================================================

def _db(query, args=(), fetchone=False):
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

def _init_combat_tables():
    conn = sqlite3.connect('aurelia_economy.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS attack_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attacker_id INTEGER,
        attacker_username TEXT,
        units_json TEXT,
        status TEXT DEFAULT 'pending',
        created_at REAL DEFAULT 0,
        chat_id INTEGER DEFAULT 0,
        message_id INTEGER DEFAULT 0
    )''')
    conn.commit()
    conn.close()

# ================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ================================================================

def _get_unit_stats():
    """Возвращает dict: name -> {attack_value, defense_value, category, display_name}"""
    rows = _db("SELECT name, display_name, attack_value, defense_value, category FROM military_types")
    return {r[0]: {'display': r[1], 'atk': r[2], 'def': r[3], 'cat': r[4]} for r in (rows or [])}

def _get_user_units(uid):
    """Возвращает dict: unit_name -> quantity (только те что > 0)"""
    rows = _db("SELECT unit_name, quantity FROM user_military WHERE user_id=? AND quantity>0", (uid,))
    return {r[0]: r[1] for r in (rows or [])}

def _get_frozen_units(uid):
    """Возвращает dict замороженных юнитов из активных pending заявок"""
    rows = _db("SELECT units_json FROM attack_requests WHERE attacker_id=? AND status='pending'", (uid,))
    frozen = {}
    for row in (rows or []):
        try:
            units = json.loads(row[0])
            for u, q in units.items():
                frozen[u] = frozen.get(u, 0) + q
        except:
            pass
    return frozen

def _get_available_units(uid):
    """Доступные юниты = все - замороженные"""
    owned = _get_user_units(uid)
    frozen = _get_frozen_units(uid)
    available = {}
    for u, q in owned.items():
        avail = q - frozen.get(u, 0)
        if avail > 0:
            available[u] = avail
    return available

def _get_tech(uid, name):
    r = _db("SELECT level FROM user_tech WHERE user_id=? AND tech_name=?", (uid, name), fetchone=True)
    return r[0] if r else 0

def _get_country(uid):
    r = _db("SELECT country_name, username FROM users WHERE user_id=?", (uid,), fetchone=True)
    if not r:
        return "???"
    return r[0] or f"@{r[1]}"

def _parse_attack_message(text):
    """
    Парсит сообщение вида:
    ➡️ rifle:300 tank:20 plane:15 bomber:5
    Возвращает dict {unit: qty} или None если не распарсилось
    """
    # Убираем стрелку и лишнее
    text = text.replace('➡️', '').replace('➡', '').strip()
    
    units = {}
    # Ищем паттерны вида word:number или word number
    patterns = re.findall(r'([a-z_]+)[:\s]+(\d+)', text.lower())
    for unit, qty in patterns:
        qty = int(qty)
        if qty > 0:
            units[unit] = units.get(unit, 0) + qty
    return units if units else None

# ================================================================
# РАСЧЁТ БОЯ
# ================================================================

def calculate_battle(attacker_units, terrain, frozen, coastal,
                     def_aa_gun, def_navy_units, def_ground_units,
                     attacker_uid=None):
    """
    attacker_units: dict {unit_name: qty}
    terrain: dict {plains:%, hills:%, plateau:%, mountains:%, peaks:%} — сумма = 100
    frozen: bool — заморозка
    coastal: bool — прибрежная клетка
    def_aa_gun: int — кол-во ПВО у защитника
    def_navy_units: dict {unit_name: qty} — флот защитника
    def_ground_units: dict {unit_name: qty} — наземная оборона защитника
    attacker_uid: для учёта технологий
    """
    stats = _get_unit_stats()

    # --- Штраф/бонус рельефа (взвешенный) ---
    total_pct = sum(terrain.values()) or 100
    atk_penalty = sum(
        TERRAIN_ATK_PENALTY.get(t, 0) * (pct / total_pct)
        for t, pct in terrain.items()
    )
    def_bonus = sum(
        TERRAIN_DEF_BONUS.get(t, 0) * (pct / total_pct)
        for t, pct in terrain.items()
    )
    if frozen:
        atk_penalty += 0.10
    atk_penalty = min(atk_penalty, 0.90)

    # --- Бонус технологий атакующего ---
    mil_sc_bonus = 1.0
    naval_bonus = 1.0
    if attacker_uid:
        mil_sc_bonus = 1 + _get_tech(attacker_uid, 'military_sc') * 0.15
        naval_bonus  = 1 + _get_tech(attacker_uid, 'naval') * 0.20

    # --- Считаем силу атаки по категориям ---
    ground_raw = 0
    air_raw = 0
    navy_raw = 0
    ground_detail = []
    air_detail = []
    navy_detail = []

    for unit, qty in attacker_units.items():
        if unit not in stats:
            continue
        s = stats[unit]
        cat = s['cat']
        atk_val = s['atk']
        disp = s['display']

        if cat == 'ground':
            # Техника в заморозку ×0.7
            coef = 0.7 if (frozen and unit in TECH_UNITS) else 1.0
            raw = qty * atk_val * coef
            ground_raw += raw
            ground_detail.append((disp, qty, atk_val, coef, raw))

        elif cat == 'air':
            raw = qty * atk_val
            air_raw += raw
            air_detail.append((disp, qty, atk_val, raw))

        elif cat == 'navy':
            raw = qty * atk_val * naval_bonus
            navy_raw += raw
            navy_detail.append((disp, qty, atk_val, naval_bonus, raw))

    # --- Штраф рельефа на наземные ---
    ground_after = ground_raw * (1 - atk_penalty)

    # --- ПВО перехват ---
    pvo_intercept = min(def_aa_gun * 0.05, 0.90)
    air_after = air_raw * (1 - pvo_intercept)

    # --- Флот перехват ---
    navy_after = 0.0
    fleet_intercept = 0.0
    if coastal and navy_raw > 0:
        def_fleet_def = sum(
            stats[u]['def'] * q
            for u, q in def_navy_units.items()
            if u in stats
        )
        fleet_intercept = min(def_fleet_def * 0.002, 0.90)
        navy_after = navy_raw * (1 - fleet_intercept)
    elif not coastal and navy_raw > 0:
        navy_after = 0  # флот не работает без моря

    # --- Итог атаки с бонусом технологий ---
    total_attack = (ground_after + air_after + navy_after) * mil_sc_bonus

    # --- Считаем оборону ---
    def_detail = []
    def_raw = 0
    for unit, qty in def_ground_units.items():
        if unit not in stats:
            continue
        s = stats[unit]
        dv = s['def']
        raw = qty * dv
        def_raw += raw
        def_detail.append((s['display'], qty, dv, raw))

    def_total = def_raw * (1 + def_bonus)

    # --- Победитель ---
    if total_attack > def_total:
        winner = 'attacker'
        margin = total_attack / max(def_total, 1)
    elif def_total > total_attack:
        winner = 'defender'
        margin = def_total / max(total_attack, 1)
    else:
        winner = 'draw'
        margin = 1.0

    # --- Предложение потерь ---
    # Победитель теряет 10-20%, проигравший 40-70%
    # Используем детерминированную формулу (без рандома — админ корректирует)
    if winner == 'attacker':
        atk_loss_pct = 0.15
        def_loss_pct = min(0.40 + (margin - 1) * 0.10, 0.70)
    elif winner == 'defender':
        atk_loss_pct = min(0.40 + (margin - 1) * 0.10, 0.70)
        def_loss_pct = 0.15
    else:
        atk_loss_pct = 0.25
        def_loss_pct = 0.25

    # Предложение потерь атакующего
    suggested_atk_losses = {}
    for unit, qty in attacker_units.items():
        loss = max(1, round(qty * atk_loss_pct)) if qty > 0 else 0
        if loss > 0:
            suggested_atk_losses[unit] = min(loss, qty)

    # Предложение потерь защитника
    suggested_def_losses = {}
    for unit, qty in def_ground_units.items():
        loss = max(1, round(qty * def_loss_pct)) if qty > 0 else 0
        if loss > 0:
            suggested_def_losses[unit] = min(loss, qty)

    return {
        'ground_raw': ground_raw,
        'ground_after': ground_after,
        'ground_detail': ground_detail,
        'air_raw': air_raw,
        'air_after': air_after,
        'air_detail': air_detail,
        'navy_raw': navy_raw,
        'navy_after': navy_after,
        'navy_detail': navy_detail,
        'pvo_intercept': pvo_intercept,
        'fleet_intercept': fleet_intercept,
        'atk_penalty': atk_penalty,
        'def_bonus': def_bonus,
        'def_raw': def_raw,
        'def_total': def_total,
        'def_detail': def_detail,
        'total_attack': total_attack,
        'winner': winner,
        'margin': margin,
        'atk_loss_pct': atk_loss_pct,
        'def_loss_pct': def_loss_pct,
        'suggested_atk_losses': suggested_atk_losses,
        'suggested_def_losses': suggested_def_losses,
        'coastal': coastal,
        'frozen': frozen,
        'terrain': terrain,
        'def_aa_gun': def_aa_gun,
    }

# ================================================================
# ФОРМАТИРОВАНИЕ КАРТОЧКИ ДЛЯ АДМИНА
# ================================================================

def format_calc_card(req_id, attacker_uid, attacker_username, attacker_units, result):
    stats = _get_unit_stats()
    country = _get_country(attacker_uid)

    terrain = result['terrain']
    terrain_str = ' | '.join(
        f"{TERRAIN_NAMES.get(t, t)} {pct}%"
        for t, pct in terrain.items() if pct > 0
    )

    lines = [f"⚔️ РАСЧЁТ ЗАЯВКИ #{req_id}"]
    lines.append(f"👤 @{attacker_username} ({country}) наступает")
    lines.append("")

    # Рельеф
    lines.append(f"🗺️ Рельеф: {terrain_str}")
    extra = []
    if result['frozen']: extra.append("❄️ Заморожена")
    if result['coastal']: extra.append("🌊 Прибрежная")
    if extra: lines.append("   " + " | ".join(extra))
    lines.append(f"   Штраф атаки: -{result['atk_penalty']*100:.1f}% | Бонус обороны: +{result['def_bonus']*100:.1f}%")
    lines.append("")

    # Наземные
    if result['ground_detail']:
        lines.append("⚔️ НАЗЕМНЫЕ:")
        for disp, qty, av, coef, raw in result['ground_detail']:
            coef_str = f" ×{coef} ❄️" if coef < 1 else ""
            lines.append(f"  {disp} ×{qty} → {qty}×{av}{coef_str} = {int(raw)}")
        lines.append(f"  После штрафа рельефа: {int(result['ground_after'])}")

    # Воздух
    if result['air_detail']:
        lines.append("")
        lines.append("✈️ ВОЗДУХ:")
        for disp, qty, av, raw in result['air_detail']:
            lines.append(f"  {disp} ×{qty} → {qty}×{av} = {int(raw)}")
        lines.append(f"  ПВО защитника: {result['def_aa_gun']} ед. → перехват {result['pvo_intercept']*100:.0f}%")
        lines.append(f"  Воздух после ПВО: {int(result['air_after'])}")

    # Флот
    if result['navy_detail']:
        lines.append("")
        lines.append("🚢 ФЛОТ:")
        for disp, qty, av, nb, raw in result['navy_detail']:
            lines.append(f"  {disp} ×{qty} → {qty}×{av} = {int(raw)}")
        if result['coastal']:
            lines.append(f"  Перехват флотом: {result['fleet_intercept']*100:.0f}%")
            lines.append(f"  Флот после перехвата: {int(result['navy_after'])}")
        else:
            lines.append(f"  ⚠️ Клетка не прибрежная — флот не засчитан!")

    lines.append("")
    lines.append(f"💥 ИТОГО АТАКА: {int(result['total_attack'])}")
    lines.append("")

    # Оборона
    if result['def_detail']:
        lines.append("🛡️ ГАРНИЗОН ЗАЩИТНИКА:")
        for disp, qty, dv, raw in result['def_detail']:
            lines.append(f"  {disp} ×{qty} → {qty}×{dv} = {int(raw)}")
        lines.append(f"  Бонус рельефа: +{result['def_bonus']*100:.1f}%")
    else:
        lines.append("🛡️ Гарнизон: пусто (нейтральная клетка?)")

    lines.append(f"🛡️ ИТОГО ОБОРОНА: {int(result['def_total'])}")
    lines.append("")

    # Результат
    if result['winner'] == 'attacker':
        lines.append(f"⚖️ ПОБЕДИТЕЛЬ: 🔴 АТАКУЮЩИЙ ({int(result['total_attack'])} vs {int(result['def_total'])})")
    elif result['winner'] == 'defender':
        lines.append(f"⚖️ ПОБЕДИТЕЛЬ: 🔵 ЗАЩИТНИК ({int(result['def_total'])} vs {int(result['total_attack'])})")
    else:
        lines.append(f"⚖️ НИЧЬЯ ({int(result['total_attack'])} vs {int(result['def_total'])})")

    lines.append("")
    lines.append(f"📉 ПРЕДЛОЖЕНИЕ ПОТЕРЬ ({int(result['atk_loss_pct']*100)}% / {int(result['def_loss_pct']*100)}%):")

    # Потери атакующего
    atk_loss_parts = []
    for unit, loss in result['suggested_atk_losses'].items():
        disp = stats.get(unit, {}).get('display', unit)
        atk_loss_parts.append(f"{disp} -{loss}")
    lines.append(f"  Атакующий: {', '.join(atk_loss_parts) if atk_loss_parts else 'нет'}")

    # Потери защитника
    def_loss_parts = []
    for unit, loss in result['suggested_def_losses'].items():
        disp = stats.get(unit, {}).get('display', unit)
        def_loss_parts.append(f"{disp} -{loss}")
    lines.append(f"  Защитник: {', '.join(def_loss_parts) if def_loss_parts else 'нет'}")

    lines.append("")
    lines.append("─────────────────────────")
    lines.append(f"✅ /approve{req_id} — принять")
    lines.append(f"✏️ /losses{req_id} a:rifle-30,tank-2 d:rifle-100,tank-5 — изменить потери")
    lines.append(f"❌ /reject{req_id} — отклонить")

    return "\n".join(lines)

# ================================================================
# ПАРСИНГ /calc и /losses
# ================================================================

def parse_calc_args(text):
    """
    Парсит: /calcN plains:30 hills:40 mountains:30 frozen:1 coastal:0 aa_gun:8 rifle:200 tank:10
    Возвращает (terrain, frozen, coastal, def_aa_gun, def_ground, def_navy)
    """
    terrain_keys = {'plains', 'hills', 'plateau', 'mountains', 'peaks'}
    terrain = {}
    frozen = False
    coastal = False
    def_aa_gun = 0
    def_ground = {}
    def_navy = {}

    pairs = re.findall(r'([a-z_]+):(\d+)', text.lower())
    for key, val in pairs:
        val = int(val)
        if key in terrain_keys:
            terrain[key] = val
        elif key == 'frozen':
            frozen = bool(val)
        elif key == 'coastal':
            coastal = bool(val)
        elif key == 'aa_gun':
            def_aa_gun = val
        else:
            cat = UNIT_CATEGORIES.get(key)
            if cat == 'navy':
                def_navy[key] = val
            elif cat in ('ground', 'air', None):
                def_ground[key] = val

    # Нормализуем terrain до 100%
    if terrain and sum(terrain.values()) == 0:
        terrain = {'plains': 100}

    return terrain, frozen, coastal, def_aa_gun, def_ground, def_navy

def parse_losses_args(text):
    """
    Парсит: /lossesN a:rifle-30,tank-2 d:rifle-100,tank-5
    Возвращает (atk_losses_dict, def_losses_dict)
    """
    atk_losses = {}
    def_losses = {}

    # Ищем блок a:...
    a_match = re.search(r'\ba:([\w,\-]+)', text.lower())
    d_match = re.search(r'\bd:([\w,\-]+)', text.lower())

    if a_match:
        for pair in a_match.group(1).split(','):
            m = re.match(r'([a-z_]+)-(\d+)', pair.strip())
            if m:
                atk_losses[m.group(1)] = int(m.group(2))

    if d_match:
        for pair in d_match.group(1).split(','):
            m = re.match(r'([a-z_]+)-(\d+)', pair.strip())
            if m:
                def_losses[m.group(1)] = int(m.group(2))

    return atk_losses, def_losses

# ================================================================
# ПРИМЕНЕНИЕ ПОТЕРЬ
# ================================================================

def apply_losses(uid, losses_dict):
    """Списывает потери из user_military"""
    for unit, loss in losses_dict.items():
        if loss <= 0:
            continue
        _db("UPDATE user_military SET quantity = MAX(0, quantity - ?) WHERE user_id=? AND unit_name=?",
            (loss, uid, unit))

# ================================================================
# РЕГИСТРАЦИЯ ХЕНДЛЕРОВ
# ================================================================

def register_combat(bot, admin_ids):
    _init_combat_tables()

    # Хранилище ожидающих расчётов в памяти
    # pending_calcs[req_id] = {'attacker_id': ..., 'attacker_units': ..., 'result': ...}
    pending_calcs = {}

    # ----------------------------------------------------------------
    # 1. ИГРОК — ловим ➡️ сообщение
    # ----------------------------------------------------------------
    @bot.message_handler(func=lambda m: m.text and (m.text.startswith('➡️') or m.text.startswith('➡')))
    def handle_attack(message):
        uid = message.from_user.id
        uname = message.from_user.username or f"player_{uid}"

        # Проверка бана
        banned = _db("SELECT banned FROM users WHERE user_id=?", (uid,), fetchone=True)
        if banned and banned[0] == 1:
            return bot.reply_to(message, "Вы заблокированы.")

        # Проверка активной заявки
        existing = _db("SELECT id FROM attack_requests WHERE attacker_id=? AND status='pending'", (uid,), fetchone=True)
        if existing:
            return bot.reply_to(message, f"❌ У вас уже есть активная заявка #{existing[0]}. Дождитесь решения администратора.")

        # Парсинг юнитов
        units = _parse_attack_message(message.text)
        if not units:
            return bot.reply_to(message, "❌ Не удалось распознать юниты.\nФормат: ➡️ rifle:300 tank:20 plane:5")

        # Проверка что юниты существуют
        stats = _get_unit_stats()
        unknown = [u for u in units if u not in stats]
        if unknown:
            return bot.reply_to(message, f"❌ Неизвестные юниты: {', '.join(unknown)}")

        # Проверка наличия
        available = _get_available_units(uid)
        not_enough = []
        for unit, qty in units.items():
            if available.get(unit, 0) < qty:
                have = available.get(unit, 0)
                disp = stats[unit]['display']
                not_enough.append(f"{disp}: нужно {qty}, есть {have}")

        if not_enough:
            return bot.reply_to(message, "❌ Недостаточно юнитов:\n" + "\n".join(not_enough))

        # Создаём заявку
        units_json = json.dumps(units)
        _db("INSERT INTO attack_requests (attacker_id, attacker_username, units_json, status, created_at, chat_id, message_id) VALUES (?,?,?,?,?,?,?)",
            (uid, uname, units_json, 'pending', time.time(), message.chat.id, message.message_id))

        req = _db("SELECT id FROM attack_requests WHERE attacker_id=? ORDER BY id DESC LIMIT 1", (uid,), fetchone=True)
        req_id = req[0]

        # Подтверждение игроку
        units_str = ", ".join(
            f"{stats[u]['display']} ×{q}" for u, q in units.items()
        )
        bot.reply_to(message, f"✅ Заявка #{req_id} принята, ожидает подтверждения.\n🔒 Заморожено: {units_str}")

        # Уведомление всем админам
        admin_msg = (
            f"⚔️ НОВАЯ ЗАЯВКА #{req_id}\n\n"
            f"👤 @{uname} наступает\n"
            f"⚔️ {units_str}\n\n"
            f"Введи параметры клетки и гарнизона:\n"
            f"/calc{req_id} plains:50 hills:30 mountains:20 frozen:0 coastal:0 "
            f"aa_gun:5 rifle:200 tank:10\n\n"
            f"Ключи рельефа: plains hills plateau mountains peaks\n"
            f"frozen:1 — заморозка | coastal:1 — прибрежная\n"
            f"aa_gun — ПВО защитника\n"
            f"Далее юниты гарнизона: rifle:N tank:N ship:N ..."
        )
        for admin_id in admin_ids:
            try:
                bot.send_message(admin_id, admin_msg)
            except:
                pass

    # ----------------------------------------------------------------
    # 2. АДМИН — /calcN
    # ----------------------------------------------------------------
    @bot.message_handler(func=lambda m: m.text and re.match(r'^/calc(\d+)', m.text))
    def handle_calc(message):
        if message.from_user.id not in admin_ids:
            return

        req_id = int(re.match(r'^/calc(\d+)', message.text).group(1))
        req = _db("SELECT attacker_id, attacker_username, units_json, status FROM attack_requests WHERE id=?",
                  (req_id,), fetchone=True)

        if not req:
            return bot.reply_to(message, f"Заявка #{req_id} не найдена.")
        if req[3] != 'pending':
            return bot.reply_to(message, f"Заявка #{req_id} уже обработана (статус: {req[3]}).")

        attacker_id, attacker_uname, units_json, _ = req
        attacker_units = json.loads(units_json)

        terrain, frozen, coastal, def_aa_gun, def_ground, def_navy = parse_calc_args(message.text)

        if not terrain:
            return bot.reply_to(message,
                "❌ Укажи рельеф. Пример:\n"
                f"/calc{req_id} plains:50 hills:30 mountains:20 frozen:0 coastal:0 aa_gun:5 rifle:200 tank:10"
            )

        result = calculate_battle(
            attacker_units=attacker_units,
            terrain=terrain,
            frozen=frozen,
            coastal=coastal,
            def_aa_gun=def_aa_gun,
            def_navy_units=def_navy,
            def_ground_units=def_ground,
            attacker_uid=attacker_id
        )

        pending_calcs[req_id] = {
            'attacker_id': attacker_id,
            'attacker_username': attacker_uname,
            'attacker_units': attacker_units,
            'def_ground': def_ground,
            'result': result
        }

        card = format_calc_card(req_id, attacker_id, attacker_uname, attacker_units, result)
        bot.reply_to(message, card)

    # ----------------------------------------------------------------
    # 3. АДМИН — /approveN
    # ----------------------------------------------------------------
    @bot.message_handler(func=lambda m: m.text and re.match(r'^/approve(\d+)', m.text))
    def handle_approve(message):
        if message.from_user.id not in admin_ids:
            return

        req_id = int(re.match(r'^/approve(\d+)', message.text).group(1))

        if req_id not in pending_calcs:
            return bot.reply_to(message, f"❌ Сначала введи /calc{req_id} для расчёта.")

        calc = pending_calcs[req_id]
        req = _db("SELECT attacker_id, chat_id, status FROM attack_requests WHERE id=?", (req_id,), fetchone=True)

        if not req or req[2] != 'pending':
            return bot.reply_to(message, f"Заявка #{req_id} уже обработана.")

        attacker_id = calc['attacker_id']
        atk_losses = calc['result']['suggested_atk_losses']
        def_losses = calc['result']['suggested_def_losses']

        _apply_and_finalize(bot, req_id, calc, atk_losses, def_losses, message, admin_ids)
        pending_calcs.pop(req_id, None)

    # ----------------------------------------------------------------
    # 4. АДМИН — /lossesN a:rifle-30,tank-2 d:rifle-100,tank-5
    # ----------------------------------------------------------------
    @bot.message_handler(func=lambda m: m.text and re.match(r'^/losses(\d+)', m.text))
    def handle_losses(message):
        if message.from_user.id not in admin_ids:
            return

        req_id = int(re.match(r'^/losses(\d+)', message.text).group(1))

        if req_id not in pending_calcs:
            return bot.reply_to(message, f"❌ Сначала введи /calc{req_id} для расчёта.")

        req = _db("SELECT status FROM attack_requests WHERE id=?", (req_id,), fetchone=True)
        if not req or req[0] != 'pending':
            return bot.reply_to(message, f"Заявка #{req_id} уже обработана.")

        atk_losses, def_losses = parse_losses_args(message.text)
        calc = pending_calcs[req_id]

        _apply_and_finalize(bot, req_id, calc, atk_losses, def_losses, message, admin_ids)
        pending_calcs.pop(req_id, None)

    # ----------------------------------------------------------------
    # 5. АДМИН — /rejectN
    # ----------------------------------------------------------------
    @bot.message_handler(func=lambda m: m.text and re.match(r'^/reject(\d+)', m.text))
    def handle_reject(message):
        if message.from_user.id not in admin_ids:
            return

        req_id = int(re.match(r'^/reject(\d+)', message.text).group(1))
        req = _db("SELECT attacker_id, chat_id, status FROM attack_requests WHERE id=?", (req_id,), fetchone=True)

        if not req:
            return bot.reply_to(message, f"Заявка #{req_id} не найдена.")
        if req[2] != 'pending':
            return bot.reply_to(message, f"Заявка #{req_id} уже обработана.")

        attacker_id, chat_id, _ = req
        _db("UPDATE attack_requests SET status='rejected' WHERE id=?", (req_id,))

        bot.reply_to(message, f"❌ Заявка #{req_id} отклонена.")

        # Уведомить игрока
        try:
            bot.send_message(attacker_id, f"❌ Ваша заявка на наступление #{req_id} отклонена администратором.\n🔓 Войска разморожены.")
        except:
            pass

        # Публикация в игровой чат
        if chat_id:
            try:
                attacker_uname = _db("SELECT username FROM users WHERE user_id=?", (attacker_id,), fetchone=True)
                uname = attacker_uname[0] if attacker_uname else str(attacker_id)
                bot.send_message(chat_id, f"🚫 Наступление @{uname} отклонено администратором.")
            except:
                pass

        pending_calcs.pop(req_id, None)


    # ----------------------------------------------------------------
    # 6. ИГРОК — /mystrike (статус своей заявки)
    # ----------------------------------------------------------------
    @bot.message_handler(commands=['mystrike'])
    def handle_mystrike(message):
        uid = message.from_user.id
        req = _db(
            "SELECT id, units_json, status, created_at FROM attack_requests WHERE attacker_id=? ORDER BY id DESC LIMIT 1",
            (uid,), fetchone=True
        )
        if not req:
            return bot.reply_to(message, "У вас ещё не было заявок на наступление.")

        req_id, units_json, status, created_at = req
        units = json.loads(units_json)
        stats = _get_unit_stats()

        import datetime
        dt = datetime.datetime.fromtimestamp(created_at).strftime('%d.%m %H:%M')

        status_emoji = {
            'pending':  '⏳ Ожидает решения',
            'approved': '✅ Подтверждена',
            'rejected': '❌ Отклонена',
        }.get(status, status)

        units_str = ', '.join(
            f"{stats[u]['display']} x{q}" for u, q in units.items() if u in stats
        )

        frozen_str = ''
        if status == 'pending':
            frozen = _get_frozen_units(uid)
            if frozen:
                frozen_str = '\n🔒 Заморожено: ' + ', '.join(
                    f"{stats[u]['display']} x{q}" for u, q in frozen.items() if u in stats
                )

        bot.reply_to(message,
            f"⚔️ Заявка #{req_id} ({dt})\n"
            f"Статус: {status_emoji}\n"
            f"Войска: {units_str}"
            f"{frozen_str}"
        )

    # ----------------------------------------------------------------
    # 7. ИГРОК/АДМИН — /warhistory (история боёв)
    # ----------------------------------------------------------------
    @bot.message_handler(commands=['warhistory'])
    def handle_warhistory(message):
        uid = message.from_user.id
        is_admin = uid in admin_ids

        if is_admin:
            # Админ видит все последние 10 боёв
            rows = _db(
                "SELECT id, attacker_username, status, created_at FROM attack_requests ORDER BY id DESC LIMIT 10"
            )
            if not rows:
                return bot.reply_to(message, "Боевых заявок ещё не было.")
            import datetime
            lines = ["📋 Последние заявки (все):"]
            for rid, uname, status, cat in rows:
                dt = datetime.datetime.fromtimestamp(cat).strftime('%d.%m %H:%M')
                emoji = {'pending': '⏳', 'approved': '✅', 'rejected': '❌'}.get(status, '?')
                lines.append(f"  #{rid} {emoji} @{uname} — {dt}")
            bot.reply_to(message, '\n'.join(lines))
        else:
            # Игрок видит свои последние 5 боёв
            rows = _db(
                "SELECT id, units_json, status, created_at FROM attack_requests WHERE attacker_id=? ORDER BY id DESC LIMIT 5",
                (uid,)
            )
            if not rows:
                return bot.reply_to(message, "У вас ещё не было заявок на наступление.")
            import datetime
            stats = _get_unit_stats()
            lines = ["⚔️ Ваши последние наступления:"]
            for rid, units_json, status, cat in rows:
                dt = datetime.datetime.fromtimestamp(cat).strftime('%d.%m %H:%M')
                emoji = {'pending': '⏳', 'approved': '✅', 'rejected': '❌'}.get(status, '?')
                units = json.loads(units_json)
                units_str = ', '.join(
                    f"{stats[u]['display']} x{q}" for u, q in units.items() if u in stats
                )
                lines.append(f"  #{rid} {emoji} {dt} — {units_str}")
            bot.reply_to(message, '\n'.join(lines))

    # ----------------------------------------------------------------
    # 8. АДМИН — /strikes (все активные pending заявки)
    # ----------------------------------------------------------------
    @bot.message_handler(commands=['strikes'])
    def handle_strikes(message):
        if message.from_user.id not in admin_ids:
            return
        rows = _db(
            "SELECT id, attacker_username, units_json, created_at FROM attack_requests WHERE status='pending' ORDER BY id ASC"
        )
        if not rows:
            return bot.reply_to(message, "Активных заявок нет.")
        import datetime
        stats = _get_unit_stats()
        lines = ["⏳ Активные заявки на наступление:"]
        for rid, uname, units_json, cat in rows:
            dt = datetime.datetime.fromtimestamp(cat).strftime('%d.%m %H:%M')
            units = json.loads(units_json)
            units_str = ', '.join(
                f"{stats[u]['display']} x{q}" for u, q in units.items() if u in stats
            )
            lines.append(f"  #{rid} @{uname} ({dt}):\n    {units_str}\n    /calc{rid} ...")
        bot.reply_to(message, '\n'.join(lines))


def _apply_and_finalize(bot, req_id, calc, atk_losses, def_losses, admin_message, admin_ids):
    """Применяет потери, закрывает заявку, публикует итог"""
    stats = _get_unit_stats()
    req = _db("SELECT attacker_id, chat_id FROM attack_requests WHERE id=?", (req_id,), fetchone=True)
    attacker_id = calc['attacker_id']
    attacker_uname = calc['attacker_username']
    chat_id = req[1] if req else 0
    result = calc['result']

    # Применяем потери атакующему
    apply_losses(attacker_id, atk_losses)

    # Применяем потери защитнику — ищем владельца юнитов гарнизона
    # (защитник идентифицируется через def_ground — в текущей версии просто логируем)
    # TODO: когда будет система клеток — списывать у конкретного игрока

    # Закрываем заявку
    _db("UPDATE attack_requests SET status='approved' WHERE id=?", (req_id,))

    # Формируем итоговое сообщение
    winner_str = {
        'attacker': f"🏆 Победитель: 🔴 АТАКУЮЩИЙ",
        'defender': f"🏆 Победитель: 🔵 ЗАЩИТНИК",
        'draw':     f"🏆 НИЧЬЯ"
    }[result['winner']]

    atk_loss_parts = []
    for unit, loss in atk_losses.items():
        disp = stats.get(unit, {}).get('display', unit)
        atk_loss_parts.append(f"{disp} -{loss}")

    def_loss_parts = []
    for unit, loss in def_losses.items():
        disp = stats.get(unit, {}).get('display', unit)
        def_loss_parts.append(f"{disp} -{loss}")

    terrain = result['terrain']
    terrain_str = " | ".join(
        f"{TERRAIN_NAMES.get(t, t)} {pct}%" for t, pct in terrain.items() if pct > 0
    )

    pub_text = (
        f"⚔️ РЕЗУЛЬТАТ БОЕВЫХ ДЕЙСТВИЙ #{req_id}\n\n"
        f"🔴 @{attacker_uname} ({_get_country(attacker_id)}) наступает\n"
        f"🗺️ Рельеф: {terrain_str}"
    )
    if result['frozen']:
        pub_text += " ❄️"
    pub_text += (
        f"\n\n💥 Атака: {int(result['total_attack'])} | 🛡️ Оборона: {int(result['def_total'])}\n"
        f"{winner_str}\n\n"
        f"📉 Потери атакующего: {', '.join(atk_loss_parts) or 'нет'}\n"
        f"📉 Потери защитника: {', '.join(def_loss_parts) or 'нет'}"
    )

    # Публикуем в игровой чат
    if chat_id:
        try:
            bot.send_message(chat_id, pub_text)
        except:
            pass

    # Подтверждение админу
    bot.reply_to(admin_message, f"✅ Заявка #{req_id} подтверждена. Итог опубликован.")

    # Уведомление игроку
    try:
        result_for_player = "🏆 Ваше наступление УСПЕШНО!" if result['winner'] == 'attacker' else "❌ Ваше наступление ОТБИТО."
        atk_loss_str = ', '.join(atk_loss_parts) or 'нет'
        bot.send_message(attacker_id,
            f"⚔️ Заявка #{req_id} обработана.\n{result_for_player}\nВаши потери: {atk_loss_str}")
    except:
        pass
