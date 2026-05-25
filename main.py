import os
import json
import random
from typing import List, Dict, Optional
from dotenv import load_dotenv

# ==============================================================================
# 0. 環境設定
# ==============================================================================
load_dotenv()
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek").lower()
LLM_API_KEY  = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_MODEL    = os.getenv("LLM_MODEL", "")

_DEFAULTS = {
    "deepseek":  {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "openai":    {"base_url": "https://api.openai.com/v1",   "model": "gpt-4o-mini"},
    "anthropic": {"base_url": "",                             "model": "claude-haiku-4-5-20251001"},
    "local":     {"base_url": "http://localhost:11434/v1",    "model": "llama3"},
}
def _resolve(key: str) -> str:
    v = {"base_url": LLM_BASE_URL, "model": LLM_MODEL}[key]
    return v if v else _DEFAULTS.get(LLM_PROVIDER, {}).get(key, "")

RESOLVED_BASE_URL = _resolve("base_url")
RESOLVED_MODEL    = _resolve("model")
if not LLM_API_KEY and LLM_PROVIDER != "local":
    raise ValueError(f"⚠️ .env に 'LLM_API_KEY' が未設定です。(provider={LLM_PROVIDER})")

# ==============================================================================
# 1. LLM 汎用クライアント
# ==============================================================================
class LLMClient:
    def __init__(self):
        self.provider = LLM_PROVIDER
        self.model    = RESOLVED_MODEL
        if self.provider in ("deepseek", "openai", "local"):
            from openai import OpenAI
            kw = {"api_key": LLM_API_KEY or "local"}
            if RESOLVED_BASE_URL: kw["base_url"] = RESOLVED_BASE_URL
            self._client = OpenAI(**kw)
        elif self.provider == "anthropic":
            import anthropic
            self._client = anthropic.Anthropic(api_key=LLM_API_KEY)
        else:
            raise ValueError(f"未対応プロバイダ: {self.provider}")

    def ask_json(self, prompt: str) -> dict:
        sys_msg = ("You are a game engine backend. "
                   "Respond ONLY with a valid JSON object. No markdown, no extra text.")
        try:
            if self.provider in ("deepseek", "openai", "local"):
                extra = {}
                if self.provider in ("deepseek", "openai"):
                    extra["response_format"] = {"type": "json_object"}
                r = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": sys_msg},
                               {"role": "user",   "content": prompt}],
                    temperature=0.3, **extra)
                raw = r.choices[0].message.content or "{}"
            elif self.provider == "anthropic":
                r = self._client.messages.create(
                    model=self.model, max_tokens=512, system=sys_msg,
                    messages=[{"role": "user", "content": prompt}])
                raw = r.content[0].text if r.content else "{}"
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"): raw = raw[4:]
            return json.loads(raw)
        except Exception as e:
            print(f"【APIエラー】({self.provider}): {e}")
            return {}

llm = LLMClient()

# ==============================================================================
# 2. マップ・時間・アイテム定義
# ==============================================================================
MAP = {
    "corridor":          {"name": "廊下",      "links": ["entertainment_room", "shower_room", "lounge"]},
    "entertainment_room":{"name": "娯楽室",    "links": ["corridor"]},
    "shower_room":       {"name": "シャワー室", "links": ["corridor"]},
    "lounge":            {"name": "ラウンジ",   "links": ["corridor", "cell", "court"]},
    "cell":              {"name": "監房",       "links": ["lounge"]},
    "court":             {"name": "裁判所",     "links": ["lounge"]},
    "punishment_cell":   {"name": "懲罰房",     "links": []},
}
TIME_SLOTS = ["6:00", "10:00", "12:00", "15:00", "17:00", "22:00"]

# アイテム定義。location は room_id かキャラ名("ema"等) か "player"
ITEMS: Dict[str, dict] = {
    "crossbow": {"name": "クロスボウ", "is_weapon": True},
}

