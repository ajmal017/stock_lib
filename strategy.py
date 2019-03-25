# -*- coding: utf-8 -*-
import re
import math
import numpy
import inspect
import utils
import simulator
import itertools
from loader import Loader
from collections import namedtuple
from simulator import SimulatorData
from argparse import ArgumentParser
import strategies.production as production
import strategies as develop

class LoadSettings:
    with_stats = False
    weekly = True

def add_options(parser):
    parser.add_argument("--position_sizing", action="store_true", default=False, dest="position_sizing", help="ポジションサイジング")
    parser.add_argument("--production", action="store_true", default=False, dest="production", help="本番向け") # 実行環境の選択
    parser.add_argument("--short", action="store_true", default=False, dest="short", help="空売り戦略")
    parser.add_argument("--tick", action="store_true", default=False, dest="tick", help="ティックデータを使う")
    parser.add_argument("--realtime", action="store_true", default=False, dest="realtime", help="リアルタイムデータを使う")
    parser.add_argument("--daytrade", action="store_true", default=False, dest="daytrade", help="デイトレ")
    parser.add_argument("--falling", action="store_true", default=False, dest="falling", help="下落相場")
    parser.add_argument("--new_high", action="store_true", default=False, dest="new_high", help="新高値")
    parser.add_argument("--nikkei", action="store_true", default=False, dest="nikkei", help="日経")
    parser.add_argument("--rising", action="store_true", default=False, dest="rising", help="上昇銘柄")
    parser.add_argument("--with_stats", action="store_true", default=False, dest="with_stats", help="統計データ込みで読み込む")
    parser.add_argument("--ignore_weekly", action="store_true", default=False, dest="ignore_weekly", help="週足統計を無視")
    parser.add_argument("--monitor_size", action="store", default=None, dest="monitor_size", help="監視銘柄数")
    return parser

def create_parser():
    parser = ArgumentParser()
    return add_options(parser)

def get_prefix(args):
    prefix = "production_" if args.production else ""

    tick = "tick_" if args.tick else ""

    method = "short_" if args.short else ""

    target = ""
    if args.daytrade:
        target = "daytrade_"
    if args.falling:
        target = "falling_"
    if args.new_high:
        target = "new_high_"
    if args.nikkei:
        target = "nikkei_"
    if args.rising:
        target = "rising_"

    return "%s%s%s%s" % (prefix, target, tick, method)

def get_filename(args):
    prefix = get_prefix(args)
    filename = "%ssimulate_setting.json" % prefix
    return filename

def load_simulator_data(code, start_date, end_date, args, load_settings=None, time=None):

    if load_settings is None:
        load_settings = LoadSettings()

    if args.realtime:
        start = utils.to_datetime(start_date) - utils.relativeterm(3, True)
        days = (utils.to_datetime(end_date) - start).days
        for i in range(5):
            data = Loader.loads_realtime(code, end_date, days+i, time=time)
            if len(data) >= 250: # weekleyのstats生成で必要な分
                break
        rule = "30T"
    elif args.tick:
        start = utils.to_format(utils.to_datetime(start_date) - utils.relativeterm(1, True))
        data = Loader.load_tick_ohlc(code, start, end_date)
        rule = "30T"
    else:
        start = utils.to_format(utils.to_datetime(start_date) - utils.relativeterm(6))
        data = Loader.load_with_realtime(code, start, end_date, with_stats=load_settings.with_stats)
        rule = "W"

    if data is None:
        print("%s: %s is None" % (start_date, code))
        return None

    try:
        if not load_settings.with_stats:
            data = utils.add_stats(data)
            data = utils.add_cs_stats(data)
        weekly = Loader.resample(data, rule=rule)
        if load_settings.weekly:
            weekly = utils.add_stats(weekly)
            weekly = utils.add_cs_stats(weekly)
        return SimulatorData(code, data, weekly, rule)
    except Exception as e:
        print("load_error: %s" % e)
        return None

def load_strategy_setting(args):
    filename = get_filename(args)
    setting_dict = Loader.simulate_setting(filename)
    print(filename, setting_dict)
    if setting_dict is None:
        strategy_setting = StrategySetting()
    else:
        strategy_setting = create_setting_by_dict(setting_dict["setting"])
    return setting_dict, strategy_setting

def load_strategy(args, combination_setting=None):
    _, settings = load_strategy_setting(args)
    return load_strategy_creator(args, combination_setting).create(settings)

def get_monitor_size(args):
    if not args.monitor_size is None:
        return int(args.monitor_size)

    setting_dict, _ = load_strategy_setting(args)
    if "monitor_size" in setting_dict.keys() and "monitor_size_ratio" in setting_dict.keys():
        monitor_size = setting_dict["monitor_size"] * setting_dict["monitor_size_ratio"]
        return monitor_size
    return 3

