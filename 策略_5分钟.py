# -*- coding: utf-8 -*-
"""
包含针对 5 分钟时间周期的交易策略
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)

def simple_sma_strategy(bar_data: pd.Series, position: dict | None, sma_period: int = 20) -> dict:
    """
    一个简单的基于 SMA 交叉的策略示例。

    Args:
        bar_data: 当前 K 线的数据 (Pandas Series)，需要包含 'close' 和 'sma' 列。
        position: 当前持仓状态字典，如果空仓则为 None。
                 结构: {'direction': 'LONG'/'SHORT', 'entry_price': float, 'size': float, ...}
        sma_period: SMA 计算周期 (主要用于日志或未来扩展)。

    Returns:
        一个包含信号和原因的字典。
        信号: 'LONG', 'SHORT', 'CLOSE_LONG', 'CLOSE_SHORT', 'HOLD'
        示例: {'signal': 'LONG', 'reason': 'Price > SMA'}
    """
    signal = 'HOLD'
    reason = 'No signal'

    try:
        current_price = bar_data['close']
        current_sma = bar_data['sma']

        if pd.isna(current_price) or pd.isna(current_sma):
            reason = "SMA 或价格数据无效"
            return {'signal': 'HOLD', 'reason': reason}

        # === 入场逻辑 ===
        if position is None: # 只有在没有持仓时才考虑开仓
            if current_price > current_sma:
                signal = 'LONG'
                reason = f'Price ({current_price:.2f}) > SMA({sma_period}) ({current_sma:.2f})'
            elif current_price < current_sma:
                signal = 'SHORT'
                reason = f'Price ({current_price:.2f}) < SMA({sma_period}) ({current_sma:.2f})'

        # === 出场逻辑 (基于信号) ===
        elif position:
            if position['direction'] == 'LONG' and current_price < current_sma:
                 signal = 'CLOSE_LONG'
                 reason = f'Price ({current_price:.2f}) < SMA({sma_period}) ({current_sma:.2f})'
            elif position['direction'] == 'SHORT' and current_price > current_sma:
                 signal = 'CLOSE_SHORT'
                 reason = f'Price ({current_price:.2f}) > SMA({sma_period}) ({current_sma:.2f})'

    except KeyError as e:
        logger.error(f"策略函数 simple_sma_strategy 缺少必要数据列: {e}")
        reason = f"缺少数据列: {e}"
    except Exception as e:
        logger.error(f"策略函数 simple_sma_strategy 发生错误: {e}", exc_info=True)
        reason = f"策略计算错误: {e}"

    return {'signal': signal, 'reason': reason}

# --- 新策略：SMA 交叉 + RSI 过滤 + EMA 趋势过滤 ---

def rsi_sma_strategy(
    bar_data: pd.Series,
    position: dict | None,
    sma_period: int = 20,
    rsi_period: int = 14,
    rsi_oversold: int = 30,
    rsi_overbought: int = 70,
    long_ema_period: int = 120,
    min_relative_volatility: float = 0.001
) -> dict:
    """
    结合 SMA 交叉、RSI 过滤、EMA 趋势过滤和 ATR 波动率过滤的策略。
    入场需要短期均线和价格都在长期均线同侧。

    Args:
        bar_data: 当前 K 线的数据 (Pandas Series)，需要包含
                  'close', 'sma', 'rsi', 'long_ema', 'atr', 'prev_close', 'prev_sma' 列。
        position: 当前持仓状态字典，如果空仓则为 None。
        sma_period: SMA 周期。
        rsi_period: RSI 周期。
        rsi_oversold: RSI 超卖阈值。
        rsi_overbought: RSI 超买阈值。
        long_ema_period: 长期 EMA 周期。
        min_relative_volatility: 允许开仓的最小相对波动率 (ATR/Close)。

    Returns:
        一个包含信号和原因的字典。
        信号: 'LONG', 'SHORT', 'CLOSE_LONG', 'CLOSE_SHORT', 'HOLD'
    """
    signal = 'HOLD'
    reason = 'No signal'

    try:
        # 从 bar_data 中获取所需数据
        current_price = bar_data['close']
        current_sma = bar_data['sma']
        current_rsi = bar_data['rsi']
        long_ema = bar_data['long_ema']
        current_atr = bar_data['atr']
        prev_price = bar_data['prev_close']
        prev_sma = bar_data['prev_sma']

        # 检查数据有效性
        if pd.isna(current_price) or pd.isna(current_sma) or pd.isna(current_rsi) or \
           pd.isna(long_ema) or pd.isna(current_atr) or pd.isna(prev_price) or pd.isna(prev_sma):
            reason = "策略所需数据不完整或无效"
            return {'signal': 'HOLD', 'reason': reason}

        # --- 计算当前相对波动率 ---
        relative_volatility = 0.0
        if current_price > 1e-9: # Avoid division by zero
            relative_volatility = current_atr / current_price

        # --- 定义趋势和穿越条件 ---
        strong_uptrend = current_price > long_ema and current_sma > long_ema
        strong_downtrend = current_price < long_ema and current_sma < long_ema
        crossed_above_sma = current_price > current_sma and prev_price <= prev_sma
        crossed_below_sma = current_price < current_sma and prev_price >= prev_sma

        # === 入场逻辑 ===
        if position is None:
            # 检查波动率是否足够
            if relative_volatility >= min_relative_volatility:
                # 做多条件：SMA上穿 + RSI未超买 + 强趋势向上
                if crossed_above_sma and current_rsi < rsi_overbought and strong_uptrend:
                    signal = 'LONG'
                    reason = f"SMA↑, RSI({current_rsi:.1f})<{rsi_overbought}, Trend↑, Vol OK (ATR/P={relative_volatility:.4f})"
                # 做空条件：SMA下穿 + RSI未超卖 + 强趋势向下
                elif crossed_below_sma and current_rsi > rsi_oversold and strong_downtrend:
                    signal = 'SHORT'
                    reason = f"SMA↓, RSI({current_rsi:.1f})>{rsi_oversold}, Trend↓, Vol OK (ATR/P={relative_volatility:.4f})"
            else:
                # 波动率不足，即使有信号也忽略
                reason = f"波动率不足 (ATR/P={relative_volatility:.4f} < {min_relative_volatility})"

        # === 出场逻辑 (基于信号 - 反向穿越) ===
        elif position:
            # 持有多单时，若价格跌破 SMA，则平仓（不再考虑趋势）
            if position['direction'] == 'LONG' and crossed_below_sma:
                 signal = 'CLOSE_LONG'
                 reason = f"SMA 下穿 ({current_price:.2f} < {current_sma:.2f})，平多仓"
            # 持有空单时，若价格涨破 SMA，则平仓（不再考虑趋势）
            elif position['direction'] == 'SHORT' and crossed_above_sma:
                 signal = 'CLOSE_SHORT'
                 reason = f"SMA 上穿 ({current_price:.2f} > {current_sma:.2f})，平空仓"

    except KeyError as e:
        logger.error(f"策略函数 rsi_sma_strategy 缺少必要数据列: {e}")
        reason = f"缺少数据列: {e}"
    except Exception as e:
        logger.error(f"策略函数 rsi_sma_strategy 发生错误: {e}", exc_info=True)
        reason = f"策略计算错误: {e}"

    return {'signal': signal, 'reason': reason}

# --- 你可以在下面添加更多的 5 分钟策略函数 ---

# --- 新策略：MACD Histogram 穿越零轴 和 EMA 趋势过滤 ---
def macd_ema_strategy(
    bar_data: pd.Series,
    position: dict | None,
    long_ema_period: int = 120 # 主要用于日志说明
) -> dict:
    """
    结合 MACD Histogram 穿越零轴 和 EMA 趋势过滤的策略。

    Args:
        bar_data: 当前 K 线的数据 (Pandas Series)，需要包含
                  'close', 'long_ema', 'macd_hist', 'prev_macd_hist' 列。
        position: 当前持仓状态字典，如果空仓则为 None。
        long_ema_period: 长期 EMA 周期 (用于日志)。

    Returns:
        一个包含信号和原因的字典。
        信号: 'LONG', 'SHORT', 'HOLD' (此策略不生成平仓信号，依赖 SL/TP)
    """
    signal = 'HOLD'
    reason = 'No signal'

    try:
        # 从 bar_data 中获取所需数据
        current_price = bar_data['close']
        long_ema = bar_data['long_ema']
        macd_hist = bar_data['macd_hist']
        prev_macd_hist = bar_data['prev_macd_hist']
        # macd = bar_data['macd'] # 不再需要
        # macd_signal_line = bar_data['macd_signal'] # 不再需要
        # prev_macd = bar_data['prev_macd'] # 不再需要
        # prev_macd_signal_line = bar_data['prev_macd_signal'] # 不再需要

        # 检查数据有效性
        if pd.isna(current_price) or pd.isna(long_ema) or pd.isna(macd_hist) or \
           pd.isna(prev_macd_hist):
            reason = "MACD Histogram 策略所需数据不完整或无效"
            return {'signal': 'HOLD', 'reason': reason}

        # --- 定义趋势和穿越条件 ---
        is_uptrend = current_price > long_ema
        is_downtrend = current_price < long_ema
        # macd_crossed_above = macd > macd_signal_line and prev_macd <= prev_macd_signal_line # 旧
        # macd_crossed_below = macd < macd_signal_line and prev_macd >= prev_macd_signal_line # 旧
        hist_crossed_above_zero = macd_hist > 0 and prev_macd_hist <= 0
        hist_crossed_below_zero = macd_hist < 0 and prev_macd_hist >= 0

        # === 入场逻辑 ===
        if position is None:
            # 做多条件：Histogram 上穿零轴 + 价格高于 EMA
            if hist_crossed_above_zero and is_uptrend:
                signal = 'LONG'
                reason = f"MACD Hist 上穿零轴 ({macd_hist:.2f}), 趋势向上 (Price>{long_ema_period}EMA)"
            # 做空条件：Histogram 下穿零轴 + 价格低于 EMA
            elif hist_crossed_below_zero and is_downtrend:
                signal = 'SHORT'
                reason = f"MACD Hist 下穿零轴 ({macd_hist:.2f}), 趋势向下 (Price<{long_ema_period}EMA)"

        # === 出场逻辑 (保持不变) ===
        # 此策略版本不生成明确的平仓信号，完全依赖回测引擎的止损/止盈机制。
        # 如果需要基于信号平仓（例如 MACD 反向交叉），可以在这里添加。
        # elif position:
        #     if position['direction'] == 'LONG' and macd_crossed_below:
        #          signal = 'CLOSE_LONG'
        #          reason = f"MACD 下穿，平多仓"
        #     elif position['direction'] == 'SHORT' and macd_crossed_above:
        #          signal = 'CLOSE_SHORT'
        #          reason = f"MACD 上穿，平空仓"

    except KeyError as e:
        logger.error(f"策略函数 macd_ema_strategy(Histogram) 缺少必要数据列: {e}")
        reason = f"缺少数据列: {e}"
    except Exception as e:
        logger.error(f"策略函数 macd_ema_strategy(Histogram) 发生错误: {e}", exc_info=True)
        reason = f"策略计算错误: {e}"

    return {'signal': signal, 'reason': reason}


if __name__ == '__main__':
    # 更新测试部分以反映新策略
    print("5分钟策略模块已加载。包含策略函数：simple_sma_strategy, rsi_sma_strategy, macd_ema_strategy")
    # 示例数据 (需要 pandas)
    try:
        print("\n--- 测试 simple_sma_strategy ---")
        test_bar = pd.Series({'close': 105, 'sma': 100})
        test_position_none = None
        test_position_long = {'direction': 'LONG', 'entry_price': 98, 'size': 1}
        print("测试1: 无持仓, 价格 > SMA")
        print(simple_sma_strategy(test_bar, test_position_none))
        test_bar = pd.Series({'close': 95, 'sma': 100})
        print("测试2: 无持仓, 价格 < SMA")
        print(simple_sma_strategy(test_bar, test_position_none))
        print("测试3: 持有多仓, 价格 < SMA (平仓信号)")
        print(simple_sma_strategy(test_bar, test_position_long))

        print("\n--- 测试 rsi_sma_strategy ---")
        # 测试做多信号：上穿 SMA，RSI < 70
        test_bar_long = pd.Series({'close': 101, 'sma': 100, 'rsi': 65, 'prev_close': 99, 'prev_sma': 99.5})
        print("测试5: 无持仓, SMA 上穿, RSI 正常 -> 做多")
        print(rsi_sma_strategy(test_bar_long, None))

        # 测试不做多：上穿 SMA，但 RSI > 70
        test_bar_long_rsi_high = pd.Series({'close': 101, 'sma': 100, 'rsi': 75, 'prev_close': 99, 'prev_sma': 99.5})
        print("测试6: 无持仓, SMA 上穿, RSI 过高 -> 不做多")
        print(rsi_sma_strategy(test_bar_long_rsi_high, None))

        # 测试做空信号：下穿 SMA，RSI > 30
        test_bar_short = pd.Series({'close': 99, 'sma': 100, 'rsi': 35, 'prev_close': 101, 'prev_sma': 100.5})
        print("测试7: 无持仓, SMA 下穿, RSI 正常 -> 做空")
        print(rsi_sma_strategy(test_bar_short, None))

        # 测试不做空：下穿 SMA，但 RSI < 30
        test_bar_short_rsi_low = pd.Series({'close': 99, 'sma': 100, 'rsi': 25, 'prev_close': 101, 'prev_sma': 100.5})
        print("测试8: 无持仓, SMA 下穿, RSI 过低 -> 不做空")
        print(rsi_sma_strategy(test_bar_short_rsi_low, None))

        # 测试平多仓：持有 LONG，下穿 SMA
        position_long = {'direction': 'LONG', 'entry_price': 95, 'size': 1}
        print("测试9: 持有多仓, SMA 下穿 -> 平多仓")
        print(rsi_sma_strategy(test_bar_short, position_long))

        # 测试 macd_ema_strategy
        test_bar_macd = pd.Series({'close': 101, 'long_ema': 100, 'macd_hist': 1})
        print("测试10: 无持仓, MACD Hist 上穿零轴, 趋势向上")
        print(macd_ema_strategy(test_bar_macd, None))

        test_bar_macd_down = pd.Series({'close': 99, 'long_ema': 100, 'macd_hist': -1})
        print("测试11: 无持仓, MACD Hist 下穿零轴, 趋势向下")
        print(macd_ema_strategy(test_bar_macd_down, None))

    except ImportError:
        print("无法导入 pandas，无法执行示例测试。")
    except Exception as e:
        print(f"执行示例测试时出错: {e}") 