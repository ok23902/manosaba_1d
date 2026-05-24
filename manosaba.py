import os
import json
import random
from typing import List, Dict, Any
from openai import OpenAI
from dotenv import load_dotenv

# ==============================================================================
# 0. 安全な環境設定 (.env からの読み込み)
# ==============================================================================
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
BASE_URL = "https://api.deepseek.com/v1"

if not DEEPSEEK_API_KEY:
    raise ValueError("⚠️ エラー: .env ファイルに 'DEEPSEEK_API_KEY' が設定されていません。")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)

# ==============================================================================
# 1. 物理制限・マップ・スケジュール定義
# ==============================================================================
MAP = {
    "corridor": {"name": "廊下", "links": ["entertainment_room", "shower_room", "lounge"], "type": "path"},
    "entertainment_room": {"name": "娯楽室", "links": ["corridor"], "type": "stress_down"},
    "shower_room": {"name": "シャワー室", "links": ["corridor"], "type": "shower"},
    "lounge": {"name": "ラウンジ", "links": ["corridor", "cell", "court"], "type": "lounge"},
    "cell": {"name": "監房", "links": ["lounge"], "type": "reset_point"},
    "court": {"name": "裁判所", "links": ["lounge"], "type": "court"},
    "punishment_cell": {"name": "懲罰房", "links": [], "type": "prison"}
}

TIME_SLOTS = ["6:00", "10:00", "12:00", "15:00", "17:00", "22:00"]

# ==============================================================================
# 2. データ構造（記憶ログ・キャラクター・ゲーム状態管理）
# ==============================================================================
class MemoryLog:
    """3ターンで自動的に風化・曖昧化する少女たちの主観ログ"""
    def __init__(self, who: str, when: str, where: str, how: str, why_stress: int):
        self.who = who
        self.when = when
        self.where = where
        self.how = how
        self.why_stress = why_stress
        self.turns_left = 3

    def age_memory(self):
        self.turns_left -= 1
        if self.turns_left == 2:
            self.where = list(set([self.where, "廊下", "ラウンジ"])) # 場所がボヤける
        elif self.turns_left == 1:
            self.when = list(set([self.when, "6:00", "12:00", "22:00"])) # 時間がボヤける
        elif self.turns_left <= 0:
            self.who = self.when = self.where = self.how = None # 完全忘却

    def to_dict(self) -> dict:
        return {"who": self.who, "when": self.when, "where": self.where, "how": self.how}

class MagicalGirl:
    def __init__(self, name: str, jp_name: str, personality: str, magic: str, prompt_hint: str):
        self.name = name
        self.jp_name = jp_name
        self.personality = personality 
        self.magic = magic             
        self.prompt_hint = prompt_hint # 口調の指示（※別プロジェクトで精査するため現状維持）
        
        self.stress = 20  # 初期ストレス（殺人発生を早めるためやや高めからスタート）
        self.location = "cell"
        self.punished_turns = 0
        self.is_alive = True
        self.hate: Dict[str, int] = {"ema": 10, "sherry": 10, "hanna": 10, "player": 10}
        self.love: Dict[str, int] = {"ema": 10, "sherry": 10, "hanna": 10, "player": 10}
        self.memories: List[MemoryLog] = []

class Guard:
    def __init__(self, name: str):
        self.name = name
        self.route = ["corridor", "entertainment_room", "shower_room", "lounge"]
        self.route_index = random.randint(0, 3)
        self.location = self.route[self.route_index]

    def move(self):
        self.route_index = (self.route_index + 1) % len(self.route)
        self.location = self.route[self.route_index]

class GameState:
    def __init__(self):
        self.day = 1
        self.time_index = 0
        self.truth_logs: List[MemoryLog] = [] # 絶対に汚染されない真実の事件ログ
        self.dead_bodies: Dict[str, str] = {} # {"room_id": "victim_name"}
        self.player_location = "lounge"      # プレイヤーの初期位置

    @property
    def current_time(self) -> str:
        return TIME_SLOTS[self.time_index]

    def get_phase_rule(self) -> dict:
        t = self.current_time
        if t == "6:00":   return {"info": "自由行動時間 (朝食)", "out_ban": False, "type": "free"}
        if t == "10:00":  return {"info": "監房強制リセット（全員点呼）", "out_ban": True, "type": "cell_reset"}
        if t == "12:00":  return {"info": "自由行動時間 (昼食)", "out_ban": False, "type": "free"}
        if t == "15:00":  return {"info": "監房強制リセット（全員点呼）", "out_ban": True, "type": "cell_reset"}
        if t == "17:00":  return {"info": "自由行動時間 (夕食)", "out_ban": False, "type": "free"}
        if t == "22:00":  return {"info": "外出禁止時間 (就寝)", "out_ban": True, "type": "free"}
        return {"info": "自由行動", "out_ban": False, "type": "free"}

    def next_time(self):
        self.time_index += 1
        if self.time_index >= len(TIME_SLOTS):
            self.time_index = 0
            self.day += 1

