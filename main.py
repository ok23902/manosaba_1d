import os
import json
import random
from typing import List, Dict, Optional, Set, Tuple
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
    raise ValueError(f"⚠️ .env に 'LLM_API_KEY' が未設定 (provider={LLM_PROVIDER})")

# ==============================================================================
# 1. LLM クライアント（3回リトライ + テンプレートフォールバック）
# ==============================================================================
_TEMPLATES = {
    "choose":   {"selected_index": 0, "display_message": "……。"},
    "respond":  {"reply": "……。"},
    "evaluate": {"stress_change": 0, "hate_change": 0},
    "court":    {"speech": "……。", "is_logical": False, "suspect": None},
    "escape":   {"agreed": False, "speech": "……今は、考えられません。"},
}

class LLMClient:
    MAX_RETRY = 3

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

    def ask_json(self, prompt: str, fallback_key: str = "choose") -> dict:
        sys_msg = ("You are a game engine backend. "
                   "Respond ONLY with a valid JSON object. No markdown.")
        for attempt in range(self.MAX_RETRY):
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
                    raw = r.choices[0].message.content or ""
                elif self.provider == "anthropic":
                    r = self._client.messages.create(
                        model=self.model, max_tokens=512, system=sys_msg,
                        messages=[{"role": "user", "content": prompt}])
                    raw = r.content[0].text if r.content else ""
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"): raw = raw[4:]
                result = json.loads(raw)
                if result:
                    return result
            except Exception as e:
                if attempt == self.MAX_RETRY - 1:
                    print(f"【API×{self.MAX_RETRY}回失敗】テンプレ使用({fallback_key}): {e}")
        return dict(_TEMPLATES.get(fallback_key, {}))

llm = LLMClient()

# ==============================================================================
# 2. 定数定義
# ==============================================================================
MAP = {
    "corridor":           {"name": "廊下",      "links": ["entertainment_room", "shower_room", "lounge"]},
    "entertainment_room": {"name": "娯楽室",    "links": ["corridor"]},
    "shower_room":        {"name": "シャワー室", "links": ["corridor"]},
    "lounge":             {"name": "ラウンジ",   "links": ["corridor", "cell", "court"]},
    "cell":               {"name": "監房",       "links": ["lounge"]},
    "court":              {"name": "裁判所",     "links": ["lounge"]},
    "punishment_cell":    {"name": "懲罰房",     "links": []},
}
TIME_SLOTS = ["6:00", "10:00", "12:00", "15:00", "17:00", "22:00"]
TIME_RULES: Dict[str, dict] = {
    "6:00":  {"info": "自由行動時間 (朝食)",          "out_ban": False, "type": "free"},
    "10:00": {"info": "監房強制リセット（全員点呼）",  "out_ban": True,  "type": "cell_reset"},
    "12:00": {"info": "自由行動時間 (昼食)",           "out_ban": False, "type": "free"},
    "15:00": {"info": "監房強制リセット（全員点呼）",  "out_ban": True,  "type": "cell_reset"},
    "17:00": {"info": "自由行動時間 (夕食)",           "out_ban": False, "type": "free"},
    "22:00": {"info": "外出禁止時間 (就寝)",           "out_ban": True,  "type": "free"},
}
ITEMS: Dict[str, dict] = {
    "crossbow": {"name": "クロスボウ", "is_weapon": True},
    "knife":    {"name": "ナイフ",     "is_weapon": True},
}

# 殺害時の偽装セリフ（APIコスト削減）
_COVER: Dict[str, List[str]] = {
    "extrovert": ["「……なんか疲れたな。少し休もうかな。」",
                  "「今日はゆっくりしよう……。」",
                  "「なんか急に眠くなってきた……。」"],
    "introvert": ["「……静かにしていたい。」",
                  "「……少し目を閉じますわ。」",
                  "「……ここで待っていますわ。」"],
}
def cover_msg(personality: str) -> str:
    return random.choice(_COVER.get(personality, _COVER["introvert"]))

def item_disp(item_id: str, state) -> str:
    """血が付いていれば「🩸血のついた〇〇」"""
    base = ITEMS[item_id]["name"]
    return f"🩸血のついた{base}" if item_id in state.bloody_items else base

