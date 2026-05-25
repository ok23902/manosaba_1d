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
    env_val = {"base_url": LLM_BASE_URL, "model": LLM_MODEL}[key]
    return env_val if env_val else _DEFAULTS.get(LLM_PROVIDER, {}).get(key, "")

RESOLVED_BASE_URL = _resolve("base_url")
RESOLVED_MODEL    = _resolve("model")

if not LLM_API_KEY and LLM_PROVIDER != "local":
    raise ValueError(f"⚠️ .env に 'LLM_API_KEY' が未設定です。(LLM_PROVIDER={LLM_PROVIDER})")

# ==============================================================================
# 1. LLM汎用クライアント
# ==============================================================================
class LLMClient:
    def __init__(self):
        self.provider = LLM_PROVIDER
        self.model    = RESOLVED_MODEL
        if self.provider in ("deepseek", "openai", "local"):
            from openai import OpenAI
            kwargs = {"api_key": LLM_API_KEY or "local"}
            if RESOLVED_BASE_URL:
                kwargs["base_url"] = RESOLVED_BASE_URL
            self._client = OpenAI(**kwargs)
        elif self.provider == "anthropic":
            import anthropic
            self._client = anthropic.Anthropic(api_key=LLM_API_KEY)
        else:
            raise ValueError(f"未対応のLLM_PROVIDER: {self.provider}")

    def ask_json(self, prompt: str) -> dict:
        system = (
            "You are a game engine backend. "
            "Respond ONLY with a valid JSON object. No markdown, no explanations."
        )
        try:
            if self.provider in ("deepseek", "openai", "local"):
                extra = {}
                if self.provider in ("deepseek", "openai"):
                    extra["response_format"] = {"type": "json_object"}
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user",   "content": prompt},
                    ],
                    temperature=0.3, **extra,
                )
                raw = resp.choices[0].message.content or "{}"
            elif self.provider == "anthropic":
                resp = self._client.messages.create(
                    model=self.model, max_tokens=512, system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = resp.content[0].text if resp.content else "{}"
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw)
        except Exception as e:
            print(f"【APIエラー】空データを返します ({self.provider}): {e}")
            return {}

llm = LLMClient()

# ==============================================================================
# 2. マップ・時間定義
# ==============================================================================
MAP = {
    "corridor":          {"name": "廊下",      "links": ["entertainment_room", "shower_room", "lounge"]},
    "entertainment_room":{"name": "娯楽室",    "links": ["corridor"]},
    "shower_room":       {"name": "シャワー室", "links": ["corridor"]},
    "lounge":            {"name": "ラウンジ",  "links": ["corridor", "cell", "court"]},
    "cell":              {"name": "監房",      "links": ["lounge"]},
    "court":             {"name": "裁判所",    "links": ["lounge"]},
    "punishment_cell":   {"name": "懲罰房",    "links": []},
}

TIME_SLOTS = ["6:00", "10:00", "12:00", "15:00", "17:00", "22:00"]

# ==============================================================================
# 3. データ構造
# ==============================================================================
class MemoryLog:
    def __init__(self, who: str, when: str, where: str, how: str, why_stress: int):
        self.who        = who
        self.when       = when
        self.where      = where
        self.how        = how
        self.why_stress = why_stress
        self.turns_left = 3

    def age_memory(self):
        self.turns_left -= 1
        if self.turns_left == 2:
            self.where = list(set([self.where, "廊下", "ラウンジ"]))
        elif self.turns_left == 1:
            self.when = list(set([self.when, "6:00", "12:00", "22:00"]))
        elif self.turns_left <= 0:
            self.who = self.when = self.where = self.how = None

    def to_dict(self) -> dict:
        return {"who": self.who, "when": self.when, "where": self.where, "how": self.how}


class MagicalGirl:
    def __init__(self, name: str, jp_name: str, personality: str, magic: str, prompt_hint: str):
        self.name        = name
        self.jp_name     = jp_name
        self.personality = personality
        self.magic       = magic
        self.prompt_hint = prompt_hint
        self.stress         = 20
        self.location       = "cell"
        self.punished_turns = 0
        self.is_alive       = True
        # hate: 他者への疑惑度（裁判で投票先に使う）
        self.hate: Dict[str, int] = {"ema": 10, "sherry": 10, "hanna": 10, "player": 10}
        self.love: Dict[str, int] = {"ema": 10, "sherry": 10, "hanna": 10, "player": 10}
        self.memories: List[MemoryLog] = []


