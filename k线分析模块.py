# -*- coding: utf-8 -*-
"""
K线分析模块

分析K线数据，侧重于价格行为、市场结构、K线形态、支撑/阻力位和波动率。
提供多时间周期协同分析。
"""

import logging
import pandas as pd
import numpy as np
import time
from typing import Dict, Any, List

# --- 导入依赖 ---
try:
    import 数据获取模块
    from 数据获取模块 import 获取K线数据, logger as data_logger
    import 配置
    # 尝试导入此模块的特定配置
    KLINE_ANALYSIS_CONFIG = getattr(配置, 'KLINE_ANALYSIS_CONFIG', {})
except ImportError as e:
    logging.critical(f"无法导入必要的模块或配置: {e}. 请确保 '数据获取模块.py' 和 '配置.py' 文件存在且路径正确。", exc_info=True)
    数据获取模块 = None
    获取K线数据 = None
    KLINE_ANALYSIS_CONFIG = {}
    data_logger = None

# --- 日志记录器配置 ---
if data_logger:
    logger = data_logger
    logger.info("K线分析模块 复用 数据获取模块 logger")
else:
    logger = logging.getLogger(__name__)
    if not logger.hasHandlers():
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.info("K线分析模块 创建了独立的 logger")

# --- 默认配置 ---
# 将 '3m' 加入默认分析的时间周期列表
DEFAULT_TIMEFRAMES = KLINE_ANALYSIS_CONFIG.get('timeframes', ['3m', '5m', '15m', '1h', '4h', '1d'])
DEFAULT_KLINE_LIMITS = KLINE_ANALYSIS_CONFIG.get('kline_limits', {
    'pattern_recognition': 10, # 形态识别所需K线数
    'volatility': 21,          # 波动率计算所需K线数 (e.g., BBands=20 + 1)
    'support_resistance': 2, # 枢轴点只需要前一根K线即可，所以需要2根数据
    # 'trend_structure': 50     # 趋势结构分析所需K线数 (MA, MACD等) - 现在基于 MA 周期决定
})
DEFAULT_BBANDS_PERIOD = KLINE_ANALYSIS_CONFIG.get('bbands_period', 20)
DEFAULT_BBANDS_STDDEV = KLINE_ANALYSIS_CONFIG.get('bbands_stddev', 2.0)
DEFAULT_ATR_PERIOD = KLINE_ANALYSIS_CONFIG.get('atr_period', 14)
# MA 双均线配置
DEFAULT_SHORT_MA_PERIOD = KLINE_ANALYSIS_CONFIG.get('short_ma_period', 10) # 短周期均线
DEFAULT_LONG_MA_PERIOD = KLINE_ANALYSIS_CONFIG.get('long_ma_period', 20) # 长周期均线 (原 DEFAULT_MA_PERIOD)
# DEFAULT_MA_PERIOD = KLINE_ANALYSIS_CONFIG.get('ma_period', 20) # 旧的单均线配置，保留注释或移除
DEFAULT_MACD_FAST = KLINE_ANALYSIS_CONFIG.get('macd_fast', 12)
DEFAULT_MACD_SLOW = KLINE_ANALYSIS_CONFIG.get('macd_slow', 26)
DEFAULT_MACD_SIGNAL = KLINE_ANALYSIS_CONFIG.get('macd_signal', 9)
DEFAULT_DMI_PERIOD = KLINE_ANALYSIS_CONFIG.get('dmi_period', 14) # 新增 DMI 周期配置

# --- 辅助函数 - 技术指标计算 (手动实现) ---

def calculate_moving_average(series: pd.Series, period: int) -> pd.Series:
    """计算简单移动平均线 (SMA)"""
    if not isinstance(series, pd.Series):
        raise TypeError("Input 'series' must be a pandas Series.")
    if not isinstance(period, int) or period <= 0:
        raise ValueError("'period' must be a positive integer.")
    if len(series) < period:
        logger.warning(f"Series length ({len(series)}) is less than MA period ({period}). Returning NaNs.")
        return pd.Series([np.nan] * len(series), index=series.index)
    return series.rolling(window=period, min_periods=period).mean() # Ensure min_periods=period

def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """计算指数移动平均线 (EMA)"""
    if not isinstance(series, pd.Series):
        raise TypeError("Input 'series' must be a pandas Series.")
    if not isinstance(period, int) or period <= 0:
        raise ValueError("'period' must be a positive integer.")
    # EMA can be calculated even if length < period, but result might be less meaningful
    return series.ewm(span=period, adjust=False, min_periods=period).mean() # Use min_periods for stability

def calculate_bollinger_bands(series: pd.Series, period: int = DEFAULT_BBANDS_PERIOD, std_dev: float = DEFAULT_BBANDS_STDDEV) -> pd.DataFrame:
    """计算布林带 (上轨, 中轨, 下轨)"""
    if len(series) < period:
        logger.warning(f"Series length ({len(series)}) is less than BBands period ({period}). Returning NaNs.")
        nan_series = pd.Series([np.nan] * len(series), index=series.index)
        return pd.DataFrame({'bb_upper': nan_series, 'bb_middle': nan_series, 'bb_lower': nan_series})

    middle_band = calculate_moving_average(series, period)
    rolling_std = series.rolling(window=period, min_periods=period).std() # Ensure min_periods
    upper_band = middle_band + (rolling_std * std_dev)
    lower_band = middle_band - (rolling_std * std_dev)
    return pd.DataFrame({'bb_upper': upper_band, 'bb_middle': middle_band, 'bb_lower': lower_band})

def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = DEFAULT_ATR_PERIOD) -> pd.Series:
    """计算平均真实波幅 (ATR)"""
    if not (isinstance(high, pd.Series) and isinstance(low, pd.Series) and isinstance(close, pd.Series)):
        raise TypeError("Inputs 'high', 'low', 'close' must be pandas Series.")
    if not (len(high) == len(low) == len(close)):
        raise ValueError("Input Series must have the same length.")
    if len(close) <= period: # Need at least period+1 for shift(1) and smoothing
        logger.warning(f"Series length ({len(close)}) is less than or equal to ATR period ({period}). Returning NaNs.")
        return pd.Series([np.nan] * len(close), index=close.index)

    high_low = high - low
    high_close = np.abs(high - close.shift(1))
    low_close = np.abs(low - close.shift(1))
    # Ensure columns exist before using .max()
    tr_df = pd.DataFrame({'h_l': high_low, 'h_pc': high_close, 'l_pc': low_close})
    tr = tr_df.max(axis=1)
    # Use EMA for smoothing ATR, common practice
    atr = tr.ewm(span=period, adjust=False, min_periods=period).mean() # Use min_periods
    return atr

def calculate_macd(close_series: pd.Series, 
                   fast_period: int = DEFAULT_MACD_FAST, 
                   slow_period: int = DEFAULT_MACD_SLOW, 
                   signal_period: int = DEFAULT_MACD_SIGNAL) -> pd.DataFrame:
    """计算MACD指标 (MACD线, 信号线, 直方图)"""
    min_len_needed = slow_period + signal_period -1 # Approximation for EMA stability
    if len(close_series) < min_len_needed:
         logger.warning(f"Series length ({len(close_series)}) is less than required for stable MACD ({min_len_needed}). Returning NaNs.")
         nan_series = pd.Series([np.nan] * len(close_series), index=close_series.index)
         return pd.DataFrame({'macd': nan_series, 'signal': nan_series, 'histogram': nan_series})

    ema_fast = calculate_ema(close_series, period=fast_period)
    ema_slow = calculate_ema(close_series, period=slow_period)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, period=signal_period)
    histogram = macd_line - signal_line
    return pd.DataFrame({'macd': macd_line, 'signal': signal_line, 'histogram': histogram})

def calculate_dmi(high: pd.Series, low: pd.Series, close: pd.Series, period: int = DEFAULT_DMI_PERIOD) -> pd.DataFrame:
    """计算 DMI 指标 (+DI, -DI, ADX)。

    使用 EMA 进行平滑处理，符合常见实现方式。
    Args:
        high (pd.Series): 最高价序列。
        low (pd.Series): 最低价序列。
        close (pd.Series): 收盘价序列。
        period (int): DMI 计算周期。

    Returns:
        pd.DataFrame: 包含 'plus_di', 'minus_di', 'adx' 列的 DataFrame。
                      如果数据不足或计算出错，则返回包含 NaN 的 DataFrame。
    """
    min_len_needed = period + 1 # For shift and initial calculations
    if not (isinstance(high, pd.Series) and isinstance(low, pd.Series) and isinstance(close, pd.Series)):
        raise TypeError("Inputs 'high', 'low', 'close' must be pandas Series.")
    if not (len(high) == len(low) == len(close)):
        raise ValueError("Input Series must have the same length.")
    if len(close) < min_len_needed:
        logger.warning(f"Series length ({len(close)}) is less than required for DMI ({min_len_needed}). Returning NaNs.")
        nan_series = pd.Series([np.nan] * len(close), index=close.index)
        return pd.DataFrame({'plus_di': nan_series, 'minus_di': nan_series, 'adx': nan_series})

    try:
        # 计算 TR (True Range)
        high_low = high - low
        high_close_prev = np.abs(high - close.shift(1))
        low_close_prev = np.abs(low - close.shift(1))
        tr = pd.DataFrame({'h_l': high_low, 'h_cp': high_close_prev, 'l_cp': low_close_prev}).max(axis=1)
        atr = calculate_ema(tr, period) # 使用 EMA 平滑 TR

        # 计算 方向移动 (+DM, -DM)
        move_up = high - high.shift(1)
        move_down = low.shift(1) - low
        plus_dm = pd.Series(np.where((move_up > move_down) & (move_up > 0), move_up, 0.0), index=high.index)
        minus_dm = pd.Series(np.where((move_down > move_up) & (move_down > 0), move_down, 0.0), index=low.index)

        # 平滑 +DM 和 -DM
        smooth_plus_dm = calculate_ema(plus_dm, period)
        smooth_minus_dm = calculate_ema(minus_dm, period)

        # 计算 +DI 和 -DI
        # 避免除以零
        atr_safe = atr.replace(0, np.nan)
        plus_di = (smooth_plus_dm / atr_safe) * 100
        minus_di = (smooth_minus_dm / atr_safe) * 100

        # 计算 DX (Directional Index)
        di_diff = np.abs(plus_di - minus_di)
        di_sum = plus_di + minus_di
        # 避免除以零
        di_sum_safe = di_sum.replace(0, np.nan)
        dx = (di_diff / di_sum_safe) * 100

        # 计算 ADX (Average Directional Index)
        adx = calculate_ema(dx, period)

        return pd.DataFrame({'plus_di': plus_di, 'minus_di': minus_di, 'adx': adx})

    except Exception as e:
        logger.error(f"计算 DMI 指标时出错: {e}", exc_info=True)
        nan_series = pd.Series([np.nan] * len(close), index=close.index)
        return pd.DataFrame({'plus_di': nan_series, 'minus_di': nan_series, 'adx': nan_series})