# ==============================================================================
# 3. データ構造
# ==============================================================================
class MemoryLog:
    def __init__(self, who: str, when: str, where: str, how: str, why_stress: int):
        self.who = who; self.when = when; self.where = where
        self.how = how; self.why_stress = why_stress; self.turns_left = 3

    def age_memory(self):
        self.turns_left -= 1
        if   self.turns_left == 2: self.where = list({self.where, "廊下", "ラウンジ"})
        elif self.turns_left == 1: self.when  = list({self.when,  "6:00", "12:00", "22:00"})
        elif self.turns_left <= 0: self.who = self.when = self.where = self.how = None

    def to_dict(self) -> dict:
        return {"who": self.who, "when": self.when, "where": self.where, "how": self.how}


class MagicalGirl:
    def __init__(self, name, jp_name, personality, magic, prompt_hint):
        self.name = name; self.jp_name = jp_name
        self.personality = personality; self.magic = magic; self.prompt_hint = prompt_hint
        self.stress = 20; self.location = "cell"; self.punished_turns = 0; self.is_alive = True
        self.hate: Dict[str, int] = {"ema": 10, "sherry": 10, "hanna": 10, "player": 10}
        self.love: Dict[str, int] = {"ema": 10, "sherry": 10, "hanna": 10, "player": 10}
        self.memories: List[MemoryLog] = []


class Guard:
    def __init__(self, name):
        self.name = name
        self.route = ["corridor", "entertainment_room", "shower_room", "lounge"]
        self.route_index = random.randint(0, 3)
        self.location = self.route[self.route_index]

    def move(self):
        self.route_index = (self.route_index + 1) % len(self.route)
        self.location = self.route[self.route_index]


class PlayerState:
    def __init__(self):
        self.location = "lounge"; self.punished_turns = 0; self.is_caught = False
        self.witness_logs: List[str] = []  # プレイヤーが目撃した情報（裁判で参照可）


class GameState:
    def __init__(self):
        self.day = 1; self.time_index = 0
        self.truth_logs: List[MemoryLog] = []
        self.dead_bodies: Dict[str, str] = {}
        self.murder_this_turn = False
        self.item_locations: Dict[str, str] = {"crossbow": "lounge"}  # アイテム位置

    @property
    def current_time(self): return TIME_SLOTS[self.time_index]

    def get_phase_rule(self) -> dict:
        t = self.current_time
        if t == "6:00":  return {"info": "自由行動時間 (朝食)",          "out_ban": False, "type": "free"}
        if t == "10:00": return {"info": "監房強制リセット（全員点呼）", "out_ban": True,  "type": "cell_reset"}
        if t == "12:00": return {"info": "自由行動時間 (昼食)",          "out_ban": False, "type": "free"}
        if t == "15:00": return {"info": "監房強制リセット（全員点呼）", "out_ban": True,  "type": "cell_reset"}
        if t == "17:00": return {"info": "自由行動時間 (夕食)",          "out_ban": False, "type": "free"}
        if t == "22:00": return {"info": "外出禁止時間 (就寝)",          "out_ban": True,  "type": "free"}
        return {"info": "自由行動", "out_ban": False, "type": "free"}

    def next_time(self):
        self.time_index = (self.time_index + 1) % len(TIME_SLOTS)
        if self.time_index == 0: self.day += 1
        self.murder_this_turn = False

    def holding(self, who: str) -> List[str]:
        """whoが所持しているアイテムIDリスト"""
        return [i for i, loc in self.item_locations.items() if loc == who]

    def item_at(self, room_id: str) -> List[str]:
        """room_idに置かれているアイテムIDリスト"""
        return [i for i, loc in self.item_locations.items() if loc == room_id]

# ==============================================================================
# 4. ユーティリティ
# ==============================================================================
def alive_in(girls: Dict[str, MagicalGirl], room_id: str) -> List[MagicalGirl]:
    return [g for g in girls.values() if g.is_alive and g.location == room_id]

def room_label(room_id: str) -> str:
    return MAP[room_id]["name"]

def show_location(loc: str, girls: Dict[str, MagicalGirl], state: GameState):
    present = alive_in(girls, loc)
    names   = "、".join(g.jp_name for g in present) if present else "誰もいない"
    items   = "、".join(ITEMS[i]["name"] for i in state.item_at(loc))
    item_str = f"  アイテム: [{items}]" if items else ""
    print(f"\n現在地: {room_label(loc)}  |  同室: [{names}]{item_str}")