# ==============================================================================
# 3. データ構造
# ==============================================================================
class MemoryLog:
    """
    is_evidence=True のメモリは風化しない（探索フェーズで得た証拠など）
    """
    def __init__(self, who, when, where, how, why_stress, is_evidence=False):
        self.who        = who
        self.when       = when
        self.where      = where
        self.how        = how
        self.why_stress = why_stress
        self.turns_left = 3
        self.is_evidence = is_evidence

    def age_memory(self):
        if self.is_evidence:
            return
        self.turns_left -= 1
        if   self.turns_left == 2: self.where = list({self.where, "廊下", "ラウンジ"})
        elif self.turns_left == 1: self.when  = list({self.when, "6:00", "12:00", "22:00"})
        elif self.turns_left <= 0: self.who = self.when = self.where = self.how = None

    def to_dict(self) -> dict:
        return {"who": self.who, "when": self.when, "where": self.where, "how": self.how}


class Character:
    """少女・プレイヤー共通の基底構造（Issue #5: 完全に等しい構造で管理）"""
    def __init__(self, name: str, jp_name: str):
        self.name           = name
        self.jp_name        = jp_name
        self.stress         = 20
        self.location       = "cell"
        self.punished_turns = 0
        self.is_alive       = True
        self.is_caught      = False
        self.hate: Dict[str, int] = {}
        self.love: Dict[str, int] = {}
        self.memories: List[MemoryLog] = []


class MagicalGirl(Character):
    def __init__(self, name, jp_name, personality, magic, prompt_hint):
        super().__init__(name, jp_name)
        self.personality   = personality
        self.magic         = magic
        self.prompt_hint   = prompt_hint
        self.hide_evidence = False  # 証拠隠滅モード中フラグ


class PlayerCharacter(Character):
    def __init__(self):
        super().__init__("player", "あなた")
        self.location    = "lounge"
        self.personality = "extrovert"  # ストレス計算用


class Guard:
    def __init__(self, name):
        self.name        = name
        self.route       = ["corridor", "entertainment_room", "shower_room", "lounge"]
        self.route_index = random.randint(0, 3)
        self.location    = self.route[self.route_index]

    def move(self):
        self.route_index = (self.route_index + 1) % len(self.route)
        self.location    = self.route[self.route_index]


class EscapeProject:
    """気球脱出プロジェクト"""
    def __init__(self):
        self.progress = 0
        self.members: Set[str] = set()

    def tick(self, all_chars: Dict[str, Character]) -> bool:
        """ターン終了後に進捗を進める。100%達成でTrueを返す。"""
        active = [n for n in self.members
                  if n in all_chars and all_chars[n].is_alive and all_chars[n].stress < 70]
        if active:
            self.progress = min(100, self.progress + sum(random.randint(5, 15) for _ in active))
        return self.progress >= 100

    @property
    def bar(self) -> str:
        f = self.progress // 10
        return f"[{'█'*f}{'░'*(10-f)}] {self.progress}%"


class GameState:
    def __init__(self):
        self.day              = 1
        self.time_index       = 0
        self.truth_logs: List[MemoryLog] = []
        self.dead_bodies: Dict[str, str] = {}
        self.murder_this_turn = False
        self.item_locations: Dict[str, str] = {"crossbow": "lounge", "knife": "shower_room"}
        self.bloody_items: Set[str]  = set()
        self.escape = EscapeProject()

    @property
    def current_time(self) -> str:
        return TIME_SLOTS[self.time_index]

    def get_phase_rule(self) -> dict:
        return TIME_RULES.get(self.current_time, {"info": "自由行動", "out_ban": False, "type": "free"})

    def next_time(self):
        self.time_index = (self.time_index + 1) % len(TIME_SLOTS)
        if self.time_index == 0: self.day += 1
        self.murder_this_turn = False

    def holding(self, who: str) -> List[str]:
        return [i for i, loc in self.item_locations.items() if loc == who]

    def item_at(self, room_id: str) -> List[str]:
        return [i for i, loc in self.item_locations.items() if loc == room_id]

    def confiscate(self, who: str, drop_room: str):
        for item_id in self.holding(who):
            self.item_locations[item_id] = drop_room
            print(f"  📦 {ITEMS[item_id]['name']}が{MAP[drop_room]['name']}に没収されました。")

    def mark_bloody(self, item_id: str):
        self.bloody_items.add(item_id)

# ==============================================================================
# 4. ユーティリティ
# ==============================================================================
def alive_girls_in(girls: Dict[str, MagicalGirl], room_id: str) -> List[MagicalGirl]:
    return [g for g in girls.values() if g.is_alive and g.location == room_id]

def rl(room_id: str) -> str:
    return MAP[room_id]["name"]

def show_loc(loc: str, girls: Dict[str, MagicalGirl], state: GameState):
    present  = alive_girls_in(girls, loc)
    names    = "、".join(g.jp_name for g in present) if present else "誰もいない"
    items_in = "、".join(item_disp(i, state) for i in state.item_at(loc))
    istr     = f"  アイテム: [{items_in}]" if items_in else ""
    print(f"\n現在地: {rl(loc)}  |  同室: [{names}]{istr}")

