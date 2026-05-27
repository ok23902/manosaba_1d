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
    raise ValueError(f"⚠️ LLM_API_KEY 未設定 (provider={LLM_PROVIDER})")

# ==============================================================================
# 1. LLM クライアント（3回リトライ + テンプレートフォールバック）
# ==============================================================================
_TEMPLATES = {
    "choose":   {"selected_index": 0, "display_message": "……。"},
    "respond":  {"reply": "……。"},
    "evaluate": {"stress_change": 0, "hate_change": 0},
    "court":    {"speech": "……。", "is_logical": False, "suspect": None, "evidence_strength": "none"},
    "escape":   {"speech": "……今は、考えられません。"},
}

class LLMClient:
    MAX_RETRY = 3
    def __init__(self):
        self.provider = LLM_PROVIDER; self.model = RESOLVED_MODEL
        if self.provider in ("deepseek", "openai", "local"):
            from openai import OpenAI
            kw = {"api_key": LLM_API_KEY or "local"}
            if RESOLVED_BASE_URL: kw["base_url"] = RESOLVED_BASE_URL
            self._client = OpenAI(**kw)
        elif self.provider == "anthropic":
            import anthropic
            self._client = anthropic.Anthropic(api_key=LLM_API_KEY)
        else:
            raise ValueError(f"未対応: {self.provider}")

    def ask_json(self, prompt: str, fallback_key: str = "choose") -> dict:
        sys = "You are a game engine backend. Respond ONLY with a valid JSON object. No markdown."
        for attempt in range(self.MAX_RETRY):
            try:
                if self.provider in ("deepseek", "openai", "local"):
                    extra = {}
                    if self.provider in ("deepseek", "openai"):
                        extra["response_format"] = {"type": "json_object"}
                    r = self._client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "system", "content": sys},
                                   {"role": "user",   "content": prompt}],
                        temperature=0.3, **extra)
                    raw = r.choices[0].message.content or ""
                elif self.provider == "anthropic":
                    r = self._client.messages.create(
                        model=self.model, max_tokens=512, system=sys,
                        messages=[{"role": "user", "content": prompt}])
                    raw = r.content[0].text if r.content else ""
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"): raw = raw[4:]
                result = json.loads(raw)
                if result: return result
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
    "6:00":  {"info": "自由行動時間 (朝食)",           "out_ban": False, "type": "free"},
    "10:00": {"info": "監房強制リセット（全員点呼）",   "out_ban": True,  "type": "cell_reset"},
    "12:00": {"info": "自由行動時間 (昼食)",            "out_ban": False, "type": "free"},
    "15:00": {"info": "監房強制リセット（全員点呼）",   "out_ban": True,  "type": "cell_reset"},
    "17:00": {"info": "自由行動時間 (夕食)",            "out_ban": False, "type": "free"},
    "22:00": {"info": "外出禁止時間 (就寝)",            "out_ban": True,  "type": "free"},
}
ITEMS: Dict[str, dict] = {
    "crossbow": {"name": "クロスボウ", "is_weapon": True},
    "knife":    {"name": "ナイフ",     "is_weapon": True},
}

_TIME_VAGUE = {
    "6:00": "早朝", "10:00": "午前中",
    "12:00": "昼頃", "15:00": "午後",
    "17:00": "夕方", "22:00": "夜"
}
def vague_time(t: str) -> str:
    return _TIME_VAGUE.get(t, "不明な時刻")

# 殺害偽装セリフ
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
    base = ITEMS[item_id]["name"]
    return f"🩸血のついた{base}" if item_id in state.bloody_items else base

# ==============================================================================
# 3. データ構造
# ==============================================================================
class MemoryLog:
    def __init__(self, who, when, where, how, why_stress,
                 is_evidence=False, evidence_strength="none"):
        self.who              = who
        self.when             = when
        self.where            = where
        self.how              = how
        self.why_stress       = why_stress
        self.turns_left       = 3
        self.is_evidence      = is_evidence
        self.evidence_strength = evidence_strength

    def age_memory(self):
        if self.is_evidence: return
        self.turns_left -= 1
        if   self.turns_left == 2: self.where = list({self.where, "廊下", "ラウンジ"})
        elif self.turns_left == 1: self.when  = list({self.when, "6:00", "12:00", "22:00"})
        elif self.turns_left <= 0: self.who = self.when = self.where = self.how = None

    def to_dict(self) -> dict:
        return {"who": self.who, "when": self.when, "where": self.where, "how": self.how}


class Character:
    def __init__(self, name: str, jp_name: str):
        self.name           = name
        self.jp_name        = jp_name
        self.stress         = random.randint(35, 55)
        self.location       = "cell"
        self.punished_turns = 0
        self.is_alive       = True
        self.is_caught      = False
        self.hate: Dict[str, int] = {}
        self.memories: List[MemoryLog] = []