class Guard:
    def __init__(self, name: str):
        self.name        = name
        self.route       = ["corridor", "entertainment_room", "shower_room", "lounge"]
        self.route_index = random.randint(0, 3)
        self.location    = self.route[self.route_index]

    def move(self):
        self.route_index = (self.route_index + 1) % len(self.route)
        self.location    = self.route[self.route_index]


class PlayerState:
    def __init__(self):
        self.location       = "lounge"
        self.punished_turns = 0
        self.is_caught      = False  # 懲罰房中フラグ


class GameState:
    def __init__(self):
        self.day              = 1
        self.time_index       = 0
        self.truth_logs: List[MemoryLog] = []
        self.dead_bodies: Dict[str, str] = {}
        self.murder_this_turn = False

    @property
    def current_time(self) -> str:
        return TIME_SLOTS[self.time_index]

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
        self.time_index += 1
        if self.time_index >= len(TIME_SLOTS):
            self.time_index = 0
            self.day += 1
        self.murder_this_turn = False

# ==============================================================================
# 4. ユーティリティ
# ==============================================================================
def get_present_girls(girls: Dict[str, MagicalGirl], location: str) -> List[MagicalGirl]:
    """指定部屋にいる生存中の少女一覧"""
    return [g for g in girls.values() if g.is_alive and g.location == location]


def print_room_header(location: str, girls: Dict[str, MagicalGirl], player: PlayerState):
    """現在地と同室人物を表示"""
    present = get_present_girls(girls, location)
    names   = "、".join(g.jp_name for g in present) if present else "誰もいない"
    print(f"\nあなたの現在位置: {MAP[location]['name']}  |  同室: [{names}]")

# ==============================================================================
# 5. AI呼び出し
# ==============================================================================
def ai_choose_action(girl: MagicalGirl, available_actions: List[dict], current_time: str) -> dict:
    prompt = f"""
キャラクター: {girl.jp_name} (性格: {girl.personality}, ストレス: {girl.stress}/100)
口調ルール: {girl.prompt_hint}
現在時刻: {current_time}

【実行可能な行動リスト（indexは0始まり）】:
{json.dumps(available_actions, ensure_ascii=False, indent=2)}

【ルール】
- ストレスが70以上かつ「殺害」が選択肢にあれば、高確率で殺害を選ぶ。
- selected_indexはリストの番号（0始まり）。
- messageは必ず selected_index で選んだ行動と矛盾しないセリフにすること。

【出力フォーマット（JSONのみ）】
{{
  "selected_index": 選択した行動の番号(int),
  "message": "選んだ行動に対応したセリフまたは心の声"
}}
"""
    res = llm.ask_json(prompt)
    return res if res else {"selected_index": 0, "message": "……行くか。"}


def ai_respond_to_player(girl: MagicalGirl, player_message: str, current_time: str) -> str:
    prompt = f"""
あなたは『魔法少女ノ魔女裁判』の登場人物、{girl.jp_name}です。
口調ルール: {girl.prompt_hint}
状態: ストレス={girl.stress}/100, プレイヤーへの疑惑度={girl.hate['player']}/100
現在時刻: {current_time}

プレイヤーの発言: 「{player_message}」

キャラクター性・口調・感情を反映した返答を1〜2文で。

【出力フォーマット（JSONのみ）】
{{"reply": "少女のセリフ"}}
"""
    res = llm.ask_json(prompt)
    return res.get("reply", "……何よ。")


def ai_evaluate_interaction(girl: MagicalGirl, player_message: str, girl_reply: str) -> dict:
    prompt = f"""
キャラクター: {girl.jp_name}
プレイヤーの発言: 「{player_message}」
キャラクターの返答: 「{girl_reply}」

この会話によるストレスとプレイヤーへの疑惑度の変動を判定。
・親切・的確 → ストレス減少（負）、疑惑度減少
・煽り・不快・怪しい → ストレス上昇（正）、疑惑度上昇
値の範囲: -20 〜 +20

【出力フォーマット（JSONのみ）】
{{"stress_change": int, "hate_change": int}}
"""
    res = llm.ask_json(prompt)
    return res if res else {"stress_change": 0, "hate_change": 0}