# --- 辅助函数 - 形态识别 ---

def _body_size(candle: pd.Series) -> float:
    """计算K线实体大小"""
    return abs(candle['open'] - candle['close'])

def _upper_shadow(candle: pd.Series) -> float:
    """计算上影线长度"""
    return candle['high'] - max(candle['open'], candle['close'])

def _lower_shadow(candle: pd.Series) -> float:
    """计算下影线长度"""
    return min(candle['open'], candle['close']) - candle['low']

def is_hammer_or_hanging_man(candle: pd.Series, body_threshold_factor: float = 0.3, shadow_ratio: float = 2.0) -> bool:
    """检查单根K线是否符合锤子线/上吊线的形态特征。
       判断是锤子还是上吊需要结合趋势。
    Args:
        candle (pd.Series): 单根K线数据 (需要 open, high, low, close).
        body_threshold_factor (float): 实体大小相对于整个K线幅度(high-low)的最大比例。
        shadow_ratio (float): 下影线长度相对于实体大小的最小比例。
    Returns:
        bool: 是否符合形态特征。
    """
    if not all(k in candle for k in ['open', 'high', 'low', 'close']): return False
    if pd.isna(candle[['open', 'high', 'low', 'close']]).any(): return False

    body = _body_size(candle)
    upper_shadow = _upper_shadow(candle)
    lower_shadow = _lower_shadow(candle)
    total_range = candle['high'] - candle['low']

    if total_range == 0: return False # 避免除零错误

    # 条件：实体很小，下影线很长，上影线很短（或没有）
    is_small_body = body <= total_range * body_threshold_factor
    is_long_lower_shadow = body > 0 and lower_shadow >= body * shadow_ratio # 实体不能为0
    is_short_upper_shadow = upper_shadow < body # 上影线比实体短

    return is_small_body and is_long_lower_shadow and is_short_upper_shadow

def is_bullish_engulfing(df_slice: pd.DataFrame) -> bool:
    """检查是否为看涨吞没形态 (基于最近两根K线)"""
    if len(df_slice) < 2: return False
    if not all(k in df_slice.columns for k in ['open', 'high', 'low', 'close']): return False
    if df_slice[['open', 'high', 'low', 'close']].iloc[-2:].isna().any().any(): return False

    prev = df_slice.iloc[-2]
    last = df_slice.iloc[-1]
    # 条件: 前阴后阳, 阳线实体完全包裹阴线实体
    return (prev['close'] < prev['open'] and
            last['close'] > last['open'] and
            last['open'] < prev['close'] and
            last['close'] > prev['open'])

def is_bearish_engulfing(df_slice: pd.DataFrame) -> bool:
    """检查是否为看跌吞没形态 (基于最近两根K线)"""
    if len(df_slice) < 2: return False
    if not all(k in df_slice.columns for k in ['open', 'high', 'low', 'close']): return False
    if df_slice[['open', 'high', 'low', 'close']].iloc[-2:].isna().any().any(): return False

    prev = df_slice.iloc[-2]
    last = df_slice.iloc[-1]
    # 条件: 前阳后阴, 阴线实体完全包裹阳线实体
    return (prev['close'] > prev['open'] and
            last['close'] < last['open'] and
            last['open'] > prev['close'] and
            last['close'] < prev['open'])

def is_piercing_pattern(df_slice: pd.DataFrame) -> bool:
    """检查是否为刺透形态 (看涨反转)"""
    if len(df_slice) < 2: return False
    if not all(k in df_slice.columns for k in ['open', 'high', 'low', 'close']): return False
    if df_slice[['open', 'high', 'low', 'close']].iloc[-2:].isna().any().any(): return False
    prev = df_slice.iloc[-2]
    last = df_slice.iloc[-1]

    # 条件: 前阴后阳
    if not (prev['close'] < prev['open'] and last['close'] > last['open']):
        return False
    # 条件: 阳线开盘低于前阴最低价 (书中通常低于收盘价即可)
    # if not (last['open'] < prev['low']):
    #     return False
    if not (last['open'] < prev['close']):
        return False
    # 条件: 阳线收盘高于前阴实体中点
    prev_body_mid = (prev['open'] + prev['close']) / 2
    if not (last['close'] > prev_body_mid):
        return False
    # 条件: 阳线收盘低于前阴开盘价 (与看涨吞没区分)
    if not (last['close'] < prev['open']):
        return False
    return True

def is_dark_cloud_cover(df_slice: pd.DataFrame) -> bool:
    """检查是否为乌云盖顶形态 (看跌反转)"""
    if len(df_slice) < 2: return False
    if not all(k in df_slice.columns for k in ['open', 'high', 'low', 'close']): return False
    if df_slice[['open', 'high', 'low', 'close']].iloc[-2:].isna().any().any(): return False
    prev = df_slice.iloc[-2]
    last = df_slice.iloc[-1]

    # 条件: 前阳后阴
    if not (prev['close'] > prev['open'] and last['close'] < last['open']):
        return False
    # 条件: 阴线开盘高于前阳最高价 (书中通常高于收盘价即可)
    # if not (last['open'] > prev['high']):
    #     return False
    if not (last['open'] > prev['close']):
        return False
    # 条件: 阴线收盘低于前阳实体中点
    prev_body_mid = (prev['open'] + prev['close']) / 2
    if not (last['close'] < prev_body_mid):
        return False
    # 条件: 阴线收盘高于前阳开盘价 (与看跌吞没区分)
    if not (last['close'] > prev['open']):
        return False
    return True

def is_doji(candle: pd.Series, body_threshold_percent: float = 0.05) -> bool:
    """检查单根K线是否为十字星 (实体极小)。"""
    if not all(k in candle for k in ['open', 'high', 'low', 'close']): return False
    if pd.isna(candle[['open', 'high', 'low', 'close']]).any(): return False

    body = _body_size(candle)
    total_range = candle['high'] - candle['low']

    if total_range == 0:
        return body == 0 # Four Price Doji

    is_tiny_body = body <= total_range * body_threshold_percent
    return is_tiny_body

def is_morning_star(df_slice: pd.DataFrame, small_body_factor: float = 0.3, penetration_factor: float = 0.5) -> bool:
    """检查是否为早晨之星形态 (看涨反转)"""
    if len(df_slice) < 3: return False
    if not all(k in df_slice.columns for k in ['open', 'high', 'low', 'close']): return False
    if df_slice[['open', 'high', 'low', 'close']].iloc[-3:].isna().any().any(): return False
    c1, c2, c3 = df_slice.iloc[-3], df_slice.iloc[-2], df_slice.iloc[-1]

    # 1. C1: 长阴线
    if not (c1['close'] < c1['open']): return False
    # 2. C2: 向下跳空的小实体 (可以是阴或阳)
    gap_down_body = max(c2['open'], c2['close']) < c1['close']
    c2_range = c2['high'] - c2['low']
    c2_body = _body_size(c2)
    is_c2_small_body = c2_range > 0 and (c2_body / c2_range) <= small_body_factor
    if not (gap_down_body and is_c2_small_body): return False
    # 3. C3: 长阳线，收盘价显著穿入第一根阴线实体内部
    if not (c3['close'] > c3['open']): return False
    penetration = c3['close'] > (c1['open'] + c1['close']) / 2 # 收盘高于C1实体中点
    # 并且 C3 实体较大 (可选)
    # c3_range = c3['high'] - c3['low']
    # c3_body = _body_size(c3)
    # is_c3_long = c3_range > 0 and (c3_body / c3_range) > 0.4
    if not penetration: return False
    return True

def is_evening_star(df_slice: pd.DataFrame, small_body_factor: float = 0.3, penetration_factor: float = 0.5) -> bool:
    """检查是否为黄昏之星形态 (看跌反转)"""
    if len(df_slice) < 3: return False
    if not all(k in df_slice.columns for k in ['open', 'high', 'low', 'close']): return False
    if df_slice[['open', 'high', 'low', 'close']].iloc[-3:].isna().any().any(): return False
    c1, c2, c3 = df_slice.iloc[-3], df_slice.iloc[-2], df_slice.iloc[-1]

    # 1. C1: 长阳线
    if not (c1['close'] > c1['open']): return False
    # 2. C2: 向上跳空的小实体
    gap_up_body = min(c2['open'], c2['close']) > c1['close']
    c2_range = c2['high'] - c2['low']
    c2_body = _body_size(c2)
    is_c2_small_body = c2_range > 0 and (c2_body / c2_range) <= small_body_factor
    if not (gap_up_body and is_c2_small_body): return False
    # 3. C3: 长阴线，收盘价显著穿入第一根阳线实体内部
    if not (c3['close'] < c3['open']): return False
    penetration = c3['close'] < (c1['open'] + c1['close']) / 2 # 收盘低于C1实体中点
    if not penetration: return False
    return True

def is_three_white_soldiers(df_slice: pd.DataFrame, min_body_factor: float = 0.6, shadow_limit_factor: float = 0.25) -> bool:
    """检查是否为三个白兵形态 (看涨持续)"""
    if len(df_slice) < 3: return False
    if not all(k in df_slice.columns for k in ['open', 'high', 'low', 'close']): return False
    if df_slice[['open', 'high', 'low', 'close']].iloc[-3:].isna().any().any(): return False
    c1, c2, c3 = df_slice.iloc[-3], df_slice.iloc[-2], df_slice.iloc[-1]

    # 都是阳线
    if not (c1['close'] > c1['open'] and c2['close'] > c2['open'] and c3['close'] > c3['open']):
        return False
    # 实体逐渐变大或差不多大，且实体占比高
    body1, body2, body3 = _body_size(c1), _body_size(c2), _body_size(c3)
    range1, range2, range3 = c1['high']-c1['low'], c2['high']-c2['low'], c3['high']-c3['low']
    if not (range1 > 0 and range2 > 0 and range3 > 0): return False # K线需要有波动
    if not ((body1/range1 > min_body_factor) and (body2/range2 > min_body_factor) and (body3/range3 > min_body_factor)):
        return False
    # 依次创新高 (收盘价和开盘价)
    if not (c2['open'] > c1['open'] and c2['close'] > c1['close'] and
            c3['open'] > c2['open'] and c3['close'] > c2['close']):
        return False
    # 开盘价在前一根实体内
    if not (c2['open'] < c1['close'] and c3['open'] < c2['close']):
         return False
    # 上影线很短
    shadow2_upper = _upper_shadow(c2)
    shadow3_upper = _upper_shadow(c3)
    if not (shadow2_upper / range2 < shadow_limit_factor and shadow3_upper / range3 < shadow_limit_factor):
         return False
    return True