# ==============================================================================
# 3. DeepSeek API 連携ロジック（思考・対話・会話評価）
# ==============================================================================
def ask_deepseek_json(prompt: str) -> dict:
    """DeepSeekに安全にJSONを返させる共通関数"""
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a game engine backend. You must respond ONLY with a valid JSON object. No markdown, no explanations."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"【APIエラー】デフォルトの空データを返します: {e}")
        return {}

def ai_choose_action(girl: MagicalGirl, available_actions: List[dict], current_time: str) -> dict:
    """物理制限された安全な選択肢から、少女の精神状態に合わせて次の行動を選択させる"""
    prompt = f"""
    キャラクター: {girl.jp_name} (性格: {girl.personality}, 魔法: {girl.magic}, ストレス: {girl.stress}/100)
    口調のルール: {girl.prompt_hint}
    現在の時刻: {current_time}
    
    【物理的に実行可能な行動リスト】:
    {json.dumps(available_actions, ensure_ascii=False, indent=2)}
    
    【重要ルール】
    ストレスが70以上の時は、殺意が高まります。もし行動リストの中に「殺害」があれば、それを選ぶ確率が跳ね上がります。
    
    【出力フォーマット（JSONのみ）】
    {{
      "selected_index": 出力したリストの選択した番号(int),
      "message": "その行動を行う時のセリフ、または心の中のつぶやき"
    }}
    """
    res = ask_deepseek_json(prompt)
    return res if res else {"selected_index": 0, "message": "……行くか。"}

def ai_respond_to_player(girl: MagicalGirl, player_message: str, current_time: str) -> str:
    """プレイヤーが同室の少女に話しかけた際、口調に沿った返答を生成する"""
    prompt = f"""
    あなたは『魔法少女ノ魔女裁判』の登場人物、{girl.jp_name}です。
    口調のルール: {girl.prompt_hint}
    現在の状態: ストレス={girl.stress}/100, プレイヤーへのヘイト={girl.hate['player']}/100, 位置={MAP[girl.location]['name']}
    現在時刻: {current_time}

    プレイヤーからあなたへの発言: 「{player_message}」

    【命令】
    あなたのキャラクター性、口調、プレイヤーへの感情を反映した返答を、少女のセリフとして1文〜2文で出力してください。
    
    【出力フォーマット（JSONのみ）】
    {{
       "reply": "少女のセリフ"
    }}
    """
    res = ask_deepseek_json(prompt)
    return res.get("reply", "……何よ。")

def ai_evaluate_interaction(girl: MagicalGirl, player_message: str, girl_reply: str) -> dict:
    """会話内容を審査し、少女のストレスおよびプレイヤーへのヘイト増減を算出する"""
    prompt = f"""
    キャラクター: {girl.jp_name}
    プレイヤーの発言: 「{player_message}」
    キャラクターの返答: 「{girl_reply}」

    【命令】
    この会話によって、少女の「ストレス」と「プレイヤーへのヘイト」がどう変動したかを判定してください。
    ・親切、または的確な言葉なら、ストレスが減少（負の値）、ヘイトも減少します。
    ・煽り、不快な言葉、怪しい言動なら、ストレスが上昇（正の値）、ヘイトも上昇します。
    ・値の範囲は -20 〜 +20 の間。

    【出力フォーマット（JSONのみ）】
    {{
      "stress_change": 変動値(int),
      "hate_change": 変動値(int)
    }}
    """
    res = ask_deepseek_json(prompt)
    return res if res else {"stress_change": 0, "hate_change": 0}

def ai_court_debate(girl: MagicalGirl, player_evidence: str, history: List[str]) -> dict:
    """裁判中、プレイヤーの主張を少女が自分の記憶ログを元に審査・反論する"""
    mem_str = json.dumps([m.to_dict() for m in girl.memories], ensure_ascii=False)
    prompt = f"""
    登場人物: {girl.jp_name}
    口調: {girl.prompt_hint}
    あなたの曖昧な記憶ログ: {mem_str}
    
    裁判の議論履歴:
    {chr(10).join(history)}
    
    プレイヤーの主張: 「{player_evidence}」
    
    【出力フォーマット（JSONのみ）】
    {{
      "speech": "裁判でのあなたの発言セリフ",
      "is_logical": プレイヤーの言い分に筋が通っていればtrue、矛盾や破綻があればfalse(bool),
      "suspect": "論理的である場合、あなたが最も怪しいと思うキャラ名(ema/sherry/hanna/player)"
    }}
    """
    return ask_deepseek_json(prompt)