def ai_court_debate(girl: MagicalGirl, player_evidence: str, all_ids: List[str], history: List[str]) -> dict:
    """
    裁判AI。疑惑度の判定を「納得したか」ではなく「誰が怪しいか」で行う。
    自分自身をsuspectにできない制約をpromptで明示。
    """
    mem_str   = json.dumps([m.to_dict() for m in girl.memories if m.who], ensure_ascii=False)
    others    = [i for i in all_ids if i != girl.name]
    prompt = f"""
登場人物: {girl.jp_name}（id: {girl.name}）
口調: {girl.prompt_hint}
あなたの記憶ログ（曖昧になっている）: {mem_str}

裁判の議論履歴:
{chr(10).join(history)}

プレイヤーの主張: 「{player_evidence}」

【判定基準】
1. is_logical: この主張は論理的か（記憶ログや状況と照合して矛盾がないか）
2. suspect: is_logicalがtrueの場合、この主張を踏まえて最も怪しいと思う人物のid
   - 選択肢: {others}
   - 必ず上記リストの中から選ぶこと（自分自身({girl.name})は選べない）
3. speech: 裁判でのあなたの発言セリフ（口調を守ること）

【出力フォーマット（JSONのみ）】
{{
  "speech": "裁判でのセリフ",
  "is_logical": true/false,
  "suspect": "id（is_logicalがfalseの場合はnull）"
}}
"""
    return llm.ask_json(prompt)

# ==============================================================================
# 6. ゲーム初期化
# ==============================================================================
def setup_game():
    girls = {
        "ema": MagicalGirl(
            "ema", "桜羽エマ", "extrovert", "none",
            "一人称は「ボク」。ボーイッシュで正義感が強くハキハキしている。"
            "思ったことをそのまま口に出す素直な性格。嘘が苦手。"
            "他人に嫌われることを極端に怖がっているため強く出られないこともある。"
            "敬語は使わない。例:「ボクはそう思わないけど」「それ、おかしくない？」"
        ),
        "sherry": MagicalGirl(
            "sherry", "橘シェリー", "extrovert", "monster_strength",
            "一人称は「私」。名探偵を自称する好奇心旺盛な探偵キャラ。"
            "常に元気で空気を読まない。道徳心がなく人の気持ちがわからない。"
            "根は諦めない強さを持つ。"
            "例:「面白いじゃないですか！」「そこが謎なんですよねー」「え、なんで怒ってるんですか？」"
        ),
        "hanna": MagicalGirl(
            "hanna", "遠野ハンナ", "introvert", "fly",
            "一人称は「わたくし」。貧乏出身だがお嬢様口調で高慢に振る舞う見栄っ張り。"
            "内心は臆病で不安定。強がりと脆さが同居している。"
            "例:「わたくしには関係ありませんわ」「……べ、別に怖くなんてありませんのよ」"
        ),
    }
    guards = [Guard("看守A"), Guard("看守B")]
    state  = GameState()
    player = PlayerState()
    return girls, guards, state, player


def generate_available_actions(girl: MagicalGirl, state: GameState, girls_dict: dict) -> List[dict]:
    actions      = []
    current_room = MAP[girl.location]
    rule         = state.get_phase_rule()

    if girl.location == "punishment_cell":
        return [{"action": "待機", "target": "punishment_cell", "description": "懲罰房で大人しく過ごす"}]

    if rule["type"] == "cell_reset":
        if girl.location != "cell":
            return [{"action": "部屋移動", "target": "cell", "description": "監房に戻る（強制ルール）"}]
        return [{"action": "待機", "target": "none", "description": "監房で大人しく過ごす"}]

    for room_id in current_room["links"]:
        if room_id == "court":
            continue
        actions.append({"action": "部屋移動", "target": room_id, "description": f"{MAP[room_id]['name']}へ移動する"})

    if girl.location == "lounge" and "食" in rule["info"]:
        actions.append({"action": "食事", "target": "lounge", "description": "ラウンジでご飯を食べる"})

    if girl.stress >= 70 and not state.murder_this_turn:
        room_members = [
            n for n, g in girls_dict.items()
            if g.location == girl.location and n != girl.name and g.is_alive
        ]
        if room_members:
            actions.append({"action": "殺害", "target": "any", "description": "同じ部屋にいる誰かを密かに殺害する（クロスボウを使用）"})

    actions.append({"action": "待機", "target": "none", "description": f"{MAP[girl.location]['name']}で静かに過ごす"})
    return actions