def is_three_black_crows(df_slice: pd.DataFrame, min_body_factor: float = 0.6, shadow_limit_factor: float = 0.25) -> bool:
    """检查是否为三只乌鸦形态 (看跌持续)"""
    if len(df_slice) < 3: return False
    if not all(k in df_slice.columns for k in ['open', 'high', 'low', 'close']): return False
    if df_slice[['open', 'high', 'low', 'close']].iloc[-3:].isna().any().any(): return False
    c1, c2, c3 = df_slice.iloc[-3], df_slice.iloc[-2], df_slice.iloc[-1]

    # 都是阴线
    if not (c1['close'] < c1['open'] and c2['close'] < c2['open'] and c3['close'] < c3['open']):
        return False
    # 实体逐渐变大或差不多大，且实体占比高
    body1, body2, body3 = _body_size(c1), _body_size(c2), _body_size(c3)
    range1, range2, range3 = c1['high']-c1['low'], c2['high']-c2['low'], c3['high']-c3['low']
    if not (range1 > 0 and range2 > 0 and range3 > 0): return False
    if not ((body1/range1 > min_body_factor) and (body2/range2 > min_body_factor) and (body3/range3 > min_body_factor)):
        return False
    # 依次创新低 (收盘价和开盘价)
    if not (c2['open'] < c1['open'] and c2['close'] < c1['close'] and
            c3['open'] < c2['open'] and c3['close'] < c2['close']):
        return False
    # 开盘价在前一根实体内
    if not (c2['open'] > c1['close'] and c3['open'] > c2['close']):
         return False
    # 下影线很短
    shadow2_lower = _lower_shadow(c2)
    shadow3_lower = _lower_shadow(c3)
    if not (shadow2_lower / range2 < shadow_limit_factor and shadow3_lower / range3 < shadow_limit_factor):
         return False
    return True

def is_spinning_top(candle: pd.Series, body_ratio_threshold: float = 0.1, shadow_ratio_threshold: float = 0.3) -> bool:
    """检查是否为纺锤线 (实体小，上下影线长)"""
    if not all(k in candle for k in ['open', 'high', 'low', 'close']): return False
    if pd.isna(candle[['open', 'high', 'low', 'close']]).any(): return False

    body = _body_size(candle)
    total_range = candle['high'] - candle['low']
    if total_range == 0: return False

    upper_shadow = _upper_shadow(candle)
    lower_shadow = _lower_shadow(candle)

    is_small_body = body <= total_range * body_ratio_threshold
    are_shadows_long = upper_shadow >= total_range * shadow_ratio_threshold and \
                       lower_shadow >= total_range * shadow_ratio_threshold
    return is_small_body and are_shadows_long

def is_harami(df_slice: pd.DataFrame) -> Dict[str, str] | None:
    """检查是否为孕线形态 (反转或持续信号减弱)"""
    if len(df_slice) < 2: return None
    if not all(k in df_slice.columns for k in ['open', 'high', 'low', 'close']): return None
    if df_slice[['open', 'high', 'low', 'close']].iloc[-2:].isna().any().any(): return None
    c1, c2 = df_slice.iloc[-2], df_slice.iloc[-1]

    # C2 的实体必须完全被 C1 的实体包含
    c1_body_top = max(c1['open'], c1['close'])
    c1_body_bottom = min(c1['open'], c1['close'])
    c2_body_top = max(c2['open'], c2['close'])
    c2_body_bottom = min(c2['open'], c2['close'])

    if not (c2_body_top < c1_body_top and c2_body_bottom > c1_body_bottom):
        return None

    # 判断看涨孕线还是看跌孕线
    if c1['close'] < c1['open']: # C1 是阴线 -> 看涨孕线?
        # 加上 C2 是阳线 或 十字星 条件会更强
        if c2['close'] > c2['open'] or is_doji(c2):
            return {'name': '看涨孕线', 'implication': '看涨反转/看跌减弱'}
    elif c1['close'] > c1['open']: # C1 是阳线 -> 看跌孕线?
        # 加上 C2 是阴线 或 十字星 条件会更强
        if c2['close'] < c2['open'] or is_doji(c2):
            return {'name': '看跌孕线', 'implication': '看跌反转/看涨减弱'}

    return {'name': '孕线', 'implication': '犹豫/潜在反转'} # 如果颜色不匹配，只是一般孕线

def is_tweezer(df_slice: pd.DataFrame, tolerance_factor: float = 0.001) -> Dict[str, str] | None:
    """检查是否为镊子顶/底形态。"""
    if len(df_slice) < 2: return None
    if not all(k in df_slice.columns for k in ['open', 'high', 'low', 'close']): return None
    if df_slice[['open', 'high', 'low', 'close']].iloc[-2:].isna().any().any(): return None
    c1, c2 = df_slice.iloc[-2], df_slice.iloc[-1]

    avg_price = (c1['close'] + c2['close']) / 2
    tolerance = avg_price * tolerance_factor

    # 镊子顶: 两根K线最高价几乎相等
    if abs(c1['high'] - c2['high']) <= tolerance:
        # 通常出现在上升趋势后，C1阳 C2阴 更典型
        if c1['close'] > c1['open'] and c2['close'] < c2['open']:
             return {'name': '镊子顶', 'implication': '看跌反转'}
        else: # 其他颜色组合也可能出现
             return {'name': '镊子顶(变体)', 'implication': '潜在看跌反转'}

    # 镊子底: 两根K线最低价几乎相等
    if abs(c1['low'] - c2['low']) <= tolerance:
        # 通常出现在下降趋势后，C1阴 C2阳 更典型
        if c1['close'] < c1['open'] and c2['close'] > c2['open']:
            return {'name': '镊子底', 'implication': '看涨反转'}
        else: # 其他颜色组合也可能出现
            return {'name': '镊子底(变体)', 'implication': '潜在看涨反转'}

    return None

def is_marubozu(candle: pd.Series, tolerance_factor: float = 0.01) -> Dict[str, str] | None:
    """检查是否为光头光脚 K 线 (Marubozu)。"""
    if not all(k in candle for k in ['open', 'high', 'low', 'close']): return None
    if pd.isna(candle[['open', 'high', 'low', 'close']]).any(): return None

    total_range = candle['high'] - candle['low']
    if total_range == 0: return None # 无法判断

    tolerance = total_range * tolerance_factor

    is_white = candle['close'] > candle['open']
    is_black = candle['close'] < candle['open']

    # 白色 Marubozu (光头光脚阳线)
    if is_white and abs(candle['high'] - candle['close']) <= tolerance and abs(candle['low'] - candle['open']) <= tolerance:
        return {'name': '光头光脚阳线', 'implication': '看涨持续/开始'}
    # 黑色 Marubozu (光头光脚阴线)
    if is_black and abs(candle['high'] - candle['open']) <= tolerance and abs(candle['low'] - candle['close']) <= tolerance:
        return {'name': '光头光脚阴线', 'implication': '看跌持续/开始'}
    # 开盘 Marubozu (光脚阳线 / 光头阴线)
    if is_white and abs(candle['low'] - candle['open']) <= tolerance and abs(candle['high'] - candle['close']) > tolerance:
         return {'name': '光脚阳线', 'implication': '看涨'}
    if is_black and abs(candle['high'] - candle['open']) <= tolerance and abs(candle['low'] - candle['close']) > tolerance:
         return {'name': '光头阴线', 'implication': '看跌'}
    # 收盘 Marubozu (光头阳线 / 光脚阴线)
    if is_white and abs(candle['high'] - candle['close']) <= tolerance and abs(candle['low'] - candle['open']) > tolerance:
         return {'name': '光头阳线', 'implication': '看涨'}
    if is_black and abs(candle['low'] - candle['close']) <= tolerance and abs(candle['high'] - candle['open']) > tolerance:
         return {'name': '光脚阴线', 'implication': '看跌'}
    
    return None

# --- 辅助函数 - 支撑/阻力 (枢轴点) ---

def calculate_standard_pivot_points(high: float, low: float, close: float) -> Dict[str, Any]:
    """计算标准枢轴点和支撑/阻力位。"""
    # 检查输入是否包含 NaN
    if pd.isna(high) or pd.isna(low) or pd.isna(close):
        return {'error': 'HLC data contains NaN'}

    # --- 修正：将计算逻辑移出 if 块 --- 
    pp = (high + low + close) / 3
    r1 = (2 * pp) - low
    s1 = (2 * pp) - high
    r2 = pp + (high - low)
    s2 = pp - (high - low)
    r3 = high + 2 * (pp - low)
    s3 = low - 2 * (high - pp)
    # --- 修正结束 ---

    return {
        'PP': pp,
        'R1': r1, 'S1': s1,
        'R2': r2, 'S2': s2,
        'R3': r3, 'S3': s3
    }


# --- 辅助函数 - MA 趋势分析 ---

def _analyze_ma_trend(close_series: pd.Series,
                      short_period: int = DEFAULT_SHORT_MA_PERIOD,
                      long_period: int = DEFAULT_LONG_MA_PERIOD) -> str:
    """分析双均线趋势，检测金叉/死叉，并提供状态描述。"""
    required_length = max(short_period, long_period) + 1
    if len(close_series) < required_length:
        return "数据不足"

    try:
        short_ma = calculate_moving_average(close_series, short_period)
        long_ma = calculate_moving_average(close_series, long_period)

        # 获取最后两个有效值
        valid_short_ma = short_ma.dropna()
        valid_long_ma = long_ma.dropna()

        if len(valid_short_ma) < 2 or len(valid_long_ma) < 2:
            return "MA计算值不足"

        short_ma_last = valid_short_ma.iloc[-1]
        short_ma_prev = valid_short_ma.iloc[-2]
        long_ma_last = valid_long_ma.iloc[-1]
        long_ma_prev = valid_long_ma.iloc[-2]

        # 检测交叉
        crossed_up = short_ma_prev <= long_ma_prev and short_ma_last > long_ma_last
        crossed_down = short_ma_prev >= long_ma_prev and short_ma_last < long_ma_last

        if crossed_up:
            return f"金叉({short_period}/{long_period}) - 看涨 (注意假突破)"
        elif crossed_down:
            return f"死叉({short_period}/{long_period}) - 看跌 (注意假突破)"
        elif short_ma_last > long_ma_last:
            return f"上行趋势 ({short_period}MA > {long_period}MA)"
        elif short_ma_last < long_ma_last:
            return f"下行趋势 ({short_period}MA < {long_period}MA)"
        else:
            return f"MA 粘合 ({short_period}/{long_period})"

    except Exception as e:
        logger.error(f"计算或分析 MA 趋势时出错: {e}", exc_info=True)
        return "分析 MA 趋势出错"