# ==============================================================================
# 5. AI 関数
# ==============================================================================
def ai_choose_action(girl: MagicalGirl, available: List[dict], current_time: str) -> dict:
    meal_hint = "\n【ヒント】外向的なので食事時間はラウンジを優先。" if (
        girl.personality == "extrovert" and "食" in current_time) else ""
    prompt = f"""
キャラクター: {girl.jp_name} (性格:{girl.personality}, ストレス:{girl.stress}/100)
口調ルール: {girl.prompt_hint}
現在時刻: {current_time}{meal_hint}
【実行可能な行動リスト(index 0始まり)】
{json.dumps(available, ensure_ascii=False, indent=2)}
selected_indexはリストの番号。display_messageは選んだ行動に沿った日常的・無害なセリフ。
{{"selected_index": int, "display_message": "セリフ"}}"""
    return llm.ask_json(prompt, "choose")


def ai_respond(girl: MagicalGirl, msg: str, current_time: str) -> str:
    prompt = f"""あなたは{girl.jp_name}。口調:{girl.prompt_hint}
状態: ストレス={girl.stress}/100, プレイヤーへの疑惑度={girl.hate.get('player',10)}/100
現在時刻:{current_time}  プレイヤーの発言:「{msg}」
1〜2文で返答。{{"reply": "セリフ"}}"""
    return llm.ask_json(prompt, "respond").get("reply", "……。")


def ai_evaluate(girl: MagicalGirl, msg: str, reply: str) -> dict:
    prompt = f"""キャラ:{girl.jp_name}
プレイヤー発言:「{msg}」 キャラ返答:「{reply}」
ストレス・疑惑度変動を判定。親切→負、煽り→正。範囲-20〜+20。
{{"stress_change": int, "hate_change": int}}"""
    return llm.ask_json(prompt, "evaluate")


def ai_court(girl: MagicalGirl, evidence: str, suspect_ids: List[str],
             history: List[str], witness_ctx: str) -> dict:
    mem_str = json.dumps([m.to_dict() for m in girl.memories if m.who], ensure_ascii=False)
    prompt = f"""
登場人物: {girl.jp_name}(id:{girl.name}) 口調: {girl.prompt_hint}
記憶ログ(曖昧): {mem_str}
{f"【目撃情報・証拠（信頼度高）】{witness_ctx}" if witness_ctx else ""}
議論履歴:
{chr(10).join(history)}
プレイヤーの主張:「{evidence}」
判定:
1. is_logical: 記憶・証拠と照合して論理的か(bool)
2. suspect: trueなら最も怪しいid。選択肢:{suspect_ids}。"player"は絶対不可。falseならnull。
3. speech: キャラクターのセリフ（口調を守ること）
{{"speech": str, "is_logical": bool, "suspect": str_or_null}}"""
    return llm.ask_json(prompt, "court")


def ai_escape_proposal(girl: MagicalGirl, love_score: int,
                        agreed: bool, current_time: str) -> str:
    result_str = "参加することにした" if agreed else "断ることにした"
    prompt = f"""{girl.jp_name}はプレイヤーから脱出作戦への参加を提案された。
好感度:{love_score}/100  結果:{result_str}  口調:{girl.prompt_hint}
1〜2文のセリフ。{{"speech": "セリフ"}}"""
    return llm.ask_json(prompt, "escape").get("speech", "……。")

# ==============================================================================
# 6. ゲーム初期化（Issue #1: hate/love を全キャラ確定後に一般化して初期化）
# ==============================================================================
def setup_game():
    girls: Dict[str, MagicalGirl] = {
        "ema": MagicalGirl("ema", "桜羽エマ", "extrovert", "none",
            "一人称「ボク」。ボーイッシュで正義感強くハキハキ。嘘が苦手。他人に嫌われることを怖がる。敬語不使用。"
            "例:「ボクはそう思わないけど」「それ、おかしくない？」"),
        "sherry": MagicalGirl("sherry", "橘シェリー", "extrovert", "monster_strength",
            "一人称「私」。名探偵自称、好奇心旺盛。常に元気、空気読まない。道徳心なし。"
            "例:「面白いじゃないですか！」「え、なんで怒ってるんですか？」"),
        "hanna": MagicalGirl("hanna", "遠野ハンナ", "introvert", "fly",
            "一人称「わたくし」。貧乏出身だがお嬢様口調で高慢。内心は臆病で不安定。"
            "例:「わたくしには関係ありませんわ」「……べ、別に怖くなんてありませんのよ」"),
    }
    player = PlayerCharacter()
    all_chars: Dict[str, Character] = {**girls, "player": player}
    all_ids = list(all_chars.keys())
    for char in all_chars.values():
        char.hate = {cid: 10 for cid in all_ids}
        char.love = {cid: 10 for cid in all_ids}
    return girls, player, [Guard("看守A"), Guard("看守B")], GameState()

