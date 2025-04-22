import pandas as pd
import pandas_ta as ta
import logging
from datetime import datetime, timedelta
from typing import Union, Tuple, Dict, List

# 配置日志 (移动到最前面)
# 将日志级别改为 DEBUG 以查看详细信息
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - [%(module)s:%(funcName)s:%(lineno)d] - %(message)s')
logger = logging.getLogger(__name__)

# 假设数据获取模块的文件名为 数据获取模块.py
try:
    import 数据获取模块
except ImportError:
    # 现在可以使用 logger 了
    logger.error("无法导入 '数据获取模块.py'，请确保该文件存在且路径正确。")
    # 可以选择抛出异常或设置一个标志位
    数据获取模块 = None 

# 导入配置模块
try:
    import 配置
    # 尝试导入配置字典，如果失败则提供更具体的错误
    try:
        from 配置 import MICRO_TREND_CONFIG
    except ImportError:
        logger.error("成功导入 配置.py 但未找到 MICRO_TREND_CONFIG 变量。请检查该文件。")
        MICRO_TREND_CONFIG = {} # 设置默认空字典
        if 配置 is None: # 如果配置模块也未加载 (虽然理论上不应发生在此处)
            配置 = type('obj', (object,), {})() # 创建一个空对象以防 AttributeError
           
except SyntaxError as e:
    logger.error(f"导入 配置.py 时发生语法错误: {e}", exc_info=True)
    配置 = None
    MICRO_TREND_CONFIG = {}
except ImportError as e:
    logger.error(f"导入 配置.py 时发生 ImportError (可能文件不存在或路径问题): {e}", exc_info=True)
    配置 = None
    MICRO_TREND_CONFIG = {}
except Exception as e: # 捕获其他可能的导入错误
    logger.error(f"导入 配置.py 时发生未知错误: {e}", exc_info=True)
    配置 = None
    MICRO_TREND_CONFIG = {}

# 日志配置代码块已移动到前面
# logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - [%(module)s:%(funcName)s:%(lineno)d] - %(message)s')
# logger = logging.getLogger(__name__)