# --- 辅助函数 - 多周期协同分析 ---

def _generate_confluence_summary(timeframe_analysis: Dict[str, Dict]) -> Dict[str, Any]:
    """根据各时间周期的分析结果，生成多周期协同分析总结。"""
    logger.info("--- [Confluence] 开始生成总结 ---")
    summary = {
        "bias": "无法判断",
        "confidence": "低",
        "weighted_score": "N/A", # 使用 N/A 作为分数默认值
        "max_possible_weight": "N/A", # 使用 N/A 作为最大权重默认值
        "reasoning": [],
        "warnings": [],
        "key_signals": {},
        "error": None
    }

    valid_tf_count = 0
    valid_tf_results = {}
    logger.debug("[Confluence] 筛选有效时间周期...")
    for tf, result in timeframe_analysis.items():
        # 检查顶层错误和 None
        if result and isinstance(result, dict) and not result.get("error"):
            ma_trend = result.get('trend_ma')
            macd_info = result.get('trend_macd', {})
            # MA 有效性检查
            is_ma_valid = isinstance(ma_trend, str) and ma_trend not in ['未分析', '数据不足'] and not ma_trend.startswith('错误')
            # MACD 有效性检查 (更严格，需要 status)
            is_macd_valid = isinstance(macd_info, dict) and not macd_info.get('error') and macd_info.get('status') not in ['未分析', 'N/A', '未知', '数据不足'] and not str(macd_info.get('status', '')).startswith('错误')

            if is_ma_valid or is_macd_valid:
                valid_tf_count += 1
                valid_tf_results[tf] = result
                logger.debug(f"  - [Confluence] 时间周期 {tf} 有效 (MA:{is_ma_valid}, MACD:{is_macd_valid})。")
            else:
                logger.warning(f"  - [Confluence] 时间周期 {tf} 无效。MA: {ma_trend}, MACD Status: {macd_info.get('status')}")
        else:
            error_msg = result.get("error", "未知错误") if isinstance(result, dict) else ("结果为空" if result is None else "结果格式错误")
            logger.warning(f"  - [Confluence] 时间周期 {tf} 因错误或无效结果跳过: {error_msg}")
    logger.debug(f"[Confluence] 有效时间周期数量: {valid_tf_count}")

    if valid_tf_count == 0:
        summary["error"] = "所有时间周期的分析结果均无效或缺失，无法进行协同分析。"
        logger.error(f"[Confluence] 无法生成总结: {summary['error']}")
        logger.info("--- [Confluence] 总结结束 (无有效周期) ---")
        return summary
    elif valid_tf_count < len(timeframe_analysis) * 0.5:
        warn_msg = f"只有 {valid_tf_count} 个时间周期的结果有效，协同分析的可靠性可能较低。"
        summary["warnings"].append(warn_msg)
        logger.warning(f"[Confluence] {warn_msg}")

    logger.debug("[Confluence] 开始评分计算和偏向判断...")
    try:
        # --- 1. 初始化评分变量 ---
        timeframe_order = sorted(valid_tf_results.keys(), key=lambda tf: {'m': 1, 'h': 60, 'd': 1440, 'w': 10080, 'M': 43200}.get(tf[-1], 0) * int(tf[:-1]))
        base_weight = 1.0
        weights = {tf: base_weight * (1 + i * 0.1) for i, tf in enumerate(timeframe_order)}
        logger.debug(f"[Confluence] 周期权重: {weights}")

        total_score = 0.0
        max_score = 0.0 # !! 必须为 0.0 初始值
        bullish_signals_weighted = 0.0
        bearish_signals_weighted = 0.0
        neutral_signals_weighted = 0.0

        pattern_signal_strength = 0.5 # 形态信号强度
        ma_signal_strength = 1.0    # MA 信号强度
        macd_signal_strength = 1.0   # MACD 信号强度

        # --- 2. 遍历有效周期计算分数 ---
        for tf, result in valid_tf_results.items():
            weight = weights[tf]
            tf_score = 0.0
            tf_max_score = 0.0 # 本周期的最大分数贡献
            logger.debug(f"-- [Confluence] 处理周期 {tf} (权重 {weight:.2f}) --")

            # 提取关键信号
            key_signals_tf = {
                'ma': result.get('trend_ma', 'N/A'),
                'macd_status': result.get('trend_macd', {}).get('status', 'N/A') if isinstance(result.get('trend_macd'), dict) else 'N/A',
                'patterns': result.get('patterns', [])
            }
            summary["key_signals"][tf] = key_signals_tf
            logger.debug(f"  [Confluence] 提取信号: MA='{key_signals_tf['ma']}', MACD='{key_signals_tf['macd_status']}', Patterns={key_signals_tf['patterns']}")

            # MA 趋势评分
            ma_trend = key_signals_tf['ma']
            ma_point = 0.0
            ma_is_directional = False
            if isinstance(ma_trend, str):
                if "金叉" in ma_trend or "上行趋势" in ma_trend:
                    ma_point = ma_signal_strength
                    bullish_signals_weighted += weight * ma_signal_strength
                    summary["reasoning"].append(f"{tf}: MA 趋势看涨 ({ma_trend})。")
                    ma_is_directional = True
                elif "死叉" in ma_trend or "下行趋势" in ma_trend:
                    ma_point = -ma_signal_strength
                    bearish_signals_weighted += weight * ma_signal_strength
                    summary["reasoning"].append(f"{tf}: MA 趋势看跌 ({ma_trend})。")
                    ma_is_directional = True
                elif "粘合" in ma_trend:
                    neutral_signals_weighted += weight * 0.5
                    summary["reasoning"].append(f"{tf}: MA 趋势粘合。")
                elif ma_trend not in ["数据不足", "未分析", "N/A"] and not ma_trend.startswith("错误"):
                    neutral_signals_weighted += weight * 0.1 # 其他非错误状态贡献少量中性权重

            tf_score += ma_point * weight
            if ma_is_directional: # 只有方向性信号才增加 max_score
                tf_max_score += ma_signal_strength * weight
            logger.debug(f"  [Confluence] MA 得分贡献: {ma_point * weight:.2f}, 本周期 MaxScore 增加: {ma_signal_strength * weight if ma_is_directional else 0.0:.2f}")

            # MACD 方向评分
            macd_status = key_signals_tf['macd_status']
            macd_point = 0.0
            macd_is_directional = False
            if isinstance(macd_status, str):
                if "看涨" in macd_status or "多头占优" in macd_status:
                    macd_point = macd_signal_strength
                    bullish_signals_weighted += weight * macd_signal_strength
                    summary["reasoning"].append(f"{tf}: MACD 指示看涨 ({macd_status})。")
                    macd_is_directional = True
                elif "看跌" in macd_status or "空头占优" in macd_status:
                    macd_point = -macd_signal_strength
                    bearish_signals_weighted += weight * macd_signal_strength
                    summary["reasoning"].append(f"{tf}: MACD 指示看跌 ({macd_status})。")
                    macd_is_directional = True
                elif macd_status == "未知": # 明确处理"未知"
                    neutral_signals_weighted += weight * 0.5
                    summary["reasoning"].append(f"{tf}: MACD 状态未知。")
                elif macd_status not in ["数据不足", "未分析", "N/A"] and not macd_status.startswith("错误"):
                    neutral_signals_weighted += weight * 0.1 # 其他非错误状态

            tf_score += macd_point * weight
            if macd_is_directional:
                tf_max_score += macd_signal_strength * weight
            logger.debug(f"  [Confluence] MACD 得分贡献: {macd_point * weight:.2f}, 本周期 MaxScore 增加: {macd_signal_strength * weight if macd_is_directional else 0.0:.2f}")

            # 形态评分
            patterns = key_signals_tf['patterns']
            pattern_point = 0.0
            pattern_is_directional = False
            if patterns and isinstance(patterns, list) and len(patterns) > 0:
                for pattern in patterns:
                    if not isinstance(pattern, dict): continue
                    impl = pattern.get('implication', '')
                    p_name = pattern.get('name', '?')
                    if p_name in ["数据不足", "计算失败", "错误", "未知"]: continue

                    if "看涨" in impl:
                        pattern_point = pattern_signal_strength
                        bullish_signals_weighted += weight * pattern_signal_strength
                        summary["reasoning"].append(f"{tf}: 出现看涨形态 '{p_name}'。")
                        pattern_is_directional = True; break # 找到第一个看涨就停止
                    elif "看跌" in impl:
                        pattern_point = -pattern_signal_strength
                        bearish_signals_weighted += weight * pattern_signal_strength
                        summary["reasoning"].append(f"{tf}: 出现看跌形态 '{p_name}'。")
                        pattern_is_directional = True; break # 找到第一个看跌就停止
                    elif "犹豫" in impl or "不确定" in impl or "减弱" in impl:
                        neutral_signals_weighted += weight * 0.5
                        summary["reasoning"].append(f"{tf}: 出现犹豫/减弱形态 '{p_name}'。")
                        break # 找到第一个犹豫/中性也停止

            if pattern_point != 0.0 or "出现犹豫" in summary["reasoning"][-1] if summary["reasoning"] else False: # 如果有得分或添加了犹豫理由
                tf_score += pattern_point * weight
                if pattern_is_directional:
                    tf_max_score += pattern_signal_strength * weight
                logger.debug(f"  [Confluence] 形态得分贡献: {pattern_point * weight:.2f}, 本周期 MaxScore 增加: {pattern_signal_strength * weight if pattern_is_directional else 0.0:.2f}")
            else:
                 logger.debug(f"  [Confluence] 形态无明确信号或得分。")


            logger.debug(f"周期 {tf} 总分: {tf_score:.2f}, 本周期最大得分贡献: {tf_max_score:.2f}")
            total_score += tf_score
            max_score += tf_max_score # 累加本周期的最大得分贡献

        # --- 3. 更新最终分数 ---
        # 只有在 max_score 大于 0 时才设置数值，否则保持 N/A
        if max_score > 0:
            summary["weighted_score"] = round(total_score, 2)
            summary["max_possible_weight"] = round(max_score, 2)
            score_ratio = total_score / max_score
            logger.info(f"[Confluence] 总得分: {total_score:.2f}, 最大可能得分: {max_score:.2f}, 得分率: {score_ratio:.3f}")
        else:
            # 如果 max_score 仍然是 0，说明没有任何方向性信号
            summary["weighted_score"] = 0.0 # 可以设为 0
            summary["max_possible_weight"] = 0.0 # 可以设为 0
            score_ratio = 0.0 # 得分率也为 0
            logger.info(f"[Confluence] 总得分: {total_score:.2f}, 最大可能得分: {max_score:.2f} (无方向性信号)")


        # --- 4. 判断整体偏向和置信度 ---
        logger.debug("[Confluence] 开始判断整体偏向和置信度...")
        # 只有在 max_score > 0 时才根据 score_ratio 判断
        if max_score > 0:
            bullish_threshold = KLINE_ANALYSIS_CONFIG.get('confluence_bullish_threshold', 0.4)
            bearish_threshold = KLINE_ANALYSIS_CONFIG.get('confluence_bearish_threshold', -0.4)
            strong_bullish_threshold = KLINE_ANALYSIS_CONFIG.get('confluence_strong_bullish_threshold', 0.7)
            strong_bearish_threshold = KLINE_ANALYSIS_CONFIG.get('confluence_strong_bearish_threshold', -0.7)
            neutral_max_ratio = KLINE_ANALYSIS_CONFIG.get('confluence_neutral_max_ratio', 0.15)

            logger.debug(f"[Confluence] 判断阈值: 看涨>{bullish_threshold}, 看跌<{bearish_threshold}, 强看涨>{strong_bullish_threshold}, 强看跌<{strong_bearish_threshold}, 中性绝对值<={neutral_max_ratio}")

            if score_ratio > bullish_threshold:
                summary["bias"] = "看涨"
                summary["confidence"] = "高" if score_ratio > strong_bullish_threshold else "中"
            elif score_ratio < bearish_threshold:
                summary["bias"] = "看跌"
                summary["confidence"] = "高" if score_ratio < strong_bearish_threshold else "中"
            # 修改中性判断: 如果绝对得分率低，并且中性信号权重显著大于方向信号权重
            elif abs(score_ratio) <= neutral_max_ratio and neutral_signals_weighted > (bullish_signals_weighted + bearish_signals_weighted):
                summary["bias"] = "震荡/方向不明"
                summary["confidence"] = "中"
            else: # 其他情况（得分不高不低，或方向信号主导但不足以触发明确偏向）
                summary["bias"] = "中性/谨慎"
                summary["confidence"] = "低" # 默认是低，除非明确满足其他条件
            logger.debug(f"[Confluence] 根据 score_ratio ({score_ratio:.3f}) 和信号权重判断: Bias='{summary['bias']}', Confidence='{summary['confidence']}'")
        else:
            # 如果 max_score 为 0，检查是否有中性信号
            if neutral_signals_weighted > 0:
                summary["bias"] = "震荡/方向不明"
                summary["confidence"] = "中"
                logger.debug("[Confluence] Max Score 为 0，但有中性信号，判断为震荡/方向不明。")
            else:
                # 如果连中性信号都没有，保持默认的"无法判断"和"低"
                logger.debug("[Confluence] Max Score 为 0，且无中性信号，保持默认判断。")


        # --- 5. 增加冲突警告 ---
        logger.debug("[Confluence] 检查信号冲突...")
        total_directional_weighted = bullish_signals_weighted + bearish_signals_weighted
        if total_directional_weighted > 0:
             conflict_ratio = min(bullish_signals_weighted, bearish_signals_weighted) / total_directional_weighted
             logger.debug(f"[Confluence] 冲突率计算: min({bullish_signals_weighted:.2f}, {bearish_signals_weighted:.2f}) / {total_directional_weighted:.2f} = {conflict_ratio:.3f}")

             significant_conflict_threshold = KLINE_ANALYSIS_CONFIG.get('confluence_significant_conflict_threshold', 0.3)
             minor_conflict_threshold = KLINE_ANALYSIS_CONFIG.get('confluence_minor_conflict_threshold', 0.15)

             if conflict_ratio > significant_conflict_threshold:
                 conflict_level = "显著"
                 warn_msg = f"各周期信号存在 {conflict_level} 冲突 (看涨权重: {bullish_signals_weighted:.1f}, 看跌权重: {bearish_signals_weighted:.1f})。"
                 summary["warnings"].append(warn_msg)
                 logger.warning(f"[Confluence] {warn_msg}")
                 # 显著冲突降低置信度
                 if summary["confidence"] == "高": summary["confidence"] = "中"
                 elif summary["confidence"] == "中": summary["confidence"] = "低"
             elif conflict_ratio > minor_conflict_threshold:
                 conflict_level = "轻微"
                 warn_msg = f"各周期信号存在 {conflict_level} 冲突 (看涨权重: {bullish_signals_weighted:.1f}, 看跌权重: {bearish_signals_weighted:.1f})。"
                 summary["warnings"].append(warn_msg)
                 logger.warning(f"[Confluence] {warn_msg}")
                 # 轻微冲突也降低置信度
                 if summary["confidence"] == "高": summary["confidence"] = "中"
        else:
            logger.debug("[Confluence] 无方向性信号，跳过冲突检查。")

    # --- 捕获计算或判断过程中的任何异常 ---
    except Exception as summary_calc_e:
        error_msg = f"生成总结的评分或判断过程中出错: {type(summary_calc_e).__name__} - {summary_calc_e}"
        summary["error"] = error_msg
        summary["bias"] = "计算错误" # 覆盖默认值
        summary["confidence"] = "错误" # 覆盖默认值
        summary["weighted_score"] = "Error" # 覆盖默认值
        summary["max_possible_weight"] = "Error" # 覆盖默认值
        logger.exception(f"[Confluence] {error_msg}") # 使用 logger.exception 记录完整堆栈

    # 确保分数/权重在出错时显示为 Error
    if summary["error"]:
        summary["weighted_score"] = "Error" if summary["weighted_score"] == "N/A" else summary["weighted_score"]
        summary["max_possible_weight"] = "Error" if summary["max_possible_weight"] == "N/A" else summary["max_possible_weight"]


    # 打印最终总结信息，包括错误状态
    logger.info(f"--- [Confluence] 总结结束: Bias={summary['bias']}, Conf={summary['confidence']}, Score={summary['weighted_score']}/{summary['max_possible_weight']}, Error='{summary['error']}' ---")
    return summary