# ==============================================================================
# 7. 行動生成
# ==============================================================================
def girl_available_actions(girl: MagicalGirl, state: GameState,
                            girls: Dict[str, MagicalGirl]) -> Tuple[List[dict], List[dict]]:
    """(normal_actions, murder_actions) — 殺害は分離してPythonが強制実行"""
    rule   = state.get_phase_rule()
    normal: List[dict] = []
    murder: List[dict] = []

    if girl.location == "punishment_cell":
        return [{"action": "待機", "target": "punishment_cell", "description": "懲罰房で大人しく過ごす"}], []

    if rule["type"] == "cell_reset":
        if girl.location != "cell":
            return [{"action": "部屋移動", "target": "cell", "description": "監房に戻る（強制ルール）"}], []
        return [{"action": "待機", "target": "none", "description": "監房で大人しく過ごす"}], []

    for rid in MAP[girl.location]["links"]:
        if rid != "court":
            normal.append({"action": "部屋移動", "target": rid, "description": f"{rl(rid)}へ移動する"})
    if girl.location == "lounge" and "食" in rule["info"]:
        normal.append({"action": "食事", "target": "lounge", "description": "ラウンジでご飯を食べる"})
    for iid in state.item_at(girl.location):
        normal.append({"action": "アイテム取得", "target": iid,
                        "description": f"{item_disp(iid, state)}を取得する"})
    for iid in state.holding(girl.name):
        normal.append({"action": "アイテム置く", "target": iid,
                        "description": f"{item_disp(iid, state)}を置く"})

    has_weapon = any(ITEMS[i].get("is_weapon") for i in state.holding(girl.name))
    if girl.stress >= 70 and has_weapon and not state.murder_this_turn:
        targets = [n for n, g in girls.items()
                   if g.location == girl.location and n != girl.name and g.is_alive]
        if targets:
            murder.append({"action": "殺害", "target": "any", "description": "同じ部屋の誰かを密かに殺害する"})

    normal.append({"action": "待機", "target": "none", "description": f"{rl(girl.location)}で静かに過ごす"})
    return normal, murder


def player_options(loc: str, girls: Dict[str, MagicalGirl],
                   state: GameState) -> List[Tuple]:
    """(kind, value, label) のリスト"""
    opts: List[Tuple] = [("noop", None, "待機（何もしない）")]
    for rid in MAP[loc]["links"]:
        if rid not in ("court", "punishment_cell"):
            opts.append(("move", rid, f"{rl(rid)}へ移動する"))
    for g in alive_girls_in(girls, loc):
        opts.append(("talk", g, f"{g.jp_name}に話しかける"))
        if g.name not in state.escape.members:
            opts.append(("escape", g, f"脱出作戦を提案する（{g.jp_name}）"))
    for iid in state.item_at(loc):
        opts.append(("pickup", iid, f"{item_disp(iid, state)}を拾う"))
    for iid in state.holding("player"):
        opts.append(("drop", iid, f"{item_disp(iid, state)}を置く"))
    has_wpn = any(ITEMS[i].get("is_weapon") for i in state.holding("player"))
    if has_wpn:
        for g in alive_girls_in(girls, loc):
            opts.append(("murder", g, f"【殺害】{g.jp_name}を殺害する"))
    return opts