class MagicalGirl(Character):
    def __init__(self, name, jp_name, personality, magic, prompt_hint):
        super().__init__(name, jp_name)
        self.personality   = personality
        self.magic         = magic
        self.prompt_hint   = prompt_hint
        self.hide_evidence = False
        self.goal          = "none"

    def update_goal(self):
        if self.stress >= 75:
            self.goal = "murder"
        elif self.stress >= 50:
            self.goal = "explore"
        else:
            self.goal = "escape"


class PlayerCharacter(Character):
    def __init__(self):
        super().__init__("player", "あなた")
        self.location    = "lounge"
        self.personality = "extrovert"


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
    def __init__(self):
        self.progress = 0
        self.members: Set[str] = set()

    def tick(self, all_chars: Dict[str, Character]) -> bool:
        to_remove = []
        for name in self.members:
            if name == "player": continue
            if name in all_chars and all_chars[name].is_alive and all_chars[name].stress >= 70:
                to_remove.append(name)
        for name in to_remove:
            self.members.remove(name)
            print(f"  ⚠️ {all_chars[name].jp_name}はストレスが溜まりすぎて脱出作戦から離脱した。")

        active = [n for n in self.members
                  if n in all_chars and all_chars[n].is_alive and all_chars[n].stress < 70]
        if active:
            self.progress = min(100, self.progress + sum(random.randint(5, 15) for _ in active))
        return self.progress >= 100

    def add_member(self, name: str):
        self.members.add(name)

    def remove_member(self, name: str):
        self.members.discard(name)

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
        self.room_traces: Dict[str, List[dict]] = {}
        self.in_explore: bool = False

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

    def add_trace(self, room_id: str, who: str, when: str):
        if self.in_explore: return
        if room_id not in self.room_traces:
            self.room_traces[room_id] = []
        self.room_traces[room_id].append({
            "who": who, "when": when, "turns_left": 4, "vague": False
        })

    def age_traces(self):
        for room_id in list(self.room_traces.keys()):
            aged = []
            for t in self.room_traces[room_id]:
                t["turns_left"] -= 1
                if t["turns_left"] == 2: t["vague"] = True
                if t["turns_left"] > 0:  aged.append(t)
            self.room_traces[room_id] = aged

    def get_visible_traces(self, room_id: str) -> List[str]:
        result = []
        seen_times = set()
        for t in self.room_traces.get(room_id, []):
            label = vague_time(t["when"]) if t["vague"] else t["when"]
            if label not in seen_times:
                result.append(f"誰かが{label}頃にここにいた痕跡がある")
                seen_times.add(label)
        return result

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
# 5. ストレスイベント
# ==============================================================================
def trigger_stress_events(girls: Dict[str, MagicalGirl], state: GameState) -> List[str]:
    rule   = state.get_phase_rule()
    events = []
    if "食" in rule["info"]:
        for g in girls.values():
            if g.is_alive and g.location == "lounge" and random.random() < 0.4:
                g.stress = min(100, g.stress + 20)
                events.append(f"⚡ {g.jp_name}は不味い食事を食べさせられてストレスが溜まった。")
    ids = list(girls.keys())
    for i, na in enumerate(ids):
        for nb in ids[i+1:]:
            ga, gb = girls[na], girls[nb]
            if (ga.is_alive and gb.is_alive
                    and ga.location == gb.location
                    and ga.location not in ("punishment_cell", "court")
                    and ga.hate.get(nb, 0) > 50 and gb.hate.get(na, 0) > 50
                    and random.random() < 0.3):
                ga.stress = min(100, ga.stress + 25)
                gb.stress = min(100, gb.stress + 25)
                ga.hate[nb] = min(100, ga.hate.get(nb, 0) + 15)
                gb.hate[na] = min(100, gb.hate.get(na, 0) + 15)
                events.append(f"⚡ {ga.jp_name}と{gb.jp_name}が激しく口論になった。")
    return events

# ==============================================================================
# 6. AI 関数
# ==============================================================================
def ai_choose_action(girl: MagicalGirl, available: List[dict], current_time: str) -> dict:
    goal_hint = ""
    if girl.goal == "murder":
        goal_hint = "\n【目標】殺人を優先しろ。武器があれば殺せ。"
    elif girl.goal == "explore":
        goal_hint = "\n【目標】見知らぬ部屋を探索しろ。"
    elif girl.goal == "escape":
        goal_hint = "\n【目標】脱出作戦に関与しろ。プレイヤーに脱出を提案しても良い。"
    meal_hint = "\n【ヒント】外向的なので食事時間はラウンジを優先。" if (
        girl.personality == "extrovert" and "食" in current_time) else ""
    prompt = f"""
キャラクター: {girl.jp_name} (性格:{girl.personality}, ストレス:{girl.stress}/100)
口調ルール: {girl.prompt_hint}
現在時刻: {current_time}{meal_hint}{goal_hint}
【実行可能な行動リスト(index 0始まり)】
{json.dumps(available, ensure_ascii=False, indent=2)}
selected_indexはリストの番号。display_messageは選んだ行動に沿った日常的・無害なセリフ。
{{"selected_index": int, "display_message": "セリフ"}}"""
    return llm.ask_json(prompt, "choose")