# ==============================================================================
# 4. ゲームのメイン処理
# ==============================================================================
def setup_game():
    girls = {
    "ema": MagicalGirl(
        "ema", "桜羽エマ", "extrovert", "none",
        """一人称は「ボク」。ボーイッシュで正義感が強くハキハキしている。
        思ったことをそのまま口に出す素直な性格。嘘が苦手。
        他人に嫌われることを極端に怖がっているため、強く出られないこともある。
        敬語は使わない。例:「ボクはそう思わないけど」「それ、おかしくない？」"""
    ),
    "sherry": MagicalGirl(
        "sherry", "橘シェリー", "extrovert", "monster_strength",
        """一人称は「私」。名探偵を自称する好奇心旺盛な探偵キャラ。
        常に元気で空気を読まない。道徳心がなく人の気持ちがわからない。
        しかし根は諦めない強さを持つ。
        例:「面白いじゃないですか！」「そこが謎なんですよねー」「え、なんで怒ってるんですか？」"""
    ),
    "hanna": MagicalGirl(
        "hanna", "遠野ハンナ", "introvert", "fly",
        """一人称は「わたくし」。貧乏出身だがお嬢様口調で高慢に振る舞う見栄っ張り。
        内心は臆病で不安定。強がりと脆さが同居している。
        例:「わたくしには関係ありませんわ」「……べ、別に怖くなんてありませんのよ」"""
    ),
    }
    guards = [Guard("看守A"), Guard("看守B")]
    state = GameState()
    return girls, guards, state

def generate_available_actions(girl: MagicalGirl, state: GameState, girls_dict: dict) -> List[dict]:
    """物理制限（マップ接続、タイムスケジュール）をPython側で厳密に計算してハルシネーションを潰す"""
    actions = []
    current_room = MAP[girl.location]
    rule = state.get_phase_rule()

    if girl.location == "punishment_cell":
        return [{"action": "待機", "target": "punishment_cell", "description": "懲罰房で大人しく過ごす"}]

    if rule["type"] == "cell_reset":
        if girl.location != "cell":
            return [{"action": "部屋移動", "target": "cell", "description": "監房に戻る（強制ルール）"}]
        else:
            return [{"action": "待機", "target": "none", "description": "監房で大人しく過ごす"}]

    # 1. 部屋移動
    for room_id in current_room["links"]:
        if room_id == "court": continue
        actions.append({"action": "部屋移動", "target": room_id, "description": f"{MAP[room_id]['name']}へ移動する"})

    # 2. 食事
    if girl.location == "lounge" and "食" in rule["info"]:
        actions.append({"action": "食事", "target": "lounge", "description": "ラウンジでご飯を食べる"})

    # 3. 殺害（ストレス70以上、かつ同室に他の生存者がいる場合）
    if girl.stress >= 70:
        room_members = [n for n, g in girls_dict.items() if g.location == girl.location and n != girl.name and g.is_alive]
        if room_members:
            actions.append({"action": "殺害", "target": "any", "description": "同じ部屋にいる誰かを密かに殺害する（クロスボウを使用）"})

    actions.append({"action": "待機", "target": "none", "description": f"{MAP[girl.location]['name']}で静かに過ごす"})
    return actions