def load_strategy_creator(args, combination_setting=None):
    if args.production:
        if args.daytrade:
            from strategies.production.daytrade import CombinationStrategy
            return CombinationStrategy(combination_setting)
        elif args.falling:
            from strategies.production.falling import CombinationStrategy
            return CombinationStrategy(combination_setting)
        elif args.nikkei:
            from strategies.production.nikkei import CombinationStrategy
            return CombinationStrategy(combination_setting)
        elif args.rising:
            from strategies.production.rising import CombinationStrategy
            return CombinationStrategy(combination_setting)
        else:
           from strategies.production.combination import CombinationStrategy
           return CombinationStrategy(combination_setting)
    else:
        if args.daytrade:
            from strategies.daytrade import CombinationStrategy
            return CombinationStrategy(combination_setting)
        elif args.falling:
            from strategies.falling import CombinationStrategy
            return CombinationStrategy(combination_setting)
        elif args.nikkei:
            from strategies.nikkei import CombinationStrategy
            return CombinationStrategy(combination_setting)
        elif args.new_high:
            from strategies.new_high import CombinationStrategy
            return CombinationStrategy(combination_setting)
        elif args.rising:
            from strategies.rising import CombinationStrategy
            return CombinationStrategy(combination_setting)
        else:
            from strategies.combination import CombinationStrategy
            return CombinationStrategy(combination_setting)

def create_combination_setting(args, monitor_size_optimize=False):
    combination_setting = CombinationSetting()
    combination_setting.position_sizing = args.position_sizing
    if monitor_size_optimize:
        combination_setting.monitor_size = get_monitor_size(args)
    else:
        combination_setting.monitor_size = combination_setting.monitor_size if args.monitor_size is None else int(args.monitor_size)
    return combination_setting

# ========================================================================
# 売買ルール
class Rule:
    def __init__(self, callback):
        self._callback = callback

    def apply(self, data):
        results = self._callback(data)
        return results

# 売買戦略
class Strategy:
    def __init__(self, new_rules, taking_rules, stop_loss_rules, closing_rules):
        self.new_rules = list(map(lambda x: Rule(x), new_rules))
        self.taking_rules = list(map(lambda x: Rule(x), taking_rules))
        self.stop_loss_rules = list(map(lambda x: Rule(x), stop_loss_rules))
        self.closing_rules = list(map(lambda x: Rule(x), closing_rules))

def create_setting_by_dict(params):
     return namedtuple("StrategySetting", params.keys())(*params.values())

def strategy_setting_to_dict(strategy_setting):
    return {"new": strategy_setting.new, "taking": strategy_setting.taking, "stop_loss": strategy_setting.stop_loss, "closing": strategy_setting.closing}

class StrategySetting():
    def __init__(self):
        self.new = 0
        self.taking = 0
        self.stop_loss = 0
        self.closing = 0

    def by_array(self, params):
        self.new = int(params[0])
        self.taking = int(params[1])
        self.stop_loss = int(params[2])
        self.closing = int(params[3])
        return self

    def to_dict(self):
        return strategy_setting_to_dict(self)

class StrategyCreator:
    def __init__(self, new=None, taking=None, stop_loss=None, closing=None):
        self.new = new
        self.taking = taking
        self.stop_loss = stop_loss
        self.closing = closing

    def create_new_rules(self, data):
        return self.new

    def create_taking_rules(self, data):
        return self.taking

    def create_stop_loss_rules(self, data):
        return self.stop_loss

    def create_closing_rules(self, data):
        return self.closing

    def create(self):
        new_rules = [lambda x: self.create_new_rules(x)]
        taking_rules = [lambda x: self.create_taking_rules(x)]
        stop_loss_rules = [lambda x: self.create_stop_loss_rules(x)]
        closing_rules = [lambda x: self.create_closing_rules(x)]
        return Strategy(new_rules, taking_rules, stop_loss_rules, closing_rules)

    def ranges(self):
        return []

class StrategyConditions():
    def __init__(self):
        self.new = []
        self.taking = []
        self.stop_loss = []
        self.closing = []

    def by_array(self, params):
        self.new = params[0]
        self.taking = params[1]
        self.stop_loss = params[2]
        self.closing = params[3]
        return self