def ai_respond(girl: MagicalGirl, msg: str, current_time: str) -> str:
    prompt = f"""あなたは{girl.jp_name}。口調:{girl.prompt_hint}
状態: ストレス={girl.stress}/100, 疑惑度={girl.hate.get('player',50)}/100
現在時刻:{current_time}  発言:「{msg}」
1〜2文で返答。{{"reply": "セリフ"}}"""
    return llm.ask_json(prompt, "respond").get("reply", "……。")


def ai_evaluate(girl: MagicalGirl, msg: str, reply: str) -> dict:
    prompt = f"""キャラ:{girl.jp_name}
発言:「{msg}」 返答:「{reply}」
ストレス・疑惑度変動を判定。親切→負、煽り→正。範囲-20〜+20。
{{"stress_change": int, "hate_change": int}}"""
    return llm.ask_json(prompt, "evaluate")


def ai_court(girl: MagicalGirl, evidence: str, suspect_ids: List[str],
             history: List[str], witness_ctx: str) -> dict:
    mem_str = json.dumps([m.to_dict() for m in girl.memories if m.who], ensure_ascii=False)
    prompt = f"""
登場人物: {girl.jp_name}(id:{girl.name})  口調: {girl.prompt_hint}
記憶ログ(曖昧): {mem_str}
{f"【証拠・目撃情報】{witness_ctx}" if witness_ctx else ""}
議論履歴:
{chr(10).join(history)}
プレイヤーの主張:「{evidence}」

【判定基準】
1. is_logical: 記憶・証拠と照合して論理的か(bool)
2. suspect: trueなら最も怪しいid。選択肢:{suspect_ids}。"player"は絶対不可。falseならnull。
3. evidence_strength: 主張の根拠の強さを判定
   - "strong": 血のついた武器・現行犯目撃など物的証拠
   - "weak":   移動痕跡・証言など状況証拠
   - "none":   推測のみ・根拠なし
4. speech: キャラクターのセリフ（口調を守ること）

{{"speech": str, "is_logical": bool, "suspect": str_or_null, "evidence_strength": "strong"|"weak"|"none"}}"""
    return llm.ask_json(prompt, "court")


def ai_escape_proposal(girl: MagicalGirl, hate_score: int,
                        agreed: bool, current_time: str) -> str:
    result_str = "参加することにした" if agreed else "断ることにした"
    prompt = f"""{girl.jp_name}はプレイヤーから脱出作戦への参加を提案された。
疑惑度:{hate_score}/100 (低いほど承諾しやすい)  結果:{result_str}  口調:{girl.prompt_hint}
1〜2文のセリフ。{{"speech": "セリフ"}}"""
    return llm.ask_json(prompt, "escape").get("speech", "……。")

# ==============================================================================
# 7. ゲーム初期化
# ==============================================================================
def setup_game():
    girls: Dict[str, MagicalGirl] = {
        "ema": MagicalGirl("ema", "桜羽エマ", "extrovert", "none",
            "一人称「ボク」。ボーイッシュで正義感が強くハキハキしている。思ったことをそのまま口に出す素直な性格。嘘が苦手。他人に嫌われることを極端に怖がっているため、強く出られないこともある。敬語は使わない。例:「ボクはそう思わないけど」「それ、おかしくない？」"),
        "sherry": MagicalGirl("sherry", "橘シェリー", "extrovert", "monster_strength",
            "一人称「私」。名探偵を自称する好奇心旺盛な探偵キャラ。常に元気で空気を読まない。道徳心がなく人の気持ちがわからない。しかし根は諦めない強さを持つ。例:「面白いじゃないですか！」「そこが謎なんですよねー」「え、なんで怒ってるんですか？」"),
        "hanna": MagicalGirl("hanna", "遠野ハンナ", "introvert", "fly",
            "一人称「わたくし」。貧乏出身だがお嬢様口調で高慢に振る舞う見栄っ張り。内心は臆病で不安定。強がりと脆さが同居している。例:「わたくしには関係ありませんわ」「……べ、別に怖くなんてありませんのよ」"),
    }
    player = PlayerCharacter()
    all_chars: Dict[str, Character] = {**girls, "player": player}
    all_ids = list(all_chars.keys())
    for char in all_chars.values():
        char.hate = {cid: 50 for cid in all_ids}
    return girls, player, [Guard("看守A"), Guard("看守B")], GameState()

# ==============================================================================
# 8. 行動生成
# ==============================================================================
def girl_available_actions(girl: MagicalGirl, state: GameState,
                            girls: Dict[str, MagicalGirl]) -> Tuple[List[dict], List[dict]]:
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

    player = girls.get("player") if "player" in girls else None
    if player and player.is_alive and player.location == girl.location and girl.name not in state.escape.members:
        normal.append({"action": "脱出提案", "target": "player", "description": "プレイヤーに脱出作戦を提案する"})

    # 殺害判定：同じ部屋に武器があれば可能（所持不要）。怪力は武器不要
    weapon_in_room = any(ITEMS[i].get("is_weapon") for i in state.item_at(girl.location))
    if girl.stress >= 70 and (weapon_in_room or girl.magic == "monster_strength") and not state.murder_this_turn:
        targets = [n for n, g in girls.items()
                   if g.location == girl.location and n != girl.name and g.is_alive]
        if targets:
            murder.append({"action": "殺害", "target": "any", "description": "同じ部屋の誰かを密かに殺害する"})

    normal.append({"action": "待機", "target": "none", "description": f"{rl(girl.location)}で静かに過ごす"})
    return normal, murder