# ==============================================================================
# 8. アクション実行（プレイヤー）
# ==============================================================================
def exec_player_action(kind, val, state: GameState,
                        girls: Dict[str, MagicalGirl],
                        player: PlayerCharacter) -> bool:
    """True=移動→次スロットへ進む / False=ターン終了"""
    if kind == "noop":
        return False

    elif kind == "move":
        player.location = val
        print(f"➡ {rl(val)} に移動しました。")
        return True  # 移動後もう1アクション可

    elif kind == "talk":
        msg   = input(f"[{val.jp_name}への発言]: ")
        reply = ai_respond(val, msg, state.current_time)
        print(f"\n[{val.jp_name}]: 「{reply}」")
        ev = ai_evaluate(val, msg, reply)
        sc, hc = ev.get("stress_change", 0), ev.get("hate_change", 0)
        val.stress         = max(0, min(100, val.stress + sc))
        val.hate["player"] = max(0, min(100, val.hate["player"] + hc))
        val.love["player"] = max(0, min(100, val.love["player"] - hc))  # hate逆転
        print(f"（ストレス={sc:+} / 疑惑度={hc:+}）")
        # 双方のメモリに記録
        val.memories.append(MemoryLog("player", state.current_time, player.location,
                                       f"プレイヤーとの会話: {msg}", val.stress))
        player.memories.append(MemoryLog(val.name, state.current_time, player.location,
                                          f"{val.jp_name}との会話: {reply[:40]}", player.stress))
        return False

    elif kind == "escape":
        target     = val
        love_score = target.love.get("player", 10)
        agreed     = random.random() < (love_score / 100.0)
        speech     = ai_escape_proposal(target, love_score, agreed, state.current_time)
        print(f"\n[{target.jp_name}]: 「{speech}」")
        if agreed:
            state.escape.members.add(target.name)
            print(f"✨ {target.jp_name}が脱出作戦に参加！（参加者: {len(state.escape.members)}人） {state.escape.bar}")
        else:
            print(f"（{target.jp_name}は断った。好感度を上げてから再度試みよう。）")
        return False

    elif kind == "pickup":
        state.item_locations[val] = "player"
        disp = item_disp(val, state)
        print(f"✅ {disp}を拾いました。")
        player.memories.append(MemoryLog(
            "player", state.current_time, player.location,
            f"{rl(player.location)}で{disp}を取得(item:{val})",
            player.stress, is_evidence=(val in state.bloody_items)))
        return False

    elif kind == "drop":
        state.item_locations[val] = player.location
        print(f"📦 {item_disp(val, state)}を{rl(player.location)}に置きました。")
        return False

    elif kind == "murder":
        target = val
        target.is_alive        = False
        state.dead_bodies[player.location] = target.name
        state.murder_this_turn = True
        weapons = [i for i in state.holding("player") if ITEMS[i].get("is_weapon")]
        if weapons: state.mark_bloody(weapons[0])
        state.truth_logs.append(
            MemoryLog("player", state.current_time, player.location, "武器", 100))
        # 同室の目撃者
        for wname, witness in girls.items():
            if witness.is_alive and witness.location == player.location and wname != target.name:
                witness.memories.append(MemoryLog(
                    "player", state.current_time, player.location,
                    f"プレイヤーが{target.jp_name}を殺害", 100, is_evidence=True))
        print(f"🔪 {target.jp_name}を殺害しました……。")
        return False

    return False

# ==============================================================================
# 9. プレイヤーターン（2アクションスロット）
# ==============================================================================
def handle_player_turn(state: GameState, girls: Dict[str, MagicalGirl],
                        player: PlayerCharacter, rule: dict):
    if player.is_caught:
        player.punished_turns -= 1
        print(f"⛓️  懲罰房に拘束中（残り {player.punished_turns} ターン）")
        if player.punished_turns <= 0:
            player.location = "cell"
            player.is_caught = False
            print("解放されて監房に戻されました。")
        return

    if rule["type"] == "cell_reset" and player.location != "cell":
        player.location = "cell"
        print("⚡ 点呼。監房へ強制移動しました。")

    for slot in range(1, 3):
        show_loc(player.location, girls, state)
        opts = player_options(player.location, girls, state)
        print(f"\n【行動 {slot}/2】")
        for i, (kind, val, label) in enumerate(opts):
            print(f"  [{i}] {label}")
        try:
            choice = int(input("選択: ").strip())
            kind, val, label = opts[choice]
        except (ValueError, IndexError):
            print("無効な入力。待機します。"); break
        if not exec_player_action(kind, val, state, girls, player):
            break

# ==============================================================================
# 10. 少女の殺害処理（Pythonが強制実行）
# ==============================================================================
def execute_girl_murder(killer: MagicalGirl, state: GameState,
                         girls: Dict[str, MagicalGirl],
                         player: PlayerCharacter) -> Optional[str]:
    targets = [n for n, g in girls.items()
               if g.location == killer.location and n != killer.name and g.is_alive]
    if not targets: return None
    victim = random.choice(targets)
    girls[victim].is_alive         = False
    state.dead_bodies[killer.location] = victim
    state.murder_this_turn         = True
    weapons = [i for i in state.holding(killer.name) if ITEMS[i].get("is_weapon")]
    if weapons:
        state.mark_bloody(weapons[0])
        killer.hide_evidence = True  # 証拠隠滅モードON
    state.truth_logs.append(
        MemoryLog(killer.name, state.current_time, killer.location,
                  f"クロスボウで{girls[victim].jp_name}を殺害", killer.stress))
    for wname, witness in girls.items():
        if (witness.is_alive and witness.location == killer.location
                and wname not in (killer.name, victim)):
            witness.memories.append(MemoryLog(
                killer.name, state.current_time, killer.location,
                f"クロスボウで{girls[victim].jp_name}を殺害",
                killer.stress, is_evidence=True))
    return victim