# --- 主分析函数 ---
def 分析K线结构与形态(symbol: str,
                       market_type: str = 'spot',
                       timeframes: List[str] = DEFAULT_TIMEFRAMES,
                       kline_limits: Dict[str, int] = None
                       ) -> tuple[Dict[str, Any], Dict[str, pd.DataFrame]]:
    """主分析函数。
    (参数和返回说明不变)
    """
    start_time_analysis = time.time()
    if not 获取K线数据:
        logger.error("核心依赖 '数据获取模块' 未加载，无法执行分析。")
        # 返回错误信息和空数据字典
        return {
            "symbol": symbol,
            "market_type": market_type,
            "analysis_time": pd.Timestamp.utcnow(),
            "timeframe_analysis": {},
            "fetched_data_info": {},
            "confluence_summary": {"error": "依赖模块加载失败"},
            "error": "依赖模块加载失败",
            "analysis_duration_seconds": 0
        }, {}

    analysis_results = {
        "symbol": symbol,
        "market_type": market_type,
        "analysis_time": pd.Timestamp.utcnow(),
        "timeframe_analysis": {},
        "fetched_data_info": {},
        "confluence_summary": {},
        "error": None,
        "analysis_duration_seconds": 0 # 初始化 duration
    }
    fetched_kline_data = {}

    # 动态计算所需的K线数量 (加入 DMI 需求)
    try:
        if kline_limits is None:
            ma_kline_needed = max(DEFAULT_SHORT_MA_PERIOD, DEFAULT_LONG_MA_PERIOD) + 1
            volatility_kline_needed = DEFAULT_BBANDS_PERIOD + 1
            atr_kline_needed = DEFAULT_ATR_PERIOD + 1
            macd_kline_needed = DEFAULT_MACD_SLOW + DEFAULT_MACD_SIGNAL + 1
            dmi_kline_needed = DEFAULT_DMI_PERIOD * 2 + 1 # DMI 需要更多历史来平滑 DX->ADX
            pattern_kline_needed = 5
            pivot_kline_needed = 2
            max_limit_needed = max(ma_kline_needed, volatility_kline_needed, atr_kline_needed,
                                   macd_kline_needed, dmi_kline_needed, # 加入 DMI
                                   pattern_kline_needed, pivot_kline_needed) + 10
            # 使用计算出的 limit 来构建 kline_limits 字典
            kline_limits = {
                 'pattern_recognition': pattern_kline_needed,
                 'volatility': volatility_kline_needed,
                 'support_resistance': pivot_kline_needed,
                 'trend_ma': ma_kline_needed,
                 'trend_macd': macd_kline_needed,
                 'trend_dmi': dmi_kline_needed # 新增 DMI limit key
            }
            logger.info(f"动态计算得出最大需要获取 {max_limit_needed} 条 K 线数据。")
        else:
            # Validate and supplement provided kline_limits
            max_limit_needed = 10 # Initialize with a small value
            required_keys = ['pattern_recognition', 'volatility', 'support_resistance', 'trend_ma', 'trend_macd', 'trend_dmi'] # 加入 DMI
            default_values = {
                 'pattern_recognition': 5,
                 'volatility': DEFAULT_BBANDS_PERIOD + 1,
                 'support_resistance': 2,
                 'trend_ma': max(DEFAULT_SHORT_MA_PERIOD, DEFAULT_LONG_MA_PERIOD) + 1,
                 'trend_macd': DEFAULT_MACD_SLOW + DEFAULT_MACD_SIGNAL + 1,
                 'trend_dmi': DEFAULT_DMI_PERIOD * 2 + 1 # 加入 DMI 默认
            }
            for key in required_keys:
                 if key not in kline_limits or not isinstance(kline_limits[key], int) or kline_limits[key] <= 0:
                      logger.warning(f"传入的 kline_limits 中 '{key}' 无效或缺失，已补充默认值 {default_values[key]}")
                      kline_limits[key] = default_values[key]
                 # Ensure max_limit_needed includes buffer
                 max_limit_needed = max(max_limit_needed, kline_limits[key] + 10)
            logger.info(f"使用外部传入的 kline_limits，最大需要获取 {max_limit_needed} 条 K 线数据。")
    except Exception as limit_calc_e:
        logger.exception("计算所需 K 线数量时出错，将使用保守默认值 100。")
        max_limit_needed = 100
        # Use default kline_limits if calculation failed
        kline_limits = {
            'pattern_recognition': 5,
            'volatility': DEFAULT_BBANDS_PERIOD + 1,
            'support_resistance': 2,
            'trend_ma': max(DEFAULT_SHORT_MA_PERIOD, DEFAULT_LONG_MA_PERIOD) + 1,
            'trend_macd': DEFAULT_MACD_SLOW + DEFAULT_MACD_SIGNAL + 1,
            'trend_dmi': DEFAULT_DMI_PERIOD * 2 + 1 # 加入 DMI
        }

    # 循环分析每个时间周期
    for tf in timeframes:
        tf_start_time = time.time()
        logger.info(f"开始分析时间周期: {tf}")
        tf_result = {
            "kline_count": 0,
            "patterns": [],
            "volatility": {"error": "未分析"},
            "pivot_point": "未分析",
            "support_levels": ["未分析"] * 3, # Initialize with correct length
            "resistance_levels": ["未分析"] * 3, # Initialize with correct length
            "trend_ma": "未分析",
            "trend_macd": {"error": "未分析"},
            "trend_dmi": {"error": "未分析"}, # 新增 DMI 结果字典
            "error": None
        }

        try:
            # 1. 获取K线数据 (假设函数返回 DataFrame 或 None)
            kline_df = 获取K线数据(symbol, interval=tf, limit=max_limit_needed, market_type=market_type)
            if kline_df is None or kline_df.empty:
                tf_result["error"] = f"获取 K 线数据失败或无数据 for {tf}"
                logger.warning(f"{tf}: {tf_result['error']}")
                analysis_results["timeframe_analysis"][tf] = tf_result
                continue

            tf_result["kline_count"] = len(kline_df)
            fetched_kline_data[tf] = kline_df # Store fetched data
            analysis_results["fetched_data_info"][tf] = f"Fetched {len(kline_df)} bars (limit={max_limit_needed})"

            # 确保数据完整性与类型正确性 (OHLCV)
            required_numeric_cols = ['open', 'high', 'low', 'close', 'volume'] # Include volume
            missing_cols = [col for col in required_numeric_cols if col not in kline_df.columns]
            if missing_cols:
                raise ValueError(f"K线数据缺少必需列: {', '.join(missing_cols)}")

            for col in required_numeric_cols:
                if not pd.api.types.is_numeric_dtype(kline_df[col]):
                    kline_df[col] = pd.to_numeric(kline_df[col], errors='coerce')

            kline_df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True) # Only drop based on OHLC
            if kline_df.empty:
                raise ValueError("转换或清理 OHLC 数据后无有效数据")

            # --- 分步进行分析 ---

            # 2. 形态识别
            try:
                pattern_limit = kline_limits.get('pattern_recognition', 5)
                if len(kline_df) >= pattern_limit:
                    logger.debug(f"{tf}: 开始形态识别 (需要 {pattern_limit} 根K线)...")
                    # --- 形态识别逻辑 ---
                    tf_result['patterns'] = [] # Reset patterns
                    is_pattern_found = False
                    
                    last_candle = kline_df.iloc[-1]
                    last_two = kline_df.iloc[-2:] if len(kline_df) >= 2 else None
                    last_three = kline_df.iloc[-3:] if len(kline_df) >= 3 else None
                    last_five = kline_df.iloc[-5:] if len(kline_df) >= 5 else None # Added last_five
                    prev_trend_down = False
                    
                    if len(kline_df) >= 6:
                        try:
                            prev_trend_down = kline_df.iloc[-6]['close'] > kline_df.iloc[-5]['close']
                        except IndexError:
                            pass # Ignore if not enough data for trend context

                    # Check patterns (add more specific checks as needed)
                    # Check Rising/Falling Three Methods first?
                    # if last_five is not None:
                         # pass # Add calls here if implemented

                    if not is_pattern_found and last_three is not None:
                        if is_morning_star(last_three):
                            tf_result['patterns'].append({'name': '早晨之星', 'implication': '看涨反转'})
                            is_pattern_found = True
                        elif is_evening_star(last_three):
                            tf_result['patterns'].append({'name': '黄昏之星', 'implication': '看跌反转'})
                            is_pattern_found = True
                        elif is_three_white_soldiers(last_three):
                            tf_result['patterns'].append({'name': '三个白兵', 'implication': '看涨持续'})
                            is_pattern_found = True
                        elif is_three_black_crows(last_three):
                            tf_result['patterns'].append({'name': '三只乌鸦', 'implication': '看跌持续'})
                            is_pattern_found = True
                    
                    if not is_pattern_found and last_two is not None:
                        if is_bullish_engulfing(last_two):
                            tf_result['patterns'].append({'name': '看涨吞没', 'implication': '看涨反转'})
                            is_pattern_found = True
                        elif is_bearish_engulfing(last_two):
                            tf_result['patterns'].append({'name': '看跌吞没', 'implication': '看跌反转'})
                            is_pattern_found = True
                        elif is_piercing_pattern(last_two):
                            tf_result['patterns'].append({'name': '刺透形态', 'implication': '看涨反转'})
                            is_pattern_found = True
                        elif is_dark_cloud_cover(last_two):
                            tf_result['patterns'].append({'name': '乌云盖顶', 'implication': '看跌反转'})
                            is_pattern_found = True
                        else: # Check Harami/Tweezer if no engulfing/piercing
                            harami = is_harami(last_two)
                            if harami:
                                tf_result['patterns'].append(harami)
                                is_pattern_found = True
                            else:
                                tweezer = is_tweezer(last_two)
                                if tweezer:
                                    tf_result['patterns'].append(tweezer)
                                    is_pattern_found = True
                    
                    # 单K线形态
                    if not is_pattern_found:
                        # 锤子线/上吊线判断
                        if is_hammer_or_hanging_man(last_candle):
                            if prev_trend_down:
                                tf_result['patterns'].append({'name': '锤子线', 'implication': '潜在看涨反转'})
                            else:
                                tf_result['patterns'].append({'name': '上吊线', 'implication': '潜在看跌反转'})
                            is_pattern_found = True
                        elif is_doji(last_candle):
                            tf_result['patterns'].append({'name': '十字线', 'implication': '犹豫不决'})
                            is_pattern_found = True
                        elif is_spinning_top(last_candle):
                            tf_result['patterns'].append({'name': '陀螺', 'implication': '不确定性'})
                            is_pattern_found = True
                        else:
                            # 检查长实体K线
                            marubozu = is_marubozu(last_candle)
                            if marubozu:
                                tf_result['patterns'].append(marubozu)
                                is_pattern_found = True
                    
                    if not tf_result['patterns']:
                        logger.debug(f"{tf}: 未发现特定K线形态。")
                    else:
                        logger.info(f"{tf}: 检测到形态: {tf_result['patterns']}")
                else:
                    logger.debug(f"{tf}: K线数据不足，跳过形态识别 (需要 {pattern_limit} 根K线，但只有 {len(kline_df)} 根)")
            except Exception as pattern_e:
                tf_result['patterns'] = [{'name': '错误', 'implication': f'形态识别过程中出错: {pattern_e}'}]
                logger.exception(f"{tf}: 形态识别过程中出错")
            
            # 在这里继续添加其他分析逻辑...

            # 3. 波动率分析
            try: # START try for volatility - 正确缩进
                volatility_limit = kline_limits.get('volatility', DEFAULT_BBANDS_PERIOD + 1)
                if len(kline_df) >= volatility_limit: # <--- 修复缩进: 将此行及后续波动率计算逻辑缩进一级
                    logger.debug(f"{tf}: 开始波动率分析 (需要 {volatility_limit} 根K线)...") # <--- 修复括号错误: 删除多余的 ')'
                    # --- 波动率计算逻辑 --- START -- 正确缩进
                    bbands = calculate_bollinger_bands(kline_df["close"], period=DEFAULT_BBANDS_PERIOD, std_dev=DEFAULT_BBANDS_STDDEV)
                    atr = calculate_atr(kline_df["high"], kline_df["low"], kline_df["close"], period=DEFAULT_ATR_PERIOD)
                    # Ensure results are checked for NaN before accessing iloc[-1]
                    latest_bb_middle = bbands["bb_middle"].iloc[-1] if not bbands["bb_middle"].empty and pd.notna(bbands["bb_middle"].iloc[-1]) else np.nan
                    latest_bb_upper = bbands["bb_upper"].iloc[-1] if not bbands["bb_upper"].empty and pd.notna(bbands["bb_upper"].iloc[-1]) else np.nan
                    latest_bb_lower = bbands["bb_lower"].iloc[-1] if not bbands["bb_lower"].empty and pd.notna(bbands["bb_lower"].iloc[-1]) else np.nan
                    latest_atr = atr.iloc[-1] if not atr.empty and pd.notna(atr.iloc[-1]) else np.nan

                    # --- 在这里添加基于 bbands 和 atr 的分析逻辑 ---
                    volatility_status = "未知"
                    band_width = np.nan
                    if pd.notna(latest_bb_upper) and pd.notna(latest_bb_lower) and pd.notna(latest_bb_middle) and latest_bb_middle > 0:
                         band_width = (latest_bb_upper - latest_bb_lower) / latest_bb_middle * 100 # Bandwidth %
                         # 可以根据 band_width 的历史变化或绝对值来判断波动状态
                         # 例如： band_width > upper_threshold -> 高波动; band_width < lower_threshold -> 低波动 (收缩)
                         # 简单的判断 (需要阈值)
                         # if band_width > KLINE_ANALYSIS_CONFIG.get('bb_bandwidth_high_threshold', 5.0):
                         #     volatility_status = "高波动"
                         # elif band_width < KLINE_ANALYSIS_CONFIG.get('bb_bandwidth_low_threshold', 1.0):
                         #     volatility_status = "低波动 (收缩)"
                         # else:
                         #     volatility_status = "正常波动"
                         # 暂时只记录数据
                         volatility_status = f"带宽 {band_width:.2f}%"


                    tf_result['volatility'] = {
                        "status": volatility_status,
                        "bb_upper": f"{latest_bb_upper:.8f}" if pd.notna(latest_bb_upper) else "N/A",
                        "bb_middle": f"{latest_bb_middle:.8f}" if pd.notna(latest_bb_middle) else "N/A",
                        "bb_lower": f"{latest_bb_lower:.8f}" if pd.notna(latest_bb_lower) else "N/A",
                        "bandwidth_pct": f"{band_width:.2f}" if pd.notna(band_width) else "N/A",
                        "atr": f"{latest_atr:.8f}" if pd.notna(latest_atr) else "N/A"
                    }
                    logger.info(f"{tf}: 波动率分析完成: {tf_result['volatility']}")
                    # --- 波动率计算逻辑 --- END -- 正确缩进
                else: # <--- 添加 else 块处理数据不足的情况
                    logger.debug(f"{tf}: K线数据不足，跳过波动率分析 (需要 {volatility_limit} 根K线，但只有 {len(kline_df)} 根)")
                    tf_result['volatility'] = {'error': f'数据不足 (需要 {volatility_limit} 根, 只有 {len(kline_df)} 根)'}

            except Exception as vol_e: # <--- 确保 except 块与 try 对齐
                tf_result['volatility'] = {'error': f'波动率分析过程中出错: {vol_e}'}
                logger.exception(f"{tf}: 波动率分析过程中出错")

            # --- 4. 支撑/阻力分析 (枢轴点) ---
            # (这部分及之后的代码缩进需要检查是否正确，假设它们不在波动率的 try 块内)
            try:
                pivot_limit = kline_limits.get('support_resistance', 2)
                if len(kline_df) >= pivot_limit:
                    logger.debug(f"{tf}: 开始支撑/阻力分析 (需要 {pivot_limit} 根K线)...") # <--- 修正后的行
                    # --- 枢轴点计算逻辑 ---
                    # 枢轴点通常基于前一周期数据计算，所以取倒数第二根K线
                    prev_candle = kline_df.iloc[-2]
                    pivot_data = calculate_standard_pivot_points(
                        prev_candle['high'], prev_candle['low'], prev_candle['close']
                    )
                    tf_result['pivot_point'] = f"{pivot_data.get('PP', 'N/A'):.8f}" if pivot_data.get('PP') is not None else "N/A"
                    tf_result['support_levels'] = [
                        f"{pivot_data.get('S1', 'N/A'):.8f}" if pivot_data.get('S1') is not None else "N/A",
                        f"{pivot_data.get('S2', 'N/A'):.8f}" if pivot_data.get('S2') is not None else "N/A",
                        f"{pivot_data.get('S3', 'N/A'):.8f}" if pivot_data.get('S3') is not None else "N/A"
                    ]
                    tf_result['resistance_levels'] = [
                        f"{pivot_data.get('R1', 'N/A'):.8f}" if pivot_data.get('R1') is not None else "N/A",
                        f"{pivot_data.get('R2', 'N/A'):.8f}" if pivot_data.get('R2') is not None else "N/A",
                        f"{pivot_data.get('R3', 'N/A'):.8f}" if pivot_data.get('R3') is not None else "N/A"
                    ]
                    logger.info(f"{tf}: 枢轴点计算完成: PP={tf_result['pivot_point']}")
                else:
                    logger.debug(f"{tf}: K线数据不足，跳过支撑/阻力分析 (需要 {pivot_limit} 根K线，但只有 {len(kline_df)} 根)")
                    tf_result['pivot_point'] = "数据不足"
                    tf_result['support_levels'] = ["数据不足"] * 3
                    tf_result['resistance_levels'] = ["数据不足"] * 3
            except Exception as pivot_e:
                tf_result['pivot_point'] = f"错误: {pivot_e}"
                tf_result['support_levels'] = [f"错误: {pivot_e}"] * 3
                tf_result['resistance_levels'] = [f"错误: {pivot_e}"] * 3
                logger.exception(f"{tf}: 支撑/阻力分析过程中出错")

            # --- 5. 趋势分析 (MA, MACD, DMI) --- (Ensure this is INSIDE the main try)
            # (MA try-except)
            try:
                # MA 趋势分析
                ma_limit = kline_limits.get('trend_ma', max(DEFAULT_SHORT_MA_PERIOD, DEFAULT_LONG_MA_PERIOD) + 1)
                if len(kline_df) >= ma_limit:
                    logger.debug(f"{tf}: 开始 MA 趋势分析 (需要 {ma_limit} 根K线)...")
                    tf_result['trend_ma'] = _analyze_ma_trend(
                        kline_df['close'],
                        short_period=DEFAULT_SHORT_MA_PERIOD,
                        long_period=DEFAULT_LONG_MA_PERIOD
                    )
                    logger.info(f"{tf}: MA 趋势分析完成: {tf_result['trend_ma']}")
                else:
                    logger.debug(f"{tf}: K线数据不足，跳过 MA 趋势分析 (需要 {ma_limit} 根K线，但只有 {len(kline_df)} 根)")
                    tf_result['trend_ma'] = "数据不足"
            except Exception as ma_trend_e:
                 tf_result['trend_ma'] = f"错误: {ma_trend_e}"
                 logger.exception(f"{tf}: MA 趋势分析过程中出错")

            # (MACD try-except)
            try:
                # MACD 趋势分析
                macd_limit = kline_limits.get('trend_macd', DEFAULT_MACD_SLOW + DEFAULT_MACD_SIGNAL + 1)
                if len(kline_df) >= macd_limit:
                    logger.debug(f"{tf}: 开始 MACD 趋势分析 (需要 {macd_limit} 根K线)...")
                    macd_df = calculate_macd(kline_df['close'])
                    latest_macd = macd_df['macd'].iloc[-1] if not macd_df['macd'].empty and pd.notna(macd_df['macd'].iloc[-1]) else np.nan
                    latest_signal = macd_df['signal'].iloc[-1] if not macd_df['signal'].empty and pd.notna(macd_df['signal'].iloc[-1]) else np.nan
                    latest_hist = macd_df['histogram'].iloc[-1] if not macd_df['histogram'].empty and pd.notna(macd_df['histogram'].iloc[-1]) else np.nan
                    
                    macd_status = "未知"
                    if pd.notna(latest_macd) and pd.notna(latest_signal):
                        if latest_macd > latest_signal and latest_hist > 0: # MACD线上穿信号线，柱状图在0轴上方
                             macd_status = "看涨 (金叉)"
                        elif latest_macd < latest_signal and latest_hist < 0: # MACD线下穿信号线，柱状图在0轴下方
                             macd_status = "看跌 (死叉)"
                        elif latest_macd > latest_signal: # 柱状图可能收缩，但仍在0轴上
                            macd_status = "多头占优"
                        else: # 柱状图可能收缩，但仍在0轴下
                            macd_status = "空头占优"

                    tf_result['trend_macd'] = {
                        "status": macd_status,
                        "macd": f"{latest_macd:.8f}" if pd.notna(latest_macd) else "N/A",
                        "signal": f"{latest_signal:.8f}" if pd.notna(latest_signal) else "N/A",
                        "histogram": f"{latest_hist:.8f}" if pd.notna(latest_hist) else "N/A"
                    }
                    logger.info(f"{tf}: MACD 趋势分析完成: {tf_result['trend_macd']['status']}")
                else:
                    logger.debug(f"{tf}: K线数据不足，跳过 MACD 趋势分析 (需要 {macd_limit} 根K线，但只有 {len(kline_df)} 根)")
                    tf_result['trend_macd'] = {"error": f'数据不足 (需要 {macd_limit} 根, 只有 {len(kline_df)} 根)'}
            except Exception as macd_trend_e:
                tf_result['trend_macd'] = {'error': f'MACD 分析过程中出错: {macd_trend_e}'}
                logger.exception(f"{tf}: MACD 趋势分析过程中出错")

            # (DMI try-except)
            try:
                # DMI 趋势分析
                dmi_limit = kline_limits.get('trend_dmi', DEFAULT_DMI_PERIOD * 2 + 1)
                if len(kline_df) >= dmi_limit:
                    logger.debug(f"{tf}: 开始 DMI 趋势分析 (需要 {dmi_limit} 根K线)...")
                    dmi_df = calculate_dmi(kline_df['high'], kline_df['low'], kline_df['close'])
                    latest_plus_di = dmi_df['plus_di'].iloc[-1] if not dmi_df['plus_di'].empty and pd.notna(dmi_df['plus_di'].iloc[-1]) else np.nan
                    latest_minus_di = dmi_df['minus_di'].iloc[-1] if not dmi_df['minus_di'].empty and pd.notna(dmi_df['minus_di'].iloc[-1]) else np.nan
                    latest_adx = dmi_df['adx'].iloc[-1] if not dmi_df['adx'].empty and pd.notna(dmi_df['adx'].iloc[-1]) else np.nan
                    
                    dmi_status = "未知"
                    trend_strength = "未知"
                    if pd.notna(latest_plus_di) and pd.notna(latest_minus_di) and pd.notna(latest_adx):
                        if latest_plus_di > latest_minus_di:
                            dmi_status = "多头占优 (+DI > -DI)"
                        else:
                            dmi_status = "空头占优 (-DI > +DI)"
                        
                        adx_threshold = KLINE_ANALYSIS_CONFIG.get('adx_trend_threshold', 25)
                        if latest_adx > adx_threshold:
                            trend_strength = f"趋势中 (ADX > {adx_threshold})"
                        else:
                            trend_strength = f"震荡或无趋势 (ADX <= {adx_threshold})"
                    
                    tf_result['trend_dmi'] = {
                        "status": dmi_status,
                        "strength": trend_strength,
                        "+DI": f"{latest_plus_di:.2f}" if pd.notna(latest_plus_di) else "N/A",
                        "-DI": f"{latest_minus_di:.2f}" if pd.notna(latest_minus_di) else "N/A",
                        "ADX": f"{latest_adx:.2f}" if pd.notna(latest_adx) else "N/A"
                    }
                    logger.info(f"{tf}: DMI 趋势分析完成: {tf_result['trend_dmi']['status']}, {tf_result['trend_dmi']['strength']}")
                else:
                    logger.debug(f"{tf}: K线数据不足，跳过 DMI 趋势分析 (需要 {dmi_limit} 根K线，但只有 {len(kline_df)} 根)")
                    tf_result['trend_dmi'] = {"error": f'数据不足 (需要 {dmi_limit} 根, 只有 {len(kline_df)} 根)'}
            except Exception as dmi_trend_e:
                tf_result['trend_dmi'] = {'error': f'DMI 分析过程中出错: {dmi_trend_e}'}
                logger.exception(f"{tf}: DMI 趋势分析过程中出错")

        # --- 主 try 块 (line 879) 的 except 块 --- 
        except FileNotFoundError as fnf_error:
            tf_result["error"] = f"文件未找到错误: {fnf_error}"
            logger.error(f"{tf}: {tf_result['error']}", exc_info=False) 
        except ValueError as val_error:
            tf_result["error"] = f"数据验证或处理错误: {val_error}"
            logger.error(f"{tf}: {tf_result['error']}", exc_info=True)
        except KeyError as key_error:
            tf_result["error"] = f"数据中缺少键或列: {key_error}"
            logger.error(f"{tf}: {tf_result['error']}", exc_info=True)
        except Exception as e: # 通用异常捕获，放在最后
            tf_result["error"] = f"处理时间周期 {tf} 时发生未知错误: {type(e).__name__} - {e}"
            logger.exception(f"处理时间周期 {tf} 时发生未知错误")
        # --- except 块结束 --- 

        # 记录当前时间周期的结果 (移到 try-except 结构外部，确保总会执行)
        analysis_results["timeframe_analysis"][tf] = tf_result
        tf_duration = time.time() - tf_start_time
        logger.info(f"完成时间周期分析: {tf}, 耗时: {tf_duration:.2f} 秒")

    # --- 生成多时间周期共振总结 --- 
    # 检查 timeframe_analysis 是否有内容
    if analysis_results["timeframe_analysis"]:
        try:
            logger.info("开始调用 _generate_confluence_summary 生成协同总结...")
            summary = _generate_confluence_summary(analysis_results["timeframe_analysis"])
            analysis_results["confluence_summary"] = summary
            logger.info("协同总结生成完毕。")
        except Exception as summary_gen_e:
            error_msg = f"调用 _generate_confluence_summary 时出错: {type(summary_gen_e).__name__} - {summary_gen_e}"
            logger.exception(f"生成协同总结时捕获到顶层异常: {error_msg}")
            analysis_results["confluence_summary"] = {"error": error_msg}
            # 也可以考虑设置 analysis_results["error"] = error_msg
    else:
        logger.warning("没有有效的时间周期分析结果，跳过生成协同总结。")
        analysis_results["confluence_summary"] = {"error": "没有有效的时间周期分析结果"}

    # --- 添加最近价格到结果中 --- 
    last_price = None
    # 尝试从已获取的 K 线数据中获取最后一个收盘价
    # 优先使用较小时间周期的数据，如 '5m' 或 '3m' 或列表中的第一个
    preferred_tf_order = ['5m', '3m', '1m', '15m'] + [tf for tf in timeframes if tf not in ['5m', '3m', '1m', '15m']]
    for tf in preferred_tf_order:
        if tf in fetched_kline_data and not fetched_kline_data[tf].empty:
            try:
                # 确保 'close' 列是数值类型
                kline_df = fetched_kline_data[tf]
                if 'close' in kline_df.columns and pd.api.types.is_numeric_dtype(kline_df['close']):
                    last_close = kline_df['close'].iloc[-1]
                    if pd.notna(last_close):
                        last_price = last_close
                        logger.info(f"从 {tf} K线获取到最近价格: {last_price}")
                        break # 找到价格后就停止
                else:
                    logger.warning(f"无法从 {tf} 获取价格：'close' 列无效或非数值类型。")
            except Exception as price_e:
                logger.warning(f"尝试从 {tf} 获取价格时出错: {price_e}")
                
    if last_price is None:        
        logger.warning(f"未能从已获取的 K 线数据中找到有效的最近价格。")
        # 这里可以考虑调用 API 单独获取 ticker price 作为备选
        # 例如: 
        # try:
        #     ticker_info = 数据获取模块.DataFetcher().client.get_symbol_ticker(symbol=symbol)
        #     last_price = float(ticker_info['price'])
        #     logger.info(f"通过 Ticker API 获取到最近价格: {last_price}")
        # except Exception as ticker_e:
        #     logger.error(f"通过 Ticker API 获取价格失败: {ticker_e}")

    analysis_results["last_price"] = last_price # 添加到主结果字典
    # --- 价格添加结束 ---

    # Calculate total duration and return
    end_time_analysis = time.time()
    analysis_results["analysis_duration_seconds"] = end_time_analysis - start_time_analysis
    logger.info(f"K线分析模块对 {symbol} ({market_type}) 的分析完成，总耗时: {analysis_results['analysis_duration_seconds']:.2f} 秒。返回结果。")

    return analysis_results, fetched_kline_data