# ==============================================================================
# 5. AI 関数
# ==============================================================================
def ai_choose_action(girl: MagicalGirl, available_actions: List[dict],
                     current_time: str, weapon_room: Optional[str]) -> dict:
    """
    display_message: 周囲に見せる無害なセリフ（殺害選択時も自然に見える）
    selected_index : 実際に行う行動
    """
    weapon_hint = ""
    if girl.stress >= 70 and weapon_room:
        weapon_hint = (f"\n【重要】ストレスが極限に達している。クロスボウは{room_label(weapon_room)}にある。"
                       f"まず武器を入手し、その後ターゲットを殺害することを優先せよ。")

    meal_hint = ""
    if girl.personality == "extrovert" and "食" in current_time:
        meal_hint = "\n【補足】外向的な性格なので、食事の時間はラウンジへ向かいやすい。"

    prompt = f"""
キャラクター: {girl.jp_name} (性格: {girl.personality}, ストレス: {girl.stress}/100)
口調ルール: {girl.prompt_hint}
現在時刻: {current_time}{weapon_hint}{meal_hint}

【実行可能な行動リスト（index 0始まり）】
{json.dumps(available_actions, ensure_ascii=False, indent=2)}

【ルール】
- selected_index はリストの番号（0始まり）。
- display_message は選んだ行動の内容に沿った自然なセリフ。
  - 殺害を選んだ場合でも display_message は殺意を一切含まないこと。
    他の少女と同様に「疲れた」「休もう」などの日常的なセリフにすること。

【出力フォーマット（JSONのみ）】
{{
  "selected_index": int,
  "display_message": "周囲に見えるセリフ（常に日常的・無害な内容）"
}}
"""
    res = llm.ask_json(prompt)
    return res if res else {"selected_index": 0, "display_message": "……。"}


def ai_respond_to_player(girl: MagicalGirl, msg: str, current_time: str) -> str:
    prompt = f"""
あなたは{girl.jp_name}です。口調: {girl.prompt_hint}
状態: ストレス={girl.stress}/100, プレイヤーへの疑惑度={girl.hate['player']}/100
現在時刻: {current_time}
プレイヤーの発言: 「{msg}」
1〜2文で返答。
{{"reply": "セリフ"}}"""
    return llm.ask_json(prompt).get("reply", "……何よ。")


def ai_evaluate_interaction(girl: MagicalGirl, msg: str, reply: str) -> dict:
    prompt = f"""
キャラ: {girl.jp_name}
プレイヤー発言: 「{msg}」
キャラ返答: 「{reply}」
ストレスと疑惑度の変動を判定。親切→負、煽り→正。範囲-20〜+20。
{{"stress_change": int, "hate_change": int}}"""
    return llm.ask_json(prompt) or {"stress_change": 0, "hate_change": 0}


def ai_court_debate(girl: MagicalGirl, evidence: str,
                    suspect_ids: List[str], history: List[str],
                    witness_context: str) -> dict:
    """
    suspect は player 以外の生存者から選ぶ。
    Python側でも suspect=="player" なら無効として扱う。
    """
    mem_str = json.dumps([m.to_dict() for m in girl.memories if m.who], ensure_ascii=False)
    prompt = f"""
登場人物: {girl.jp_name}（id: {girl.name}）口調: {girl.prompt_hint}
記憶ログ（曖昧）: {mem_str}
{f"【目撃情報（信頼度高）】{witness_context}" if witness_context else ""}

議論履歴:
{chr(10).join(history)}

プレイヤーの主張: 「{evidence}」

【判定】
1. is_logical: 記憶・状況と照合して論理的か（bool）
2. suspect: is_logicalがtrueの場合、最も怪しいキャラのid
   - 選択肢: {suspect_ids}（この中から必ず選ぶ。"player"は絶対に選ばない）
3. speech: 口調を守った裁判でのセリフ

{{"speech": str, "is_logical": bool, "suspect": str_or_null}}"""
    return llm.ask_json(prompt)