# ==============================================================================
# 11. 探索フェーズ（3ターン・証拠隠滅＆発見）
# ==============================================================================
def run_explore_phase(girls: Dict[str, MagicalGirl], player: PlayerCharacter,
                       state: GameState, victim_id: str):
    print(f"\n{'='*50}")
    print(f" 🔍 探索フェーズ（3ターン）  被害者: {girls[victim_id].jp_name}")
    print(f" 証拠を集めて裁判に備えろ！")
    print("="*50)

    real_killer_name = state.truth_logs[-1].who if state.truth_logs else None
    state.murder_this_turn = False

    all_chars: Dict[str, Character] = {**girls, "player": player}

    for et in range(1, 4):
        print(f"\n--- 探索 {et}/3  [{state.current_time}] ---")

        # 犯人が証拠隠滅行動
        if real_killer_name and real_killer_name in girls:
            killer = girls[real_killer_name]
            if killer.is_alive and killer.hide_evidence:
                _killer_hide(killer, state, player)

        # プレイヤーの自動証拠発見
        _auto_discover(player, state)

        # プレイヤー行動（2スロット）
        show_loc(player.location, girls, state)
        for slot in range(1, 3):
            opts = player_options(player.location, girls, state)
            print(f"\n【探索行動 {slot}/2】")
            for i, (kind, val, label) in enumerate(opts):
                print(f"  [{i}] {label}")
            try:
                choice = int(input("選択: ").strip())
                kind, val, label = opts[choice]
            except (ValueError, IndexError):
                break
            if not exec_player_action(kind, val, state, girls, player):
                break
            _auto_discover(player, state)  # 移動後も即チェック

        # 他の少女が移動（犯人以外の通常行動）
        for name, girl in girls.items():
            if not girl.is_alive or name == real_killer_name: continue
            normal, _ = girl_available_actions(girl, state, girls)
            ai_res = ai_choose_action(girl, normal, state.current_time)
            idx    = min(ai_res.get("selected_index", 0), len(normal) - 1)
            if normal[idx]["action"] == "部屋移動":
                girl.location = normal[idx]["target"]

        # メモリ風化
        for char in all_chars.values():
            for mem in char.memories: mem.age_memory()

        state.next_time()

    print("\n探索フェーズ終了。裁判に移行します。")


def _killer_hide(killer: MagicalGirl, state: GameState, player: PlayerCharacter):
    """犯人が血の付いた武器をプレイヤーのいない部屋に隠す"""
    bloody = [i for i in state.holding(killer.name) if i in state.bloody_items]
    if not bloody:
        killer.hide_evidence = False
        return
    item_id = bloody[0]
    # プレイヤーのいない隣接部屋を優先
    options = [r for r in MAP[killer.location]["links"]
               if r not in ("court", "punishment_cell") and r != player.location]
    if not options:
        options = [r for r in MAP[killer.location]["links"]
                   if r not in ("court", "punishment_cell")]
    if options:
        dest = random.choice(options)
        print(f"（{killer.jp_name}が移動した……）")
        killer.location = dest
        state.item_locations[item_id] = dest
        killer.hide_evidence = False


def _auto_discover(player: PlayerCharacter, state: GameState):
    """プレイヤーがいる部屋の血の付いたアイテムを自動発見（重複なし）"""
    for item_id in state.item_at(player.location):
        if item_id not in state.bloody_items:
            continue
        already = any(f"item:{item_id}" in (m.how or "") for m in player.memories if m.is_evidence)
        if not already:
            disp = item_disp(item_id, state)
            print(f"🩸【証拠発見！】{rl(player.location)}に{disp}が落ちていた！")
            player.memories.append(MemoryLog(
                "?", state.current_time, player.location,
                f"{rl(player.location)}で{disp}を発見(item:{item_id})",
                0, is_evidence=True))