class StrategyUtil:
    def max_risk(self, data):
        return data.assets * data.setting.stop_loss_rate

    # 利益目標
    def goal(self, data):
        order = data.position.num() # 現在の保有数
        if data.setting.short_trade:
            price = data.data["daily"]["low"].iloc[-1]
            line = data.data["daily"]["support"].iloc[-1]
            goal = (price - line)
        else:
            price = data.data["daily"]["high"].iloc[-1]
            line = data.data["daily"]["resistance"].iloc[-1]
            goal = (line - price)

        goal = 0 if goal < 0 else goal * (order + 100)
        return goal

    # 損失リスク
    def risk(self, data):
        order = data.position.num() # 現在の保有数
        price = data.data["daily"]["close"].iloc[-1]

        if data.setting.short_trade:
            safety = data.data["daily"]["fall_safety"].iloc[-1]
            risk = (safety - price)
        else:
            safety = data.data["daily"]["rising_safety"].iloc[-1]
            risk = (price - safety)

        # riskがマイナスの場合、safetyを抜けているのでリスクが高い
        risk = 0 if risk < 0 else risk * (order + 100)
        return risk

    # 上限
    def upper(self, data, term=1):
        upper = data.data["daily"]["resistance"].iloc[-term]

        return upper

    # 下限
    def lower(self, data, term=1):
        lower= data.data["daily"]["support"].iloc[-term]

        return lower

    # 不安要素
    def falling(self, data, risk):
        conditions = [
            risk == 0, # セーフティーを下回っている
        ]
        return any(conditions)

    # 最大ポジションサイズ
    def max_order(self, max_risk, risk):
        if risk == 0:
            return 0
        return int(max_risk / risk) * 100

    # ポジションサイズ
    def order(self, data, max_risk, risk):
        current = data.position.num()
        max_order = int((self.max_order(max_risk, risk) - current)) # 保有できる最大まで
        max_order = int(max_order / 2) # 半分ずつ
        max_order = int(math.ceil(max_order / 100) * 100) # 端数を切り上げ
        order = 100 if self.falling(data, risk) else max_order

        if order < 100:
            order = 0

        return order

    def safety(self, data, term):
        return data.data["daily"]["rising_safety"].iloc[-term:].max() * 0.98

    def term(self, data):
        return 1 if data.position.term()  == 0 else data.position.term()

    # 強気のダイバージェンス
    def rising_divergence(self, data):
        conditions = [
            data.data["daily"]["weekly_average_trend"].iloc[-1] < 0,
            data.data["daily"]["daily_average_trend"].iloc[-1] >= 0,
            data.data["daily"]["macd_trend"].iloc[-1] > 0,
            data.data["daily"]["macdhist_trend"].iloc[-1] > 0,
        ]

        return [
            data.data["daily"]["weekly_average_trend"].iloc[-1] > 0 and data.data["daily"]["daily_average_trend"].iloc[-1] <= 0,
            data.data["daily"]["weekly_average_trend"].iloc[-1] >= 0 and data.data["daily"]["daily_average_trend"].iloc[-1] < 0,
            all(conditions),
        ]

## 指定可能な戦略====================================================================================================================

class CombinationSetting:
    simple = False
    position_sizing = False
    sorted_conditions = True
    monitor_size = 3

class Combination(StrategyCreator, StrategyUtil):
    def __init__(self, conditions, common, setting=None):
        self.conditions = conditions
        self.common = common
        self.setting = CombinationSetting() if setting is None else setting

    def apply(self, data, conditions):
        if len(conditions) == 0:
            return False
        a = list(map(lambda x: x(data), conditions[0]))
        b = list(map(lambda x: x(data), conditions[1]))
        return all(a) and any(b)

    def apply_common(self, data, conditions):
        common = list(map(lambda x: x(data), conditions))
        return all(common)

    # 買い
    def create_new_rules(self, data):
        drawdown = list(map(lambda x: x["drawdown"], data.stats.drawdown[-20:]))
        drawdown_gradient = list(filter(lambda x: x > 0.06, numpy.gradient(drawdown))) if len(drawdown) > 1 else []
        drawdown_sum = list(filter(lambda x: x > 0, numpy.gradient(drawdown))) if len(drawdown) > 1 else []
        risk = self.risk(data)
        max_risk = self.max_risk(data)
        drawdown_conditions = [
            len(drawdown_gradient) == 0, # 6%ルール条件外(-6%を超えて一定期間たった)
            sum(drawdown_sum) < 0.06 # 6%ルール(直近のドローダウン合計が6%以下)
        ]

        if not all(drawdown_conditions) and data.setting.debug:
            print("over drawdown: ", drawdown_conditions)

        conditions = [
            all(drawdown_conditions), # ドローダウンが問題ない状態
            (data.position.num() < self.max_order(max_risk, risk)) if risk > 0 else False, # 最大ポジションサイズ以下
            self.apply_common(data, self.common.new)
        ]

        order = self.order(data, max_risk, risk) if self.setting.position_sizing else 100

        if self.apply(data, self.conditions.new):
            if all(conditions) or self.setting.simple:
                return simulator.Order(order, [lambda x: True])

        return None

    # 利食い
    def create_taking_rules(self, data):
        conditions = [
            self.apply_common(data, self.common.taking),
            self.apply(data, self.conditions.taking)
        ]
        return simulator.Order(data.position.num(), [lambda x: True]) if all(conditions) else None

    # 損切
    def create_stop_loss_rules(self, data):
        conditions = [
            utils.rate(data.position.value(), data.data["daily"]["close"].iloc[-1]) < -0.02, # 損益が-2%
            self.apply_common(data, self.common.stop_loss) and self.apply(data, self.conditions.stop_loss),
        ]
        if any(conditions):
            return simulator.Order(data.position.num(), [lambda x: True])
        return None

    # 手仕舞い
    def create_closing_rules(self, data):
        conditions = [
            self.apply_common(data, self.common.closing) and self.apply(data, self.conditions.closing),
        ]

        if any(conditions):
            return simulator.Order(data.position.num(), [lambda x: True])

        return None