# ==============================================================================
# 6. ゲーム初期化・行動生成
# ==============================================================================
def setup_game():
    girls = {
        "ema": MagicalGirl("ema", "桜羽エマ", "extrovert", "none",
            "一人称「ボク」。ボーイッシュで正義感強くハキハキ。"
            "思ったことをそのまま言う。嘘が苦手。他人に嫌われることを極端に怖がる。敬語不使用。"
            "例:「ボクはそう思わないけど」「それ、おかしくない？」"),
        "sherry": MagicalGirl("sherry", "橘シェリー", "extrovert", "monster_strength",
            "一人称「私」。名探偵自称、好奇心旺盛。常に元気、空気読まない。道徳心なし。"
            "例:「面白いじゃないですか！」「え、なんで怒ってるんですか？」"),
        "hanna": MagicalGirl("hanna", "遠野ハンナ", "introvert", "fly",
            "一人称「わたくし」。貧乏出身だがお嬢様口調で高慢。内心は臆病で不安定。"
            "例:「わたくしには関係ありませんわ」「……べ、別に怖くなんてありませんのよ」"),
    }
    return girls, [Guard("看守A"), Guard("看守B")], GameState(), PlayerState()


def generate_available_actions(girl: MagicalGirl, state: GameState,
                                girls: Dict[str, MagicalGirl]) -> List[dict]:
    rule    = state.get_phase_rule()
    actions = []

    if girl.location == "punishment_cell":
        return [{"action": "待機", "target": "punishment_cell", "description": "懲罰房で大人しく過ごす"}]

    if rule["type"] == "cell_reset":
        if girl.location != "cell":
            return [{"action": "部屋移動", "target": "cell", "description": "監房に戻る（強制ルール）"}]
        return [{"action": "待機", "target": "none", "description": "監房で大人しく過ごす"}]

    # 移動
    for rid in MAP[girl.location]["links"]:
        if rid != "court":
            actions.append({"action": "部屋移動", "target": rid,
                             "description": f"{room_label(rid)}へ移動する"})
    # 食事
    if girl.location == "lounge" and "食" in rule["info"]:
        actions.append({"action": "食事", "target": "lounge", "description": "ラウンジでご飯を食べる"})

    # アイテム取得
    for item_id in state.item_at(girl.location):
        actions.append({"action": "アイテム取得", "target": item_id,
                         "description": f"{ITEMS[item_id]['name']}を取得する"})

    # 殺害（武器所持 + ストレス70以上 + 今ターン未発生）
    has_weapon = any(ITEMS[i].get("is_weapon") for i in state.holding(girl.name))
    if girl.stress >= 70 and has_weapon and not state.murder_this_turn:
        room_targets = [n for n, g in girls.items()
                        if g.location == girl.location and n != girl.name and g.is_alive]
        if room_targets:
            actions.append({"action": "殺害", "target": "any",
                             "description": "同じ部屋にいる誰かを密かに殺害する（クロスボウを使用）"})

    actions.append({"action": "待機", "target": "none",
                    "description": f"{room_label(girl.location)}で静かに過ごす"})
    return actions

