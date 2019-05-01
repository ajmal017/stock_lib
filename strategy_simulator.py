import sys
import numpy

sys.path.append("lib")
import checker
import cache
import utils
import strategy
from simulator import Simulator, TradeRecorder


class StrategySimulator:
    def __init__(self, simulator_setting, strategy_creator, verbose=False):
        self.simulator_setting = simulator_setting
        self.strategy_creator = strategy_creator
        self.verbose = verbose
        self.cacher = cache.Cache("/tmp/strategy_simulator")
        self.cacher.remove_dir()

    def append_daterange(self, codes, date, daterange):
        for code in codes:
            if not code in daterange.keys():
                daterange[code] = []
            daterange[code].append(date)
            daterange[code].sort()
        return daterange

    def select_codes(self, args, start_date, end_date):
        codes = []
        daterange = {}
        start = utils.to_datetime_by_term(start_date, tick=args.tick)
        end = utils.to_datetime_by_term(end_date, tick=args.tick) + utils.relativeterm(1, tick=True)
        for date in utils.daterange(start, end):
            codes = self.get_targets(args, codes, utils.to_format_by_term(date, args.tick))
            daterange = self.append_daterange(codes, date, daterange)
        validate_codes = codes
        return codes, validate_codes, daterange

    def get_targets(self, args, targets, date):
        if args.code is None:
            date = utils.to_format(utils.to_datetime_by_term(date, args.tick))
            targets = list(set(targets + self.strategy_creator.subject(date)))
        else:
            targets = [args.code]
        return targets

    def manda(self, data, code, start, end):
        manda_cache_name = "%s_%s_%s" % (code, start, end)
        if self.cacher.exists(manda_cache_name):
            manda = self.cacher.get(manda_cache_name)
        else:
            split_data = data.split(start, end)
            manda = checker.manda(split_data.daily)
            self.cacher.create(manda_cache_name, manda)
        return manda

    def log(self, message, verbose):
        if verbose:
             print(message)

    def simulates(self, strategy_setting, data, start_date, end_date, verbose=False):
        self.log("simulating %s %s" % (start_date, end_date), verbose)

        args = data["args"]
        tick = args.tick

        # この期間での対象銘柄
        codes, _, _ = self.select_codes(args, start_date, end_date)
        index = data["index"]
        stocks = {}
        for code in codes:
            if code in data["data"].keys():
                stocks[code] = data["data"][code]

        # シミュレーター準備
        simulators = {}
        self.simulator_setting.debug = verbose
        self.simulator_setting.strategy = self.strategy_creator.create(strategy_setting)
        for code in stocks.keys():
            simulators[code] = Simulator(self.simulator_setting)

        # 日付のリストを取得
        dates = []
        for d in stocks.values():
            dates = list(set(dates + d.dates(start_date, end_date)))

        # 日付ごとにシミュレーション
        targets = []
        dates = sorted(dates, key=lambda x: utils.to_datetime_by_term(x, tick))
        for date in dates:
            # 休日はスキップ
            if not utils.is_weekday(utils.to_datetime_by_term(date, tick)):
                self.log("%s is not weekday" % date, verbose)
                continue

            self.log("=== [%s] ===" % date, verbose)

            # この日の対象銘柄
            targets = self.get_targets(args, targets, date)

            # 保有銘柄を対象に追加
            for code, simulator in simulators.items() :
                if simulator.position().num() > 0:
                    targets.append(code)

            targets = list(set(targets))

            self.log("targets: %s" % targets, verbose)

            for code in targets:
                # M&Aのチェックのために期間を区切ってデータを渡す(M&Aチェックが重いから)
                start = utils.to_format_by_term(utils.to_datetime_by_term(date, tick) - utils.relativeterm(args.validate_term, tick), tick)
                manda = self.manda(stocks[code], code, start, date)
                if manda:
                    self.log("[%s] is manda" % code, verbose)
                    continue

                # 対象日までのデータの整形
                # filter -> ohlc をすべてoにする-> add_stats