# --- 内部辅助函数：解读指标 ---
def _interpret_indicators(last_row: pd.Series, prev_row: pd.Series, config: dict,
                        ema_short_col: str, ema_long_col: str, roc_col: str,
                        rsi_col: str, bb_upper_col: str, bb_lower_col: str, bb_mid_col: str,
                        macd_hist_col: str, volume_col: str, volume_ma_col: str,
                        kdj_k_col: str, kdj_d_col: str, kdj_j_col: str,
                        ichi_tenkan_col: str, ichi_kijun_col: str, ichi_senkou_a_col: str, ichi_senkou_b_col: str, ichi_chikou_col: str,
                        adx_col: str, adx_dip_col: str, adx_din_col: str
                        ) -> Dict[str, Union[str, float, Dict[str, str]]]:
    """
    解读单个时间点的所有指标，生成详细解读、评分和组合信号。

    Args:
        last_row (pd.Series): 最新的包含指标的 K 线数据行。
        prev_row (pd.Series): 倒数第二行 K 线数据，用于计算交叉等。
        config (dict): 包含解读阈值的配置 (e.g., rsi_oversold, adx_threshold)。
        ... (column names for all indicators) ...

    Returns:
        Dict: 包含 'combined_signal', 'score', 'details' 的字典。
              'details' 是一个包含各项指标解读字符串的子字典。
    """
    interpretations = {}
    combined_signal_str = "↔️" # Default signal string
    score = 0.0 # Default score
    params = config.get('PARAMS', {})
    thresholds_interpret = config.get('THRESHOLDS', {}) # Thresholds for interpretation
    # !!! Get Scoring Config !!!
    scoring_config = config.get('SCORING', {})
    weights = scoring_config.get('WEIGHTS', {}) # Scoring weights
    thresholds_score = scoring_config.get('THRESHOLDS', {}) # Scoring thresholds

    try:
        # --- 提取基础数据 ---
        close = last_row['close']
        # --- 现有指标解读 --- 
        # 1. EMA Trend
        ema_short = last_row.get(ema_short_col, pd.NA)
        ema_long = last_row.get(ema_long_col, pd.NA)
        trend_strength_threshold = thresholds_interpret.get('trend_strength_threshold', 0.001) # Example threshold
        ema_trend = "趋势: 未知"
        if pd.notna(ema_short) and pd.notna(ema_long):
            diff_pct = (ema_short - ema_long) / ema_long if ema_long else 0
            if diff_pct > trend_strength_threshold * 2: ema_trend = "趋势: 强升(↑↑)"
            elif diff_pct > 0: ema_trend = "趋势: 上升(↑)"
            elif diff_pct < -trend_strength_threshold * 2: ema_trend = "趋势: 强降(↓↓)"
            elif diff_pct < 0: ema_trend = "趋势: 下降(↓)"
            else: ema_trend = "趋势: 盘整(↔)"
        interpretations['ema_trend'] = ema_trend

        # 2. ROC Momentum
        roc = last_row.get(roc_col, pd.NA)
        mom_strength_threshold = thresholds_interpret.get('momentum_strength_threshold', 0.1) # Example threshold
        roc_momentum = "动量: 未知"
        if pd.notna(roc):
            if roc > mom_strength_threshold * 2: roc_momentum = "动量: 强正(++)"
            elif roc > 0: roc_momentum = "动量: 正向(+)"
            elif roc < -mom_strength_threshold * 2: roc_momentum = "动量: 强负(--)"
            elif roc < 0: roc_momentum = "动量: 负向(-)"
            else: roc_momentum = "动量: 趋平(0)"
        interpretations['roc_momentum'] = roc_momentum

        # 3. RSI Overbought/Oversold
        rsi = last_row.get(rsi_col, pd.NA)
        oversold = thresholds_interpret.get('rsi_oversold', 30)
        overbought = thresholds_interpret.get('rsi_overbought', 70)
        rsi_state = "RSI: 未知"
        if pd.notna(rsi):
            if rsi > overbought: rsi_state = f"RSI: 超买(>{overbought})"
            elif rsi < oversold: rsi_state = f"RSI: 超卖(<{oversold})"
            else: rsi_state = "RSI: 中性"
        interpretations['rsi_state'] = rsi_state

        # 4. Bollinger Bands Position
        bb_upper = last_row.get(bb_upper_col, pd.NA)
        bb_lower = last_row.get(bb_lower_col, pd.NA)
        bb_mid = last_row.get(bb_mid_col, pd.NA) # Get Mid Band value
        bb_pos = "BB: 未知"
        if pd.notna(close) and pd.notna(bb_upper) and pd.notna(bb_lower) and pd.notna(bb_mid):
            if close > bb_upper: bb_pos = "BB: 穿上轨(↗↗)" 
            elif close < bb_lower: bb_pos = "BB: 穿下轨(↘↘)" 
            # Use a small tolerance for touching
            elif abs(close - bb_upper) < (bb_upper - bb_mid) * 0.05 : bb_pos = "BB: 触上轨(↗)" 
            elif abs(close - bb_lower) < (bb_mid - bb_lower) * 0.05 : bb_pos = "BB: 触下轨(↘)"
            elif close > bb_mid: bb_pos = "BB: 中轨上方"
            elif close < bb_mid: bb_pos = "BB: 中轨下方"
            else: bb_pos = "BB: 在中轨"
        interpretations['bb_pos'] = bb_pos

        # 5. MACD Histogram and Cross
        macd_hist = last_row.get(macd_hist_col, pd.NA)
        prev_macd_hist = prev_row.get(macd_hist_col, pd.NA) if prev_row is not None else pd.NA
        macd_cross = ""
        macd_hist_state = ""
        if pd.notna(macd_hist):
            if macd_hist > 0:
                 macd_hist_state = "柱>0"
                 if pd.notna(prev_macd_hist) and prev_macd_hist <= 0: macd_cross = ",金叉(🔼)" # Gold Cross
            elif macd_hist < 0:
                 macd_hist_state = "柱<0"
                 if pd.notna(prev_macd_hist) and prev_macd_hist >= 0: macd_cross = ",死叉(🔽)" # Dead Cross
            else:
                 macd_hist_state = "柱=0"
        macd_combined_state = f"MACD:{macd_hist_state}{macd_cross}"
        interpretations['macd_state'] = macd_combined_state
        interpretations['macd_cross'] = macd_cross # Store cross separately if needed for logic
        interpretations['macd_hist_state'] = macd_hist_state # Store state separately

        # 6. Volume Analysis
        volume = last_row.get(volume_col, pd.NA)
        volume_ma = last_row.get(volume_ma_col, pd.NA)
        volume_increase_threshold = thresholds_interpret.get('volume_increase_threshold', 1.2)
        volume_state = "Vol: 未知"
        if pd.notna(volume) and pd.notna(volume_ma) and volume_ma > 0:
            if volume > volume_ma * volume_increase_threshold: volume_state = "Vol: 放量(📈)"
            elif volume < volume_ma / volume_increase_threshold: volume_state = "Vol: 缩量(📉)"
            else: volume_state = "Vol: 平量"
        interpretations['volume_state'] = volume_state

        # --- 新指标解读 --- 
        
        # 7. KDJ Interpretation
        kdj_k = last_row.get(kdj_k_col, pd.NA)
        kdj_d = last_row.get(kdj_d_col, pd.NA)
        kdj_j = last_row.get(kdj_j_col, pd.NA)
        prev_k = prev_row.get(kdj_k_col, pd.NA) if prev_row is not None else pd.NA
        prev_d = prev_row.get(kdj_d_col, pd.NA) if prev_row is not None else pd.NA
        kdj_cross = ""
        kdj_level = ""
        kdj_signal_str = "KDJ: 未知"
        if pd.notna(kdj_k) and pd.notna(kdj_d) and pd.notna(kdj_j) and pd.notna(prev_k) and pd.notna(prev_d):
            # KDJ Cross
            if kdj_k > kdj_d and prev_k <= prev_d: kdj_cross = ",金叉(🔼)" 
            elif kdj_k < kdj_d and prev_k >= prev_d: kdj_cross = ",死叉(🔽)"
            # J Level (common thresholds: 80-100 overbought, 0-20 oversold)
            kdj_overbought = thresholds_interpret.get('kdj_overbought', 80)
            kdj_oversold = thresholds_interpret.get('kdj_oversold', 20)
            if kdj_j > kdj_overbought: kdj_level = f",J超买(>{kdj_overbought})"
            elif kdj_j < kdj_oversold: kdj_level = f",J超卖(<{kdj_oversold})"
            kdj_signal_str = f"KDJ: K>D" if kdj_k > kdj_d else "KDJ: K<D" 
            kdj_signal_str += kdj_cross + kdj_level
        elif pd.notna(kdj_k) and pd.notna(kdj_d): # Handle case with no prev data
             kdj_signal_str = f"KDJ: K>D" if kdj_k > kdj_d else "KDJ: K<D" 
             # J Level interpretation still possible
             kdj_overbought = thresholds_interpret.get('kdj_overbought', 80)
             kdj_oversold = thresholds_interpret.get('kdj_oversold', 20)
             if pd.notna(kdj_j):
                 if kdj_j > kdj_overbought: kdj_level = f",J超买(>{kdj_overbought})"
                 elif kdj_j < kdj_oversold: kdj_level = f",J超卖(<{kdj_oversold})"
             kdj_signal_str += kdj_level
        interpretations['kdj_signal'] = kdj_signal_str

        # 8. Ichimoku Interpretation
        tenkan = last_row.get(ichi_tenkan_col, pd.NA)
        kijun = last_row.get(ichi_kijun_col, pd.NA)
        senkou_a = last_row.get(ichi_senkou_a_col, pd.NA)
        senkou_b = last_row.get(ichi_senkou_b_col, pd.NA)
        chikou = last_row.get(ichi_chikou_col, pd.NA)
        # Note: Chikou needs comparison against price N periods ago (e.g., 26). This row doesn't have it directly.
        # We can only compare Chikou with the *current* close for a rough idea, or ignore Chikou for simplicity here.
        ichi_signal_parts = []
        if pd.notna(close) and pd.notna(senkou_a) and pd.notna(senkou_b):
            if close > senkou_a and close > senkou_b: ichi_signal_parts.append("价在云上")
            elif close < senkou_a and close < senkou_b: ichi_signal_parts.append("价在云下")
            else: ichi_signal_parts.append("价在云中")
        if pd.notna(tenkan) and pd.notna(kijun):
            if tenkan > kijun: ichi_signal_parts.append("转>基") # Tenkan > Kijun (Bullish)
            elif tenkan < kijun: ichi_signal_parts.append("转<基") # Tenkan < Kijun (Bearish)
            else: ichi_signal_parts.append("转=基")
        # Chikou interpretation (simplified: vs current close - less accurate)
        if pd.notna(chikou) and pd.notna(close):
             if chikou > close: ichi_signal_parts.append("迟>价")
             elif chikou < close: ichi_signal_parts.append("迟<价")
        ichi_signal_str = "Ichi: " + (", ".join(ichi_signal_parts) if ichi_signal_parts else "未知")
        interpretations['ichi_signal'] = ichi_signal_str

        # 9. ADX Interpretation
        adx = last_row.get(adx_col, pd.NA)
        adx_dip = last_row.get(adx_dip_col, pd.NA) # +DI
        adx_din = last_row.get(adx_din_col, pd.NA) # -DI
        adx_trend_threshold = thresholds_interpret.get('adx_trend_threshold', 25) # Common threshold for trending market
        adx_weak_threshold = thresholds_interpret.get('adx_weak_threshold', 20)
        adx_signal_parts = []
        if pd.notna(adx):
            if adx > adx_trend_threshold: adx_signal_parts.append(f"强趋(>{adx_trend_threshold:.0f})")
            elif adx < adx_weak_threshold: adx_signal_parts.append(f"弱趋(<{adx_weak_threshold:.0f})")
            else: adx_signal_parts.append("趋中")
        if pd.notna(adx_dip) and pd.notna(adx_din):
            if adx_dip > adx_din: adx_signal_parts.append("+DI>-DI") # Uptrend bias
            elif adx_din > adx_dip: adx_signal_parts.append("-DI>+DI") # Downtrend bias
            else: adx_signal_parts.append("+DI=-DI")
        adx_signal_str = "ADX: " + (", ".join(adx_signal_parts) if adx_signal_parts else "未知")
        interpretations['adx_signal'] = adx_signal_str
        
        # --- 提取状态变量 (用于计分) ---
        # (This logic remains the same)
        is_strong_bull_trend = interpretations.get('ema_trend') == "趋势: 强升(↑↑)"
        is_bull_trend = interpretations.get('ema_trend') == "趋势: 上升(↑)"
        is_strong_bear_trend = interpretations.get('ema_trend') == "趋势: 强降(↓↓)"
        is_bear_trend = interpretations.get('ema_trend') == "趋势: 下降(↓)"
        is_ranging_trend = interpretations.get('ema_trend') == "趋势: 盘整(↔)"
        is_strong_pos_mom = interpretations.get('roc_momentum') == "动量: 强正(++)"
        is_pos_mom = interpretations.get('roc_momentum') == "动量: 正向(+)"
        is_strong_neg_mom = interpretations.get('roc_momentum') == "动量: 强负(--)"
        is_neg_mom = interpretations.get('roc_momentum') == "动量: 负向(-)"
        is_weak_mom = interpretations.get('roc_momentum') == "动量: 趋平(0)"
        is_overbought = "超买" in interpretations.get('rsi_state', "")
        is_oversold = "超卖" in interpretations.get('rsi_state', "")
        is_macd_gold_cross = "金叉" in interpretations.get('macd_state', "")
        is_macd_dead_cross = "死叉" in interpretations.get('macd_state', "")
        is_macd_hist_pos = "柱>0" in interpretations.get('macd_state', "")
        is_macd_hist_neg = "柱<0" in interpretations.get('macd_state', "")
        is_volume_high = "放量" in interpretations.get('volume_state', "") # Volume score not implemented yet
        is_kdj_gold_cross = "金叉" in interpretations.get('kdj_signal', "")
        is_kdj_dead_cross = "死叉" in interpretations.get('kdj_signal', "")
        is_kdj_overbought = "J超买" in interpretations.get('kdj_signal', "")
        is_kdj_oversold = "J超卖" in interpretations.get('kdj_signal', "")
        is_kdj_k_above_d = "K>D" in interpretations.get('kdj_signal', "")
        is_kdj_d_above_k = "K<D" in interpretations.get('kdj_signal', "")
        is_price_above_cloud = "价在云上" in interpretations.get('ichi_signal', "")
        is_price_below_cloud = "价在云下" in interpretations.get('ichi_signal', "")
        is_tenkan_above_kijun = "转>基" in interpretations.get('ichi_signal', "")
        is_kijun_above_tenkan = "转<基" in interpretations.get('ichi_signal', "")
        is_adx_strong_trend = "强趋" in interpretations.get('adx_signal', "")
        is_adx_medium_trend = "趋中" in interpretations.get('adx_signal', "")
        is_adx_weak_trend = "弱趋" in interpretations.get('adx_signal', "")
        is_adx_pos_dominant = "+DI>-DI" in interpretations.get('adx_signal', "")
        is_adx_neg_dominant = "-DI>+DI" in interpretations.get('adx_signal', "")

        # --- 计算总分 --- 
        score = 0
        if not weights: 
             logging.warning("评分权重未在配置中定义，无法计算分数。")
        else:
            # Trend
            if is_strong_bull_trend: score += weights.get('strong_bull_trend', 3)
            if is_bull_trend: score += weights.get('bull_trend', 1)
            if is_strong_bear_trend: score += weights.get('strong_bear_trend', -3)
            if is_bear_trend: score += weights.get('bear_trend', -1)
            # Momentum
            if is_strong_pos_mom: score += weights.get('strong_pos_mom', 2)
            if is_pos_mom: score += weights.get('pos_mom', 1)
            if is_strong_neg_mom: score += weights.get('strong_neg_mom', -2)
            if is_neg_mom: score += weights.get('neg_mom', -1)
            # Oscillators
            if is_overbought: score += weights.get('rsi_overbought', -2)
            if is_oversold: score += weights.get('rsi_oversold', 2)
            if is_kdj_overbought: score += weights.get('kdj_overbought', -1)
            if is_kdj_oversold: score += weights.get('kdj_oversold', 1)
            # Crosses
            if is_macd_gold_cross: score += weights.get('macd_gold_cross', 3)
            if is_macd_dead_cross: score += weights.get('macd_dead_cross', -3)
            if is_kdj_gold_cross: score += weights.get('kdj_gold_cross', 2)
            if is_kdj_dead_cross: score += weights.get('kdj_dead_cross', -2)
            # State/Location
            if is_macd_hist_pos: score += weights.get('macd_hist_pos', 1)
            if is_macd_hist_neg: score += weights.get('macd_hist_neg', -1)
            if is_kdj_k_above_d: score += weights.get('kdj_k_above_d', 0.5)
            if is_kdj_d_above_k: score += weights.get('kdj_d_above_k', -0.5)
            if is_price_above_cloud: score += weights.get('price_above_cloud', 2)
            if is_price_below_cloud: score += weights.get('price_below_cloud', -2)
            if is_tenkan_above_kijun: score += weights.get('tenkan_above_kijun', 1)
            if is_kijun_above_tenkan: score += weights.get('kijun_above_tenkan', -1)
            # ADX Confirmation
            if is_adx_strong_trend and is_adx_pos_dominant: score += weights.get('adx_strong_pos', 2)
            if is_adx_medium_trend and is_adx_pos_dominant: score += weights.get('adx_medium_pos', 1)
            if is_adx_strong_trend and is_adx_neg_dominant: score += weights.get('adx_strong_neg', -2)
            if is_adx_medium_trend and is_adx_neg_dominant: score += weights.get('adx_medium_neg', -1)
        
        logging.debug(f"Calculated score: {score}")

        # --- 映射分数到信号 --- 
        strong_bull_thresh = thresholds_score.get('strong_bullish', 8)
        bull_thresh = thresholds_score.get('bullish', 3)
        strong_bear_thresh = thresholds_score.get('strong_bearish', -8)
        bear_thresh = thresholds_score.get('bearish', -3)
        adx_override = thresholds_score.get('adx_weak_override_enabled', True)
        adx_max_signal = thresholds_score.get('adx_weak_max_signal', 1) # 0: force ↔️, 1: cap at +/-
        
        signal_level = 0 # 0: Neutral, 1: Bearish, 2: Strong Bearish, 3: Bullish, 4: Strong Bullish
        
        if score >= strong_bull_thresh: signal_level = 4
        elif score >= bull_thresh: signal_level = 3
        elif score <= strong_bear_thresh: signal_level = 2
        elif score <= bear_thresh: signal_level = 1
        else: signal_level = 0
            
        # Apply ADX Weak Override
        if adx_override and is_adx_weak_trend:
            logging.debug(f"ADX weak trend detected. Applying override (max_signal={adx_max_signal}). Original signal level: {signal_level}")
            if adx_max_signal == 0:
                signal_level = 0 # Force neutral
            elif adx_max_signal == 1:
                # Cap at +/- ; Strong signals become normal, neutral remains neutral
                if signal_level == 4: signal_level = 3 # Strong Bull -> Bull
                elif signal_level == 2: signal_level = 1 # Strong Bear -> Bear
            # If adx_max_signal is > 1, no capping applied based on this setting
            logging.debug(f"Signal level after ADX override: {signal_level}")
            
        # Map final level to signal string
        if signal_level == 4: combined_signal_str = "强看涨(🚀)"
        elif signal_level == 3: combined_signal_str = "看涨(+)"
        elif signal_level == 2: combined_signal_str = "强看跌(💥)"
        elif signal_level == 1: combined_signal_str = "看跌(-)"
        else: combined_signal_str = "盘整/不明(↔️)"
            
        # --- 返回结构化结果 --- 
        return {
            "combined_signal": combined_signal_str,
            "score": round(score, 2), # Round score for cleaner output
            "details": interpretations # Return the dictionary with detailed interpretations
        }

    except Exception as e:
        logging.error(f"Error interpreting indicators: {e}", exc_info=True)
        # Return an error structure
        return {
            "combined_signal": "错误",
            "score": 0.0,
            "details": {"error": "无法解读指标"}
        }