# ==============================================================================
# 7. プレイヤー行動フェーズ
# ==============================================================================
def handle_player_turn(state: GameState, girls: Dict[str, MagicalGirl], player: PlayerState, rule: dict):
    if player.is_caught:
        player.punished_turns -= 1
        print(f"⛓️  懲罰房に拘束中（残り {player.punished_turns} ターン）")
        if player.punished_turns <= 0:
            player.location = "cell"; player.is_caught = False
            print("解放されて監房に戻されました。")
        return

    # 点呼：強制移動（会話は可能）
    if rule["type"] == "cell_reset" and player.location != "cell":
        player.location = "cell"
        print("⚡ 点呼。監房へ強制移動しました。")

    # ── STEP 1: 移動 ─────────────────────────────────────
    show_location(player.location, girls, state)

    adjacent = [r for r in MAP[player.location]["links"]
                if r not in ("court", "punishment_cell")]

    print("\n【移動先を選んでください】")
    print(f"  [0] その場に留まる（{room_label(player.location)}）")
    for i, rid in enumerate(adjacent, 1):
        print(f"  [{i}] {room_label(rid)}へ移動する")

    try:
        idx = int(input("選択: ").strip())
        if 1 <= idx <= len(adjacent):
            player.location = adjacent[idx - 1]
            print(f"➡ {room_label(player.location)} に移動しました。")
    except ValueError:
        pass

    # ── STEP 2: 行動選択（会話・アイテム操作） ────────────
    show_location(player.location, girls, state)
    present = alive_in(girls, player.location)
    items   = state.item_at(player.location)
    held    = state.holding("player")

    options = [("なし", "何もしない")]
    for g in present:
        options.append(("talk", g))
    for item_id in items:
        options.append(("pickup", item_id))
    for item_id in held:
        options.append(("drop", item_id))

    print("\n【行動を選んでください】")
    print(f"  [0] 何もしない")
    for i, (kind, val) in enumerate(options[1:], 1):
        if kind == "talk":
            print(f"  [{i}] {val.jp_name}に話しかける")
        elif kind == "pickup":
            print(f"  [{i}] {ITEMS[val]['name']}を拾う")
        elif kind == "drop":
            print(f"  [{i}] {ITEMS[val]['name']}を置く")

    try:
        choice = int(input("選択: ").strip())
        if choice == 0 or choice >= len(options):
            return
        kind, val = options[choice]

        if kind == "talk":
            target = val
            msg   = input(f"[{target.jp_name}への発言]: ")
            reply = ai_respond_to_player(target, msg, state.current_time)
            print(f"\n[{target.jp_name}]: 「{reply}」")
            ev = ai_evaluate_interaction(target, msg, reply)
            target.stress           = max(0, min(100, target.stress + ev.get("stress_change", 0)))
            target.hate["player"]   = max(0, min(100, target.hate["player"] + ev.get("hate_change", 0)))
            print(f"（ストレス={ev.get('stress_change',0):+} / 疑惑度={ev.get('hate_change',0):+}）")
            target.memories.append(MemoryLog("player", state.current_time, player.location,
                                             f"プレイヤーとの会話: {msg}", target.stress))

        elif kind == "pickup":
            state.item_locations[val] = "player"
            print(f"✅ {ITEMS[val]['name']}を拾いました。")
            player.witness_logs.append(
                f"[{state.current_time}] {room_label(player.location)}で{ITEMS[val]['name']}を取得した")

        elif kind == "drop":
            state.item_locations[val] = player.location
            print(f"📦 {ITEMS[val]['name']}を{room_label(player.location)}に置きました。")

    except (ValueError, IndexError):
        pass