class CombinationCreator(StrategyCreator, StrategyUtil):
    def __init__(self, setting=None):
        self.setting = CombinationSetting() if setting is None else setting
        if self.setting.sorted_conditions:
            # 条件のインデックスの組み合わせを生成
            self.new_combinations = utils.combinations(list(range(len(self.new()))))
            self.taking_combinations = utils.combinations(list(range(len(self.taking()))))
            self.stop_loss_combinations = utils.combinations(list(range(len(self.stop_loss()))))
            self.closing_combinations = utils.combinations(list(range(len(self.closing()))))

    def ranges(self):
        return [
            list(range(utils.combinations_size(self.new()))),
            list(range(utils.combinations_size(self.taking()))),
            list(range(utils.combinations_size(self.stop_loss()))),
            list(range(utils.combinations_size(self.closing()))),
        ]

    def create(self, setting):
        condition = self.sorted_conditions(setting) if self.setting.sorted_conditions else self.conditions(setting)
        c = StrategyConditions().by_array(condition)
        return Combination(c, self.common(), self.setting).create()

    # ソート済みのリストから条件を取得
    def sorted_conditions(self, setting):
        return [
            self.conditions_by_index(self.new(), self.new_combinations[setting.new]),
            self.conditions_by_index(self.taking(), self.taking_combinations[setting.taking]),
            self.conditions_by_index(self.stop_loss(), self.stop_loss_combinations[setting.stop_loss]),
            self.conditions_by_index(self.closing(), self.closing_combinations[setting.closing]),
        ]

    # インデックスから直接条件を生成
    def conditions(self, setting):
        return [
            utils.combination(setting.new, self.new()),
            utils.combination(setting.taking, self.taking()),
            utils.combination(setting.stop_loss, self.stop_loss()),
            utils.combination(setting.closing, self.closing()),
        ]

    def conditions_by_index(self, conditions, index):
        a = [conditions[i] for i in index[0]]
        b = [conditions[i] for i in index[1]]
        return [a, b]


    def subject(self):
        raise Exception("Need override subject.")

    def default_common(self):
        rules = [lambda d: True]
        return StrategyCreator(rules, rules, rules, rules)

    # @return StrategyCreator
    def common(self):
        return self.default_common()

    def new(self):
        return [
            lambda d: False
        ]

    def taking(self):
        return [
            lambda d: False
        ]

    def stop_loss(self):
        return [
            lambda d: False
        ]

    def closing(self):
        return [
            lambda d: False
        ]

class CombinationChecker:
    def __init__(self, combination_strategy):
        self.new_combinations = utils.combinations(range(len(combination_strategy.new())))
        self.taking_combinations = utils.combinations(range(len(combination_strategy.taking())))
        self.stop_loss_combinations = utils.combinations(range(len(combination_strategy.stop_loss())))
        self.closing_combinations = utils.combinations(range(len(combination_strategy.closing())))

        self.combinations_dict = {
            "new": (self.new_combinations, combination_strategy.new),
            "taking": (self.taking_combinations, combination_strategy.taking),
            "closing": (self.closing_combinations, combination_strategy.closing),
            "stop_loss": (self.stop_loss_combinations, combination_strategy.stop_loss),
        }

    def get_strategy_source_by_index(self, index, method):
        source = inspect.getsource(method)
        pattern = r"d: .*[,$\n]"
        source = re.findall(pattern, source)
        return source[index].strip("\n")

    def get_strategy_source(self, combinations, method):
        source = inspect.getsource(method)
        pattern = r"d: .*[,$\n]"
        source = re.findall(pattern, source)
        a = numpy.array([source[i].strip("\n") for i in combinations[0]])
        b = numpy.array([source[i].strip("\n") for i in combinations[1]])
        return a, b

    def get_strategy_sources(self, setting):
        results = []
        for k, v in self.combinations_dict.items():
           combinations = v[0][setting["setting"][k]]
           a, b = self.get_strategy_source(combinations, v[1])
           results.append({"key":k, "all": a, "any": b, "combinations": combinations})
        return results