# --- 测试执行块 ---
if __name__ == '__main__':
    print("执行 K线分析模块 测试...")
    # Use basicConfig for simple testing if logger wasn't configured earlier
    if not logger.hasHandlers():
         logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # --- 测试配置 ---
    test_symbol = 'BTCUSDT'
    test_market_type = 'futures' # or 'spot'
    test_timeframes = ['5m', '15m', '1h'] # 使用较少周期进行测试

    print(f"测试交易对: {test_symbol} ({test_market_type})")
    print(f"测试时间周期: {test_timeframes}")

    # --- 执行分析 ---
    results = None # Initialize results to None
    klines = None  # Initialize klines to None
    try:
        results, klines = 分析K线结构与形态(
            symbol=test_symbol,
            market_type=test_market_type,
            timeframes=test_timeframes
        )
    except Exception as e:
        print(f"\n!!! 分析执行过程中捕获到异常: {e} !!!\n")
        logger.exception("测试执行块捕获到异常:")

    # --- 结果打印 --- 
    print("\n--- 分析结果 ---")
    if results is not None:
        print(f"分析时间: {results.get('analysis_time')}")
        analysis_duration = results.get('analysis_duration_seconds')
        print(f"分析耗时: {analysis_duration:.2f} 秒" if isinstance(analysis_duration, (int, float)) else "N/A")
        if results.get('error'):
             print(f"分析过程中出现整体错误: {results['error']}")

        print("\n--- 多周期协同总结 ---")
        summary = results.get('confluence_summary', {})
        if summary.get("error"):
            print(f"协同分析错误: {summary['error']}")
        # 修正：只有在没有错误时才打印其他总结信息
        elif summary:
            print(f"整体偏向: {summary.get('bias', 'N/A')}")
            print(f"置信度: {summary.get('confidence', 'N/A')}")
            weighted_score = summary.get('weighted_score')
            max_weight = summary.get('max_possible_weight')
            score_str = f"{weighted_score:.1f}" if isinstance(weighted_score, (int, float)) else 'N/A'
            max_weight_str = f"{max_weight:.1f}" if isinstance(max_weight, (int, float)) else 'N/A'
            print(f"加权分数: {score_str} / {max_weight_str}")
            print("理由:")
            for reason in summary.get('reasoning', []): print(f"- {reason}")
            print("警告:")
            for warning in summary.get('warnings', []): print(f"- {warning}")
        else:
            print("(无有效总结信息)")

        print("\n--- 各时间周期详情 ---")
        tf_analysis = results.get('timeframe_analysis', {})
        if not tf_analysis:
            print("无任何时间周期分析数据。")
        else:
            for tf in test_timeframes: # Iterate over requested timeframes
                print(f"\n=== {tf} 周期 ===")
                tf_data = tf_analysis.get(tf)
                if not tf_data:
                    print("未找到此周期数据。")
                    continue
                if tf_data.get("error"):
                    print(f"错误: {tf_data['error']}")
                    continue

                print(f" K线数量: {tf_data.get('kline_count', 'N/A')}")
                print(f" MA趋势 ({DEFAULT_SHORT_MA_PERIOD}/{DEFAULT_LONG_MA_PERIOD}): {tf_data.get('trend_ma', 'N/A')}")

                macd_res = tf_data.get('trend_macd', {})
                if isinstance(macd_res, dict):
                    status = macd_res.get('status', 'N/A')
                    hist = macd_res.get('histogram', 'N/A')
                    macd_val = macd_res.get('macd', 'N/A')
                    print(f" MACD ({DEFAULT_MACD_FAST},{DEFAULT_MACD_SLOW},{DEFAULT_MACD_SIGNAL}): Status={status}, Hist={hist}, Val={macd_val}")
                    if macd_res.get('error'): print(f"  MACD 错误: {macd_res['error']}")
                else: print(f" MACD: {macd_res}")

                dmi_res = tf_data.get('trend_dmi', {})
                if isinstance(dmi_res, dict):
                    plus_di = dmi_res.get('+DI', 'N/A')
                    minus_di = dmi_res.get('-DI', 'N/A')
                    adx = dmi_res.get('ADX', 'N/A')
                    strength = dmi_res.get('strength', 'N/A')
                    status = dmi_res.get('status', 'N/A')
                    print(f" DMI ({DEFAULT_DMI_PERIOD}): Status={status}, Strength={strength}, +DI={plus_di}, -DI={minus_di}, ADX={adx}")
                    if dmi_res.get('error'): print(f"  DMI 错误: {dmi_res['error']}")
                else: print(f" DMI: {dmi_res}")

                vol_res = tf_data.get('volatility', {})
                if isinstance(vol_res, dict):
                    bbw_pct = vol_res.get('bandwidth_pct', 'N/A') # Corrected key
                    atr_val = vol_res.get('atr', 'N/A') # Corrected key
                    print(f" 波动率: BBW%={bbw_pct}, ATR={atr_val}") # Corrected output
                    if vol_res.get('error'): print(f"  波动率错误: {vol_res['error']}")
                else: print(f" 波动率: {vol_res}")

                print(f" 枢轴点 PP: {tf_data.get('pivot_point', 'N/A')}")
                print(f"   支撑: {tf_data.get('support_levels', ['N/A']*3)}")
                print(f"   阻力: {tf_data.get('resistance_levels', ['N/A']*3)}")

                print(" 形态:")
                patterns = tf_data.get('patterns', [])
                if not patterns:
                    print("  (无)")
                else:
                    for p in patterns:
                        if isinstance(p, dict):
                             print(f"  - {p.get('name', '?')}: {p.get('implication', '?')}")
                        else:
                             print(f"  - 格式错误: {p}") 
    else:
        print("\n分析未成功执行或未返回结果。")

    print("\n测试执行完毕。")