# ==============================================================================
# 8. メインループ
# ==============================================================================
def main_loop():
    girls, guards, state, player = setup_game()
    print("=" * 50)
    print(" 🩸 manosaba3d 1Dプロトタイプ Ver 2.3")
    print(f"    LLM: {LLM_PROVIDER} / {RESOLVED_MODEL}")
    print("=" * 50)

    while True:
        rule = state.get_phase_rule()
        print(f"\n{'='*50}")
        print(f"【Day {state.day} - {state.current_time}】 {rule['info']}")
        print("=" * 50)

        for g in guards: g.move()

        # ストレス上昇（個人差あり）
        for girl in girls.values():
            if girl.is_alive and girl.location != "punishment_cell":
                base = random.randint(2, 7) if girl.personality == "introvert" else random.randint(3, 12)
                girl.stress = min(100, girl.stress + base)

        # 同室不和（40%確率）
        ids = list(girls.keys())
        for i, na in enumerate(ids):
            for nb in ids[i+1:]:
                ga, gb = girls[na], girls[nb]
                if ga.is_alive and gb.is_alive and ga.location == gb.location:
                    if random.random() < 0.4:
                        for g, other in [(ga, nb), (gb, na)]:
                            g.stress      = min(100, g.stress + 8)
                            g.hate[other] = min(100, g.hate[other] + 10)

        # 死体発見チェック
        for room_id, victim in list(state.dead_bodies.items()):
            if player.location == room_id and not player.is_caught:
                print(f"\n🚨【事件発生】{room_label(room_id)}で{girls[victim].jp_name}の死体を発見！")
                run_court_phase(girls, state, player, victim)
                return

        # ステータス表示
        print("\n--- 魔法少女たちの現在のステータス ---")
        for name, g in girls.items():
            loc = room_label(g.location) if g.is_alive else "死亡"
            held = "、".join(ITEMS[i]["name"] for i in state.holding(name))
            held_str = f" 【{held}】" if held else ""
            print(f" ・{g.jp_name}: {loc} | ストレス: {g.stress}/100{held_str}")
        held_p = "、".join(ITEMS[i]["name"] for i in state.holding("player"))
        print(f" [看守] A: {room_label(guards[0].location)}, B: {room_label(guards[1].location)}")
        if held_p: print(f" [所持品] {held_p}")

        # プレイヤー行動
        handle_player_turn(state, girls, player, rule)

        # AI少女の自律行動
        print("\n--- 魔法少女たちの行動 ---")
        for name, girl in girls.items():
            if not girl.is_alive: continue

            if girl.location == "punishment_cell":
                girl.punished_turns -= 1
                if girl.punished_turns <= 0: girl.location = "cell"
                print(f" ・{girl.jp_name}: 懲罰房で隔離中...")
                continue

            available = generate_available_actions(girl, state, girls)

            # 武器がどこにあるか（殺意があるが未所持の場合にヒントとして渡す）
            weapon_room = None
            if girl.stress >= 70 and not state.holding(girl.name):
                for item_id, loc in state.item_locations.items():
                    if ITEMS[item_id].get("is_weapon") and loc in MAP:
                        weapon_room = loc

            ai_res  = ai_choose_action(girl, available, state.current_time, weapon_room)
            idx     = min(ai_res.get("selected_index", 0), len(available) - 1)
            chosen  = available[idx]
            display = ai_res.get("display_message", "……。")

            # 殺害時は行動説明をカモフラージュ
            if chosen["action"] == "殺害":
                shown_desc = f"{room_label(girl.location)}で静かに過ごす"
            else:
                shown_desc = chosen["description"]

            print(f" ・{girl.jp_name}: 「{display}」 ({shown_desc})")

            # 実際の行動処理
            if chosen["action"] == "部屋移動":
                girl.location = chosen["target"]
                girl.memories.append(MemoryLog(girl.name, state.current_time, girl.location, "移動", girl.stress))

            elif chosen["action"] == "食事":
                girl.stress = max(0, girl.stress - 25)

            elif chosen["action"] == "アイテム取得":
                state.item_locations[chosen["target"]] = girl.name
                girl.memories.append(MemoryLog(girl.name, state.current_time, girl.location,
                                                f"{ITEMS[chosen['target']]['name']}を取得", girl.stress))

            elif chosen["action"] == "殺害" and not state.murder_this_turn:
                targets = [n for n, g in girls.items()
                           if g.location == girl.location and n != girl.name and g.is_alive]
                if targets:
                    victim = random.choice(targets)
                    girls[victim].is_alive = False
                    state.dead_bodies[girl.location] = victim
                    state.murder_this_turn = True
                    state.truth_logs.append(
                        MemoryLog(girl.name, state.current_time, girl.location, "クロスボウ", girl.stress))

                    # 同室の別キャラに目撃ログ
                    for wname, witness in girls.items():
                        if (witness.is_alive and witness.location == girl.location
                                and wname not in (girl.name, victim)):
                            witness.memories.append(MemoryLog(
                                girl.name, state.current_time, girl.location,
                                f"クロスボウで{girls[victim].jp_name}を殺害", girl.stress))

                    # プレイヤーが同室→現行犯
                    if player.location == girl.location and not player.is_caught:
                        player.witness_logs.append(
                            f"[{state.current_time}] {room_label(girl.location)}で"
                            f"{girl.jp_name}が{girls[victim].jp_name}をクロスボウで殺害するのを目撃")
                        print(f"\n🚨【現行犯！】{girl.jp_name}が{girls[victim].jp_name}を殺害するのを目撃！")
                        run_court_phase(girls, state, player, victim)
                        return

        # 看守検問（少女・プレイヤー共通）
        if rule["out_ban"]:
            for name, girl in girls.items():
                if girl.is_alive and girl.location not in ("cell", "punishment_cell"):
                    for g in guards:
                        if g.location == girl.location:
                            print(f"🚨【捕縛】{girl.jp_name}が{room_label(girl.location)}で発見→懲罰房！")
                            girl.location = "punishment_cell"; girl.punished_turns = 2
            if not player.is_caught and player.location not in ("cell", "punishment_cell"):
                for g in guards:
                    if g.location == player.location:
                        print(f"🚨【捕縛】あなたが{room_label(player.location)}で発見→懲罰房！")
                        player.location = "punishment_cell"; player.is_caught = True
                        player.punished_turns = 2; break

        # 忘却処理
        for girl in girls.values():
            for mem in girl.memories: mem.age_memory()

        state.next_time()