def main_loop():
    girls, guards, state = setup_game()
    
    print("==================================================")
    print(" 🩸 プロジェクト『manosaba3d』1Dプロトタイプ Ver 2.0")
    print("==================================================")

    while True:
        rule = state.get_phase_rule()
        print(f"\n==================================================")
        print(f"【Day {state.day} - {state.current_time}】 状況: {rule['info']}")
        print(f"==================================================")
        
        # --- 0. 環境・看守の自動移動 ---
        for g in guards: g.move()

        # 毎ターンの環境によるランダムストレス自動上昇（殺人発生の土壌）
        for girl in girls.values():
            if girl.is_alive and girl.location != "punishment_cell":
                inc = random.randint(5, 15)
                girl.stress = min(100, girl.stress + inc)

        # 少女同士の「エコ」な内部不和処理（同じ部屋に居合わせると、確率で勝手にヘイト・ストレス上昇）
        for name_a, girl_a in girls.items():
            for name_b, girl_b in girls.items():
                if name_a != name_b and girl_a.is_alive and girl_b.is_alive and girl_a.location == girl_b.location:
                    if random.random() < 0.4: # 40%の確率で険悪に
                        girl_a.stress = min(100, girl_a.stress + 8)
                        girl_a.hate[name_b] = min(100, girl_a.hate[name_b] + 10)

        # 死体発見チェック（ターンの最初に前ターンの死体があれば即裁判）
        for room_id, victim_name in list(state.dead_bodies.items()):
            if state.player_location == room_id:
                print(f"\n🚨【!!! 事件発生 !!!】\n{MAP[room_id]['name']}で、{girls[victim_name].jp_name}の冷たい死体を発見しました！")
                run_court_phase(girls, state, victim_name)
                return

        # ステータス一覧の可視化
        print("\n--- 魔法少女たちの現在のステータス ---")
        for name, g in girls.items():
            status = f"位置: {MAP[g.location]['name'] if g.is_alive else '死亡'} | ストレス: {g.stress}/100"
            print(f" ・{g.jp_name}: {status}")
        print(f" [看守位置] 看守A: {MAP[guards[0].location]['name']}, 看守B: {MAP[guards[1].location]['name']}\n")

        # --- 1. プレイヤーの行動フェーズ（介入・会話） ---
        print(f"あなたの現在位置: {MAP[state.player_location]['name']}")
        print("【コマンド】 1:部屋移動する  2:同じ部屋のキャラと1対1で会話する")
        cmd = input("選択してください (1 or 2): ").strip()

        if cmd == "1":
            print("\n【移動可能な部屋】")
            for room_id, room_data in MAP.items():
                if room_id != "court" and room_id != "punishment_cell":
                    print(f" ・{room_data['name']}")
            p_action = input("移動先の部屋名を入力してください: ").strip()
            for r_id, r_data in MAP.items():
                if p_action in r_data["name"]:
                    state.player_location = r_id
                    print(f"➡ {r_data['name']} に移動しました。")
                    break
        elif cmd == "2":
            # 同室の少女を検索
            present_girls = [g for g in girls.values() if g.location == state.player_location and g.is_alive]
            if not present_girls:
                print("この部屋には誰もいません。")
            else:
                print("\n【会話可能な相手】")
                for i, g in enumerate(present_girls):
                    print(f" [{i}] {g.jp_name}")
                target_idx = input("話しかける相手の番号を入力してください: ").strip()
                try:
                    target_girl = present_girls[int(target_idx)]
                    player_msg = input(f"[{target_girl.jp_name}への発言内容]: ")
                    
                    # 1. 話しかけられた少女がDeepSeekで返答
                    reply = ai_respond_to_player(target_girl, player_msg, state.current_time)
                    print(f"\n[{target_girl.jp_name}]: 「{reply}」")
                    
                    # 2. 会話内容によるストレス・ヘイトの評価
                    eval_res = ai_evaluate_interaction(target_girl, player_msg, reply)
                    s_change = eval_res.get("stress_change", 0)
                    h_change = eval_res.get("hate_change", 0)
                    
                    target_girl.stress = max(0, min(100, target_girl.stress + s_change))
                    target_girl.hate["player"] = max(0, min(100, target_girl.hate["player"] + h_change))
                    print(f"（裏の変動: ストレス={s_change:+} / プレイヤーへのヘイト={h_change:+}）")
                    
                    # プレイヤー用ログに手動で履歴を記憶
                    target_girl.memories.append(MemoryLog("player", state.current_time, state.player_location, f"プレイヤーとの会話: {player_msg}", target_girl.stress))
                except (ValueError, IndexError):
                    print("無効な選択です。会話を中止しました。")

        # --- 2. AI魔法少女たちの自律行動フェーズ ---
        print("\n--- 魔法少女たちの行動 ---")
        for name, girl in girls.items():
            if not girl.is_alive: continue
            
            if girl.location == "punishment_cell":
                girl.punished_turns -= 1
                if girl.punished_turns <= 0:
                    girl.location = "cell"
                print(f" ・{girl.jp_name}: 懲罰房で隔離中...")
                continue

            # 安全な物理選択肢をPythonがビルド
            available = generate_available_actions(girl, state, girls)
            ai_res = ai_choose_action(girl, available, state.current_time)
            
            idx = ai_res.get("selected_index", 0)
            if idx >= len(available): idx = 0
            chosen = available[idx]
            
            print(f" ・{girl.jp_name}: 「{ai_res.get('message', '……')}」 ({chosen['description']})")

            # 行動の結果をPython側で確実に処理
            if chosen["action"] == "部屋移動":
                girl.location = chosen["target"]
                # 移動ログを本人の記憶へ蓄積
                girl.memories.append(MemoryLog(girl.name, state.current_time, girl.location, "移動", girl.stress))
            elif chosen["action"] == "食事":
                girl.stress = max(0, girl.stress - 25) # 飯を食うとストレス大幅減
            elif chosen["action"] == "殺害":
                # 同室のターゲットをここで即殺害
                room_members = [n for n, g in girls.items() if g.location == girl.location and n != girl.name and g.is_alive]
                if room_members:
                    victim = random.choice(room_members)
                    girls[victim].is_alive = False
                    state.dead_bodies[girl.location] = victim
                    # 絶対に改ざんされない真実のログをシステムが確保
                    state.truth_logs.append(MemoryLog(girl.name, state.current_time, girl.location, "クロスボウ", girl.stress))

        # --- 3. 看守の検問（外出禁止時間の捕縛） ---
        if rule["out_ban"]:
            for name, girl in girls.items():
                if girl.location != "cell" and girl.location != "punishment_cell":
                    for g in guards:
                        if g.location == girl.location:
                            print(f"🚨【検問捕縛】{girl.jp_name}が外出禁止時間中に{MAP[girl.location]['name']}にいるのを見つかり、懲罰房へ連行されました！")
                            girl.location = "punishment_cell"
                            girl.punished_turns = 2

        # --- 4. 忘却の自動進行 ---
        for girl in girls.values():
            for mem in girl.memories:
                mem.age_memory()

        # 時間の進捗
        state.next_time()