# ==============================================================================
# 7. プレイヤー行動フェーズ（移動→会話の順）
# ==============================================================================
def handle_player_turn(state: GameState, girls: Dict[str, MagicalGirl], player: PlayerState, rule: dict):
    """
    ① 移動（隣接部屋 or その場に留まる）
    ② 移動後の部屋で会話（任意）
    """
    # 懲罰房中は行動不可
    if player.is_caught:
        player.punished_turns -= 1
        print(f"⛓️ あなたは懲罰房に拘束されています。（残り {player.punished_turns} ターン）")
        if player.punished_turns <= 0:
            player.location  = "cell"
            player.is_caught = False
            print("解放されて監房に戻されました。")
        return

    # 点呼時間はプレイヤーも監房へ強制
    if rule["type"] == "cell_reset":
        if player.location != "cell":
            player.location = "cell"
            print("⚡ 点呼時間です。監房へ強制移動しました。")
        print_room_header(player.location, girls, player)
        return

    # ── ① 移動フェーズ ──────────────────────────────
    print_room_header(player.location, girls, player)

    adjacent = [r for r in MAP[player.location]["links"] if r not in ("court", "punishment_cell")]
    print("\n【移動先を選んでください】")
    print(f"  [0] その場に留まる（{MAP[player.location]['name']}）")
    for i, room_id in enumerate(adjacent, start=1):
        print(f"  [{i}] {MAP[room_id]['name']}へ移動する")

    move_choice = input("選択してください: ").strip()
    try:
        idx = int(move_choice)
        if idx == 0:
            print(f"➡ {MAP[player.location]['name']} に留まります。")
        elif 1 <= idx <= len(adjacent):
            player.location = adjacent[idx - 1]
            print(f"➡ {MAP[player.location]['name']} に移動しました。")
        else:
            print("無効な入力です。その場に留まります。")
    except ValueError:
        print("無効な入力です。その場に留まります。")

    # ── ② 会話フェーズ ──────────────────────────────
    present = get_present_girls(girls, player.location)
    names   = "、".join(g.jp_name for g in present) if present else "誰もいない"
    print(f"\n現在地: {MAP[player.location]['name']}  |  同室: [{names}]")

    if not present:
        return

    talk = input("\n同室のキャラに話しかけますか？ (y/n): ").strip().lower()
    if talk != "y":
        return

    print("\n【会話相手を選んでください】")
    for i, g in enumerate(present):
        print(f"  [{i}] {g.jp_name}")

    try:
        idx    = int(input("番号を入力してください: ").strip())
        target = present[idx]
        player_msg = input(f"[{target.jp_name}への発言]: ")

        reply    = ai_respond_to_player(target, player_msg, state.current_time)
        print(f"\n[{target.jp_name}]: 「{reply}」")

        eval_res = ai_evaluate_interaction(target, player_msg, reply)
        s_change = eval_res.get("stress_change", 0)
        h_change = eval_res.get("hate_change", 0)
        target.stress         = max(0, min(100, target.stress + s_change))
        target.hate["player"] = max(0, min(100, target.hate["player"] + h_change))
        print(f"（裏の変動: ストレス={s_change:+} / 疑惑度={h_change:+}）")

        target.memories.append(
            MemoryLog("player", state.current_time, player.location,
                      f"プレイヤーとの会話: {player_msg}", target.stress)
        )
    except (ValueError, IndexError):
        print("無効な選択です。会話を中止しました。")

