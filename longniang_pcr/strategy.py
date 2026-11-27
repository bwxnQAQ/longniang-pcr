"""局内策略（纯计算，不碰画面）：带谁上场、开局选谁、招募选谁、印记选什么属性、遗物选哪个。

方向（2026-11-18 用户定的，账号是高练度全角色）：
- 不用每场都带坦克和治疗（奶妈和坦克一个道理：不需要就不选、不上）：所有的关第一次打都先不上坦克治疗、全输出、尽快打完，
  没打过再换——重打时才看谁点名要（对策表里写了 need 的，或者首领战编组页面上「对首领的有效效果」里游戏自己写着“坦克型”的），
  并换成带坦克、带治疗的稳妥队；而且只在队伍真的倒了的时候，时间到了输的（人还活着）是伤害不够，照样全输出。开局三人和招募也一样，坦克和治疗排在最后。
- 坦克要站在最前面才有意义（站位数最小，data/characters.json 的 pos）：坦克前面还站着别人，这个坦克就不算数。
- 敌人是一群还是一个：一群时先带打一群的输出，一个大敌人时先带打单体的（data/characters.json 的 hits）。
- 物理队和法队分开：一队里的输出、破防、增益、减益尽量是同一种伤害类型（每个角色是物理还是魔法见 data/characters.json 的 atks）。
- 同一个角色的不同版本不能同时上场：一队里不重复带。
- 2026-11-18 晚（真机上厄勒克特拉夫人三次没打过之后）用户又定的：
  · 厄勒克特拉夫人默认就带一个坦克（对策表里写 always 的职能第一次打就带）；区域 3 首领只用一队打。
  · 打输了看是怎么输的：从最前面开始一个个倒 → 加坦克；全队血量一起崩 → 加治疗；时间到了人还活着 → 伤害不够，保命的人留着、把输出换一批。
    加过的坦克 / 治疗不会再拿掉（那一趟第三次又退回了不带坦克的队）。
  · 选人看强度：给每个角色标了强度档（data/characters.json 的 power），别的条件一样时先带强的，强的增益 / 强化排在弱的输出前面。

- 2026-11-19（真机第六趟之后）用户又定的：
  · 敌人是一群还是一个要真的管用：每个角色擅长打一群还是打一个，改成按技能说明标（data/characters.json 的 hits，320 个里 284 个有）。
  · 极难里机制很强的关（好朋友X、美空、几组装置……对策表里 mech = true 的）第一次打就按机制来：攻略点名的效果先带齐。
  · 其他的关先定队伍路线——看名单里哪种队凑得最好（暗属性法队、火属性物理队……，同属性有加成、物理和魔法不混），
    对策表里写了敌人吃哪边（side）的照它来——再在这条路线里挑人。
  · 要带奶的时候不一定带职能是“治疗”的：技能里能给全队回血的都算（data/characters.json 的 heals），谁强带谁（比如厄里斯）。
    毒液沙罗曼蛇带奶、不用坦克：它是全队血量一起掉，才一个个倒的。
  · 打输了怎么分“要坦克 / 要奶”补了一条：第一个人倒下以后，后排的人没站到最前面也一直在掉血 → 是全队一起掉血，要奶。

- 2026-11-19 晚（真机第八趟之后）：用户要“以后战斗一次过”，那一趟输的三场逐场看过以后加的——
  · 自损的角色（杏奈：用完连结爆发自己大幅降防、残血自爆；伊莉亚：每个技能都扣自己的血）不站全队最前面：那一趟两场输的都是她站最前面、几秒就倒；
  · 极难、首领战里站最前面的人越肉越好（不是硬带坦克，是同样好的队里挑前面扛得住的）；
  · 这一局里赢过的人优先沿用（那一趟物理队连赢六场，打首领却换了一队没上过场的法队）；
  · 熔岩龙：站位要集中（对策表的 pack）；冰霜魔狼、愤怒巨龙：多目标，要打一群的输出（need_hit）；对策表可以点名角色（picks）；
  · 输过的队不原样再上；输的那一队已经带了奶 / 有人顶着还是倒 → 奶带两个、另一种保命位一起加；
  · 首领战失败页面上还有人活着、但倒了一大半：不算“时间到了伤害不够”，按战斗中是怎么倒的来分；
  · 纯竞技场用的角色不上（data/characters.json 的 pvp：只标攻略站“竞技场评价很高、打怪两项评价都低”的，两边都强的不动）。
  同一晚用户又要“查敌我双方的数值、技能、机制，每场上最优解”——能查到的部分：
  · 对策表每个敌人记了面板数值（stats）和技能各打谁（moves），并写了 hits = 它的技能打我方最前面几个人、是物理还是魔法；
    会挨打的位置上的人按“对这种伤害的耐打程度”（Unit.tough_p / tough_m）加分，自损的不站这些位置，坦克也按这种伤害挑；
  · 对策表写了敌人吃哪边（side）：现在是每一队都按它实际是哪边加减分再比（以前另一边的强角色混进路线时，吃的那一边的队排不上来）；
  · 敌人技能的倍率查不到，所以算不出“哪一队最快”——这里做的仍然是按规则打分，不是模拟战斗。
- 2026-11-19 夜：用户要“学战斗的数值计算，按伤害、回复的公式算，每场确定最优解”，随后又定：
  **“之前定的每场战斗选人规则都推倒，按新的模拟来。”** 倍率找到了（公开的 Expugn/priconne-diff），做了战斗估算
  （battle.py 推演、advisor.py 挑队、data/battle.json 是数据）。现在的分工：
  · 极难和区域 3 首领（估算认得敌人、名单里认得的人够 5 个）：上面这些规矩都不作数了——这个文件排出来的几队只当搜索的起点，
    估算在整个名单里换人推演，上估算最好的一队（flows/walk.py 的 _estimate）。带不带坦克、带不带奶、哪一边、谁站最前面、
    要不要打一群的输出、是不是竞技场角色，都不再由规则定。plan_of() 是给它用的：按挑好的五个人补出谁上谁下。
  · 估算管不了的地方还是这个文件：普通小怪战、敌人没认出来的战斗、名单里认得的人不够、估算关掉（walk.estimate = false）的时候；
    开局三人、招募、印记、遗物、商店也还是这里的规则（估算只管“这一场上哪五个人”）。
- 2026-11-19 傍晚（真机第七趟之后）用户又定的：
  · 名单里没有坦克的时候，可以让够肉的前排顶在最前面当坦克用（那一趟打厄勒克特拉夫人：名单 27 人没有一个坦克，工具三次都上同一队全输出；
    用户换成 纯（夏日）站最前面就打过了）。谁肉看 data/characters.json 的 tough（按资料站的生命值、物防、魔防算的耐打程度，一般坦克 = 1）。
  · 迷宫遗物优先选削弱（弱体）系列，其次加速。
- 2026-11-27（正式版 V1.06，两个玩家的排查包）：
  · 幽灵领主：它的 UB 打“最前面的人和她周围”，范围里站了两个以上就一起倒，只站一个她反而活得下来（手头 9 场输的记录都是这么倒的）。
    用户要“按攻略上一个坦克和四个后排”：对策表给它写了 spread——最前面只留一个人，其余的人都要比她靠后这么多。规则排队和战斗估算都照这个来
    （估算只在站位拉开的队里挑；battle.py 也把这一下补上了）。第一次打就带坦克站最前面（always），名单里没有坦克就让最耐打的前排顶。
  · 攻略点名要范围输出的关（need_hit = aoe：回复装置、破防装置、炸弹装置、美空……）以前只是“加一点分”，被同属性加成和“沿用赢过的人”盖过去，
    排出来的还是一队打单体的。现在：**极难关**里这种关会打一群的输出至少要 AOE_WANT 个（名单里没那么多就有几个带几个）；首领战不动。
    页面上没有名字、画面也认不出是哪一组的极难关，按“要范围输出”排（没见过的那两组——回复装置、炸弹装置——攻略都点名要范围输出）。

出处（细节见开发计划「策略细则」）：
- note ω4.1《黎明界ラビリンスで「スコアを高くするために」考えていること》（日服，目标极难全踩、稳定 5 万分）：
  除最终首领外，每场赢了给的金币随剩余秒数涨，所以要最快打完；普通战带强力范围输出、自己回 TP 的输出、能给全队回 TP 的角色；
  巨型魔像双防是 0、不用坦克；冰霜魔狼多带输出比堆持续伤害快；毒液沙罗曼蛇、厄勒克特拉夫人、暗黑滴水嘴兽前排放坦克。
- note あのあれ《黎明界ラビリンスで高得点を取るために意識していること》：普通战 5～20 秒打完；开局没有专职坦克；
  角色属性优先 火 ≧ 暗 > 光 >>>> 风 ≧ 水。
- GameWith《難易度5攻略まとめ》《攻略と報酬》：首领的有效效果；究极守护者血量 50% 以上物理队、以下法队；各公会开局推荐（面向一般练度）。
- 巴哈姆特讨论串：路上的战斗打得越快拿的金币越多。
- 属性加成（GameWith / rwiki）：同属性上场 2 / 3 / 4 / 5 人，这个属性的角色伤害 +5% / 10% / 25% / 50%；敌人有弱点属性时另有加成。
- 早先那条“开局必须带坦克”（note あまうさ）是面向一般练度的，按用户的方向不再用。

职能用游戏自己的 8 类（角色卡右下角的图标）：坦克 tank、治疗 heal、攻击 attack、破防 break、
强化 support（回 TP、加速）、增益 buff、减益 debuff、干扰 jam。

极难、区域 3 首领、最终首领各有各的对策（data/counters.json，按攻略整理）：认出敌人以后，choose_team 的 tweak
就是表里那一条——need（一定要带的职能）、roles（某种职能加减分）、profiles（先用哪种打法）、
effect（要从「有效效果」页签里优先带几个，只有攻略点名要持续伤害 / 降攻这类特定效果时才用）、
sides（首领战每一队是物理队还是法队）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Iterable, Sequence

ROLES = ("tank", "heal", "attack", "break", "support", "buff", "debuff", "jam")
GUARD = ("tank", "heal")                               # 保命的两种职能：不需要就不带
ATTRS = ("fire", "water", "wind", "light", "dark")
DAMAGE = ("attack", "break")

# 每种打法里，同一职能的第 1、2、3… 个人各值多少分（越往后越不值）。
#   fast   普通战：输出、破防、回 TP 的强化型、增益；坦克和治疗几乎不值分（名单里没别人了才上）
#   burst  极难 / 首领第一次打：全输出。对策表里点名要的职能（need）另外加分，所以是“对策位 + 其余全输出”
#   steady 打输以后重打：坦克 + 治疗 + 输出 + 破防 + 强化（或增益）
#   sturdy 再输：更稳——两个治疗、坦克更重
PROFILES: dict[str, dict[str, list[float]]] = {
    "fast": {"attack": [30, 26, 22, 16, 10], "break": [24, 16, 9, 4, 2], "support": [26, 16, 6, 2, 1], "buff": [18, 8, 3, 1, 1],
             "debuff": [8, 3, 1, 1, 1], "jam": [6, 2, 1, 1, 1], "tank": [3, 0, 0, 0, 0], "heal": [2, 0, 0, 0, 0], "?": [5, 4, 3, 2, 1]},
    "steady": {"tank": [26, 3, 0, 0, 0], "heal": [22, 6, 1, 0, 0], "attack": [28, 16, 10, 6, 3], "break": [24, 10, 4, 2, 1],
               "support": [20, 6, 2, 1, 1], "buff": [16, 6, 2, 1, 1], "debuff": [12, 5, 2, 1, 1], "jam": [8, 3, 1, 1, 1], "?": [6, 5, 4, 3, 2]},
    "sturdy": {"tank": [30, 8, 0, 0, 0], "heal": [26, 14, 2, 0, 0], "attack": [24, 12, 6, 3, 1], "break": [20, 8, 3, 1, 1],
               "support": [12, 4, 1, 1, 1], "buff": [12, 4, 1, 1, 1], "debuff": [12, 5, 2, 1, 1], "jam": [8, 3, 1, 1, 1], "?": [5, 4, 3, 2, 1]},
    "burst": {"attack": [30, 26, 22, 16, 10], "break": [26, 18, 9, 4, 2], "support": [24, 12, 4, 2, 1], "buff": [20, 10, 3, 1, 1],
              "debuff": [10, 4, 1, 1, 1], "jam": [5, 2, 1, 1, 1], "tank": [3, 0, 0, 0, 0], "heal": [3, 0, 0, 0, 0], "?": [5, 4, 3, 2, 1]},
}
# 每种战斗第 1、2、3 次打各用哪种打法：先全输出，输了才换稳妥的
ATTEMPTS = {"normal": ["fast", "steady", "sturdy"], "extreme": ["burst", "steady", "sturdy"], "boss": ["burst", "steady", "sturdy"]}
# 物理队和法队分开：一队算物理队还是法队，看哪边混进来的人少；另一边的人带进来，这些职能各扣多少分——
# 差不多把这个人本身的分扣光，也不再算“攻略推荐”的加分，所以只有名单里实在没人了才会混着带。
#（输出打不到一块儿；增益、破防、减益大多只对一种伤害有用；回 TP / 加速的强化型两边都能用，扣得少；坦克、治疗、干扰不看）
OFF_SIDE = {"attack": 28.0, "break": 24.0, "buff": 18.0, "debuff": 10.0, "support": 6.0}
SIDES = ("phys", "magic")
SIDE_CN = {"phys": "物理队", "magic": "法队"}
# 敌人是一群还是一个（2026-11-18 用户定的：多目标上打一群的角色，单体上打单体的）。只看输出位（攻击、破防）；没有资料的角色不加不减
#   multi：打一群的输出每个加 AOE_FIT，只会打单体的扣 AOE_MISS；single：打单体的加 ONE_FIT，只会打一群的扣 ONE_MISS（范围技能打一个也打得到，扣得少）
AOE_FIT, AOE_MISS, ONE_FIT, ONE_MISS = 10.0, 8.0, 8.0, 4.0
TARGETS_CN = {"multi": "敌人是一群，打一群的输出优先", "single": "敌人是一个，打单体的输出优先"}
STACK = {1: 0.0, 2: 1.5, 3: 3.0, 4: 7.0, 5: 14.0}      # 同属性上场 n 人时，这个属性的每个输出位加多少分（对应 +5/10/25/50% 伤害）
STACK_SCALE = {"fast": 1.0, "burst": 1.0, "steady": 0.6, "sturdy": 0.5}
WEAK_DAMAGE, WEAK_OTHER = 10.0, 3.0                    # 属性正好是敌人弱点：输出位 / 其他位各加多少分
EFFECTIVE = 40.0                                       # 对策要特定效果时：有这种效果的角色每个加多少分（比一个主力输出位还高：攻略点名的对策先带齐）
MECH = 150.0                                           # 机制很强的关（对策表里 mech = true）：有这种效果的角色每个加这么多——别的都靠后，先把机制带齐
MECH_HIT = 25.0                                        # 这种关还点名要“打得到一群 / 打得到后面”的输出（need_hit）：对得上的输出每个加这么多
MECH_HIT_MISS = 10.0                                   # ……对不上的扣这么多（2026-11-19 晚从 25 改小：只会打单体的输出照样打得出伤害，扣太狠会把队里唯一的输出换成辅助）
HEAL_MORE = 30.0                                       # 对策表里写了要两个奶（heals = 2）：第二个有奶的人再加这么多
HEAL_SKILL = 4.0                                       # 要带奶的时候：能给全队回血的技能每多一个加这么多（奶量足的先带）
SIDE_PREF = 60.0                                       # 对策表里写了敌人吃哪边（side）：照它来的队加这么多（名单里凑不出那一边时才用另一边）
# 开局给全队充能的角色（开场就能放 UB）：第一个加多少分。普通战最值钱——比“五个人同属性”的加成还优先
TP_START = {"fast": 30.0, "burst": 16.0, "steady": 8.0, "sturdy": 4.0}
TOP = 8.0                                               # 黎明界攻略点名推荐的角色：每个再加多少分（强度另算，见 POWER）
# 角色强度（data/characters.json 的 power）：数字越大越强，没有上限（2026-11-18 用户定的：方便给以后出的更强的角色分配）。
# 现在的榜是 1～5（没上榜 1、C 2、B 3、A 4、S 5），以后可以直接写 6、7……，也可以写小数。每高 1 加 POWER_STEP 分——
# 差一档大约抵得上“同职能里往后排一位”，所以强的增益 / 强化会排到弱的输出前面，同职能、同属性时强的一定先上。
# 坦克和治疗只有这一场要带的时候才算（不然强的坦克会混进全输出的队）
POWER_STEP = 6.5
POWER_RECRUIT_STEP = 1.0                                # 招募时：强度每高 1，相当于往前排一位


def power_bonus(power: float) -> float:
    return max(0.0, float(power) - 1.0) * POWER_STEP
RETRY_KEEP = 6.0                                        # 伤害报告里打得多的人：下一次加这么多分，留着
RETRY_AVOID = 12.0                                      # 上一次时间到了没打完：那一队的输出每人扣这么多，换一批人试
TAG_CN = {"tp_start": "开局充能", "tp_start_phys": "开局给物理角色充能", "dot": "持续伤害", "patk_down": "降物攻", "matk_down": "降魔攻", "top": "攻略推荐",
          "selfharm": "自损"}
RECRUIT_TAGS = {"tp_start": 2.0, "tp_start_phys": 2.0, "top": 1.5, "dot": 1.0, "patk_down": 1.0, "matk_down": 1.0}   # 招募时：有这些特点的人，相当于往前排几位
NEED = 40.0                                            # 对策表里写着“一定要带”的职能：队里有就加这么多（名单里没有也没办法）
NEED_GUARD = 200.0                                     # 这一场定了要带的坦克 / 治疗：名单里有就一定带上——而且坦克得站在最前面才算，所以挡在坦克前面的人会被换掉
TANK_VOID = 6.0                                        # 坦克没站在最前面（前面还有站位更靠前的人）：挡不了刀，不但不算分还倒扣（白占一个位置）
# 没有坦克时拿肉的前排顶上（2026-11-19 用户定的）：名单里一个坦克都没有、这一场又要坦克时，队里站最前面的那个人耐打程度
# （Unit.tough，一般坦克 = 1）到了 TOUGH_MIN，就算“有人顶在前面”。数是量出来的：坦克大多 0.9～1.1，一般的攻击 / 破防 0.07～0.12，
# 肉一点的前排 0.3～0.5（用户那一局手动打赢母鸡用的 纯（夏日）是 0.34，工具输掉的那一队最前面的 嘉夜 是 0.12）。
TOUGH_MIN = 0.3                                        # 耐打程度至少要有一般坦克的这么多，才敢让她顶在最前面
FRONT_ROW = 300                                        # 站位数比这个小的算前排
STAND_IN_ROW = 600                                     # 能顶的人得站在前排或中排（站位数比这个小）：让后排的人站全队最前面、别人都缩在她后面，那不叫顶
STAND_IN = 100.0                                       # 有这样一个人顶在最前面：加这么多
STAND_IN_TOUGH = 60.0                                  # 再按耐打程度加：× min(耐打程度, 1.5)（最多再加 90，合起来不超过真坦克的 200）
STAND_IN_FAILED = 40.0                                 # 上一次顶在最前面的人没顶住（从前面一个个倒）：这一次最前面的人不比她更肉就扣这么多（有更肉的就换，没有还是她）
# 2026-11-19 晚加的几样（都是为了“第一次就打过”）：
SELF_FRONT = 60.0                                      # 自损的角色（标签 selfharm）在极难、首领战里站全队最前面：扣这么多（一上来就倒，后面的人跟着暴露）。
                                                       # 前面有人挡着就不扣：用户 11-18 手动打赢母鸡的那一队里就有花音（连结爆发扣自己的血），站在坦克后面没问题
FRONT_SOFT = 30.0                                      # 极难、首领战：站最前面的人不是坦克时，按她的耐打程度加分 × min(耐打程度, 1)——同样好的队里挑前面扛得住的
PACK_FREE, PACK_STEP = 150, 12.0                       # 对策表写了 pack（站位要集中，比如熔岩龙）：其他人比最前面的人靠后超过 PACK_FREE 的部分，每 100 扣 PACK_STEP（每人各算）
PROVEN, PROVEN_MAX = 4.0, 3                            # 这一局里赢过的人：每赢一场加 PROVEN，最多算 PROVEN_MAX 场（赢过的阵容优先沿用，换路线要有明显好处才换）
PVP_OUT = 45.0                                         # 纯竞技场用的角色（data/characters.json 的 pvp）：不是坦克时扣这么多——名单里实在没人了才会上
TOUGH_ALL = 20.0                                       # 对策表写了 tough_all（会随机点杀脆皮的关：攻击装置、炸弹装置）：每个人按耐打程度加分 × min(耐打程度, 1)
HIT_ROW = 12.0                                         # 对策表写了 hits（按游戏里的敌人说明：它的攻击打我方最前面几个人、是物理还是魔法）：会挨打的位置上（最前面那个另算）每个人按“对这种伤害的耐打程度”加分 × min(耐打, 1)
HIT_SELF = 20.0                                        # 同上：会挨打的位置上站着“自损”的人（放技能会掉自己的防御 / 血）扣这么多——最前面那个已经按 SELF_FRONT 扣了，不重复
TANK_FIT = 20.0                                        # 同上：站最前面的坦克按“对这种伤害的耐打程度”和一般坦克（1）的差加减分，上下最多各 0.5——物理首领带物防高的坦克，魔法首领带魔防高的
HEAL_BACK = 15.0                                       # 对策表写了 heal_back（毒液沙罗曼蛇：前 3 个位置会被降攻击，而奶量看奶自己的攻击力）：有奶的人站最后两个位置加这么多，站前三个扣这么多
NO_DEALER = 60.0                                       # 一队里一个输出（攻击 / 破防）都没有：扣这么多（全是辅助打不死人；点名要“打一群”时会把只会打单体的输出扣掉，别扣到一个不剩）
SPREAD_NEAR = 200.0                                    # 对策表写了 spread（敌人的大招打“最前面的人和她周围”：幽灵领主）：除了最前面那个人，每多一个站在这个范围里的扣这么多
                                                       # ——比“攻略点名的效果”（MECH 150）还大：带降魔攻的人站在范围里一样会一起倒，先把站位拉开，再在这样的队里挑人
AOE_WANT = 3                                           # 极难关里攻略点名要范围输出（need_hit = aoe）的：队里会打一群的输出至少要这么多个（名单里没那么多就有几个带几个）
REPEAT_AVOID = 25.0                                    # 排出来的队和输过的某一队一模一样：把这一队里不是保命位的人各扣这么多再排一次
KEEP = 0.6                                             # 已经在队里的人：分数一样时不换，少点几下
MARK_ORDER = ["dark", "fire", "light", "water", "wind"]
ROLE_CN_S = {"tank": "坦克", "heal": "治疗", "attack": "攻击", "break": "破防", "support": "强化", "buff": "增益", "debuff": "减益", "jam": "干扰"}
# 招募时先补哪种职能：按这个顺序往下数，名单里已经有的划掉，第一个还缺的就是最想要的
# 输出优先；坦克和治疗不主动要（2026-11-18 用户定的：不需要就不选），三个里没有别的可拿时才拿
RECRUIT_ORDER = ["attack", "attack", "break", "support", "attack", "buff", "debuff", "attack", "break", "support",
                 "buff", "attack", "debuff", "jam", "break", "attack", "support", "buff", "attack", "debuff", "jam", "break"]
RECRUIT_REST = ["attack", "break", "support", "buff", "debuff", "jam", "heal", "tank"]      # 上面那一串都有了以后，按这个顺序
START_AVOID = {"roles": {"tank": [-20.0] * 5, "heal": [-20.0] * 5}}                          # 开局三人：坦克和治疗排到最后
SIDE_FULL = 4                                          # 一边的输出位（攻击 + 破防）凑到这么多个，招募就转去凑另一边
# 遗物三选一（高分向攻略 ω4.1 / あのあれ / 台服高分打法）：分数只看遗物个数、不看星数，所以路上拿星多的（升级快，也让商店多出便宜的 ★1）；
# 2026-11-19 用户定的：削弱（弱体）系列最厉害，优先选；其次加速。三个里有削弱就拿削弱（有几个拿星多的），没有削弱有加速就拿加速，
# 都没有再按老办法在剩下的里挑（星多的升得快，正好跨过 4 / 9 / 15 级的加分；强化 ≥ 暴击 > 守备）。
# （之前照高分向攻略写的是“各系列均衡着升，削弱前期加的火力少、不要一味堆”——以用户实际打出来的感受为准。）
SERIES_FIRST = ("weaken", "speed")
SERIES_WEIGHT = {"weaken": 1.3, "speed": 1.15, "power": 1.0, "crit": 0.95, "guard": 0.8, None: 0.4}
SERIES_CN_S = {"power": "强化", "speed": "加速", "crit": "暴击", "weaken": "削弱", "guard": "守备"}
SERIES_STEPS = (4, 9, 15)
STEP_BONUS = {4: 2.0, 9: 1.2, 15: 1.2}                 # 这一下正好让系列跨过 4 / 9 / 15 级：加多少分（4 级最要紧）


@dataclass
class Unit:
    """名单里的一张角色卡。key 由调用方定（比如 (页签, 第几张)），这里只原样带回去。"""
    key: Any
    role: str | None
    attr: str | None
    selected: bool = False
    effective: bool = False
    order: int = 0
    name: str | None = None                             # 认出来是哪个角色（头像库里有才有）
    tags: frozenset = frozenset()                       # 这个角色的特点（data/characters.json）
    atk: str | None = None                              # "phys" 物理 / "magic" 魔法（认出名字才有）
    base: str | None = None                             # 本名（去掉“（版本）”）：同一个角色的不同版本不能同时上场
    hit: str | None = None                              # "aoe" 擅长打一群 / "single" 擅长打一个 / "both"；没有资料是 None
    pos: int | None = None                              # 站位（数越小越靠前，一队里最小的站最前面）；不认识名字是 None
    func: str | None = None                             # 实际按哪种职能用（游戏标的职能不合用时才有，比如标着治疗的强力增益）
    aid: str | None = None                              # 增益 / 支援是给物理队（"phys"）、法队（"magic"）还是两边（"both"）；不知道是 None
    power: float = 1                                    # 强度（data/characters.json 的 power，数字越大越强、没有上限）；不认识名字是 1
    heal: float = 0.0                                   # 会不会给队友回血（data/characters.json 的 heals）：≥1 = 有几个技能能给全队回，0.5 = 只能回一个人，0 = 不会
    pvp: bool = False                                   # 纯竞技场用的角色（data/characters.json 的 pvp）：不是坦克时基本不上
    tough: float = 0.0                                  # 耐打程度（data/characters.json 的 tough）：按生命值、物防、魔防算，一般坦克 = 1；不认识名字是 0
    tough_p: float | None = None                        # 只算挨物理伤害时的耐打程度（data/characters.json 的 tough_phys，一般坦克 = 1）；没有资料是 None，用 tough 代替
    tough_m: float | None = None                        # 只算挨魔法伤害时的（tough_magic）

    unlisted: bool = False

    @property
    def kind(self) -> str | None:
        """编队时算哪种职能：有改写用改写的，没有就是游戏标的。"""
        return self.func or self.role

    @property
    def helps(self) -> str | None:
        """这个人算物理这边还是魔法这边：输出看她自己；增益、强化、减益看她帮的是哪边（"both" = 两边都行）。"""
        if self.kind in DAMAGE or self.aid is None:
            return self.atk
        return self.aid


def tough_vs(u: Unit, kind: str | None = None) -> float:
    """这个人对某一种伤害有多耐打：kind = "phys" / "magic"；别的（两种都有、不知道）或者没有分开的资料时用总的 tough。"""
    v = u.tough_p if kind == "phys" else u.tough_m if kind == "magic" else None
    return float(u.tough if v is None else v)


def can_heal(u: Unit) -> bool:
    """这个人算不算“有奶”：职能是治疗的，或者技能里能给全队回血的（2026-11-19 用户定的：不一定带纯奶）。"""
    return u.kind == "heal" or u.heal >= 1


@dataclass
class TeamPlan:
    team: list[Unit]
    score: float
    profile: str
    side: str | None = None                             # 这一队是物理队（"phys"）还是法队（"magic"）；分不出来是 None
    concept: str = ""                                   # 队伍路线，写日志用（“暗属性·法队”“混合属性·物理队”）
    add: list[Unit] = field(default_factory=list)       # 要点上场的
    drop: list[Unit] = field(default_factory=list)      # 要点下场的
    why: str = ""


def off_side(team: Sequence[Unit]) -> dict[str, float]:
    """把这一队当物理队 / 当法队时，各要扣多少分（另一边混进来的人越多扣得越多）。"""
    pen = {sd: 0.0 for sd in SIDES}
    for u in team:
        if u.helps in SIDES and u.kind in OFF_SIDE:
            pen[SIDES[1 - SIDES.index(u.helps)]] += OFF_SIDE[u.kind] + (TOP if "top" in u.tags else 0.0) + power_bonus(u.power)
    return pen


def team_side(team: Sequence[Unit]) -> str | None:
    """这一队算物理队还是法队：混进来的人少的那边；一个带类型的人都没有，或者两边一样，返回 None。"""
    pen = off_side(team)
    if pen["phys"] == pen["magic"]:
        return None
    return min(SIDES, key=lambda sd: pen[sd])


def side_bonus(team: Sequence[Unit], prefer: str | None) -> float:
    if prefer not in SIDES:
        return 0.0
    actual = team_side(team)
    if actual is None:
        return 0.0
    return SIDE_PREF if actual == prefer else -SIDE_PREF


def has_dup(team: Sequence[Unit]) -> bool:
    """队里有没有同一个角色的两个版本（游戏不让同时上场）。"""
    seen: set[str] = set()
    for u in team:
        if u.base:
            if u.base in seen:
                return True
            seen.add(u.base)
    return False


def fit_targets(u: Unit, targets: str | None) -> float:
    """这个人对“敌人是一群 / 是一个”合不合适，加多少分（只看输出位；没有资料的不加不减）。"""
    if targets not in TARGETS_CN or u.kind not in DAMAGE or not u.hit:
        return 0.0
    if targets == "multi":
        return AOE_FIT if u.hit in ("aoe", "both") else -AOE_MISS
    return ONE_FIT if u.hit in ("single", "both") else -ONE_MISS


def crowd(team: Sequence[Unit], gap: float) -> int | None:
    """除了站最前面的那个人，还有几个人站在离她 gap 以内（敌人打“最前面的人和她周围”的技能会把她们一起带上）。
    有人的站位不知道就说不准，返回 None。"""
    if not team or gap <= 0 or any(u.pos is None for u in team):
        return None
    front = min(team, key=lambda z: z.pos)
    return sum(1 for u in team if u is not front and u.pos - front.pos < gap)


def roster_facts(units: Sequence[Unit], tweak: dict[str, Any] | None = None) -> dict[str, Any]:
    """名单里“做得到什么”（核对攻略要求时用：名单里根本没有那种人，就不算差）。一份名单算一次，排队时每一队都拿它对。"""
    want = frozenset((tweak or {}).get("want") or [])
    return {"tank": any(u.kind == "tank" for u in units),
            "sturdy": any(u.tough >= TOUGH_MIN and u.pos is not None and u.pos < STAND_IN_ROW for u in units),
            "heal": any(can_heal(u) for u in units),
            "aoe": aoe_dealers(units),
            "side": {sd: sum(1 for u in units if u.kind in DAMAGE and u.atk == sd) for sd in SIDES},
            "want": len({u.base or u.name or id(u) for u in units if u.effective or (want & u.tags)}) if want else 0,
            "placed": sum(1 for u in units if u.pos is not None)}


def weak_front(team: Sequence[Unit], units: Sequence[Unit] | dict[str, Any]) -> bool:
    """站位拉开的打法里，独自站最前面的那个人要撑到敌人放大招：名单里有坦克就该是坦克；没有坦克、但有够肉的前排 / 中排（能顶的人），就该是够肉的。
    返回 True = 这一队最前面的人不合这个要求（名单里明明有更合适的）。名单里既没有坦克也没有够肉的人、或者站位说不准，返回 False（没得挑）。
    units 可以是名单，也可以是 roster_facts 算好的那份。"""
    if not team or any(u.pos is None for u in team):
        return False
    facts = units if isinstance(units, dict) else roster_facts(units)
    front = min(team, key=lambda z: z.pos)
    if facts["tank"]:
        return front.kind != "tank"
    if facts["sturdy"]:
        return front.tough < TOUGH_MIN
    return False


def aoe_dealers(units: Iterable[Unit]) -> int:
    """名单里会打一群的输出（攻击 / 破防，打一群或者两样都行）有几个；同一个角色的几个版本只算一个。"""
    return len({u.base or u.name or id(u) for u in units if u.kind in DAMAGE and u.hit in ("aoe", "both")})


PACK_FAR = 450                                         # 对策表写了 pack（站位要集中：熔岩龙）：比最前面的人靠后超过这么多的人，算“没挤在一起”。
                                                       # 熔岩龙的范围技能是“最前面的人和她周围 400”，按真机上幽灵领主量出来的余量再加 50；
                                                       # 真机记录：五个人都在 450 以内的三场都赢了，有两个人在 450 以外的那一场输了
SIDE_MIN = 2                                           # 对策表写了敌人吃哪边（side）：名单里那一边的输出至少有这么多个，才硬要求用那一边
WANT_HARD = 2                                          # 攻略点名的效果（持续伤害……）：硬要求最多带这么多个（再多的只是加分——同一种持续伤害不叠，工具分不出是哪一种）
GUIDE_GAP = 200.0                                      # 极难关按攻略来（tweak 里 strict）：和攻略点名的要求每差一个扣这么多——和“要带的坦克 / 奶”（NEED_GUARD）一个量级


def guide_gaps(team: Sequence[Unit], units: Sequence[Unit] | dict[str, Any], tweak: dict[str, Any] | None) -> list[tuple[str, int]]:
    """这一队和攻略对这个敌人点名的要求差在哪：[(差的是什么, 差几个)]，空的 = 都合。只数“名单里明明做得到”的——
    名单里根本没有那种人，不算差（units 可以是名单，也可以是 roster_facts 算好的那份）。
    2026-11-27 用户定的：极难关按攻略来；估算下来秒得掉（敌人放大招之前就打完）才不管机制。
    看这几样（对策表里写了才看）：
      spread 站位拉开（除了最前面那个人，范围里还站着几个）、独自站最前面的人是不是坦克 / 够肉的人；
      side 敌人吃哪边（名单里那一边凑得出输出才要求）；need_hit = aoe 会打一群的输出够不够数；
      want + effect 攻略点名的效果（持续伤害……）带了几个；always 第一次打就要带的坦克 / 奶；pack 站位集中。"""
    tw = tweak or {}
    out: list[tuple[str, int]] = []
    if not team:
        return out
    facts = units if isinstance(units, dict) else roster_facts(units, tw)
    front = min(team, key=lambda z: z.pos) if all(u.pos is not None for u in team) else None
    gap = float(tw.get("spread") or 0.0)
    if gap > 0:
        n = crowd(team, gap) or 0
        if n:
            out.append((f"站位没拉开：除了最前面的人，还有 {n} 个人站在离她 {gap:g} 以内", n))
        if weak_front(team, facts):
            out.append(("独自站最前面的人不是坦克" if facts["tank"] else "独自站最前面的人不够肉", 1))
    side = tw.get("side")
    if side in SIDES and facts["side"].get(side, 0) >= SIDE_MIN and team_side(team) != side:
        out.append((f"攻略说这个敌人吃{SIDE_CN[side]}，这一队不是", 1))
    if tw.get("need_hit") == "aoe":
        short = min(AOE_WANT, facts["aoe"]) - sum(1 for u in team if u.kind in DAMAGE and u.hit in ("aoe", "both"))
        if short > 0:
            out.append((f"会打一群的输出少 {short} 个", short))
    want = frozenset(tw.get("want") or [])
    eff = min(WANT_HARD, int(tw.get("effect", 0) or 0))
    if want and eff > 0 and gap <= 0:                # 要站位拉开的敌人：点名的效果带不带看站不站得开，不硬要求
        short = min(eff, facts["want"]) - sum(1 for u in team if u.effective or (want & u.tags))
        if short > 0:
            out.append((f"攻略点名的效果（{'、'.join(TAG_CN.get(t, t) for t in sorted(want))}）少带 {short} 个", short))
    always = [r for r in (tw.get("always") or []) if r in GUARD]
    if "tank" in always and gap <= 0 and facts["tank"] and tank_in_front(team) is not True:
        out.append(("没带站最前面的坦克", 1))
    if "heal" in always and facts["heal"] and not any(can_heal(u) for u in team):
        out.append(("没带有奶的人", 1))
    if tw.get("pack") and front is not None and facts["placed"] >= 5:
        far = sum(1 for u in team if u is not front and u.pos - front.pos > PACK_FAR)
        if far:
            out.append((f"站位不集中：有 {far} 个人比最前面的人靠后 {PACK_FAR} 以上（它的范围技能打不到她们，前面的人就要多挨）", far))
    return out


def tank_in_front(team: Sequence[Unit]) -> bool | None:
    """队里的坦克是不是站在最前面（站位数比其他人都小）。坦克不在最前面就挡不了刀，带了也没意义。
    队里没有坦克、或者坦克的站位不知道，返回 None（不判断）；和别人站位一样、分不出谁在前，算 False。"""
    tanks = [u.pos for u in team if u.kind == "tank" and u.pos is not None]
    if not tanks:
        return None
    front = min(tanks)
    return all(front < u.pos for u in team if u.kind != "tank" and u.pos is not None)


def stand_in_tank(team: Sequence[Unit]) -> Unit | None:
    """队里没有坦克时，谁在顶坦克的位置：站最前面（站位数比别人都小）、是前排或中排的人、而且够肉（tough ≥ TOUGH_MIN）的那个人。
    队里有坦克、有人的站位不知道（说不准谁在最前）、最前面的人不够肉或者是后排的，都返回 None。"""
    if not team or any(u.kind == "tank" for u in team) or any(u.pos is None for u in team):
        return None
    front = min(team, key=lambda z: z.pos)             # 敌人先打离得最近的人：谁站位数最小谁挨打
    if sum(1 for u in team if u.pos == front.pos) > 1 or front.tough < TOUGH_MIN or front.pos >= STAND_IN_ROW:
        return None
    return front


def team_score(team: Sequence[Unit], profile: str, weak: str | None = None, tweak: dict[str, Any] | None = None,
               side: str | None = None, targets: str | None = None, avoid: dict[str, float] | None = None) -> float:
    """side = 指定这一队必须是物理队 / 法队（不指定就取扣分少的那边）；targets = 敌人是一群（"multi"）还是一个（"single"）；
    avoid = {名字: 扣多少分}（上一次没打完的那一队的输出，换一批人试）。"""
    table = PROFILES[profile]
    extra: dict[str, list[float]] = (tweak or {}).get("roles") or {}
    eff_max = int((tweak or {}).get("effect", 0) or 0)
    want = frozenset((tweak or {}).get("want") or [])
    need = list((tweak or {}).get("need") or [])
    mech = bool((tweak or {}).get("mech"))             # 机制很强的关：点名的效果先带齐
    need_hit = (tweak or {}).get("need_hit")           # 攻略点名要“打得到一群 / 打得到后面”的输出
    heal_need = "heal" in need
    heal_min = max(1, int((tweak or {}).get("heal_min", 1) or 1))      # 奶至少要几个才算“带了奶”（输的那一队已经有一个奶时，下一次要两个）
    picks: dict[str, float] = (tweak or {}).get("picks") or {}         # 对策表点名的角色：{名字: 加多少分}
    proven: dict[str, int] = (tweak or {}).get("proven") or {}         # 这一局里谁赢过几场
    hard = profile != "fast"                                           # 极难、首领战（和普通战打输以后的重打）
    hits: dict[str, Any] = (tweak or {}).get("hits") or {}             # 敌人的攻击打我方最前面几个人（n）、是物理还是魔法（type）——按游戏里的敌人说明写的
    hit_kind = hits.get("type") if hits.get("type") in SIDES else None
    pen = off_side(team)
    sd = side if side in SIDES else (None if pen["phys"] == pen["magic"] else min(SIDES, key=lambda k: pen[k]))
    tank_void = tank_in_front(team) is False         # 坦克前面还站着别人：这个坦克不算数
    tp_seen = False
    seen: dict[str, int] = {}
    total = -(pen[side] if side in SIDES else min(pen.values()))
    attrs: dict[str, int] = {}
    for u in team:
        if u.attr:
            attrs[u.attr] = attrs.get(u.attr, 0) + 1
    eff = 0
    for u in sorted(team, key=lambda z: z.order):
        r = u.kind if u.kind in table else "?"
        n = seen.get(r, 0)
        seen[r] = n + 1
        if r == "tank" and tank_void:
            total -= TANK_VOID
        else:
            total += table[r][min(n, 4)]
            if r in extra and n < len(extra[r]):
                total += float(extra[r][n])
        dmg = u.kind in DAMAGE
        if dmg and u.attr:
            total += STACK[min(attrs[u.attr], 5)] * STACK_SCALE[profile]
        if weak and u.attr == weak:
            total += WEAK_DAMAGE if dmg else WEAK_OTHER
        total += fit_targets(u, targets)
        # 攻略点名要的效果：认出名字的看角色表，认不出的看「有效效果」页签。点名要的职能（need）另算，这里不重复加
        if (u.effective or (want & u.tags)) and eff < eff_max and u.kind not in need:
            eff += 1
            total += MECH if mech else EFFECTIVE
        if need_hit and dmg and u.hit:
            total += MECH_HIT if u.hit in (need_hit, "both") else -MECH_HIT_MISS
        if heal_need and can_heal(u):
            total += HEAL_SKILL * min(max(u.heal, 1.0), 3.0)
        if "top" in u.tags:
            total += TOP
        if u.kind not in GUARD or u.kind in need:      # 强度：坦克和治疗只有这一场要带时才算
            total += power_bonus(u.power)
        if avoid and u.name and u.kind not in GUARD:
            total -= avoid.get(u.name, 0.0)
        if u.name:
            total += float(picks.get(u.name, 0.0)) + PROVEN * min(int(proven.get(u.name, 0) or 0), PROVEN_MAX)
        if u.pvp and u.kind != "tank":
            total -= PVP_OUT
        if not tp_seen and ("tp_start" in u.tags or ("tp_start_phys" in u.tags and sd != "magic")):     # 只给物理角色充能的：法队里不算
            tp_seen = True
            total += TP_START[profile]
        if u.selected:
            total += KEEP
        total -= 0.01 * u.order
        if u.unlisted:
            total -= 26.0
    healers = sum(1 for u in team if can_heal(u))
    if len(team) >= 3 and not any(u.kind in DAMAGE for u in team):
        total -= NO_DEALER
    front = min(team, key=lambda z: z.pos) if team and all(u.pos is not None for u in team) else None      # 站最前面的人（有人站位不知道就不看）
    if hard and front is not None:
        if "selfharm" in front.tags:
            total -= SELF_FRONT
        if front.kind != "tank":
            total += FRONT_SOFT * min(max(tough_vs(front, hit_kind), 0.0), 1.0)
        elif hit_kind and not tank_void:
            total += TANK_FIT * (min(max(tough_vs(front, hit_kind), 0.5), 1.5) - 1.0)
        n_hit = int(hits.get("n", 0) or 0)
        if n_hit >= 2:                               # 第 2～n 个位置也会挨打：站在那儿的人越耐打越好，自损的别站那儿
            for u in sorted(team, key=lambda z: z.pos)[1:n_hit]:
                total += HIT_ROW * min(max(tough_vs(u, hit_kind), 0.0), 1.0)
                if "selfharm" in u.tags:
                    total -= HIT_SELF
    if (tweak or {}).get("tough_all"):
        total += TOUGH_ALL * sum(min(max(tough_vs(u, hit_kind), 0.0), 1.0) for u in team)
    if (tweak or {}).get("heal_back") and front is not None and len(team) >= 4:
        back = sorted(team, key=lambda z: z.pos)[-2:]
        total += sum((HEAL_BACK if any(u is b for b in back) else -HEAL_BACK) for u in team if can_heal(u))
    facts = (tweak or {}).get("_facts")
    if (tweak or {}).get("strict") and facts:        # 极难关按攻略来：和攻略点名的要求每差一个都重扣（名单里做不到的不算）
        total -= GUIDE_GAP * sum(n for _, n in guide_gaps(team, facts, tweak))
    else:                                            # 不是极难关（首领战 / 普通战）：只留“站位拉开”这一条软的；范围输出的个数不硬凑（首领战照 11-19 那一套）
        gap = float((tweak or {}).get("spread") or 0.0)
        if gap > 0:                                  # 站位拉开：最前面只留一个人，其余的人都要比她靠后 gap 以上
            total -= SPREAD_NEAR * (crowd(team, gap) or 0)
    if (tweak or {}).get("pack") and front is not None:
        total -= PACK_STEP * sum(max(0.0, u.pos - front.pos - PACK_FREE) for u in team if u is not front) / 100.0
    for role in need:
        ok = healers >= heal_min if role == "heal" else (seen.get(role, 0) > 0 and not (role == "tank" and tank_void))
        if ok:
            total += NEED_GUARD if role in GUARD else NEED
        elif role == "tank" and (tweak or {}).get("stand_in", True):       # 名单里没有坦克：够肉的前排顶在最前面也算（给的分比真坦克少）
            front = stand_in_tank(team)
            if front is not None:
                total += STAND_IN + STAND_IN_TOUGH * min(front.tough, 1.5)
                if front.tough <= float((tweak or {}).get("front_lost") or 0.0):
                    total -= STAND_IN_FAILED
    if heal_need and healers >= 2 and int((tweak or {}).get("heals", 1) or 1) >= 2:
        total += HEAL_MORE
    return total


def _shortlist(units: Sequence[Unit], weak: str | None, cap: int = 30, must_tags: frozenset = frozenset(), small: int = 20,
               need: Sequence[str] = ()) -> list[Unit]:
    """名单很长时先筛一遍，免得组合太多：按重要程度一层层往里放，放满 cap 个为止。
    顺序：攻略点名的对策角色 → 这一场要带的保命位（坦克按站位从前往后、有奶的按强度）→ 输出（攻击 4、破防 3）→ 强化、增益、减益各 2、干扰 1
    → 没点名时的保命位各留 1 → 现在场上的人 → 还有位置就按强度补。同一层里强的在前。"""
    if len(units) <= small:
        return list(units)
    keep: dict[int, Unit] = {}

    def add(lst: Iterable[Unit]) -> None:
        for u in lst:
            if len(keep) < cap:
                keep.setdefault(id(u), u)

    rank = lambda z: (-z.power, z.attr != weak, not z.hit, not z.selected, z.order)      # noqa: E731
    of = lambda kind: sorted((u for u in units if u.kind == kind), key=rank)             # noqa: E731
    tanks = sorted((u for u in units if u.kind == "tank"), key=lambda z: (z.pos if z.pos is not None else 9999, -z.power, z.order))
    healers = sorted((u for u in units if can_heal(u)), key=lambda z: (-z.power, -z.heal, z.order))
    add(sorted((u for u in units if u.effective or (must_tags & u.tags)), key=rank)[:5])
    if "tank" in need:
        add(tanks[:2])
        if not tanks:                                # 没有坦克：最肉的几个留着（前排里最肉的 2 个 + 前排中排里最肉的 3 个），看谁能顶在最前面
            meat = sorted((u for u in units if u.tough >= TOUGH_MIN and u.pos is not None and u.pos < STAND_IN_ROW), key=lambda z: (-z.tough, z.order))
            add([u for u in meat if u.pos < FRONT_ROW][:2])
            add(meat[:3])
    if "heal" in need:
        add(healers[:3])
    add(of("attack")[:4])
    add(of("break")[:3])
    for kind, n in (("support", 2), ("buff", 2), ("debuff", 2), ("jam", 1)):
        add(of(kind)[:n])
    add(tanks[:1])
    add(healers[:1])
    add(u for u in units if u.selected)
    add(sorted(units, key=rank))
    return sorted(keep.values(), key=lambda z: z.order)


def first_try(tweak: dict[str, Any] | None) -> dict[str, Any] | None:
    """第一次打用的对策：把“要带坦克 / 治疗”去掉（2026-11-18 用户定的：所有的关第一次都先不上坦克治疗，没打过再换）。
    别的要求（破防多带、要持续伤害、物理队还是法队……）照旧。"""
    if not tweak:
        return tweak
    always = [r for r in (tweak.get("always") or []) if r in GUARD]      # 这个敌人第一次打就要带的（用户点名的，比如厄勒克特拉夫人带坦克）
    tw = dict(tweak)
    tw["need"] = [r for r in (tweak.get("need") or []) if r not in GUARD] + always
    tw["roles"] = {r: v for r, v in (tweak.get("roles") or {}).items() if r not in GUARD or r in always or all(float(x) <= 0 for x in v)}
    return tw


FRONT_REST = 0.6        # 第一个人倒下时，其他人平均还剩这么多血以上：算“从前面一个个倒”（要坦克）；不到：算“全队一起崩”（要治疗）
BACK_FULL = 0.9         # 第二个人倒下时，还没轮到站最前面的那些人平均血量不到这么多：后排也一直在掉血，是全队一起掉的（要治疗）
LOSS_CN = {"front": "从最前面开始一个个倒的", "collapse": "全队血量一起崩的", "wiped": "队伍倒了（没看清是怎么倒的）", "timeout": "时间到了、人还活着"}


def loss_cause(samples: Sequence[tuple[float, Sequence[float]]], final: Sequence[float] | None = None) -> str | None:
    """这一场是怎么输的（2026-11-18 用户定的分法）。samples = 战斗中隔一会儿读一次的血量 [(第几秒, [最前面的人, …, 最后面的人])]，
    每个数 0～1；final = 失败页面上的血量（首领战才有）。返回：
      "timeout"   时间到了还有人活着——伤害不够，不是扛不住
      "front"     从最前面开始一个个倒：第一个人倒下的时候，后面的人血还多——要坦克顶在前面
      "collapse"  全队血量一起崩：第一个人倒下的时候，其他人的血也没剩多少（或者几个人几乎同时倒）——要治疗
      "wiped"     倒光了，但战斗中的血量没读到，分不出是哪一种
      None        什么都看不出来"""
    last = list(final) if final else (list(samples[-1][1]) if samples else [])
    if final is None and not samples:
        return None
    alive = sum(1 for v in last if v > 0.02)
    if alive and (final is None or alive * 2 >= len(last)):
        return "timeout"
    # 失败页面上还有人活着，但倒了一大半（2026-11-19 冰霜魔狼：前三个人 12 秒内倒光，剩两个辅助满血站到时间到）：
    # 那不是伤害不够，是前面的人没顶住——接着看战斗中是怎么倒的
    rows = [(t, list(hp)) for t, hp in samples if hp]
    start = next((i for i, (_t, hp) in enumerate(rows) if all(v >= 0.5 for v in hp)), None)      # 从“大家都还好好的”那一下开始看（开场血条还没亮起来的不算）
    rows = rows[start:] if start is not None else []

    def gone(i: int) -> list[int]:                      # 这一下谁倒了：下一下还是空的才算（免得把特效挡住血条的那一下当成倒了）
        return [k for k, v in enumerate(rows[i][1]) if v <= 0.02 and (i + 1 >= len(rows) or rows[i + 1][1][k] <= 0.02)]

    first = next((i for i in range(1, len(rows)) if gone(i)), None)
    if first is None or len(rows) < 3:
        return "timeout" if alive else "wiped"         # 战斗中没读清：页面上有人活着就还按时间到算
    hp = rows[first][1]
    before = rows[first - 1][1]
    dead = gone(first)
    rest = [max(v, b) for i, (v, b) in enumerate(zip(hp, before)) if i not in dead]      # 取倒下前后两次里高的那次：免得把特效挡住的那一下当成掉血
    if not rest:
        return "collapse"                               # 同一下全倒了
    mean = sum(rest) / len(rest)
    if len(dead) >= 3 or mean < FRONT_REST:
        return "collapse"
    # 第二个人倒下的时候再看一眼：还没轮到站最前面的那些人如果也掉了不少血，说明伤害是全队一起吃的（中毒、全体攻击），
    # 只是前排先撑不住——这种要的是奶，不是坦克（2026-11-19 真机上的毒液沙罗曼蛇就是这样：前排 5 秒倒，后排没挨过正面的打也一直在掉）
    gone_all = set(dead)
    second = next((i for i in range(first + 1, len(rows)) if set(gone(i)) - gone_all), None)
    if second is not None:
        down = gone_all | set(gone(second))
        alive = [k for k in range(len(rows[second][1])) if k not in down]
        back = alive[1:]                               # 活着的人里最前面那个接下来要挨打，不算；看他后面的
        if back:
            prev = rows[second - 1][1]
            if sum(max(rows[second][1][k], prev[k]) for k in back) / len(back) < BACK_FULL:
                return "collapse"
    if 0 in dead:
        return "front"
    return "wiped"


def plan_retry(kind: str, tries: Sequence[dict[str, Any]], tweak: dict[str, Any] | None) -> tuple[str, dict[str, Any], dict[str, float], str]:
    """这一场接下来这一次怎么编队。tries = 这一场前面每次是怎么输的 [{"how": loss_cause 的结果, "team": [名字…], "front_tough": 那一次顶在最前面的替身坦克有多肉（没有就不写）}]（第一次打是空的）。
    返回（打法, 这一次用的对策, {名字: 扣分}, 一句说明）。规矩：
    - 第一次全输出，只带对策表里写了 always 的保命职能；
    - 一个个倒 → 加坦克（名单里没有坦克时是“够肉的前排顶在最前面”；已经有人顶了还是从前面倒 → 有更肉的就换更肉的，见 front_tough）；一起崩 → 加治疗；倒了但分不出 → 先加攻略点名的（need 里的），再坦克、再治疗；带了还是那样倒 → 再加另一种，都带了就换最稳的打法；
    - 时间到了 → 不加保命的，上一队的输出各扣一点分，换一批人；
    - 加过的保命职能不再拿掉。"""
    tw = dict(tweak or {})
    order = [p for p in (tw.get("profiles") or []) if p in PROFILES] or ATTEMPTS.get(kind, ATTEMPTS["extreme"])
    named = [r for r in (tw.get("need") or []) if r in GUARD]
    guards = [r for r in (tw.get("always") or []) if r in GUARD]
    avoid: dict[str, float] = {}
    sturdy = False
    notes: list[str] = []
    for t in tries:
        how = t.get("how")
        if how == "timeout":
            if t.get("weak") or t.get("strong"):                               # 那一次看了伤害报告：打得少的输出换掉，打得多的留着
                avoid = {n: RETRY_AVOID for n in (t.get("weak") or []) if n}
                avoid.update({n: -RETRY_KEEP for n in (t.get("strong") or []) if n})
                notes.append("上一次时间到了没打完，照伤害报告换人：" + ("换掉 " + "、".join(t.get("weak") or []) if t.get("weak") else "没有明显打得少的")
                             + ("，留着 " + "、".join(t["strong"]) if t.get("strong") else ""))
                continue
            avoid = {n: RETRY_AVOID for n in (t.get("team") or []) if n}       # 只看最近没打完的那一队（不累加：不然越换越弱）
            notes.append("上一次时间到了没打完：保命的人不动，输出换一批")
            continue
        want = "tank" if how == "front" else "heal" if how == "collapse" else next((r for r in named + ["tank", "heal"] if r not in guards), None)
        if how == "front" and isinstance(t.get("front_tough"), (int, float)):      # 那一次是肉的前排在顶、没顶住：记下她有多肉
            tw["front_lost"] = max(float(tw.get("front_lost") or 0.0), float(t["front_tough"]))
            if not any("没顶住" in x for x in notes):
                notes.append("名单里没有坦克，上一次顶在最前面的人没顶住：有更肉的就换更肉的来顶（没有就还是她）")
        had = set(t.get("had") or [])                   # 输的那一队本来就带着哪种保命的人（walk 记的）
        if want and want not in guards and want in had:
            # 那一队其实已经有这种人了（比如队里本来就有个会回血的强化）还是这样倒：只写“要带”排出来还是原来那队——奶带两个，另一种保命位一起加
            guards.append(want)
            other = next((r for r in GUARD if r not in guards), None)
            if other:
                guards.append(other)
            if "heal" in guards:
                tw["heal_min"] = 2
                tw["heals"] = max(2, int(tw.get("heals", 1) or 1))
            notes.append(f"上一次是{LOSS_CN.get(how, '打输了')}，那一队已经带着{'坦克' if want == 'tank' else '有奶的人'}还是这样："
                         + ("奶带两个" if "heal" in guards else "") + (f"，再加{'坦克' if other == 'tank' else '治疗'}" if other else ""))
        elif want and want not in guards:
            guards.append(want)
            notes.append(f"上一次是{LOSS_CN.get(how, '打输了')}：加{'坦克' if want == 'tank' else '治疗'}")
        else:
            other = next((r for r in GUARD if r not in guards), None)
            if other:
                guards.append(other)
                notes.append(f"上一次是{LOSS_CN.get(how, '打输了')}，已经带了还是这样：再加{'坦克' if other == 'tank' else '治疗'}")
            else:
                sturdy = True
                notes.append("坦克和治疗都带了还是倒：换最稳的打法")
    tw["need"] = [r for r in (tw.get("need") or []) if r not in GUARD] + guards
    tw["roles"] = {r: v for r, v in (tw.get("roles") or {}).items() if r not in GUARD or r in guards or all(float(x) <= 0 for x in v)}
    profile = ("sturdy" if "sturdy" in PROFILES else order[-1]) if sturdy else order[0]
    return profile, tw, avoid, "；".join(notes)


CONCEPT_CAP = 16                                       # 每条路线里最多拿这么多“合路线”的人出来排列组合
CONCEPT_FILL = 5                                       # 另外再放进最多这么多个“不合路线”的人垫着（攻略点名的对策角色、最强的几个）：带他们照常扣分，
                                                       # 但路线里的人实在不行（只剩坦克、治疗）时，带一个别的队的强力角色也比硬凑强
ATTR_CN_S = {"fire": "火", "water": "水", "wind": "风", "light": "光", "dark": "暗"}


def _fits(u: Unit, sd: str, at: str | None) -> bool:
    """这个人放不放得进“sd 这一边（物理 / 魔法）、输出都是 at 属性（None = 不限属性）”的队。
    输出看自己是哪边、什么属性；增益、减益看帮的是哪边；回 TP / 加速的强化型、坦克、治疗、干扰哪种队都能带。"""
    if u.kind in DAMAGE:
        return u.atk in (sd, None) and (at is None or u.attr == at)
    if u.kind in ("buff", "debuff"):
        return u.helps in (sd, "both", None)
    return True


def concept_name(team: Sequence[Unit], side: str | None) -> str:
    """队伍路线的叫法：输出里最多的那个属性在队里有 3 个人以上就叫“X 属性”，不然叫“混合属性”；后面跟 物理队 / 法队。"""
    dmg = [u.attr for u in team if u.kind in DAMAGE and u.attr]
    top = max(sorted(set(dmg)), key=dmg.count) if dmg else None
    n = sum(1 for u in team if u.attr == top) if top else 0
    return (f"{ATTR_CN_S[top]}属性" if top and n >= 3 else "混合属性") + (f"·{SIDE_CN[side]}" if side in SIDES else "")


def choose_team(units: Sequence[Unit], kind: str = "normal", weak: str | None = None, attempt: int = 0,
                must: Iterable[Unit] = (), size: int = 5, tweak: dict[str, Any] | None = None, side: str | None = None,
                targets: str | None = None, profile: str | None = None, avoid: dict[str, float] | None = None) -> TeamPlan:
    """从名单里挑 size 个人。kind = normal / extreme / boss；attempt = 这一场第几次打（从 0 数）；must = 一定要带的；
    tweak = 对策表里这个敌人的那一条（没认出敌人就是 None）——其中“要带坦克 / 治疗”从第 2 次打才算；side = 指定物理队 / 法队（不指定就自己看哪边强）；
    targets = 敌人是一群（"multi"）还是一个（"single"）：对上号的输出优先。
    profile / avoid = plan_retry 定好的打法和扣分（给了就照它来，tweak 也已经是它改过的，不再按 attempt 换）。
    同一个角色的不同版本不会一起带。

    做法（2026-11-19 用户定的）：先定队伍路线，再在路线里挑人。路线 = 物理队 / 法队 × 输出是不是同一个属性——
    把名单按每条路线各筛一遍（另一边的输出、帮另一边的增益不进来），每条路线里排出最好的一队，再比哪条路线的队最好；
    对策表里写了敌人吃哪边（side）的，那一边加分（另一边实在凑得好很多才会用）。机制很强的关（mech）点名的效果在哪条路线里都先带齐。"""
    if profile not in PROFILES:
        order = ATTEMPTS.get(kind, ATTEMPTS["extreme"])
        custom = [p for p in ((tweak or {}).get("profiles") or []) if p in PROFILES]
        if custom:
            order = custom
        profile = order[min(attempt, len(order) - 1)]
        if attempt == 0:                             # 第一次打：不管对策表和游戏怎么说，先不上坦克治疗（写了 always 的除外）
            tweak = first_try(tweak)
    must = [u for u in must]
    if (tweak or {}).get("strict") and "_facts" not in tweak:                   # 极难关按攻略来：名单里做得到什么，先算好
        tweak = {**tweak, "_facts": roster_facts(units, tweak)}
    if any(u.kind == "tank" for u in units):          # 名单里有坦克：要坦克就带真坦克，不拿别人顶
        tweak = {**(tweak or {}), "stand_in": False}
    rest = [u for u in units if not any(u is m for m in must)]
    n0 = max(0, min(size, len(rest) + len(must)) - len(must))
    want_tags = frozenset((tweak or {}).get("want") or [])
    prefer = (tweak or {}).get("side") if side not in SIDES else None
    best: tuple[float, float, tuple[Unit, ...], str] | None = None
    for sd in ([side] if side in SIDES else SIDES):
        dealers = [u for u in rest if u.kind in DAMAGE and u.atk in (sd, None)]
        for at in [None] + [a for a in ATTRS if sum(1 for u in dealers if u.attr == a) >= 3]:
            inside = [u for u in rest if _fits(u, sd, at)]
            if at is not None and len(inside) < n0:
                continue
            pool = _shortlist(inside, weak, cap=CONCEPT_CAP, must_tags=want_tags, small=CONCEPT_CAP, need=list((tweak or {}).get("need") or []))
            outside = [u for u in rest if not _fits(u, sd, at)]
            marked = [u for u in outside if u.effective or (want_tags & u.tags)]             # 攻略点名的对策角色：不合路线也放进来
            strong = sorted((u for u in outside if not any(u is m for m in marked)), key=lambda z: (-z.power, z.order))
            fill = (marked + strong)[:max(CONCEPT_FILL, n0 - len(pool))] if at is None else marked[:CONCEPT_FILL]
            pool = sorted(pool + fill, key=lambda z: z.order)
            n, got = n0, None
            while got is None and n >= 0:            # 名单里全是同一个角色的几个版本时凑不满：少带一个再试
                for combo in combinations(pool, n):
                    cand = must + list(combo)
                    if has_dup(cand) and not has_dup(must):
                        continue
                    sc = team_score(cand, profile, weak, tweak, sd if side in SIDES else None, targets, avoid)
                    adj = sc + side_bonus(cand, prefer)
                    if got is None or adj > got[0]:
                        got = (adj, combo, sc)
                n -= 1
            if got is None:
                continue
            if best is None or got[0] > best[0] + 1e-9:
                best = (got[0], got[2], got[1], sd)
    team = must + list(best[2]) if best else must
    team.sort(key=lambda z: z.order)
    plan = TeamPlan(team, best[1] if best else 0.0, profile, side if side in SIDES else team_side(team))
    plan.concept = concept_name(team, plan.side)
    plan.add = [u for u in team if not u.selected]
    plan.drop = [u for u in units if u.selected and not any(u is t for t in team)]
    return plan


def plan_of(units: Sequence[Unit], team: Sequence[Unit], profile: str, weak: str | None = None, tweak: dict[str, Any] | None = None,
            targets: str | None = None) -> TeamPlan:
    """就带这几个人（战斗估算挑出来的）：做成和 choose_team 一样的编队计划（要点谁上场、谁下场）。"""
    team = sorted(team, key=lambda z: z.order)
    plan = TeamPlan(list(team), team_score(team, profile if profile in PROFILES else "burst", weak, tweak, None, targets), profile, team_side(team))
    plan.concept = concept_name(team, plan.side)
    plan.add = [u for u in team if not u.selected]
    plan.drop = [u for u in units if u.selected and not any(u is t for t in team)]
    return plan


def choose_new_team(units: Sequence[Unit], kind: str = "normal", weak: str | None = None, attempt: int = 0,
                    lost: Sequence[Iterable[str]] = (), **kw: Any) -> tuple[TeamPlan, bool]:
    """和 choose_team 一样，但不原样再上输过的队：lost = 这一场前面输掉的每一队的名字。
    排出来的队和其中某一队一模一样时，把这一队里不是保命位的人各扣 REPEAT_AVOID 再排一次；还是一样（名单里换不出别人）就只好原样上。
    返回（队伍, 是不是为了不重复换过人）。"""
    plan = choose_team(units, kind, weak, attempt, **kw)
    seen = [frozenset(x) for x in lost if x]
    names = lambda p: frozenset(u.name for u in p.team if u.name)      # noqa: E731
    if not seen or names(plan) not in seen or any(not u.name for u in plan.team):
        return plan, False
    avoid = dict(kw.get("avoid") or {})
    for u in plan.team:
        if u.kind not in GUARD:
            avoid[u.name] = avoid.get(u.name, 0.0) + REPEAT_AVOID
    again = choose_team(units, kind, weak, attempt, **{**kw, "avoid": avoid})
    if names(again) in seen:
        return plan, False
    return again, True


def roster_side(units: Iterable[Unit]) -> str | None:
    """招募时往哪边凑：先把输出位多的那边凑到 SIDE_FULL 个，够了转去凑另一边，两边都够了就不挑（返回 None）。"""
    n = {sd: 0 for sd in SIDES}
    for u in units:
        if u.kind in DAMAGE and u.atk in SIDES:
            n[u.atk] += 1
    main = max(SIDES, key=lambda sd: n[sd])
    other = SIDES[1 - SIDES.index(main)]
    if n[main] == n[other]:
        return None
    if n[main] < SIDE_FULL:
        return main
    return other if n[other] < SIDE_FULL else None


def roster_counts(units: Iterable[Unit]) -> dict[str, int]:
    out: dict[str, int] = {}
    for u in units:
        if u.kind:
            out[u.kind] = out.get(u.kind, 0) + 1
    return out


def wanted_roles(have: dict[str, int], order: Sequence[str] = RECRUIT_ORDER) -> list[str]:
    """名单里已经有 have 这些职能时，接下来最想要的职能，从最想要到最不想要。"""
    left = dict(have)
    out: list[str] = []
    for r in order:
        if left.get(r, 0) > 0:
            left[r] -= 1
        elif r not in out:
            out.append(r)
    for r in RECRUIT_REST:
        if r not in out:
            out.append(r)
    return out


def choose_recruit(cands: Sequence[tuple[str | None, str | None]], have: dict[str, int],
                   attr_order: Sequence[str] = MARK_ORDER, tags: Sequence[frozenset] | None = None,
                   atks: Sequence[str | None] | None = None, side: str | None = None,
                   powers: Sequence[float] | None = None, wants: dict[str, Any] | None = None,
                   heals: Sequence[float] | None = None, unlisted: Sequence[bool] | None = None,
                   eligible: Sequence[int] | None = None) -> tuple[int, str]:
    """战斗后三选一。cands = [(职能, 属性), …]；tags = 每个人的特点、atks = 物理还是魔法（认出名字才有）；
    heals = 每个人会不会给全队回血（≥1 算有奶：后面的首领要奶时，有奶的强力角色和纯治疗一样算数）；
    side = 现在在凑物理队还是法队（roster_side）；powers = 每个人的强度档；
    wants = 这一局后面两个首领要的东西 {"roles": [还缺的职能], "tags": [还缺的效果]}（开局看过首领才有）。返回（选第几个，为什么）。
    先补缺的职能（输出优先）；后面的首领点名要、名单里还没有的排最前；强的人、有开局充能 / 持续伤害 / 降攻这类特点的人往前排；
    职能一样先看是不是正在凑的那一边，再看强度，再看属性。"""
    want = wanted_roles(have)
    tags = list(tags) if tags is not None else [frozenset()] * len(cands)
    atks = list(atks) if atks is not None else [None] * len(cands)
    powers = list(powers) if powers is not None else [1] * len(cands)
    need_roles = [r for r in ((wants or {}).get("roles") or []) if have.get(r, 0) == 0]
    need_tags = set((wants or {}).get("tags") or [])
    heals = list(heals) if heals is not None else [0.0] * len(cands)

    def has_heal(i: int) -> bool:
        return "heal" in need_roles and heals[i] >= 1

    def for_boss(i: int) -> bool:
        return cands[i][0] in need_roles or has_heal(i) or bool(need_tags & tags[i])

    def boost(i: int) -> float:
        return (min(3.0, sum(RECRUIT_TAGS.get(t, 0.0) for t in tags[i])) + max(0.0, powers[i] - 1.0) * POWER_RECRUIT_STEP
                + (8.0 if for_boss(i) else 0.0))

    def off(i: int) -> int:
        return 1 if (side in SIDES and atks[i] in SIDES and atks[i] != side and cands[i][0] in OFF_SIDE) else 0

    def rank(i: int) -> tuple:
        role, attr = cands[i]
        penalty = 4.0 if unlisted and unlisted[i] else 0.0
        return ((want.index(role) if role in want else 99) - boost(i) + penalty, off(i), -powers[i], attr_order.index(attr) if attr in attr_order else 9, i)

    best = min(range(len(cands)) if eligible is None else eligible, key=rank)
    role, attr = cands[best]
    if role is None and eligible is not None:
        return best, "按首领需要的效果选择"
    if role is None:
        return 0, "三个人的职能都没认出来，选最左边"
    lack = have.get(role, 0)
    why = f"名单里{('还没有' if lack == 0 else f'只有 {lack} 个')}这种职能"
    if for_boss(best):
        why = "后面的首领要用（" + "、".join([ROLE_CN_S.get(role, role)] * (role in need_roles) + ["有奶"] * (has_heal(best) and role != "heal")
                                          + [TAG_CN.get(t, t) for t in sorted(need_tags & tags[best])]) + "），" + why
    if powers[best] >= 3:
        why += f"，强度 {powers[best]:g}"
    if any(t in RECRUIT_TAGS for t in tags[best]):
        why += "，而且有" + "、".join(TAG_CN.get(t, t) for t in sorted(tags[best]) if t in RECRUIT_TAGS)
    if side in SIDES and atks[best] == side and any(off(i) for i in range(len(cands))):
        why += f"，正在凑{SIDE_CN[side]}"
    return best, why


def choose_start(cands: Sequence[tuple[str | None, str | None]], n: int = 3, attr_order: Sequence[str] = MARK_ORDER,
                 names: Sequence[str | None] | None = None, tags: Sequence[frozenset] | None = None,
                 atks: Sequence[str | None] | None = None, bases: Sequence[str | None] | None = None,
                 funcs: Sequence[str | None] | None = None, aids: Sequence[str | None] | None = None,
                 powers: Sequence[float] | None = None) -> list[int]:
    """开局从公会成员里挑 n 个：当成一支只有 n 个人的快攻队来挑——输出、破防、回 TP 的强化型、增益优先，坦克和治疗不到没人可选不拿；
    物理和魔法不混；同一个角色的不同版本不能同时上场，所以不重复拿；别的都一样时看属性（暗 = 火 > 光 > 水 > 风）。
    names / tags / atks / bases / funcs / aids 是每张卡认出来的名字、特点、物理还是魔法、本名、实际按哪种职能用、增益给哪边（认不出就是 None）。
    返回选中的第几张（从 0 数）。"""
    def opt(lst: Sequence | None, i: int, default: Any = None) -> Any:
        return lst[i] if lst is not None and i < len(lst) and lst[i] is not None else default

    if not any(role for role, _a in cands) and not any(funcs or []):           # 职能都没认出来：按顺序拿
        return list(range(min(n, len(cands))))
    by_attr = sorted(range(len(cands)), key=lambda i: (attr_order.index(cands[i][1]) if cands[i][1] in attr_order else 9, i))
    units = [Unit(i, cands[i][0], cands[i][1], order=by_attr.index(i), name=opt(names, i), tags=opt(tags, i, frozenset()),
                  atk=opt(atks, i), base=opt(bases, i), func=opt(funcs, i), aid=opt(aids, i), power=float(opt(powers, i, 1))) for i in range(len(cands))]
    picked = sorted(u.key for u in choose_team(units, "normal", size=n, tweak=START_AVOID, targets="multi").team)
    for i in range(len(cands)):                       # 凑不满（比如名单里全是同一个角色）：按顺序补
        if len(picked) >= min(n, len(cands)):
            break
        if i not in picked:
            picked.append(i)
    return picked


MARK_TEAM = 0.12        # 选印记属性：这一局里已经有这个属性的输出 / 辅助，每有一个加这么多（凑同属性的队），最多算 6 个
MARK_GUARD = 0.5        # 账号里那个属性的坦克、纯治疗：平时用不上，算平均强度时只算一半分量


def attr_values(owned: Iterable[tuple[str | None, float, str | None]], in_run: Iterable[tuple[str | None, str | None]] = (),
                unlisted: Iterable[str] = ()) -> dict[str, dict[str, float]]:
    """连结印记选哪个属性，按账号主人有哪些角色来算（2026-11-19 用户定的）。
    owned = 账号里还没进这一局的角色 [(属性, 强度, 职能)]——随机印记就是从这里面抽；in_run = 这一局已经有的角色 [(属性, 职能)]。
    按剩余图鉴人数估算抽取概率：名单内取加权平均强度，名单外按 1 分；再加本局同属性成队奖励。
    返回 {属性: {"value": 分, "mean": 平均强度, "left": 还能抽到几个, "have": 这一局已经有几个}}；一个都抽不到的属性不在里面。"""
    pools: dict[str, list[tuple[float, float]]] = {}
    for attr, power, kind in owned:
        if attr in ATTRS:
            pools.setdefault(attr, []).append((float(power), MARK_GUARD if kind in GUARD else 1.0))
    have: dict[str, int] = {}
    for attr, kind in in_run:
        if attr in ATTRS and kind not in GUARD:
            have[attr] = have.get(attr, 0) + 1
    out: dict[str, dict[str, float]] = {}
    missing: dict[str, int] = {}
    for attr in unlisted:
        if attr in ATTRS:
            missing[attr] = missing.get(attr, 0) + 1
    for attr in pools.keys() | missing.keys():
        lst = pools.get(attr, [])
        mean = sum(p * w for p, w in lst) / sum(w for _p, w in lst) if lst else 0.0
        outside = missing.get(attr, 0)
        expected = (len(lst) * mean + outside * 1.0) / (len(lst) + outside)
        n = have.get(attr, 0)
        out[attr] = {"value": round(expected + MARK_TEAM * min(n, 6), 3), "mean": round(mean, 2), "left": len(lst), "unlisted": outside, "have": n}
    return out


def choose_mark(attrs: Sequence[str | None], order: Sequence[str] = MARK_ORDER,
                values: dict[str, dict[str, float]] | None = None) -> tuple[int, str]:
    """连结印记三选一。values = attr_values() 算出来的各属性的分（认得出账号里有哪些角色时才有）：挑分最高的；
    没有就按属性的固定顺序（攻略里的 暗 = 火 > 光 > 水 > 风）。分一样时也按这个顺序。"""
    rank = lambda i: (order.index(attrs[i]) if attrs[i] in order else 9, i)       # noqa: E731
    if values and any(a in values for a in attrs):
        best = max(range(len(attrs)), key=lambda i: ((values.get(attrs[i] or "") or {}).get("value", -1.0), [-x for x in rank(i)]))
        say = "；".join(f"{ATTR_CN_S[a]} {values[a]['value']:.2f}（剩余名单内 {int(values[a]['left'])} 个，名单外 {int(values[a].get('unlisted', 0))} 个按1分估算，本局已有 {int(values[a]['have'])} 个）"
                       for a in attrs if a in values)
        return best, "按账号里各属性的角色算：" + say
    best = min(range(len(attrs)), key=rank)
    if attrs[best] is None:
        return 0, "属性没认出来，选最左边"
    return best, "属性优先顺序 " + " > ".join(order)


def choose_relic(options: Sequence[tuple[str | None, int]], levels: dict[str, int] | None = None,
                 weights: dict | None = None) -> tuple[int, str]:
    """迷宫遗物三选一。options = [(系列, 星数), …]；levels = 各系列现在几级（自己记的）。

    先看系列：有削弱拿削弱，没有削弱有加速拿加速（SERIES_FIRST，用户 2026-11-19 定的）；同一个系列有几个时拿星多的。
    都没有时：一颗星让系列升 1 级，所以星多的升得快；正好能跨过 4 / 9 / 15 级的加分；系列之间 强化 ≥ 暴击 > 守备。
    """
    levels = levels or {}
    w = dict(SERIES_WEIGHT)
    w.update(weights or {})

    def value(i: int) -> float:
        ser, stars = options[i]
        stars = max(1, stars)
        v = w.get(ser, w[None]) * stars
        cur = levels.get(ser, 0) if ser else 0
        if ser:
            v += sum(b for step, b in STEP_BONUS.items() if cur < step <= cur + stars)
        return v - 0.001 * i

    first = next((f for f in SERIES_FIRST if any(ser == f for ser, _ in options)), None)
    pool = [i for i in range(len(options)) if options[i][0] == first] if first else list(range(len(options)))
    best = max(pool, key=lambda i: (max(1, options[i][1]), value(i)) if first else (value(i),))
    ser, stars = options[best]
    if ser is None:
        return best, "系列没认出来，按星数选"
    cur = levels.get(ser, 0)
    crossed = [step for step in SERIES_STEPS if cur < step <= cur + max(1, stars)]
    lead = (f"{SERIES_CN_S[ser]}系列优先（" + ("最厉害" if ser == SERIES_FIRST[0] else "没有削弱时选它") + "）；") if first else ""
    return best, lead + f"这个系列现在 {cur} 级，拿了升 {max(1, stars)} 级" + (f"，正好到 {crossed[-1]} 级" if crossed else "")


# ---- 商店：买什么 ----
# 难度 5 的最终分数里，多 1 个迷宫遗物 +400、多 1 名角色 +200（score.py）；遗物几星分数都一样。所以按“每 1 分花多少金币”从便宜到贵买：
#   ★1 遗物 1,350 ÷ 400 = 3.4    随机印记（多 1 名角色）900 ÷ 200 = 4.5    ★2 遗物 2,100 ÷ 400 = 5.25
#   ★3 遗物 2,850 ÷ 400 = 7.1    ★4 遗物 7,499 ÷ 400 = 18.7（2026-11-18 真机上区域 4 那家商店卖的）
# 价格是从画面上读的。有的公会商店打折（咲恋救济院：★1 遗物 1,170、随机印记 780、★2 遗物 1,820，都是平常的 13/15）：
# 打折是所有东西一起便宜，哪件更划算并没有变，所以**买不买按平常的价来判断**（先算出这家店打了几折，见 shop_discount），
# 要留的钱按折后的价算。2026-11-25 以前是直接拿折后的价去比下面这几条按平常价定的线，结果在救济院：★2 遗物掉进“划算”线里被当便宜货买，
# “更新以后至少留 900 买一个印记”这些数也没跟着变。
SHOP_POINTS = {"relic": 400, "random": 200}
SHOP_BASE = {("relic", 1): 1350, ("relic", 2): 2100, ("relic", 3): 2850, ("relic", 4): 7499, ("random", None): 900, ("choose", None): 2100}   # 平常的价
SHOP_MAX_RATE = 5.0             # 平时只买每 1 分不超过这么多金币的（★1 遗物、随机印记）：金币是有限的，留给后面的商店买同样划算的
SHOP_LAST_RATE = 8.0            # 最后一个区域的商店：金币带不走，这个价以内的（★2、★3 遗物）在更新之前也买，只要不耽误后面买更划算的
SHOP_REFRESH_COSTS = (300, 600)  # 一家商店能更新两次，第一次 300、第二次 600（录制里两家商店都是；实际花多少以「更新确认」上读到的为准）
SHOP_SET_COST = 4300            # 更新出来的一批里，划算的那几件（★1 遗物、随机印记）大约一共要这么多：录制和真机见过的 8 批平均 1.5 个 ★1、2.5 个随机印记
SHOP_RELIC_SET = 2000           # 其中 ★1 遗物大约要这么多（1.5 个）
SHOP_BEST_RATE = 3.5            # 每 1 分不超过这么多金币的是“最划算的”（★1 遗物），见到就买
SHOP_KEEP = 900                 # 更新以后至少还买得起一件最便宜的（随机印记）才更新
SHOP_CARRY = 12000              # 不是最后一个区域时，手里留着这么多（最后一家店的便宜货大约吃得下这么多）以外的钱才买贵一点的（★2、★3）；
                                # 台服高分打法里区域 4 那家店“金币 ≥ 15,000 才买元素宝珠（★3，2,850）”，和这个数正好对上
SHOP_TRAP = 4000                # 遗物卖到这个价以上的是区域 4 那种卖 ★4 遗物的店（7,499 一个）：只买它最下面一排的印记，不更新
SHOP_ROLE_ORDER = ["attack", "break", "support", "buff", "debuff", "jam", "heal", "tank"]     # 价钱一样时先买哪种职能的印记


def shop_rate(kind: str | None, price: int | None) -> float | None:
    """这件商品每 1 分要花多少金币；不算分的（选择印记、不认识的）返回 None。"""
    pts = SHOP_POINTS.get(kind or "")
    return price / pts if pts and price else None


def shop_discount(items: Sequence[Sequence]) -> float:
    """这家商店的价是平常的几成（不打折 = 1.0）。看货架上认得出来的每一件：读到的价 ÷ 平常的价，取大多数商品都对得上的那个数。

    卖掉的、钱不够的也算（价照样读得出）；星数没认出来的遗物、不认识的东西不算。个别商品星数认错了会算出一个离谱的比例——
    所以不取平均，取“最多商品一致”的那个比例；一样多时取更接近不打折的。认不出就当不打折。"""
    ratios = []
    for kind, stars, _series, _role, price, _state in items:
        base = SHOP_BASE.get((kind, stars if kind == "relic" else None))
        if base and price and 0.6 <= price / base <= 1.02:
            ratios.append(price / base)
    if not ratios:
        return 1.0
    best = max(ratios, key=lambda r: (sum(1 for x in ratios if abs(x - r) <= 0.015), r))
    return 1.0 if best >= 0.985 else best


def choose_shop(items: Sequence[Sequence], coins: int | None, can_refresh: bool, refreshes_done: int = 0, last: bool = False,
                skip: Sequence[tuple] = (), max_rate: float = SHOP_MAX_RATE, discount: float | None = None) -> tuple[str, int | None, str]:
    """商店里下一步做什么。items = [(种类, 星数, 系列, 职能, 价格, 状态), …]（vision.shop.Item.as_list()）。

    items 可以只是现在看得见的那几件（列表要拖着看）：流程里看得见的没有要买的就往下拖，拖到底了才照这里说的更新 / 离开。
    返回（"buy" / "refresh" / "leave", 买第几件, 说明）。规则：
    1. 先买划算的（每 1 分不超过 max_rate）：最划算的先买；一样划算时遗物按系列、印记按职能排。
       其中 ★1 遗物（最划算）见到就买；随机印记要看钱：后面还能更新时，先留够买更新出来的 ★1 遗物的钱，够才买印记，
       不够就直接更新（计划里攻略的说法：★1 遗物买光 → 更新 → 再买，剩下的零头才买印记）；
    2. 划算的买完了，还能更新、更新完还买得起东西 → 更新；
    3. 最后一个区域（last）：金币带不走。更新之前，贵一点的（SHOP_LAST_RATE 以内）只要不占后面那几批划算货的钱也买；
       不能再更新以后，买得起的从划算到不划算都买；
       不是最后一个区域：贵一点的只有钱富余（买完还剩 SHOP_CARRY 以上）才买；
       卖 ★4 遗物的那种店（看得见 SHOP_TRAP 以上的遗物）：印记照买，钱富余再买 ★3 的宝珠，不更新；
    4. 「选择印记」不买（买了要进一个没见过的选人页面）；认不出、价格读不出、skip 里的（上次核对金额没对上）也不买。
    5. 商店打折（discount = 价是平常的几成；不给就从 items 里算）：划不划算按平常的价比（折后的价 ÷ discount），要留的钱按折后的算；
       更新的花费不打折，照实算。
    """
    f = float(discount) if discount else shop_discount(items)
    f = f if 0.5 <= f <= 1.0 else 1.0
    cands = []
    for i, it in enumerate(items):
        kind, stars, series, role, price, state = it
        rate = shop_rate(kind, price)
        if state != "buy" or rate is None or (kind, stars, series, role, price) in skip:
            continue
        pref = -SERIES_WEIGHT.get(series, SERIES_WEIGHT[None]) if kind == "relic" else \
            (SHOP_ROLE_ORDER.index(role) if role in SHOP_ROLE_ORDER else len(SHOP_ROLE_ORDER))
        cands.append((rate, 0 if kind == "relic" else 1, pref, i))
    cands.sort()
    good = [c for c in cands if c[0] / f <= max_rate]
    left = SHOP_REFRESH_COSTS[min(refreshes_done, len(SHOP_REFRESH_COSTS)):] if can_refresh else ()
    if can_refresh and not left:                         # 按钮还亮着但已经更新过两次了：没见过，按最后一档的价钱算
        left = SHOP_REFRESH_COSTS[-1:]
    trap = any(it[0] == "relic" and it[4] and it[4] / f >= SHOP_TRAP for it in items)
    if trap and not last:
        left = ()                                        # 卖 ★4 遗物的店：不更新（攻略里都只买它的印记；它更新出来是什么没见过），印记直接买
    if good:
        rate, _, _, i = good[0]
        price = items[i][4]
        need = sum(left) + SHOP_RELIC_SET * f * len(left)                # 后面每更新一次，留够买那一批 ★1 遗物的钱
        if rate / f <= SHOP_BEST_RATE or coins is None or not left or coins - price >= need:
            return "buy", i, f"每 1 分 {rate:.1f} 金币"
        # 钱不够两头都顾：更新是为了等 ★1 遗物——更新完得买得起一个才值得更新（2026-11-25 以前只要求“买得起一个印记”：
        # 真机上 1,730 金币花 600 更新，剩 1,130，★1 遗物 1,170 差 40 买不起，白花了更新的钱，还把货架上现成的印记换没了）
        if coins - left[0] >= SHOP_BASE[("relic", 1)] * f:
            return "refresh", None, f"钱不多，{'印记' if items[i][0] == 'random' else '这件'}先不买，花 {left[0]} 更新一批看有没有 ★1 遗物"
        return "buy", i, f"每 1 分 {rate:.1f} 金币（更新完也买不起 ★1 遗物，不更新了）"
    if last and cands and coins is not None:
        rate, _, _, i = cands[0]
        price = items[i][4]
        reserve = sum(left) + SHOP_SET_COST * f * len(left)              # 后面每更新一次，留够买那一批划算货的钱
        if (not left) or (rate / f <= SHOP_LAST_RATE and coins - price >= reserve):
            return "buy", i, f"最后一个区域，金币带不走（每 1 分 {rate:.1f} 金币）"
    if not last and cands and coins is not None:
        rate, _, _, i = cands[0]
        price = items[i][4]
        if rate / f <= SHOP_LAST_RATE and coins - price >= (SHOP_CARRY + SHOP_SET_COST * len(left)) * f + sum(left):
            return "buy", i, f"钱富余，买完还剩 {coins - price:,}（每 1 分 {rate:.1f} 金币）"
    if left and (coins is None or coins >= left[0] + SHOP_KEEP * f):
        return "refresh", None, f"划算的买完了，花 {left[0]} 更新一批"
    if cands and not last:
        return "leave", None, "剩下的不划算（留着金币去后面的商店买便宜的）"
    return "leave", None, "没有要买的了" if not cands else "剩下的买不起或不划算"