#                d = stocks[code].daily
#                d = d[d["date"] <= date].iloc[-300:].copy()
#                for column in ["high", "low", "close"]:
#                    tmp = d[column].as_matrix().tolist()
#                    tmp[-1] = d["open"].iloc[-1]
#                    d[column] = tmp
#                d = strategy.add_stats(code, d, stocks[code].rule)
                d = stocks[code]

                if len(stocks[code].at(date)) > 0:
                    self.log("[%s]" % code, verbose)
                    simulators[code].simulate_by_date(date, d, index)
                else:
                    self.log("[%s] is less data: %s" % (code, date), verbose)
        # 手仕舞い
        if len(dates) > 0:
            recorder = TradeRecorder(strategy.get_prefix(args))
            for code in stocks.keys():
                split_data = stocks[code].split(dates[0], dates[-1])
                if len(split_data.daily) == 0:
                    continue
                simulators[code].closing(split_data.daily["close"].iloc[-1], data=split_data.daily)
                recorder.concat(simulators[code].trade_recorder)
            recorder.output("%s_%s" % (start_date, end_date), append=True)

        # 統計 ====================================
        stats = {}
        for code in stocks.keys():
            s = simulators[code].get_stats()
            keys = ["return", "drawdown", "win_trade", "trade", "assets", "max_unavailable_assets", "trade_history"]
            result = {}
            for k in keys:
                result[k] = s[k]
            stats[code] = result

        return self.get_results(stats, start_date, end_date, verbose)

    def get_results(self, stats, start_date, end_date, verbose):
        # 統計 =======================================
        wins = list(filter(lambda x: x[1]["return"] > 0, stats.items()))
        lose = list(filter(lambda x: x[1]["return"] < 0, stats.items()))
        win_codes = list(map(lambda x: x[0], wins))
        lose_codes = list(map(lambda x: x[0], lose))
        codes = win_codes + lose_codes
        gain = list(map(lambda x: x[1]["assets"] - self.simulator_setting.assets, stats.items()))
        trade_history = list(map(lambda x: x[1]["trade_history"], stats.items()))
        position_size = list(map(lambda x: list(map(lambda y: y["size"], x)), trade_history))
        position_size = list(filter(lambda x: x != 0, sum(position_size, [])))
        position_term = list(map(lambda x: list(map(lambda y: y["term"], x)), trade_history))
        position_term = list(filter(lambda x: x != 0, sum(position_term, [])))
        max_unavailable_assets = list(map(lambda x: x[1]["max_unavailable_assets"], stats.items()))

        if verbose:
            print(start_date, end_date, "assets:", self.simulator_setting.assets, "gain:", gain, sum(gain))
            for code, s in sorted(stats.items(), key=lambda x: x[1]["return"]):
                print("[%s] return: %s, drawdown: %s, trade: %s, win: %s" % (code, s["return"], s["drawdown"], s["trade"], s["win_trade"]))

        s = stats.values()
        results = {
            "codes": codes,
            "win": win_codes,
            "lose": lose_codes,
            "gain": sum(gain),
            "return": sum(gain) / self.simulator_setting.assets,
            "drawdown": numpy.average(list(map(lambda x: x["drawdown"], s))) if len(s) > 0 else 0,
            "max_drawdown": max(list(map(lambda x: x["drawdown"], s))) if len(s) > 0 else 0,
            "win_trade": sum(list(map(lambda x: x["win_trade"], s))) if len(s) > 0 else 0,
            "trade": sum(list(map(lambda x: x["trade"], s))) if len(s) > 0 else 0,
            "position_size": numpy.average(position_size) if len(position_size) > 0 else 0,
            "max_position_size": max(position_size) if len(position_size) > 0 else 0,
            "position_term": numpy.average(position_term) if len(position_term) > 0 else 0,
            "max_position_term": max(position_term) if len(position_term) > 0 else 0,
            "max_unavailable_assets": max(max_unavailable_assets) if len(max_unavailable_assets) > 0 else 0,
        }

        return results