# ==============================================================================
# 12. メインループ
# ==============================================================================
def main_loop():
    girls, player, guards, state = setup_game()
    all_chars: Dict[str, Character] = {**girls, "player": player}

    print("="*50)
    print(" 🩸 manosaba3d 1Dプロトタイプ v0.0.4")
    print(f"    LLM: {LLM_PROVIDER} / {RESOLVED_MODEL}")
    print("="*50)

    while True:
        rule = state.get_phase_rule()
        print(f"\n{'='*50}")
        print(f"【Day {state.day} - {state.current_time}】 {rule['info']}")
        print("="*50)

        for g in guards: g.move()

        # ストレス上昇（全キャラ共通）
        for char in all_chars.values():
            if not char.is_alive: continue
            if char.location == "punishment_cell":
                char.stress = min(100, char.stress + random.randint(5, 15))
            else:
                base = random.randint(2, 7) if getattr(char, "personality", "") == "introvert" \
                       else random.randint(3, 12)
                char.stress = min(100, char.stress + base)

        # 同室不和（懲罰房・裁判所は除外）
        ids = list(girls.keys())
        for i, na in enumerate(ids):
            for nb in ids[i+1:]:
                ga, gb = girls[na], girls[nb]
                if (ga.is_alive and gb.is_alive and ga.location == gb.location
                        and ga.location not in ("punishment_cell", "court")):
                    if random.random() < 0.4:
                        for g, other in [(ga, nb), (gb, na)]:
                            g.stress      = min(100, g.stress + 8)
                            g.hate[other] = min(100, g.hate[other] + 10)

        # 死体発見チェック
        for room_id, victim in list(state.dead_bodies.items()):
            if player.location == room_id and not player.is_caught:
                print(f"\n🚨【事件発生】{rl(room_id)}で{girls[victim].jp_name}の死体を発見！")
                run_explore_phase(girls, player, state, victim)
                run_court_phase(girls, player, state, victim)
                return

        # ステータス表示
        print("\n--- 魔法少女たちの現在のステータス ---")
        for name, g in girls.items():
            loc  = rl(g.location) if g.is_alive else "死亡"
            held = "、".join(item_disp(i, state) for i in state.holding(name))
            hstr = f" 【{held}】" if held else ""
            print(f" ・{g.jp_name}: {loc} | ストレス: {g.stress}/100{hstr}")
        print(f" [看守] A:{rl(guards[0].location)}, B:{rl(guards[1].location)}")
        held_p = "、".join(item_disp(i, state) for i in state.holding("player"))
        if held_p: print(f" [所持品] {held_p}")
        if state.escape.members:
            print(f" [脱出作戦] {state.escape.bar}  参加者: {', '.join(state.escape.members)}")

        # プレイヤー行動
        handle_player_turn(state, girls, player, rule)

        # AI少女の行動
        print("\n--- 魔法少女たちの行動 ---")
        for name, girl in girls.items():
            if not girl.is_alive: continue
            if girl.location == "punishment_cell":
                girl.punished_turns -= 1
                if girl.punished_turns <= 0: girl.location = "cell"
                print(f" ・{girl.jp_name}: 懲罰房で隔離中...")
                continue

            normal, murder = girl_available_actions(girl, state, girls)

            if murder:
                # 殺害はPythonが強制実行（AIに委ねない）
                display = cover_msg(girl.personality)
                print(f" ・{girl.jp_name}: {display} ({rl(girl.location)}で静かに過ごす)")
                victim = execute_girl_murder(girl, state, girls, player)
                if victim and player.location == girl.location and not player.is_caught:
                    player.memories.append(MemoryLog(
                        girl.name, state.current_time, player.location,
                        f"{girl.jp_name}が{girls[victim].jp_name}を殺害(クロスボウ)",
                        girl.stress, is_evidence=True))
                    print(f"\n🚨【現行犯！】{girl.jp_name}が{girls[victim].jp_name}を目撃！")
                    run_explore_phase(girls, player, state, victim)
                    run_court_phase(girls, player, state, victim)
                    return
            else:
                ai_res = ai_choose_action(girl, normal, state.current_time)
                idx    = min(ai_res.get("selected_index", 0), len(normal) - 1)
                chosen = normal[idx]
                print(f" ・{girl.jp_name}: 「{ai_res.get('display_message','……。')}」 ({chosen['description']})")
                if chosen["action"] == "部屋移動":
                    girl.location = chosen["target"]
                    girl.memories.append(MemoryLog(girl.name, state.current_time,
                                                    girl.location, "移動", girl.stress))
                elif chosen["action"] == "食事":
                    girl.stress = max(0, girl.stress - 25)
                elif chosen["action"] == "アイテム取得":
                    state.item_locations[chosen["target"]] = girl.name
                    girl.memories.append(MemoryLog(girl.name, state.current_time, girl.location,
                                                    f"{item_disp(chosen['target'],state)}を取得",
                                                    girl.stress))
                elif chosen["action"] == "アイテム置く":
                    state.item_locations[chosen["target"]] = girl.location

        # 看守検問（少女・プレイヤー共通）
        if rule["out_ban"]:
            for name, girl in girls.items():
                if girl.is_alive and girl.location not in ("cell", "punishment_cell"):
                    for g in guards:
                        if g.location == girl.location:
                            print(f"🚨【捕縛】{girl.jp_name}が{rl(girl.location)}で発見→懲罰房！")
                            state.confiscate(name, girl.location)
                            girl.location = "punishment_cell"; girl.punished_turns = 2
            if not player.is_caught and player.location not in ("cell", "punishment_cell"):
                for g in guards:
                    if g.location == player.location:
                        print(f"🚨【捕縛】あなたが{rl(player.location)}で発見→懲罰房！")
                        state.confiscate("player", player.location)
                        player.location = "punishment_cell"
                        player.is_caught = True; player.punished_turns = 2; break

        # 脱出作戦の進捗
        if state.escape.tick(all_chars):
            print(f"\n🎈【ハッピーエンド！】気球が完成し、全員で脱出に成功した！")
            return

        # 忘却処理（全キャラ共通）
        for char in all_chars.values():
            for mem in char.memories: mem.age_memory()

        state.next_time()