# --- 指标计算 ---
def _calculate_indicators(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    计算所有需要的技术指标。
    """
    params = config.get('PARAMS', {}) # 获取参数子字典
    try:
        # 确保列名正确 (小写)
        df.columns = df.columns.str.lower()
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_cols):
            missing_cols = [col for col in required_cols if col not in df.columns]
            logging.error(f"Missing required columns for indicator calculation: {missing_cols}")
            return df # 返回原始df或引发错误

        logging.debug(f"Calculating indicators for DataFrame with shape: {df.shape}. Initial columns: {df.columns.tolist()}")

        # 1. EMA (趋势)
        ema_short = params.get('ema_short_period', 10)
        ema_long = params.get('ema_long_period', 30)
        df.ta.ema(length=ema_short, append=True, col_names=(f'EMA_{ema_short}',))
        df.ta.ema(length=ema_long, append=True, col_names=(f'EMA_{ema_long}',))
        logging.debug(f"EMA_{ema_short} and EMA_{ema_long} calculated.")

        # 2. ROC (动量)
        roc_period = params.get('roc_period', 9)
        df.ta.roc(length=roc_period, append=True, col_names=(f'ROC_{roc_period}',))
        logging.debug(f"ROC_{roc_period} calculated.")

        # 3. RSI (超买超卖)
        rsi_period = params.get('rsi_period', 14)
        df.ta.rsi(length=rsi_period, append=True, col_names=(f'RSI_{rsi_period}',))
        logging.debug(f"RSI_{rsi_period} calculated.")

        # 4. Bollinger Bands (波动性/通道)
        bb_period = params.get('bb_period', 20)
        bb_std = params.get('bb_std_dev', 2)
        # Note: ta.bbands appends multiple columns like BBL_20_2.0, BBM_20_2.0 etc.
        df.ta.bbands(length=bb_period, std=bb_std, append=True)
        logging.debug(f"Bollinger Bands (period={bb_period}, std={bb_std}) calculated.")

        # 5. MACD (动量/趋势)
        macd_fast = params.get('macd_fast_period', 12)
        macd_slow = params.get('macd_slow_period', 26)
        macd_signal = params.get('macd_signal_period', 9)
        # Note: ta.macd appends MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
        df.ta.macd(fast=macd_fast, slow=macd_slow, signal=macd_signal, append=True)
        logging.debug(f"MACD (fast={macd_fast}, slow={macd_slow}, signal={macd_signal}) calculated.")

        # 6. Volume MA (成交量)
        vol_ma_period = params.get('volume_ma_period', 20)
        df[f'Vol_MA_{vol_ma_period}'] = df['volume'].rolling(window=vol_ma_period).mean()
        logging.debug(f"Volume MA_{vol_ma_period} calculated.")

        # --- 新增指标 ---

        # 7. KDJ (随机指标)
        kdj_len = params.get('kdj_length', 9)
        kdj_sig = params.get('kdj_signal', 3)
        kdj_k = params.get('kdj_k_period', 3) # This k parameter is for internal smoothing, might not appear in column name
        # !!! FIX: Adjust original column names based on DEBUG logs !!!
        kdj_cols_orig = [f'K_{kdj_len}_{kdj_sig}', f'D_{kdj_len}_{kdj_sig}', f'J_{kdj_len}_{kdj_sig}'] 
        kdj_cols_new = ['KDJ_K', 'KDJ_D', 'KDJ_J']
        try:
            df.ta.kdj(length=kdj_len, signal=kdj_sig, k=kdj_k, append=True)
            logging.debug(f"Columns after KDJ calculation (before rename): {df.columns.tolist()}") 
            # 重命名 KDJ 列 (using corrected original names)
            rename_dict = dict(zip(kdj_cols_orig, kdj_cols_new))
            df.rename(columns=rename_dict, inplace=True, errors='ignore')
            logging.debug(f"KDJ (length={kdj_len}, signal={kdj_sig}, k={kdj_k}) calculated. Attempted rename using {rename_dict}.")
            # Verify rename success, add NA if still missing
            for i, col_new in enumerate(kdj_cols_new):
                 if col_new not in df.columns:
                      logging.warning(f"Column '{col_new}' is missing after attempted KDJ rename from '{kdj_cols_orig[i]}'. Adding as NA.")
                      df[col_new] = pd.NA
        except Exception as e:
            logging.warning(f"KDJ calculation/rename failed: {e}. Adding NA columns {kdj_cols_new}.")
            for col in kdj_cols_new:
                if col not in df.columns: df[col] = pd.NA

        # 8. Ichimoku Cloud (一目均衡表)
        ichi_tenkan = params.get('ichimoku_tenkan', 9)
        ichi_kijun = params.get('ichimoku_kijun', 26)
        ichi_senkou_b_period = params.get('ichimoku_senkou_b', 52) # Config name for the period used in calculation
        ichi_cols_new = ['Ichi_Tenkan', 'Ichi_Kijun', 'Ichi_SenkouA', 'Ichi_SenkouB', 'Ichi_Chikou']
        try:
            ichi_df, _ = df.ta.ichimoku(tenkan=ichi_tenkan, kijun=ichi_kijun, senkou=ichi_senkou_b_period, include_chikou=True, append=False)
            if ichi_df is not None:
                logging.debug(f"Ichimoku DataFrame columns returned by ta.ichimoku: {ichi_df.columns.tolist()}")
            else:
                logging.warning("ta.ichimoku returned None for ichi_df")
                raise ValueError("Ichimoku calculation returned None.")
                
            if not ichi_df.empty:
                 # Build the rename map dynamically based on DEBUG logs
                 rename_map = {}
                 # Tenkan
                 tenkan_col_orig = f'ITS_{ichi_tenkan}'
                 if tenkan_col_orig in ichi_df.columns: rename_map[tenkan_col_orig] = 'Ichi_Tenkan'
                 # Kijun
                 kijun_col_orig = f'IKS_{ichi_kijun}'
                 if kijun_col_orig in ichi_df.columns: rename_map[kijun_col_orig] = 'Ichi_Kijun'
                 # !!! FIX: Senkou A name based on DEBUG logs !!!
                 senkou_a_col_orig = f'ISA_{ichi_tenkan}' # Was ISA_9 in logs
                 if senkou_a_col_orig in ichi_df.columns: rename_map[senkou_a_col_orig] = 'Ichi_SenkouA'
                 # !!! FIX: Senkou B name based on DEBUG logs !!!
                 senkou_b_col_orig = f'ISB_{ichi_kijun}' # Was ISB_26 in logs (uses kijun period)
                 if senkou_b_col_orig in ichi_df.columns: rename_map[senkou_b_col_orig] = 'Ichi_SenkouB'
                 # Chikou
                 chikou_col_orig = f'ICS_{ichi_kijun}'
                 if chikou_col_orig in ichi_df.columns: rename_map[chikou_col_orig] = 'Ichi_Chikou'
                 
                 logging.debug(f"Ichimoku rename map constructed: {rename_map}")
                 
                 if not rename_map:
                      logging.warning("Ichimoku rename map is empty. Cannot merge Ichimoku columns.")
                 else:
                      cols_to_select = list(rename_map.keys())
                      # Check if all expected new columns are in the map keys
                      missing_in_map = [ichi_cols_new[i] for i, orig_col in enumerate([tenkan_col_orig, kijun_col_orig, senkou_a_col_orig, senkou_b_col_orig, chikou_col_orig]) if orig_col not in rename_map]
                      if missing_in_map:
                          logging.warning(f"Could not find original columns in ichi_df for: {missing_in_map}. Corresponding columns will be missing.")
                      
                      ichi_selected = ichi_df[cols_to_select].rename(columns=rename_map)
                      df = pd.concat([df, ichi_selected], axis=1)
                      logging.debug(f"Ichimoku columns merged and renamed: {ichi_selected.columns.tolist()}")
                      # Add NA for any columns that failed to map/merge
                      for col_new in ichi_cols_new:
                          if col_new not in df.columns:
                              logging.warning(f"Column '{col_new}' is missing after Ichimoku merge. Adding as NA.")
                              df[col_new] = pd.NA
            else:
                 raise ValueError("Ichimoku calculation returned empty DataFrame.")
        except Exception as e:
            logging.warning(f"Ichimoku calculation/merge failed: {e}. Adding NA columns {ichi_cols_new}.")
            for col in ichi_cols_new:
                if col not in df.columns: df[col] = pd.NA

        # 9. ADX (Already confirmed working from logs, keeping rename)
        adx_len = params.get('adx_length', 14)
        adx_cols_orig = [f'ADX_{adx_len}', f'DMP_{adx_len}', f'DMN_{adx_len}']
        adx_cols_new = ['ADX', 'ADX_DIp', 'ADX_DIn']
        try:
            df.ta.adx(length=adx_len, append=True)
            logging.debug(f"Columns after ADX calculation (before rename): {df.columns.tolist()}")
            rename_dict = dict(zip(adx_cols_orig, adx_cols_new))
            df.rename(columns=rename_dict, inplace=True, errors='ignore')
            logging.debug(f"ADX (length={adx_len}) calculated. Attempted rename using {rename_dict}.")
            # Verify rename success, add NA if still missing
            for i, col_new in enumerate(adx_cols_new):
                 if col_new not in df.columns:
                      logging.warning(f"Column '{col_new}' is missing after attempted ADX rename from '{adx_cols_orig[i]}'. Adding as NA.")
                      df[col_new] = pd.NA
        except Exception as e:
            logging.warning(f"ADX calculation/rename failed: {e}. Adding NA columns {adx_cols_new}.")
            for col in adx_cols_new:
                if col not in df.columns: df[col] = pd.NA

        # --- End of New Indicators ---

        logging.info(f"All indicators calculation attempt finished. DataFrame final shape: {df.shape}")
        logging.debug(f"Final columns before returning from _calculate_indicators: {df.columns.tolist()}")

    except Exception as e:
        logging.error(f"Critical error during indicator calculation: {e}", exc_info=True)
        # Depending on policy, return df as is, or return None, or raise error
        # Returning df might lead to errors downstream if columns are missing
        # Adding expected columns as NA might be safer if downstream needs them
        expected_cols = [f'EMA_{ema_short}', f'EMA_{ema_long}', f'ROC_{roc_period}', f'RSI_{rsi_period}',
                         f'BBL_{bb_period}_{bb_std}.0', f'BBM_{bb_period}_{bb_std}.0', f'BBU_{bb_period}_{bb_std}.0', # Adjust BB names if needed
                         f'MACD_{macd_fast}_{macd_slow}_{macd_signal}', f'MACDh_{macd_fast}_{macd_slow}_{macd_signal}', f'MACDs_{macd_fast}_{macd_slow}_{macd_signal}',
                         f'Vol_MA_{vol_ma_period}'] + kdj_cols_new + ichi_cols_new + adx_cols_new
        for col in expected_cols:
             if col not in df.columns: df[col] = pd.NA
        logging.warning("Returning DataFrame potentially with NAs due to calculation error.")

    return df

# --- 单周期分析函数 ---
# 重命名：分析微观趋势 -> 分析单周期趋势
def 分析单周期趋势(df_with_indicators: pd.DataFrame, config: dict, interval: str = "") -> Dict[str, Union[str, float, Dict[str, str], None]]:
    """
    分析单个时间周期的、已包含指标的DataFrame，提取最新信号信息。

    Args:
        df_with_indicators (pd.DataFrame): 已计算指标的 K 线数据。
        config (dict): 包含计算和解读所需参数的配置字典。
        interval (str, optional): 当前分析的时间周期 (用于日志或错误信息). Defaults to "".

    Returns:
        Dict: 包含 'interval', 'combined_signal', 'score', 'details' 的字典，
              或者在错误时包含 'error' 键。
    """
    interval_prefix = f"[{interval}] " if interval else ""
    result_base = {"interval": interval, "combined_signal": None, "score": None, "details": None} 
    
    if df_with_indicators is None or df_with_indicators.empty:
        logger.warning(f"{interval_prefix}输入数据为空，无法分析。")
        result_base["error"] = "输入数据为空"
        return result_base

    if len(df_with_indicators) < 2:
        logger.warning(f"{interval_prefix}数据不足 (<2 行)，无法计算交叉信号。")
        # Decide how to handle this - maybe still try to interpret?
        # For now, let's return an error state for consistency in MTF analysis
        result_base["error"] = "数据行数不足 (<2)"
        # If you want to proceed with single-row analysis, adjust here
        # last_row = df_with_indicators.iloc[-1]
        # prev_row = None 
        return result_base 
    else:
        last_row = df_with_indicators.iloc[-1]
        prev_row = df_with_indicators.iloc[-2]

    try:
        # --- 动态确定列名 --- 
        params = config.get('PARAMS', {})
        ema_short_period = params.get('ema_short_period', 10)
        ema_long_period = params.get('ema_long_period', 30)
        roc_period = params.get('roc_period', 9)
        rsi_period = params.get('rsi_period', 14)
        bb_period = params.get('bb_period', 20)
        bb_std_dev = params.get('bb_std_dev', 2.0)
        macd_fast = params.get('macd_fast_period', 12)
        macd_slow = params.get('macd_slow_period', 26)
        macd_signal = params.get('macd_signal_period', 9)
        volume_ma_period = params.get('volume_ma_period', 20)

        ema_short_col = f'EMA_{ema_short_period}'
        ema_long_col = f'EMA_{ema_long_period}'
        roc_col = f'ROC_{roc_period}'
        rsi_col = f'RSI_{rsi_period}'
        # pandas_ta bbands 列名可能包含小数点 (e.g., BBU_20_2.0)
        bb_std_str = f"{bb_std_dev:.1f}" # Format std dev for column name
        bb_upper_col = f'BBU_{bb_period}_{bb_std_str}'
        bb_lower_col = f'BBL_{bb_period}_{bb_std_str}'
        bb_mid_col = f'BBM_{bb_period}_{bb_std_str}' # 中轨列名
        # MACD Histogram 列名约定为 'MACDh_...' (注意小写 h)
        macd_hist_col = f'MACDh_{macd_fast}_{macd_slow}_{macd_signal}'
        volume_col = 'volume' # Assuming original volume column exists
        volume_ma_col = f'Vol_MA_{volume_ma_period}'

        # 新指标 (使用 _calculate_indicators 中重命名后的列名)
        kdj_k_col = 'KDJ_K'
        kdj_d_col = 'KDJ_D'
        kdj_j_col = 'KDJ_J'
        ichi_tenkan_col = 'Ichi_Tenkan'
        ichi_kijun_col = 'Ichi_Kijun'
        ichi_senkou_a_col = 'Ichi_SenkouA'
        ichi_senkou_b_col = 'Ichi_SenkouB'
        ichi_chikou_col = 'Ichi_Chikou'
        adx_col = 'ADX'
        adx_dip_col = 'ADX_DIp' # DI+
        adx_din_col = 'ADX_DIn' # DI-
        
        # --- 检查列 --- 
        required_cols_for_interpret = [
            ema_short_col, ema_long_col, roc_col, rsi_col, 
            bb_upper_col, bb_lower_col, bb_mid_col, 
            macd_hist_col, volume_col, volume_ma_col,
            kdj_k_col, kdj_d_col, kdj_j_col,
            ichi_tenkan_col, ichi_kijun_col, ichi_senkou_a_col, ichi_senkou_b_col, ichi_chikou_col,
            adx_col, adx_dip_col, adx_din_col
        ]
        missing_cols = [col for col in required_cols_for_interpret if col not in df_with_indicators.columns]
        if missing_cols:
            logger.error(f"{interval_prefix}无法解读指标，缺少列: {missing_cols}")
            result_base["error"] = f"缺少指标列: {', '.join(missing_cols)}"
            return result_base

        # --- 调用解读函数 --- 
        interpretation_result = _interpret_indicators(
            last_row, prev_row, config,
            ema_short_col, ema_long_col, roc_col, rsi_col,
            bb_upper_col, bb_lower_col, bb_mid_col,
            macd_hist_col, volume_col, volume_ma_col,
            kdj_k_col, kdj_d_col, kdj_j_col,
            ichi_tenkan_col, ichi_kijun_col, ichi_senkou_a_col, ichi_senkou_b_col, ichi_chikou_col,
            adx_col, adx_dip_col, adx_din_col
        )
        
        # --- 组合最终结果字典 --- 
        result_base.update(interpretation_result) # Merge results from _interpret_indicators
        return result_base

    except Exception as e:
        logger.error(f"{interval_prefix}Error in 分析单周期趋势: {e}", exc_info=True)
        result_base["error"] = "分析过程中断"
        return result_base

# --- 多周期分析协调函数 (新增) ---
def 执行多周期分析(symbol: str, market_type: str, intervals: List[str], config: dict, kline_limit_base: int = 100) -> Dict[str, Dict[str, Union[str, float, Dict[str, str], None]]]:
    """
    执行多周期微观趋势分析。

    Args:
        symbol (str): 交易对。
        market_type (str): 市场类型 ('spot' or 'futures')。
        intervals (list): 需要分析的时间周期列表 (e.g., ['1m', '5m', '15m', '1h'])。
        config (dict): 指标计算和解读的配置。
        kline_limit_base (int): 获取K线的基础数量，会根据指标周期适当调整。

    Returns:
        Dict: 键是时间周期, 值是包含该周期分析结果的字典 (来自 分析单周期趋势)。
    """
    results: Dict[str, Dict[str, Union[str, float, Dict[str, str], None]]] = {} # Type hint added
    if 数据获取模块 is None:
        logger.error("数据获取模块未加载，无法执行多周期分析。")
        return {"error": "数据获取模块不可用"}

    # 确定计算指标所需的最少 K 线数量 (基于配置中的最长周期)
    # (这个逻辑可以更精确，但简单起见，我们先用一个基数，或取配置中的最大值)
    max_period = max(
        config.get('ema_long_period', 30),
        config.get('bb_period', 20),
        config.get('macd_slow_period', 26) + config.get('macd_signal_period', 9),
        config.get('volume_ma_period', 20),
        config.get('kdj_length', 9) + config.get('kdj_signal', 3),
        config.get('ichimoku_senkou_b', 52) + config.get('ichimoku_kijun', 26), # Ichimoku 需要考虑位移
        config.get('adx_length', 14) * 2 # ADX 计算比较复杂，给些余量
    )
    required_limit = max(kline_limit_base, max_period + 5) # 加一点 buffer
    logger.info(f"多周期分析将为每个周期请求 {required_limit} 条 K 线数据。")

    for interval in intervals:
        logger.info(f"--- 开始分析周期: {interval} ---")
        # Store analysis result dictionary directly
        results[interval] = {"interval": interval, "combined_signal": "分析中...", "score": None, "details": None}
        try:
            # 1. 获取 K 线数据
            logger.debug(f"[{interval}] 获取 {symbol} {market_type} {interval} K线数据, limit={required_limit}...")
            kline_data = 数据获取模块.获取K线数据(
                symbol=symbol,
                interval=interval,
                limit=required_limit,
                market_type=market_type
            )

            if kline_data is None or kline_data.empty or len(kline_data) < 2: # 需要至少2条才能分析
                logger.warning(f"[{interval}] 未能获取到足够的 K 线数据 (获取到 {len(kline_data) if kline_data is not None else 0} 条)。")
                results[interval] = {"interval": interval, "error": "K线数据不足"}
                continue # 继续下一个周期
            
            logger.debug(f"[{interval}] 成功获取 {len(kline_data)} 条K线数据.")
            
            # 2. 计算指标
            data_with_indicators = _calculate_indicators(kline_data.copy(), config)

            if data_with_indicators is None or data_with_indicators.empty:
                logger.error(f"[{interval}] 指标计算失败或返回空的 DataFrame.")
                results[interval] = {"interval": interval, "error": "指标计算失败"}
                continue
                
            logger.debug(f"[{interval}] 指标计算完成.")
                
            # 3. 分析单周期趋势 (调用返回字典的函数) --- 
            single_interval_result = 分析单周期趋势(data_with_indicators, config, interval=interval)
            results[interval] = single_interval_result # Store the entire result dictionary
            # Log the combined signal and score for info
            log_signal = single_interval_result.get('combined_signal', 'N/A')
            log_score = single_interval_result.get('score')
            log_error = single_interval_result.get('error')
            if log_error:
                 logger.info(f"[{interval}] 分析完成 (有错误): {log_error}")
            else:
                 logger.info(f"[{interval}] 分析完成: 组合:{log_signal} (评分:{log_score})")

        except Exception as e:
            logger.error(f"[{interval}] 处理周期时发生意外错误: {e}", exc_info=True)
            results[interval] = {"interval": interval, "error": "周期处理异常"}
            
    logger.info("--- 多周期分析全部完成 ---")
    return results

# --- 多周期信号整合函数 (优化) ---
def 整合多周期信号(mtf_results: Dict[str, Dict[str, Union[str, float, Dict[str, str], None]]],
                   config: dict) -> Dict[str, Union[str, List[str], float, None]]: # 返回类型可能增加 score
    """
    根据配置规则整合多周期分析结果，生成结构化判断。
    新规则：基于配置的周期列表和权重进行加权评分，并检测冲突。

    Args:
        mtf_results (Dict): 执行多周期分析返回的结果字典。
        config (dict): 包含 'INTEGRATION' 配置的字典。

    Returns:
        Dict: 包含整合结果的字典, e.g., 
              {'type': 'StrongConfirmation', 'direction': 'Bullish', 'score': 2.5, 
               'periods_involved': ['1m', '5m', '15m', '1h', '4h'], 'message': '强烈看涨确认...'}
              or {'type': 'Conflicting', 'direction': 'Neutral', ...}
    """
    # !! 修改：直接从全局配置读取，不再依赖传入的 config['INTEGRATION'] !!
    try:
        intervals_to_integrate = getattr(配置, 'MOMENTUM_INTEGRATION_TIMEFRAMES', ['1m', '5m', '15m', '1h', '4h'])
        interval_weights = getattr(配置, 'MOMENTUM_INTEGRATION_WEIGHTS', {})
        conflict_diff_threshold = getattr(配置, 'MOMENTUM_CONFLICT_SCORE_DIFF_THRESHOLD', 5.0)
        # 加权阈值可以保留在函数内部或也移到配置
        weighted_bull_threshold = 1.5
        weighted_bear_threshold = -1.5
        conflict_ratio_threshold = 0.4 # 默认40%
    except AttributeError as e:
        logger.error(f"无法从 配置.py 读取整合配置: {e}，将使用默认值。")
        intervals_to_integrate = ['1m', '5m', '15m', '1h', '4h']
        interval_weights = {}
        conflict_diff_threshold = 5.0
        weighted_bull_threshold = 1.5
        weighted_bear_threshold = -1.5
        conflict_ratio_threshold = 0.4
        
    # 单项评分的阈值 (从传入的 config['SCORING'] 获取)
    scoring_thresholds = config.get('SCORING', {}).get('THRESHOLDS', {})
    single_bull_threshold = scoring_thresholds.get('bullish', 1.0) # 默认 1.0
    single_bear_threshold = scoring_thresholds.get('bearish', -1.0) # 默认 -1.0

    logger.info(f"开始整合信号. 整合周期: {intervals_to_integrate}, 权重: {interval_weights}, 冲突阈值: {conflict_diff_threshold}")

    # --- 提取相关周期的有效评分和权重 --- 
    valid_scores = {}
    total_weighted_score = 0.0
    total_weight = 0.0
    periods_involved = []
    
    for interval in intervals_to_integrate:
        result = mtf_results.get(interval)
        weight = interval_weights.get(interval)
        
        if result and not result.get("error") and result.get("score") is not None and weight is not None:
            score = result["score"]
            valid_scores[interval] = score
            total_weighted_score += score * weight
            total_weight += weight
            periods_involved.append(interval)
        elif weight is None:
             logger.warning(f"跳过周期 {interval}：未在配置中找到权重。")
        # else: 忽略错误或无分数的周期

    # --- 检查是否有足够的有效周期数据 --- 
    if not valid_scores or total_weight == 0:
        msg = f"无法整合：缺少足够的可用于整合的周期数据或有效权重。参与周期: {periods_involved}"
        logger.warning(msg)
        return {"type": "Error", "direction": "Neutral", "score": None, "periods_involved": periods_involved, "message": msg}
        
    # --- 计算加权平均分 --- 
    average_weighted_score = total_weighted_score / total_weight
    logger.info(f"计算完成: 总加权分={total_weighted_score:.2f}, 总权重={total_weight:.2f}, 平均加权分={average_weighted_score:.2f}")

    # --- 初步判断方向 --- 
    preliminary_direction = "Neutral"
    if average_weighted_score >= weighted_bull_threshold:
        preliminary_direction = "Bullish"
    elif average_weighted_score <= weighted_bear_threshold:
        preliminary_direction = "Bearish"
        
    # --- 冲突检测 --- 
    is_conflicting = False
    conflict_reasons = []
    num_bullish_periods = 0
    num_bearish_periods = 0
    scores_list = list(valid_scores.values())
    max_score = max(scores_list)
    min_score = min(scores_list)
    
    for score in scores_list:
        if score >= single_bull_threshold: # 使用单项评分阈值统计
            num_bullish_periods += 1
        elif score <= single_bear_threshold:
            num_bearish_periods += 1
            
    num_total_periods = len(scores_list)
    
    # 1. 检查评分差异
    score_diff = max_score - min_score
    if score_diff >= conflict_diff_threshold:
        is_conflicting = True
        conflict_reasons.append(f"评分差异过大({score_diff:.1f} >= {conflict_diff_threshold:.1f})，Max={max_score:.1f}, Min={min_score:.1f}")
        logger.debug("冲突检测：评分差异过大")
        
    # 2. 检查多空周期比例
    if num_total_periods > 1: # 至少需要两个周期才能比较比例
        if num_bullish_periods > 0 and num_bearish_periods > 0: # 同时存在多空信号
            # 计算少数派占比
            min_periods = min(num_bullish_periods, num_bearish_periods)
            minority_ratio = min_periods / num_total_periods
            if minority_ratio >= conflict_ratio_threshold:
                 is_conflicting = True
                 conflict_reasons.append(f"多空周期比例冲突(少数派占比 {minority_ratio:.2f} >= {conflict_ratio_threshold:.2f}，多:{num_bullish_periods},空:{num_bearish_periods})")
                 logger.debug("冲突检测：多空周期比例冲突")
        elif num_bullish_periods == 0 and num_bearish_periods == 0: # 全是中性或评分在阈值之间
             pass # 不是典型的冲突，但也不是强信号

    # --- 确定最终类型和消息 --- 
    final_type = "Neutral"
    final_direction = preliminary_direction
    message_parts = [f"整合信号(均分:{average_weighted_score:.2f})"]

    if is_conflicting:
        final_type = "Conflicting"
        final_direction = "Neutral" # 冲突时方向倾向于中性
        message_parts.append("信号冲突:")
        message_parts.extend([f"- {r}" for r in conflict_reasons])
        logger.info(f"整合结果: 信号冲突")
    else:
        # 非冲突情况，根据平均分强度判断
        abs_score = abs(average_weighted_score)
        # 使用加权阈值的倍数来判断强度 (可以调整这个逻辑)
        if preliminary_direction == "Bullish":
            if abs_score >= weighted_bull_threshold * 1.5: # 比如超过阈值的1.5倍算强确认
                final_type = "StrongConfirmation"
                message_parts.append("强烈看涨确认")
            else:
                final_type = "WeakConfirmation"
                message_parts.append("看涨信号(较弱)")
            logger.info(f"整合结果: {final_type} {preliminary_direction}")
        elif preliminary_direction == "Bearish":
            if abs_score >= abs(weighted_bear_threshold) * 1.5: # 比如超过阈值的1.5倍算强确认
                final_type = "StrongConfirmation"
                message_parts.append("强烈看跌确认")
            else:
                final_type = "WeakConfirmation"
                message_parts.append("看跌信号(较弱)")
            logger.info(f"整合结果: {final_type} {preliminary_direction}")
        else: # Neutral
             final_type = "Neutral"
             message_parts.append("信号中性或强度不足")
             logger.info(f"整合结果: 中性")

    result_dict = {
        "type": final_type, 
        "direction": final_direction, 
        "score": round(average_weighted_score, 2), # 保留两位小数
        "periods_involved": periods_involved, 
        "message": "\n".join(message_parts)
    }
    
    # --- 添加中文映射 --- 
    type_cn_map = {
        'StrongConfirmation': '强力确认',
        'WeakConfirmation': '弱确认',
        'Conflicting': '信号冲突',
        'Neutral': '中性',
        'Error': '错误',
        'Incomplete Data': '数据不足'
    }
    direction_cn_map = {
        'Bullish': '看涨',
        'Bearish': '看跌',
        'Neutral': '中性'
    }
    
    result_dict['type'] = type_cn_map.get(final_type, final_type) # 替换为中文，找不到则保留原文
    result_dict['direction'] = direction_cn_map.get(final_direction, final_direction) # 替换为中文
    
    return result_dict

# --- 主逻辑和测试 ---
if __name__ == '__main__':
    test_symbol = 'BTCUSDT'
    test_market_type = 'futures'
    # !!! 更新：从配置读取要分析的时间周期列表 !!!
    try:
        intervals_to_analyze = getattr(配置, 'MOMENTUM_TIMEFRAMES', ['1m', '5m', '15m', '1h', '4h', '1d', '1w'])
        # 从配置读取测试循环参数
        num_iterations = getattr(配置, 'TEST_LOOP_ITERATIONS', 2)
        interval_seconds = getattr(配置, 'TEST_LOOP_INTERVAL', 10)
    except AttributeError as e:
        logger.error(f"无法从 配置.py 读取分析周期或测试循环参数: {e}，将使用默认值。")
        intervals_to_analyze = ['1m', '5m', '15m', '1h', '4h', '1d', '1w']
        num_iterations = 2
        interval_seconds = 10

    logger.info(f"--- 测试 微观趋势动量模块 (多周期) ({test_symbol}, {test_market_type.upper()}) ---")
    logger.info(f"计划分析周期: {intervals_to_analyze}")
    logger.info(f"测试循环次数: {num_iterations}, 间隔: {interval_seconds}秒") # 添加日志

    # --- 获取配置 --- 
    # 从 配置 模块导入集中管理的配置
    # (已在文件顶部导入: from 配置 import MICRO_TREND_CONFIG)
    if 配置 is None or not hasattr(配置, 'MICRO_TREND_CONFIG'): # 检查配置模块和变量是否存在
         logger.error("配置.py 未加载或缺少 MICRO_TREND_CONFIG，无法执行分析。")
         micro_trend_config_to_use = {} # 使用空字典以防后续代码出错
    else:
        micro_trend_config_to_use = 配置.MICRO_TREND_CONFIG
        logger.debug(f"使用导入的配置: {micro_trend_config_to_use}")

    # --- 执行分析 --- 
    # 调用多周期分析函数，传入获取到的配置字典
    mtf_results = 执行多周期分析(
        symbol=test_symbol,
        market_type=test_market_type,
        intervals=intervals_to_analyze,
        config=micro_trend_config_to_use, # 使用从配置加载的字典
        kline_limit_base=100 
    )

    # --- 打印原始多周期结果 --- 
    print("\n--- Multi-Timeframe Analysis Results (Raw) ---")
    if isinstance(mtf_results, dict):
        max_interval_len = max(len(interval) for interval in mtf_results.keys()) if mtf_results else 3
        for interval in intervals_to_analyze:
            result = mtf_results.get(interval)
            if result and not result.get('error'):
                # 格式化输出，包含信号和评分
                signal_str = result.get('combined_signal', 'N/A')
                score_val = result.get('score')
                score_str = f"(评分:{score_val:.1f})" if score_val is not None else ""
                print(f"{interval:>{max_interval_len}s}: 组合:{signal_str} {score_str}")
            elif result and result.get('error'):
                 print(f"{interval:>{max_interval_len}s}: 错误: {result.get('error')}")
            else:
                print(f"{interval:>{max_interval_len}s}: 未分析或出错")
    else:
        print("多周期分析未能返回有效结果。")

    # --- 执行并打印整合信号 --- 
    if isinstance(mtf_results, dict) and intervals_to_analyze:
        # 调用整合函数 (现在直接从 配置 读取整合参数，但仍需传入指标计算相关的 config)
        integration_result = 整合多周期信号(mtf_results, config=micro_trend_config_to_use)
        print("\n--- Integrated Multi-Timeframe Signal --- ")
        # 打印结构化结果
        if isinstance(integration_result, dict):
            print(f"  类型: {integration_result.get('type', 'N/A')}")
            print(f"  方向: {integration_result.get('direction', 'N/A')}")
            print(f"  涉及周期: {integration_result.get('periods_involved', [])}")
            print(f"  消息: {integration_result.get('message', 'N/A')}")
        else:
             print(f"整合信号返回格式错误: {integration_result}")
    else:
        logger.warning("无法执行信号整合，因为多周期分析结果无效或未执行。")