# ==============================================================================
# 9. 魔女裁判フェーズ
# ==============================================================================
def run_court_phase(girls: Dict[str, MagicalGirl], state: GameState,
                    player: PlayerState, victim_id: str):
    alive = {n: g for n, g in girls.items() if g.is_alive}
    if not alive:
        print("\n💀【詰み】生存者なし。裁判不成立。"); return

    print(f"\n{'='*50}\n ⚖️ 魔女裁判 開廷 ⚖️\n 被害者: {girls[victim_id].jp_name}")
    print(" 5ターンの間に証拠を突きつけ、犯人の疑惑度を上げろ！\n" + "="*50)

    for g in alive.values(): g.location = "court"
    player.location = "court"

    # 裁判でsuspect候補はplayerを除いた生存者のみ
    suspect_ids = list(alive.keys())
    history     = [f"裁判開始。被害者は{girls[victim_id].jp_name}。"]

    # プレイヤーの目撃情報を文字列化（裁判コンテキストに渡す）
    witness_ctx = "\n".join(player.witness_logs) if player.witness_logs else ""
    if witness_ctx:
        print(f"\n📋【あなたの目撃情報】\n{witness_ctx}\n")

    for turn in range(1, 6):
        print(f"\n【裁判ターン {turn} / 5】")
        evidence = input("主張を入力してください:\n> ")
        history.append(f"プレイヤーの主張: {evidence}")

        for name, girl in alive.items():
            res    = ai_court_debate(girl, evidence, suspect_ids, history, witness_ctx)
            speech = res.get("speech", "……。")
            print(f"[{girl.jp_name}]: 「{speech}」")
            history.append(f"{girl.jp_name}: {speech}")

            if res.get("is_logical", False):
                suspect = res.get("suspect")
                # player は suspect にしない（Python側ガード）
                if suspect and suspect in girl.hate and suspect != girl.name and suspect != "player":
                    girl.hate[suspect] += 25
                    print(f"  (➡ {girl.jp_name}は納得。{suspect}への疑惑度が上昇！)")
                else:
                    print(f"  (➡ {girl.jp_name}は考え込んでいる。)")
            else:
                girl.hate["player"] += 15
                print(f"  (➡ {girl.jp_name}はあなたを疑っている。プレイヤーへの疑惑度上昇。)")

    # 投票
    print(f"\n{'='*50}\n 🗳️ 投票の刻\n{'='*50}")
    votes = {k: 0 for k in suspect_ids + ["player"]}
    for name, girl in alive.items():
        candidates = {k: v for k, v in girl.hate.items() if k != girl.name and k in votes}
        if candidates:
            target = max(candidates, key=candidates.get)
            votes[target] += 1
            print(f" ・{girl.jp_name} → 【{target}】(疑惑度: {girl.hate[target]})")

    max_v      = max(votes.values(), default=0)
    candidates = [k for k, v in votes.items() if v == max_v and max_v > 0]
    if not candidates:
        print("有効票なし。裁判不成立。"); return
    executed = random.choice(candidates)

    print(f"\n最多票: 【{executed}】 の処刑が決定しました。")
    print("黒い鎖が天井から引きちぎるように伸び、肉体を締め上げる……。")

    real_killer = state.truth_logs[0].who if state.truth_logs else "不明"
    if executed == "player":
        print(f"\n💀【ゲームオーバー】あなたが処刑されました。真犯人は「{real_killer}」でした。")
    elif executed == real_killer:
        print(f"\n🎉【裁判勝利】真犯人「{girls[executed].jp_name}」を処刑しました！")
    else:
        name_ex = girls[executed].jp_name if executed in girls else executed
        print(f"\n💀【冤罪】「{name_ex}」は無実でした。真犯人は「{real_killer}」でした。")
    print("=" * 50)

if __name__ == "__main__":
    main_loop()