# ==============================================================================
# 8. メインループ
# ==============================================================================
def main_loop():
    girls, guards, state, player = setup_game()

    print("=" * 50)
    print(" 🩸 プロジェクト『manosaba3d』1Dプロトタイプ Ver 2.2")
    print(f"    LLM: {LLM_PROVIDER} / {RESOLVED_MODEL}")
    print("=" * 50)

    while True:
        rule = state.get_phase_rule()
        print(f"\n{'='*50}")
        print(f"【Day {state.day} - {state.current_time}】 状況: {rule['info']}")
        print(f"{'='*50}")

        # ── 看守移動 ────────────────────────────────────
        for g in guards:
            g.move()

        # ── ストレス自動上昇（個人差あり） ───────────────
        for girl in girls.values():
            if girl.is_alive and girl.location != "punishment_cell":
                base = random.randint(2, 7) if girl.personality == "introvert" else random.randint(3, 12)
                girl.stress = min(100, girl.stress + base)

        # ── 同室の不和処理（40%確率） ─────────────────────
        names = list(girls.keys())
        for i, na in enumerate(names):
            for nb in names[i+1:]:
                ga, gb = girls[na], girls[nb]
                if ga.is_alive and gb.is_alive and ga.location == gb.location:
                    if random.random() < 0.4:
                        for g, other in [(ga, nb), (gb, na)]:
                            g.stress          = min(100, g.stress + 8)
                            g.hate[other]     = min(100, g.hate[other] + 10)

        # ── 死体発見チェック（プレイヤーと同室） ───────────
        for room_id, victim_name in list(state.dead_bodies.items()):
            if player.location == room_id and not player.is_caught:
                print(f"\n🚨【!!! 事件発生 !!!】\n{MAP[room_id]['name']}で、{girls[victim_name].jp_name}の冷たい死体を発見しました！")
                run_court_phase(girls, state, player, victim_name)
                return

        # ── ステータス表示 ──────────────────────────────
        print("\n--- 魔法少女たちの現在のステータス ---")
        for name, g in girls.items():
            loc = MAP[g.location]["name"] if g.is_alive else "死亡"
            print(f" ・{g.jp_name}: 位置: {loc} | ストレス: {g.stress}/100")
        print(f" [看守位置] 看守A: {MAP[guards[0].location]['name']}, 看守B: {MAP[guards[1].location]['name']}")

        # ── プレイヤーの行動（移動→会話） ──────────────
        handle_player_turn(state, girls, player, rule)

        # ── AI少女たちの自律行動 ────────────────────────
        print("\n--- 魔法少女たちの行動 ---")
        for name, girl in girls.items():
            if not girl.is_alive:
                continue
            if girl.location == "punishment_cell":
                girl.punished_turns -= 1
                if girl.punished_turns <= 0:
                    girl.location = "cell"
                print(f" ・{girl.jp_name}: 懲罰房で隔離中...")
                continue

            available = generate_available_actions(girl, state, girls)
            ai_res    = ai_choose_action(girl, available, state.current_time)
            idx       = ai_res.get("selected_index", 0)
            if idx >= len(available):
                idx = 0
            chosen = available[idx]
            print(f" ・{girl.jp_name}: 「{ai_res.get('message', '……')}」 ({chosen['description']})")

            if chosen["action"] == "部屋移動":
                girl.location = chosen["target"]
                girl.memories.append(
                    MemoryLog(girl.name, state.current_time, girl.location, "移動", girl.stress)
                )
            elif chosen["action"] == "食事":
                girl.stress = max(0, girl.stress - 25)
            elif chosen["action"] == "殺害" and not state.murder_this_turn:
                room_members = [
                    n for n, g in girls.items()
                    if g.location == girl.location and n != girl.name and g.is_alive
                ]
                if room_members:
                    victim = random.choice(room_members)
                    girls[victim].is_alive = False
                    state.dead_bodies[girl.location] = victim
                    state.murder_this_turn           = True
                    state.truth_logs.append(
                        MemoryLog(girl.name, state.current_time, girl.location, "クロスボウ", girl.stress)
                    )
                    # 殺害現場を目撃した少女にもログを残す（証拠として使える）
                    for witness_name, witness in girls.items():
                        if (witness.is_alive and witness.location == girl.location
                                and witness_name != girl.name and witness_name != victim):
                            witness.memories.append(
                                MemoryLog(girl.name, state.current_time, girl.location,
                                          f"クロスボウで{girls[victim].jp_name}を殺害", girl.stress)
                            )
                    # プレイヤーが同室なら殺害を目撃→即発見
                    if player.location == girl.location and not player.is_caught:
                        print(f"\n🚨【現行犯！】{girl.jp_name}が{girls[victim].jp_name}を殺害するのを目撃しました！")
                        run_court_phase(girls, state, player, victim)
                        return

        # ── 看守の検問（プレイヤーも対象） ───────────────
        if rule["out_ban"]:
            # 少女の検問
            for name, girl in girls.items():
                if girl.is_alive and girl.location not in ("cell", "punishment_cell"):
                    for g in guards:
                        if g.location == girl.location:
                            print(f"🚨【検問捕縛】{girl.jp_name}が{MAP[girl.location]['name']}にいるのを見つかり、懲罰房へ連行されました！")
                            girl.location       = "punishment_cell"
                            girl.punished_turns = 2
            # プレイヤーの検問
            if not player.is_caught and player.location not in ("cell", "punishment_cell"):
                for g in guards:
                    if g.location == player.location:
                        print(f"🚨【検問捕縛】あなたが外出禁止時間中に{MAP[player.location]['name']}にいるのを見つかり、懲罰房へ連行されました！")
                        player.location       = "punishment_cell"
                        player.is_caught      = True
                        player.punished_turns = 2
                        break

        # ── 忘却処理 ────────────────────────────────────
        for girl in girls.values():
            for mem in girl.memories:
                mem.age_memory()

        state.next_time()