# ==============================================================================
# 13. 魔女裁判フェーズ
# ==============================================================================
def run_court_phase(girls: Dict[str, MagicalGirl], player: PlayerCharacter,
                     state: GameState, victim_id: str):
    alive = {n: g for n, g in girls.items() if g.is_alive}
    if not alive:
        print("\n💀【詰み】生存者なし。裁判不成立。"); return

    print(f"\n{'='*50}\n ⚖️ 魔女裁判 開廷 ⚖️\n 被害者: {girls[victim_id].jp_name}")
    print(" 5ターンの間に証拠を突きつけ、犯人の疑惑度を上げろ！\n" + "="*50)

    for g in alive.values(): g.location = "court"
    player.location = "court"

    suspect_ids = list(alive.keys())
    history     = [f"裁判開始。被害者は{girls[victim_id].jp_name}。"]

    # プレイヤーの証拠メモリを整形（is_evidence=Trueのみ）
    ev_mems = [m for m in player.memories if m.is_evidence and m.who]
    witness_ctx = "\n".join(
        f"[{m.when}] {m.where if isinstance(m.where, str) else m.where[0]}: {m.how}"
        for m in ev_mems
    ) if ev_mems else ""
    if witness_ctx:
        print(f"\n📋【あなたの証拠・目撃情報】\n{witness_ctx}\n")

    for turn in range(1, 6):
        print(f"\n【裁判ターン {turn}/5】")
        evidence = input("主張を入力してください:\n> ")
        history.append(f"プレイヤーの主張: {evidence}")

        for name, girl in alive.items():
            res    = ai_court(girl, evidence, suspect_ids, history, witness_ctx)
            speech = res.get("speech", "……。")
            print(f"[{girl.jp_name}]: 「{speech}」")
            history.append(f"{girl.jp_name}: {speech}")
            if res.get("is_logical", False):
                suspect = res.get("suspect")
                if suspect and suspect in girl.hate and suspect != girl.name and suspect != "player":
                    girl.hate[suspect] += 25
                    print(f"  (➡ {girl.jp_name}は納得。{suspect}への疑惑度が上昇！)")
                else:
                    print(f"  (➡ {girl.jp_name}は考え込んでいる。)")
            else:
                girl.hate["player"] += 15
                print(f"  (➡ {girl.jp_name}はあなたを疑っている。疑惑度上昇。)")

    # 投票
    print(f"\n{'='*50}\n 🗳️ 投票の刻\n{'='*50}")
    all_ids = suspect_ids + ["player"]
    votes   = {k: 0 for k in all_ids}
    for name, girl in alive.items():
        cands = {k: v for k, v in girl.hate.items() if k != girl.name and k in votes}
        if cands:
            target = max(cands, key=cands.get)
            votes[target] += 1
            print(f" ・{girl.jp_name} → 【{target}】(疑惑度:{girl.hate[target]})")

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
        name_ex = girls[executed].jp_name if executed in girls else executed
        print(f"\n🎉【裁判勝利】真犯人「{name_ex}」を処刑しました！")
    else:
        name_ex = girls[executed].jp_name if executed in girls else executed
        print(f"\n💀【冤罪】「{name_ex}」は無実でした。真犯人は「{real_killer}」でした。")
    print("="*50)

if __name__ == "__main__":
    main_loop()