# ==============================================================================
# 5. 魔女裁判フェーズ（5ターンの制限論破・動的ヘイト集約）
# ==============================================================================
def run_court_phase(girls: Dict[str, MagicalGirl], state: GameState, victim_id: str):
    print("\n" + "="*50)
    print(" ⚖️ 魔女裁判 開廷 ⚖️")
    print(f" 被害者: {girls[victim_id].jp_name}")
    print(" 5ターンの間に手持ちの矛盾や状況証拠を突きつけ、犯人のヘイトを上げろ！")
    print("="*50)

    for g in girls.values():
        if g.is_alive: g.location = "court"

    court_history = [f"裁判開始。被害者は{girls[victim_id].jp_name}。"]
    
    for turn in range(1, 6):
        print(f"\n【裁判ターン {turn} / 5】")
        player_evidence = input("あなたの主張、または目撃した少女の行動矛盾を入力してください:\n> ")
        court_history.append(f"プレイヤーの主張: {player_evidence}")

        for name, girl in girls.items():
            if not girl.is_alive: continue
            
            res = ai_court_debate(girl, player_evidence, court_history)
            speech = res.get("speech", "……。")
            print(f"[{girl.jp_name}]: 「{speech}」")
            court_history.append(f"{girl.jp_name}: {speech}")

            # AIの判断に基づいて、Python側でヘイトパラメータを増減
            if res.get("is_logical", False):
                suspect = res.get("suspect")
                if suspect in girl.hate:
                    girl.hate[suspect] += 35
                    print(f"  (➡ {girl.jp_name}は納得した。{suspect}へのヘイトが大幅に上昇！)")
            else:
                girl.hate["player"] += 15
                print(f"  (➡ {girl.jp_name}はあなたの言動を疑っている。プレイヤーへのヘイトが上昇。)")

    # --- 投票処理 ---
    print("\n" + "="*50)
    print(" 🗳️ 投票の刻")
    print("="*50)
    
    votes = {"ema": 0, "sherry": 0, "hanna": 0, "player": 0}
    for name, girl in girls.items():
        if not girl.is_alive: continue
        # キャラは自分の中で「最もヘイトが高い相手」に一票を投じる
        highest_hate_target = max(girl.hate, key=girl.hate.get)
        votes[highest_hate_target] += 1
        print(f" ・{girl.jp_name} の投票 ➡ 【{highest_hate_target}】 (内部ヘイト: {girl.hate[highest_hate_target]})")

    # 最多得票の集計
    max_vote = max(votes.values())
    candidates = [k for k, v in votes.items() if v == max_vote]
    executed = random.choice(candidates)

    print(f"\n最多数の票を集めた 【{executed}】 の処刑が決定しました。")
    print("黒い鎖が天井から引きちぎるように伸び、肉体を締め上げる……。")
    
    real_killer = state.truth_logs[0].who if state.truth_logs else "誰も殺していない"
    if executed == real_killer:
        print(f"\n🎉【裁判完全勝利】おめでとうございます！見事に真犯人「{executed}」を処刑しました！")
    else:
        print(f"\n💀【冤罪】無実の少女を殺してしまいました。真犯人は「{real_killer}」です。")
    print("="*50)

if __name__ == "__main__":
    main_loop()