def player_options(loc: str, girls: Dict[str, MagicalGirl],
                   state: GameState) -> List[Tuple]:
    opts: List[Tuple] = [("noop", None, "待機（何もしない）")]
    for rid in MAP[loc]["links"]:
        if rid not in ("court", "punishment_cell"):
            opts.append(("move", rid, f"{rl(rid)}へ移動する"))
    for g in alive_girls_in(girls, loc):
        opts.append(("talk", g, f"{g.jp_name}に話しかける"))
        if g.name not in state.escape.members:
            opts.append(("escape_propose", g, f"脱出作戦を提案する（{g.jp_name}）"))
    for iid in state.item_at(loc):
        opts.append(("pickup", iid, f"{item_disp(iid, state)}を拾う"))
    for iid in state.holding("player"):
        opts.append(("drop", iid, f"{item_disp(iid, state)}を置く"))
    weapon_in_room = any(ITEMS[i].get("is_weapon") for i in state.item_at(loc))
    if weapon_in_room or any(ITEMS[i].get("is_weapon") for i in state.holding("player")):
        for g in alive_girls_in(girls, loc):
            opts.append(("murder", g, f"【殺害】{g.jp_name}を殺害する"))
    if "player" in state.escape.members:
        opts.append(("escape_leave", None, "脱出作戦から離脱する"))
    return opts

# ==============================================================================
# 9. アクション実行（プレイヤー）
# ==============================================================================
def exec_player_action(kind, val, state: GameState,
                        girls: Dict[str, MagicalGirl],
                        player: PlayerCharacter) -> bool:
    if kind == "noop":
        return False

    elif kind == "move":
        state.add_trace(val, "player", state.current_time)
        player.location = val
        print(f"➡ {rl(val)} に移動しました。")
        return True

    elif kind == "talk":
        msg   = input(f"[{val.jp_name}への発言]: ")
        reply = ai_respond(val, msg, state.current_time)
        print(f"\n[{val.jp_name}]: 「{reply}」")
        ev = ai_evaluate(val, msg, reply)
        sc, hc = ev.get("stress_change", 0), ev.get("hate_change", 0)
        val.stress         = max(0, min(100, val.stress + sc))
        val.hate["player"] = max(0, min(100, val.hate.get("player", 50) + hc))
        print(f"（ストレス={sc:+} / 疑惑度={hc:+}）")
        val.memories.append(MemoryLog("player", state.current_time, player.location,
                                       f"プレイヤーとの会話: {msg}", val.stress))
        is_ev = state.in_explore
        player.memories.append(MemoryLog(
            val.name, state.current_time, player.location,
            f"{val.jp_name}の証言: {reply[:50]}",
            player.stress,
            is_evidence=is_ev, evidence_strength="weak" if is_ev else "none"))
        if is_ev:
            print(f"📝【証言記録】{val.jp_name}の発言を証拠として記録しました。")
        return False

    elif kind == "escape_propose":
        target = val
        hate_score = target.hate.get("player", 50)
        prob = (100 - hate_score) / 100.0
        agreed = random.random() < prob
        speech = ai_escape_proposal(target, hate_score, agreed, state.current_time)
        print(f"\n[{target.jp_name}]: 「{speech}」")
        if agreed:
            state.escape.add_member(target.name)
            print(f"✨ {target.jp_name}が参加！（{len(state.escape.members)}人） {state.escape.bar}")
        else:
            print(f"（断られた。疑惑度を下げてから再度試みよう。）")
        return False

    elif kind == "escape_leave":
        if "player" in state.escape.members:
            state.escape.remove_member("player")
            print("あなたは脱出作戦から離脱しました。")
        return False

    elif kind == "pickup":
        state.item_locations[val] = "player"
        disp = item_disp(val, state)
        print(f"✅ {disp}を拾いました。")
        is_bloody = val in state.bloody_items
        player.memories.append(MemoryLog(
            "player", state.current_time, player.location,
            f"{rl(player.location)}で{disp}を取得(item:{val})",
            player.stress,
            is_evidence=is_bloody,
            evidence_strength="strong" if is_bloody else "none"))
        if is_bloody:
            print(f"🩸【重要証拠！】血のついた{ITEMS[val]['name']}を確保しました。")
        return False

    elif kind == "drop":
        state.item_locations[val] = player.location
        print(f"📦 {item_disp(val, state)}を{rl(player.location)}に置きました。")
        return False

    elif kind == "murder":
        target = val
        target.is_alive = False
        state.dead_bodies[player.location] = target.name
        state.murder_this_turn = True
        weapon_used = None
        player_weapons = [i for i in state.holding("player") if ITEMS[i].get("is_weapon")]
        if player_weapons:
            weapon_used = player_weapons[0]
        else:
            room_weapons = [i for i in state.item_at(player.location) if ITEMS[i].get("is_weapon")]
            if room_weapons:
                weapon_used = room_weapons[0]
                state.item_locations[weapon_used] = "player"
        if weapon_used:
            state.mark_bloody(weapon_used)
            print(f"🔪 {target.jp_name}を{ITEMS[weapon_used]['name']}で殺害しました。")
        else:
            print(f"💪 {target.jp_name}を素手で殺害しました。")
        state.truth_logs.append(
            MemoryLog("player", state.current_time, player.location, "殺害", 100))
        for wname, witness in girls.items():
            if witness.is_alive and witness.location == player.location and wname != target.name:
                witness.memories.append(MemoryLog(
                    "player", state.current_time, player.location,
                    f"プレイヤーが{target.jp_name}を殺害", 100,
                    is_evidence=True, evidence_strength="strong"))
        return False

    return False