# ==============================================================================
# 9. 魔女裁判フェーズ
# ==============================================================================
def run_court_phase(girls: Dict[str, MagicalGirl], state: GameState, player: PlayerState, victim_id: str):
    alive_girls = {n: g for n, g in girls.items() if g.is_alive}
    all_ids     = list(alive_girls.keys()) + ["player"]

    if not alive_girls:
        print("\n💀【詰み】生存者がいません。裁判は成立しませんでした。")
        return

    print("\n" + "="*50)
    print(" ⚖️ 魔女裁判 開廷 ⚖️")
    print(f" 被害者: {girls[victim_id].jp_name}")
    print(" 5ターンの間に証拠を突きつけ、真犯人の疑惑度を上げろ！")
    print("="*50)

    for g in alive_girls.values():
        g.location = "court"
    player.location = "court"

    court_history: List[str] = [f"裁判開始。被害者は{girls[victim_id].jp_name}。"]

    for turn in range(1, 6):
        print(f"\n【裁判ターン {turn} / 5】")
        player_evidence = input("あなたの主張、または目撃した行動矛盾を入力してください:\n> ")
        court_history.append(f"プレイヤーの主張: {player_evidence}")

        for name, girl in alive_girls.items():
            res    = ai_court_debate(girl, player_evidence, all_ids, court_history)
            speech = res.get("speech", "……。")
            print(f"[{girl.jp_name}]: 「{speech}」")
            court_history.append(f"{girl.jp_name}: {speech}")

            if res.get("is_logical", False):
                suspect = res.get("suspect")
                # 自分自身への疑惑は無効（AIが守れなかった場合の保険）
                if suspect and suspect in girl.hate and suspect != girl.name:
                    girl.hate[suspect] += 25
                    print(f"  (➡ {girl.jp_name}は納得。{suspect}への疑惑度が上昇！)")
                else:
                    print(f"  (➡ {girl.jp_name}は考え込んでいる。)")
            else:
                girl.hate["player"] += 15
                print(f"  (➡ {girl.jp_name}はあなたの言動を疑っている。プレイヤーへの疑惑度が上昇。)")

    # ── 投票 ──────────────────────────────────────────
    print("\n" + "="*50)
    print(" 🗳️ 投票の刻")
    print("="*50)

    votes: Dict[str, int] = {k: 0 for k in all_ids}
    for name, girl in alive_girls.items():
        # 生存者の中で自分以外の最高疑惑度の相手に投票
        candidates = {k: v for k, v in girl.hate.items() if k != girl.name and k in votes}
        if candidates:
            target = max(candidates, key=candidates.get)
            votes[target] += 1
            print(f" ・{girl.jp_name} の投票 ➡ 【{target}】 (疑惑度: {girl.hate[target]})")

    max_vote   = max(votes.values()) if votes else 0
    candidates = [k for k, v in votes.items() if v == max_vote and max_vote > 0]
    if not candidates:
        print("有効票がありませんでした。裁判不成立。")
        return
    executed = random.choice(candidates)

    print(f"\n最多票を集めた 【{executed}】 の処刑が決定しました。")
    print("黒い鎖が天井から引きちぎるように伸び、肉体を締め上げる……。")

    real_killer = state.truth_logs[0].who if state.truth_logs else "不明"

    if executed == "player":
        print(f"\n💀【ゲームオーバー】あなたが処刑されました。真犯人は「{real_killer}」です。")
    elif executed == real_killer:
        print(f"\n🎉【裁判勝利】真犯人「{girls[executed].jp_name}」を処刑しました！")
    else:
        print(f"\n💀【冤罪】「{girls[executed].jp_name}」は無実でした。真犯人は「{real_killer}」です。")
    print("="*50)


if __name__ == "__main__":
    main_loop()