# ==============================================================================
# 10. プレイヤーターン
# ==============================================================================
def handle_player_turn(state: GameState, girls: Dict[str, MagicalGirl],
                        player: PlayerCharacter, rule: dict):
    if player.is_caught:
        player.punished_turns -= 1
        print(f"⛓️  懲罰房に拘束中（残り {player.punished_turns} ターン）")
        if player.punished_turns <= 0:
            player.location = "cell"; player.is_caught = False
            print("解放されて監房に戻されました。")
        return
    if rule["type"] == "cell_reset" and player.location != "cell":
        player.location = "cell"; print("⚡ 点呼。監房へ強制移動しました。")

    for slot in range(1, 3):
        show_loc(player.location, girls, state)
        opts = player_options(player.location, girls, state)
        print(f"\n【行動 {slot}/2】")
        for i, (kind, val, label) in enumerate(opts): print(f"  [{i}] {label}")
        try:
            choice = int(input("選択: ").strip())
            kind, val, label = opts[choice]
        except (ValueError, IndexError):
            print("無効な入力。待機します。"); break
        if not exec_player_action(kind, val, state, girls, player): break

# ==============================================================================
# 11. 少女の殺害処理（表示条件付き）
# ==============================================================================
def execute_girl_murder(killer: MagicalGirl, state: GameState,
                         girls: Dict[str, MagicalGirl],
                         player: PlayerCharacter) -> Optional[str]:
    targets = [n for n, g in girls.items()
               if g.location == killer.location and n != killer.name and g.is_alive]
    if not targets: return None
    victim = random.choice(targets)
    girls[victim].is_alive = False
    state.dead_bodies[killer.location] = victim
    state.murder_this_turn = True

    weapon_used = None
    # プレイヤーが同室にいるかどうかでメッセージ制御
    player_present = (player.location == killer.location)

    if killer.magic == "monster_strength":
        # 怪力: 武器不要。証拠は残さない（凶器証拠なし）
        if player_present:
            print(f"💪 {killer.jp_name}が素手で{girls[victim].jp_name}を殺害した！")
        # 証拠として追加しない（凶器なし）
    else:
        room_weapons = [i for i in state.item_at(killer.location) if ITEMS[i].get("is_weapon")]
        if room_weapons:
            weapon_used = room_weapons[0]
            state.item_locations[weapon_used] = killer.name
            state.mark_bloody(weapon_used)
            killer.hide_evidence = True
            if player_present:
                print(f"🔪 {killer.jp_name}が{ITEMS[weapon_used]['name']}で{girls[victim].jp_name}を殺害した！")
        else:
            # 武器なしでの殺害は本来発生しないが、念のため
            if player_present:
                print(f"⚠️ {killer.jp_name}が武器なしで殺害しようとしたが失敗")
            return None

    state.truth_logs.append(
        MemoryLog(killer.name, state.current_time, killer.location,
                  f"殺害: {girls[victim].jp_name}", killer.stress))
    for wname, witness in girls.items():
        if (witness.is_alive and witness.location == killer.location
                and wname not in (killer.name, victim)):
            # 目撃者の記憶は証拠として追加（強い証拠）
            witness.memories.append(MemoryLog(
                killer.name, state.current_time, killer.location,
                f"{killer.jp_name}が{girls[victim].jp_name}を殺害",
                killer.stress, is_evidence=True, evidence_strength="strong"))
    return victim

# ==============================================================================
# 12. 探索フェーズ
# ==============================================================================
def run_explore_phase(girls: Dict[str, MagicalGirl], player: PlayerCharacter,
                       state: GameState, victim_id: str):
    print(f"\n{'='*50}")
    print(f" 🔍 探索フェーズ（3ターン）  被害者: {girls[victim_id].jp_name}")
    print(f" 部屋を調べ、証言を集め、証拠を掴め！")
    print("="*50)

    real_killer_name = state.truth_logs[-1].who if state.truth_logs else None
    state.murder_this_turn = False
    state.in_explore = True
    all_chars: Dict[str, Character] = {**girls, "player": player}

    for et in range(1, 4):
        print(f"\n--- 探索 {et}/3  [{state.current_time}] ---")

        if real_killer_name and real_killer_name in girls:
            killer = girls[real_killer_name]
            if killer.is_alive and killer.hide_evidence:
                _killer_hide(killer, state, player)

        _auto_discover(player, state)

        show_loc(player.location, girls, state)
        for slot in range(1, 3):
            opts = player_options(player.location, girls, state)
            print(f"\n【探索行動 {slot}/2】")
            for i, (kind, val, label) in enumerate(opts): print(f"  [{i}] {label}")
            try:
                choice = int(input("選択: ").strip())
                kind, val, label = opts[choice]
            except (ValueError, IndexError):
                break
            if not exec_player_action(kind, val, state, girls, player): break
            _auto_discover(player, state)

        for name, girl in girls.items():
            if not girl.is_alive or name == real_killer_name: continue
            girl.update_goal()
            normal, _ = girl_available_actions(girl, state, girls)
            ai_res = ai_choose_action(girl, normal, state.current_time)
            idx    = min(ai_res.get("selected_index", 0), len(normal) - 1)
            action = normal[idx]
            if action["action"] == "部屋移動":
                girl.location = action["target"]
            elif action["action"] == "脱出提案":
                if player.location == girl.location and player.is_alive:
                    hate_score = girl.hate.get("player", 50)
                    prob = (100 - hate_score) / 100.0
                    agreed = random.random() < prob
                    speech = ai_escape_proposal(girl, hate_score, agreed, state.current_time)
                    print(f"[{girl.jp_name}]（プレイヤーに）: 「{speech}」")
                    if agreed:
                        print(f"✨ {girl.jp_name}が脱出作戦に参加したいと言ってきた！")
                        print("あなたは承諾しますか？ (y/n)")
                        ans = input().strip().lower()
                        if ans == 'y':
                            state.escape.add_member(girl.name)
                            print(f"{girl.jp_name}が脱出メンバーに加わった。")
                    else:
                        print(f"{girl.jp_name}は断った。")

        for char in all_chars.values():
            for mem in char.memories: mem.age_memory()
        state.age_traces()
        state.next_time()

    state.in_explore = False
    print("\n探索フェーズ終了。裁判に移行します。")


def _killer_hide(killer: MagicalGirl, state: GameState, player: PlayerCharacter):
    bloody = [i for i in state.holding(killer.name) if i in state.bloody_items]
    if not bloody: killer.hide_evidence = False; return
    item_id  = bloody[0]
    options  = [r for r in MAP[killer.location]["links"]
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
    loc = player.location
    for item_id in state.item_at(loc):
        if item_id not in state.bloody_items: continue
        already = any(f"item:{item_id}" in (m.how or "") for m in player.memories if m.is_evidence)
        if not already:
            disp = item_disp(item_id, state)
            print(f"🩸【証拠発見！】{rl(loc)}に{disp}が落ちていた！")
            player.memories.append(MemoryLog(
                "?", state.current_time, loc,
                f"{rl(loc)}で{disp}を発見(item:{item_id})",
                0, is_evidence=True, evidence_strength="strong"))
    for trace_str in state.get_visible_traces(loc):
        already = any(trace_str in (m.how or "") for m in player.memories if m.is_evidence)
        if not already:
            print(f"👣【痕跡発見】{rl(loc)}: {trace_str}")
            player.memories.append(MemoryLog(
                "trace", state.current_time, loc,
                trace_str, 0, is_evidence=True, evidence_strength="weak"))

# ==============================================================================
# 13. メインループ
# ==============================================================================
def main_loop():
    girls, player, guards, state = setup_game()
    all_chars: Dict[str, Character] = {**girls, "player": player}

    print("="*50)
    print(" 🩸 manosaba3d 1Dプロトタイプ v0.0.7")
    print(f"    LLM: {LLM_PROVIDER} / {RESOLVED_MODEL}")
    print("="*50)

    while True:
        rule = state.get_phase_rule()
        print(f"\n{'='*50}")
        print(f"【Day {state.day} - {state.current_time}】 {rule['info']}")
        print("="*50)

        for g in guards: g.move()

        # ストレス上昇（調整済み）
        for char in all_chars.values():
            if not char.is_alive: continue
            if char.location == "punishment_cell":
                char.stress = min(100, char.stress + random.randint(3, 10))
            else:
                # 通常のストレス上昇: introvert 1〜4, extrovert 2〜6
                # ただし怪力のシェリーはさらに半減
                if isinstance(char, MagicalGirl) and char.magic == "monster_strength":
                    base = random.randint(1, 3)   # 怪力は非常にストレスに強い
                elif getattr(char, "personality", "") == "introvert":
                    base = random.randint(1, 4)
                else:
                    base = random.randint(2, 6)
                char.stress = min(100, char.stress + base)

        events = trigger_stress_events(girls, state)
        for ev in events: print(f" {ev}")

        # 同室不和
        ids = list(girls.keys())
        for i, na in enumerate(ids):
            for nb in ids[i+1:]:
                ga, gb = girls[na], girls[nb]
                if (ga.is_alive and gb.is_alive and ga.location == gb.location
                        and ga.location not in ("punishment_cell", "court")):
                    if random.random() < 0.4:
                        for g, other in [(ga, nb), (gb, na)]:
                            g.stress      = min(100, g.stress + 8)
                            g.hate[other] = min(100, g.hate.get(other, 50) + 10)

        # 死体発見チェック
        for room_id, victim in list(state.dead_bodies.items()):
            if player.location == room_id and not player.is_caught:
                print(f"\n🚨【事件発生】{rl(room_id)}で{girls[victim].jp_name}の死体を発見！")
                run_explore_phase(girls, player, state, victim)
                run_court_phase(girls, player, state, victim)
                return

        # ステータス表示（同室の情報のみ表示）
        print("\n--- 魔法少女たちの現在のステータス ---")
        for name, g in girls.items():
            if not g.is_alive:
                print(f" ・{g.jp_name}: 死亡")
                continue
            if g.location == player.location:
                loc = rl(g.location)
                held = "、".join(item_disp(i, state) for i in state.holding(name))
                hstr = f" 【{held}】" if held else ""
                print(f" ・{g.jp_name}: {loc} | ストレス: {g.stress}/100{hstr}")
            else:
                # 同室にいない少女は詳細不明（ただし居場所は大まかに表示しても良い）
                # 推理の難易度を上げるため「別の場所にいる」とだけ表示
                print(f" ・{g.jp_name}: 別の場所にいる | ストレス: ???")
        print(f" [看守] A:{rl(guards[0].location)}, B:{rl(guards[1].location)}")
        held_p = "、".join(item_disp(i, state) for i in state.holding("player"))
        if held_p: print(f" [所持品] {held_p}")
        if state.escape.members:
            mem_names = []
            for m in state.escape.members:
                if m == "player": mem_names.append("あなた")
                elif m in girls: mem_names.append(girls[m].jp_name)
            print(f" [脱出作戦] {state.escape.bar}  参加者: {', '.join(mem_names)}")

        # プレイヤー行動
        handle_player_turn(state, girls, player, rule)

        # 少女の行動（AI）
        print("\n--- 魔法少女たちの行動 ---")
        for name, girl in girls.items():
            if not girl.is_alive: continue
            girl.update_goal()
            if girl.location == "punishment_cell":
                girl.punished_turns -= 1
                if girl.punished_turns <= 0: girl.location = "cell"
                print(f" ・{girl.jp_name}: 懲罰房で隔離中..."); continue

            normal, murder = girl_available_actions(girl, state, girls)

            if murder and (girl.goal == "murder" or random.random() < 0.6):
                # 殺害実行（ただしプレイヤーが同室にいなければ黙って実行）
                display = cover_msg(girl.personality)
                # プレイヤーが同室にいる場合のみ偽装セリフを表示（そうでなければ無表示）
                if player.location == girl.location:
                    print(f" ・{girl.jp_name}: {display} ({rl(girl.location)}で静かに過ごす)")
                victim = execute_girl_murder(girl, state, girls, player)
                if victim and player.location == girl.location and not player.is_caught:
                    # プレイヤーが同室にいた場合、現行犯で探索突入
                    player.memories.append(MemoryLog(
                        girl.name, state.current_time, player.location,
                        f"{girl.jp_name}が{girls[victim].jp_name}を殺害",
                        girl.stress, is_evidence=True, evidence_strength="strong"))
                    print(f"\n🚨【現行犯！】{girl.jp_name}が殺害を目撃された！")
                    run_explore_phase(girls, player, state, victim)
                    run_court_phase(girls, player, state, victim)
                    return
            else:
                ai_res = ai_choose_action(girl, normal, state.current_time)
                idx    = min(ai_res.get("selected_index", 0), len(normal) - 1)
                chosen = normal[idx]
                # プレイヤーと同室の時だけセリフを表示
                if player.location == girl.location:
                    print(f" ・{girl.jp_name}: 「{ai_res.get('display_message','……。')}」 ({chosen['description']})")
                else:
                    print(f" ・{girl.jp_name}: （別の部屋で行動している）")
                if chosen["action"] == "部屋移動":
                    state.add_trace(chosen["target"], girl.name, state.current_time)
                    girl.location = chosen["target"]
                    girl.memories.append(MemoryLog(girl.name, state.current_time,
                                                    girl.location, "移動", girl.stress))
                elif chosen["action"] == "食事":
                    # 食事のストレス減少を-15に調整
                    girl.stress = max(0, girl.stress - 15)
                elif chosen["action"] == "アイテム取得":
                    state.item_locations[chosen["target"]] = girl.name
                    girl.memories.append(MemoryLog(girl.name, state.current_time, girl.location,
                                                    f"{item_disp(chosen['target'],state)}を取得",
                                                    girl.stress))
                elif chosen["action"] == "アイテム置く":
                    state.item_locations[chosen["target"]] = girl.location
                elif chosen["action"] == "脱出提案":
                    if player.location == girl.location and player.is_alive:
                        hate_score = girl.hate.get("player", 50)
                        prob = (100 - hate_score) / 100.0
                        agreed = random.random() < prob
                        speech = ai_escape_proposal(girl, hate_score, agreed, state.current_time)
                        print(f"[{girl.jp_name}]（プレイヤーに）: 「{speech}」")
                        if agreed:
                            print(f"✨ {girl.jp_name}が脱出作戦に参加したいと言ってきた！")
                            print("あなたは承諾しますか？ (y/n)")
                            ans = input().strip().lower()
                            if ans == 'y':
                                state.escape.add_member(girl.name)
                                print(f"{girl.jp_name}が脱出メンバーに加わった。")
                        else:
                            print(f"{girl.jp_name}は断った。")

        # 看守検問（浮遊回避あり）
        if rule["out_ban"]:
            for name, girl in girls.items():
                if not girl.is_alive: continue
                if girl.location in ("cell", "punishment_cell"): continue
                if girl.magic == "fly" and random.random() < 0.5:
                    # 浮遊で見つからない場合、何も表示しない（プレイヤー同室なら表示しても良い）
                    if player.location == girl.location:
                        print(f"  🕊️ {girl.jp_name}は浮遊して看守の目を逃れた。")
                    continue
                for g in guards:
                    if g.location == girl.location:
                        print(f"🚨【捕縛】{girl.jp_name}が{rl(girl.location)}で発見→懲罰房！")
                        state.confiscate(name, girl.location)
                        girl.location = "punishment_cell"; girl.punished_turns = 2
                        break
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

        # 忘却 + 痕跡風化
        for char in all_chars.values():
            for mem in char.memories: mem.age_memory()
        state.age_traces()

        state.next_time()

# ==============================================================================
# 14. 裁判フェーズ（証拠漏洩修正済み）
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

    # プレイヤーの証拠リスト（表示用）
    ev_mems = [m for m in player.memories if m.is_evidence and m.who]
    player_witness_lines = []
    for m in ev_mems:
        strength_label = {"strong": "【強】", "weak": "【弱】", "none": ""}.get(
            m.evidence_strength, "")
        when_str = m.when if isinstance(m.when, str) else m.when[0]
        player_witness_lines.append(f"{strength_label}[{when_str}] {m.how}")
    if player_witness_lines:
        print(f"\n📋【あなたの証拠リスト】\n{chr(10).join(player_witness_lines)}\n")

    HATE_TABLE = {"strong": 40, "weak": 20, "none": 10}

    def get_witness_ctx_for(girl: MagicalGirl) -> str:
        lines = []
        for mem in girl.memories:
            if mem.is_evidence and mem.who:
                strength_label = {"strong": "【強】", "weak": "【弱】", "none": ""}.get(
                    mem.evidence_strength, "")
                when_str = mem.when if isinstance(mem.when, str) else mem.when[0]
                lines.append(f"{strength_label}[{when_str}] {mem.how}")
        return "\n".join(lines)

    for turn in range(1, 6):
        print(f"\n【裁判ターン {turn}/5】")
        evidence = input("主張を入力してください:\n> ")
        history.append(f"プレイヤーの主張: {evidence}")

        for name, girl in alive.items():
            witness_ctx = get_witness_ctx_for(girl)
            res = ai_court(girl, evidence, suspect_ids, history, witness_ctx)
            speech = res.get("speech", "……。")
            print(f"[{girl.jp_name}]: 「{speech}」")
            history.append(f"{girl.jp_name}: {speech}")

            if res.get("is_logical", False):
                suspect  = res.get("suspect")
                strength = res.get("evidence_strength", "weak")
                delta    = HATE_TABLE.get(strength, 20)
                if suspect and suspect in girl.hate and suspect != girl.name and suspect != "player":
                    girl.hate[suspect] = min(100, girl.hate.get(suspect, 50) + delta)
                    slabel = {"strong": "【強い証拠】", "weak": "【状況証拠】", "none": ""}.get(strength, "")
                    print(f"  (➡ {girl.jp_name}は納得。{slabel}{suspect}への疑惑度+{delta}！)")
                else:
                    print(f"  (➡ {girl.jp_name}は考え込んでいる。)")
            else:
                girl.hate["player"] = min(100, girl.hate.get("player", 50) + 10)
                print(f"  (➡ {girl.jp_name}はあなたを疑っている。疑惑度+10。)")

    print(f"\n{'='*50}\n 🗳️ 投票の刻\n{'='*50}")
    all_ids = suspect_ids + ["player"]
    votes   = {k: 0 for k in all_ids}
    for name, girl in alive.items():
        cands = {k: v for k, v in girl.hate.items() if k != girl.name and k in votes}
        if cands:
            target = max(cands, key=cands.get)
            votes[target] += 1
            print(f" ・{girl.jp_name} → 【{target}】(疑惑度:{girl.hate.get(target,0)})")
        else:
            print(f" ・{girl.jp_name} → 棄権")

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