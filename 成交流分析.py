'''
成交流分析模块 (Trade Flow / Tape Reading)

分析实时成交记录，识别主动买卖力量、大单成交等。
'''

import logging
import pandas as pd
from pathlib import Path
import time
from datetime import datetime, timezone, timedelta
import numpy as np

# 导入自定义模块
import 配置
import 数据获取模块

# --- 日志配置 ---
log_level = getattr(logging, 配置.LOG_LEVEL.upper(), logging.INFO)
log_file = Path(配置.LOG_FILE) # 使用与数据获取模块相同的日志文件
log_file.parent.mkdir(parents=True, exist_ok=True)

log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 文件处理器 (追加模式)
file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.DEBUG)

# 控制台处理器
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(log_formatter)
stream_handler.setLevel(log_level)

# 获取日志记录器
logger = logging.getLogger(__name__) # 使用模块名
logger.setLevel(log_level)
if not logger.handlers: # 防止重复添加 handler
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

logger.info("成交流分析模块日志记录器初始化完成。")

# --- 内部辅助函数 ---
def _calculate_trade_metrics(df, large_order_percentiles=[98]):
    """
    计算给定时间窗口内成交记录的各项指标。

    Args:
        df (pd.DataFrame): 包含时间窗口内成交记录的 DataFrame。
                           需要 'timestamp', 'price', 'quoteQty', 'is_buyer_maker' 列。
        large_order_percentiles (list): 要计算的大单成交额百分位列表。

    Returns:
        dict: 包含各项计算指标的字典。
    """
    metrics = {}
    if df.empty:
        # 返回一个包含所有期望键的空/默认值字典，以便后续处理统一
        metrics = {
            'start_time': None, 'end_time': None, 'time_span_seconds': 0,
            'first_price': None, 'last_price': None, 'high_price': None, 'low_price': None,
            'total_quote_volume': 0.0, 'total_trades': 0,
            'taker_buy_quote_volume': 0.0, 'taker_sell_quote_volume': 0.0,
            'taker_buy_trades': 0, 'taker_sell_trades': 0,
            'taker_volume_ratio': None, 'taker_trade_ratio': None,
            'delta_volume': None, # <--- 包含 Delta
            'large_trades_analysis': {},
            'trades_per_second': 0.0, 'avg_trade_size_quote': None,
            'price_change_pct': None
        }
        for p in large_order_percentiles:
             metrics['large_trades_analysis'][p] = {} # 初始化大单分析为空字典
        return metrics

    # --- 时间跨度 ---
    start_time = df['timestamp'].min()
    end_time = df['timestamp'].max()
    time_span = (end_time - start_time).total_seconds()
    # 如果只有一条记录，时间跨度为0，后续频率计算可能需要特殊处理
    if time_span == 0 and len(df) == 1:
         time_span = 1.0 # 假设至少跨越1秒，避免除零

    # --- 基本价格和成交量统计 ---
    first_price = df['price'].iloc[0]
    last_price = df['price'].iloc[-1]
    high_price = df['price'].max()
    low_price = df['price'].min()
    total_volume = df['quoteQty'].sum()
    total_trades = len(df)

    # --- 主动买卖统计 ---
    t_buy_vol = None
    t_sell_vol = None
    t_buy_trades = None
    t_sell_trades = None
    if 'is_buyer_maker' in df.columns:
        # 假设 is_buyer_maker 已经根据 market_type 调整过含义
        # True = Taker Sell, False = Taker Buy
        is_taker_sell = df['is_buyer_maker']
        t_buy_vol = df.loc[~is_taker_sell, 'quoteQty'].sum()
        t_sell_vol = df.loc[is_taker_sell, 'quoteQty'].sum()
        t_buy_trades = (~is_taker_sell).sum()
        t_sell_trades = is_taker_sell.sum()
    else:
        logger.warning("成交数据缺少 'is_buyer_maker' 列，无法计算主动买卖指标。")

    # --- 大单分析 --- 
    large_trades_analysis = {}
    if 'quoteQty' in df.columns and not df['quoteQty'].empty:
        for percentile in large_order_percentiles:
            try:
                threshold = np.percentile(df['quoteQty'], percentile)
                large_trades_df = df[df['quoteQty'] >= threshold]
                large_metrics = {}
                if not large_trades_df.empty:
                     large_metrics = _calculate_large_trade_metrics(large_trades_df) # 调用辅助函数
                large_trades_analysis[percentile] = {
                    'large_order_threshold_quote': threshold,
                    **large_metrics # 合并大单计算结果
                }
            except Exception as e:
                 logger.error(f"计算 P{percentile} 大单指标时出错: {e}")
                 large_trades_analysis[percentile] = {'error': str(e)}
    else:
         logger.warning("无法进行大单分析，缺少 'quoteQty' 列或数据为空。")
         for p in large_order_percentiles:
             large_trades_analysis[p] = {'error': '缺少成交额数据'} # 初始化为空或错误

    # --- 衍生指标 --- 
    taker_volume_ratio = t_buy_vol / t_sell_vol if t_sell_vol is not None and t_sell_vol != 0 else np.inf if t_buy_vol is not None and t_buy_vol > 0 else None
    taker_trade_ratio = t_buy_trades / t_sell_trades if t_sell_trades is not None and t_sell_trades > 0 else np.inf if t_buy_trades is not None and t_buy_trades > 0 else None
    trades_per_second = total_trades / time_span if time_span is not None and time_span > 0 else None
    avg_trade_size_quote = total_volume / total_trades if total_trades > 0 else None
    price_change_pct = (last_price - first_price) / first_price * 100 if first_price is not None and first_price != 0 else None

    # --- 计算 Delta ---
    delta_volume = None
    if t_buy_vol is not None and t_sell_vol is not None:
        delta_volume = t_buy_vol - t_sell_vol
    # ----------------------

    metrics = {
        'start_time': start_time,
        'end_time': end_time,
        'time_span_seconds': time_span,
        'first_price': first_price,
        'last_price': last_price,
        'high_price': high_price,
        'low_price': low_price,
        'total_quote_volume': total_volume,
        'total_trades': total_trades,
        'taker_buy_quote_volume': t_buy_vol,
        'taker_sell_quote_volume': t_sell_vol,
        'taker_buy_trades': t_buy_trades,
        'taker_sell_trades': t_sell_trades,
        'taker_volume_ratio': taker_volume_ratio,
        'taker_trade_ratio': taker_trade_ratio,
        'delta_volume': delta_volume, # <-- 确认 Delta 在结果中
        'large_trades_analysis': large_trades_analysis,
        'trades_per_second': trades_per_second,
        'avg_trade_size_quote': avg_trade_size_quote,
        'price_change_pct': price_change_pct
    }
    return metrics

# --- 内部辅助函数：计算大单具体指标 --- 
def _calculate_large_trade_metrics(large_trades_df):
    """计算大单 DataFrame 的具体指标，如成交量、VWAP 等。"""
    metrics = {
        'large_trades_count': 0,
        'large_total_quote_volume': 0.0,
        'large_taker_buy_quote_volume': None,
        'large_taker_sell_quote_volume': None,
        'large_taker_volume_ratio': None,
        'large_taker_buy_trades': None,
        'large_taker_sell_trades': None,
        'large_taker_trade_ratio': None,
        'large_taker_buy_vwap': None,
        'large_taker_sell_vwap': None,
        'large_trades_price_stddev': None,
        'large_trades_min_price': None,
        'large_trades_max_price': None
    }
    if large_trades_df.empty:
        return metrics

    metrics['large_trades_count'] = len(large_trades_df)
    metrics['large_total_quote_volume'] = large_trades_df['quoteQty'].sum()

    # 计算大单价格标准差
    if metrics['large_trades_count'] > 1:
        try: metrics['large_trades_price_stddev'] = large_trades_df['price'].std()
        except Exception as std_e: logger.warning(f"计算大单价格标准差时出错: {std_e}")

    # 计算大单价格范围
    try:
        metrics['large_trades_min_price'] = large_trades_df['price'].min()
        metrics['large_trades_max_price'] = large_trades_df['price'].max()
    except Exception as range_e: logger.warning(f"计算大单价格范围时出错: {range_e}")

    # 计算大单主动性指标和 VWAP (如果可用)
    if 'is_buyer_maker' in large_trades_df.columns:
        is_taker_sell = large_trades_df['is_buyer_maker']
        large_taker_buy_volume = large_trades_df.loc[~is_taker_sell, 'quoteQty'].sum()
        large_taker_sell_volume = large_trades_df.loc[is_taker_sell, 'quoteQty'].sum()
        metrics['large_taker_buy_quote_volume'] = large_taker_buy_volume
        metrics['large_taker_sell_quote_volume'] = large_taker_sell_volume
        if large_taker_sell_volume is not None and large_taker_sell_volume > 0: metrics['large_taker_volume_ratio'] = large_taker_buy_volume / large_taker_sell_volume
        elif large_taker_buy_volume is not None and large_taker_buy_volume > 0: metrics['large_taker_volume_ratio'] = float('inf')
        else: metrics['large_taker_volume_ratio'] = None

        large_taker_buy_trades = (~is_taker_sell).sum()
        large_taker_sell_trades = is_taker_sell.sum()
        metrics['large_taker_buy_trades'] = large_taker_buy_trades
        metrics['large_taker_sell_trades'] = large_taker_sell_trades
        if large_taker_sell_trades is not None and large_taker_sell_trades > 0: metrics['large_taker_trade_ratio'] = large_taker_buy_trades / large_taker_sell_trades
        elif large_taker_buy_trades is not None and large_taker_buy_trades > 0: metrics['large_taker_trade_ratio'] = float('inf')
        else: metrics['large_taker_trade_ratio'] = None

        # 计算大单 VWAP
        large_buy_df = large_trades_df[~is_taker_sell]
        if not large_buy_df.empty and 'quantity' in large_buy_df.columns:
            buy_numerator = (large_buy_df['price'] * large_buy_df['quantity']).sum()
            buy_denominator = large_buy_df['quantity'].sum()
            if buy_denominator is not None and buy_denominator > 0: metrics['large_taker_buy_vwap'] = buy_numerator / buy_denominator
        
        large_sell_df = large_trades_df[is_taker_sell]
        if not large_sell_df.empty and 'quantity' in large_sell_df.columns:
            sell_numerator = (large_sell_df['price'] * large_sell_df['quantity']).sum()
            sell_denominator = large_sell_df['quantity'].sum()
            if sell_denominator is not None and sell_denominator > 0: metrics['large_taker_sell_vwap'] = sell_numerator / sell_denominator
            
    return metrics

# --- 核心功能 ---

def 获取并处理近期成交(symbol, limit=100, market_type='spot'):
    """
    获取指定交易对指定市场的近期成交记录，并进行初步处理。

    Args:
        symbol (str): 交易对, e.g., 'BTCUSDT'.
        limit (int): 获取的成交记录数量上限。
        market_type (str): 市场类型, 'spot' 或 'futures'.

    Returns:
        pd.DataFrame or None: 包含处理后成交数据的 DataFrame。
                              对于现货，包含 'trade_type' 列。
                              对于合约，可能不包含 'isBuyerMaker' 和 'trade_type' 列。
    """
    logger.debug(f"获取 {symbol} ({market_type}) 的 {limit} 条近期成交记录...")

    df = None
    if market_type == 'spot':
        df = 数据获取模块.获取近期成交记录(symbol, limit=limit)
    elif market_type == 'futures':
        logger.info(f"合约市场 ({symbol})：使用聚合交易记录进行分析。")
        df = 数据获取模块.获取聚合交易记录(symbol, limit=limit)
        # 注意：聚合交易数据可能没有 quoteQty，isBuyerMaker 意义相反
    else:
        logger.error(f"无效的市场类型: {market_type}。仅支持 'spot' 或 'futures'。")
        return None

    if df is None:
        logger.error(f"无法获取 {symbol} ({market_type}) 的近期成交记录。")
        return None
    if not isinstance(df, pd.DataFrame):
        logger.error(f"数据获取模块返回类型错误: {type(df)}。")
        return None

    # --- 调试信息 (可选，可以注释掉) ---
    # print(f"[调试] {market_type} 模块返回的列: {df.columns.tolist()}")
    # print(f"[调试] {market_type} 模块返回的 DataFrame (前5行):")
    # print(df.head())
    # ---

    if df.empty:
        logger.warning(f"{symbol} ({market_type}) 近期无成交或返回为空。")
        return df

    try:
        # 0. 统一 Taker 方向列名为 'is_buyer_maker' (小写)
        if 'isBuyerMaker' in df.columns: # 检查现货原始列名 (大写 B)
            df = df.rename(columns={'isBuyerMaker': 'is_buyer_maker'})
        elif 'm' in df.columns: # 检查聚合数据原始列名 ('m')
            df = df.rename(columns={'m': 'is_buyer_maker'})
        # else: 可能两种都没有，后续检查会处理

        # 尝试重命名其他列名
        if 'time' in df.columns: df = df.rename(columns={'time': 'timestamp'})
        if 'qty' in df.columns: df = df.rename(columns={'qty': 'quantity'})
        if 'p' in df.columns: df = df.rename(columns={'p': 'price'})
        if 'q' in df.columns: df = df.rename(columns={'q': 'quantity'})
        if 'T' in df.columns: df = df.rename(columns={'T': 'timestamp'})

        # 计算 quoteQty (如果不存在)
        if 'quoteQty' not in df.columns and all(col in df.columns for col in ['price', 'quantity']):
            logger.debug(f"计算 {market_type} 数据的 quoteQty (price * quantity)...")
            df['quoteQty'] = df['price'] * df['quantity']
        elif 'quoteQty' not in df.columns:
             logger.error(f"无法计算 quoteQty，缺少 price 或 quantity 列。列: {df.columns.tolist()}")
             return None

        # 1. 检查所有必需的最终列是否存在
        required_cols = {'timestamp', 'price', 'quantity', 'quoteQty', 'is_buyer_maker'}
        missing_cols = required_cols - set(df.columns)
        if missing_cols:
            # 特别检查 is_buyer_maker 是否确实没有被任何方式提供
            if 'is_buyer_maker' in missing_cols:
                 logger.warning(f"DataFrame ({market_type}) 缺少 Taker 方向信息 ('is_buyer_maker' 或 'm')。将无法计算主动买卖指标。")
                 # 从必需列中移除，允许继续处理，但没有主动性分析
                 required_cols.remove('is_buyer_maker')
                 missing_cols = required_cols - set(df.columns)
                 if missing_cols: # 如果移除后还有缺失，则报错
                     logger.error(f"处理后的 DataFrame ({market_type}) 缺少基本列: {missing_cols}")
                     return None
            else: # 如果缺少的是其他列
                logger.error(f"处理后的 DataFrame ({market_type}) 缺少必要列: {missing_cols}")
                return None

        # 2. 确保数据类型正确
        try:
            df['price'] = pd.to_numeric(df['price'], errors='coerce')
            df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce')
            df['quoteQty'] = pd.to_numeric(df['quoteQty'], errors='coerce')
            if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
                 df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True, errors='coerce')
            elif df['timestamp'].dt.tz is None:
                 df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
            # 只有当 is_buyer_maker 列实际存在时才转换它
            if 'is_buyer_maker' in df.columns:
                df['is_buyer_maker'] = df['is_buyer_maker'].astype(bool)
        except Exception as type_e:
             logger.error(f"转换数据类型时出错 ({market_type}): {type_e}")
             return None

        # 3. 丢弃转换失败或必要列为空的数据
        df = df.dropna(subset=list(required_cols)) # 使用可能已修改的 required_cols
        if df.empty: logger.warning(f"处理 {symbol} ({market_type}) 成交数据后为空。"); return df

        # 4. 计算 trade_type (仅当 is_buyer_maker 存在时)
        final_cols = list(required_cols)
        if 'is_buyer_maker' in df.columns:
            try:
                if market_type == 'spot':
                    # 现货: is_buyer_maker=False -> Taker Buy
                    df['trade_type'] = df['is_buyer_maker'].apply(lambda x: 'Taker Sell' if x else 'Taker Buy')
                elif market_type == 'futures':
                    # 合约(聚合): is_buyer_maker=True ('m'=True) -> Taker Sell
                    df['trade_type'] = df['is_buyer_maker'].apply(lambda x: 'Taker Sell' if x else 'Taker Buy')
                final_cols.append('trade_type') # 只有成功计算才加入最终列
            except Exception as tt_e:
                 logger.error(f"计算 trade_type 时出错 ({market_type}): {tt_e}")
                 # 不中断，但后续分析会缺少 trade_type
        else:
             logger.debug(f"DataFrame ({market_type}) 无 Taker 方向信息，跳过 trade_type 计算。")

        # 5. 选择最终列并排序
        final_cols_present = list(set(final_cols) & set(df.columns))
        df = df[final_cols_present].sort_values(by='timestamp').reset_index(drop=True)

        logger.debug(f"成功处理了 {len(df)} 条 {symbol} ({market_type}) 的成交记录。")
        return df

    except Exception as e:
        logger.error(f"处理 {symbol} ({market_type}) 成交数据时发生意外错误: {e}", exc_info=True)
        return None

def 分析成交流(symbol: str, market_type: str = 'spot', 
             limit: int = 1000, 
             large_order_percentiles=[98], 
             time_windows_seconds=None):
    """
    获取并分析指定交易对指定市场的近期成交记录。
    (此函数现在负责获取数据)

    Args:
        symbol (str): 交易对标识符。
        market_type (str): 市场类型 ('spot' 或 'futures')。
        limit (int): 获取的成交记录数量上限。
        large_order_percentiles (list[int]): 定义大单的百分位列表。
        time_windows_seconds (list[int], optional): 需要分析的时间窗口列表（秒）。
                                                  如果为 None，则只分析整体。

    Returns:
        dict: 包含整体分析和各时间窗口分析结果的字典。
    """
    analysis_output = {'overall': {}, 'windows': {}, 'interpretation': {}, 'error': None}
    
    # --- 1. 获取并处理数据 ---
    try:
        trades_df = 获取并处理近期成交(symbol, limit=limit, market_type=market_type)
        if trades_df is None or trades_df.empty:
             logger.warning(f"分析成交流({symbol}, {market_type}): 未能获取或处理成交数据。")
             analysis_output['error'] = "未能获取或处理成交数据"
             return analysis_output
        logger.debug(f"成功获取并处理了 {len(trades_df)} 条成交数据 for {symbol} ({market_type})")
    except Exception as e:
        logger.error(f"在分析成交流({symbol}, {market_type}) 的数据获取阶段出错: {e}", exc_info=True)
        analysis_output['error'] = f"数据获取/处理失败: {e}"
        return analysis_output
        
    # --- 2. 分析整体时间段 --- 
    try:
        logger.debug(f"分析整体 ({len(trades_df)} 条记录) ...")
        analysis_output['overall'] = _calculate_trade_metrics(trades_df, large_order_percentiles)
    except Exception as e:
         logger.error(f"分析整体成交流({symbol})时出错: {e}", exc_info=True)
         analysis_output['overall'] = {'error': str(e)}
         # 即使整体分析出错，也尝试继续分析时间窗口

    # --- 3. 分析指定时间窗口 --- 
    if time_windows_seconds:
        # ... (时间窗口分析逻辑保持不变) ...
        now = pd.Timestamp.now(tz='UTC') # 使用 UTC 时间
        for window_sec in time_windows_seconds:
             window_key = f'{window_sec}s'
             try:
                 start_time = now - pd.Timedelta(seconds=window_sec)
                 window_df = trades_df[trades_df['timestamp'] >= start_time]
                 logger.debug(f"分析时间窗口 {window_key} ({len(window_df)} 条记录) ...")
                 if not window_df.empty:
                     analysis_output['windows'][window_key] = _calculate_trade_metrics(window_df, large_order_percentiles)
                 else:
                     logger.debug(f"时间窗口 {window_key} 内无成交数据。")
                     analysis_output['windows'][window_key] = _calculate_trade_metrics(pd.DataFrame(columns=trades_df.columns)) # 返回空指标结构
             except Exception as e:
                  logger.error(f"分析时间窗口 {window_key} ({symbol}) 时出错: {e}", exc_info=True)
                  analysis_output['windows'][window_key] = {'error': str(e)}

    # --- 4. 生成解读 --- 
    try:
        analysis_output['interpretation'] = 解读成交流分析(analysis_output)
    except Exception as e:
         logger.error(f"解读成交流分析({symbol})时出错: {e}", exc_info=True)
         # 不覆盖之前的 error，但记录解读错误
         analysis_output['interpretation'] = {'error': f"解读失败: {e}"}
         if not analysis_output['error']: # 如果之前没错误，才记录这个
              analysis_output['error'] = "解读阶段出错"

    return analysis_output

def 解读成交流分析(analysis_results, previous_analysis=None):
    """
    根据分析结果字典生成可读的解读和评分。

    Args:
        analysis_results (dict): 来自 `分析成交流` 的结果字典。
        previous_analysis (dict, optional): 上一轮的分析结果 (结构同 analysis_results)。

    Returns:
        dict: 包含 'overall', 'bias_score', 'is_conflicting_refined', 'time_segments' 等键的综合解读字典。
    """
    interpretation_details_by_scope = {}
    overall_summary = []
    overall_details = []
    bias_score = 0 # 初始化总评分
    is_conflicting_refined = False # 初始化精细冲突标志

    # 从配置导入阈值，如果配置不存在则使用默认值
    try:
        thresholds = 配置.TRADE_FLOW_INTERPRETATION_THRESHOLDS
        logger.debug("成功加载成交流解读阈值配置。")
    except AttributeError:
        logger.warning("在 配置.py 中未找到 TRADE_FLOW_INTERPRETATION_THRESHOLDS，使用默认阈值。")
        thresholds = {
            'taker_vol_strong_buy': 2.0, 'taker_vol_weak_buy': 1.3,
            'taker_vol_weak_sell': 0.7, 'taker_vol_strong_sell': 0.5,
            'large_taker_vol_strong_buy': 1.8, 'large_taker_vol_weak_buy': 1.2,
            'large_taker_vol_weak_sell': 0.8, 'large_taker_vol_strong_sell': 0.6,
            'large_vol_contribution_pct': 20.0,
            'large_trade_contribution_pct': 10.0,
            'trend_ratio_change_threshold': 0.2,
            'trend_large_count_change_threshold': 0.3,
            'trend_large_volume_change_threshold': 0.3,
            'trend_frequency_change_threshold': 0.3,
            'price_change_significant_pct': 0.1,
            'trend_avg_trade_size_change_threshold': 0.25,
            'large_price_stddev_high_pct': 0.15
        }

    # 提取所有范围的 metrics
    all_scopes = {} # 先收集所有有效的 metrics
    if 'overall' in analysis_results and analysis_results['overall']:
        all_scopes['overall'] = analysis_results['overall']
    if 'windows' in analysis_results:
        all_scopes.update(analysis_results['windows'])

    # 用于计算最终 bias_score 的加权分数
    weighted_score_sum = 0
    total_weight = 0
    # 定义不同时间窗口的权重 (例如，越近权重越高)
    scope_weights = {
        '60s': 1.5,
        '300s': 1.0,
        '900s': 0.8,
        'overall': 0.5 # 整体权重相对较低
    }

    for scope, metrics in all_scopes.items():
        scope_interpretations = []
        scope_score = 0 # 初始化当前范围的评分

        if not metrics or metrics.get('total_trades', 0) == 0:
            scope_interpretations.append("(无有效成交数据)")
            interpretation_details_by_scope[scope] = {'details': scope_interpretations, 'score': 0}
            continue

        # --- 获取上一次指标并判断趋势 ---
        prev_metrics = None
        if previous_analysis and scope in previous_analysis:
            prev_data = previous_analysis[scope]
            if isinstance(prev_data, dict) and prev_data.get('total_trades', 0) > 0:
                 prev_metrics = prev_data

        trend_interpretations = []
        current_ratio = metrics.get('taker_volume_ratio')
        if prev_metrics and current_ratio is not None:
            prev_ratio = prev_metrics.get('taker_volume_ratio')
            if prev_ratio is not None and prev_ratio > 0:
                ratio_change = (current_ratio - prev_ratio) / prev_ratio
                if ratio_change > thresholds.get('trend_ratio_change_threshold', 0.2):
                    trend_interpretations.append("买盘增强")
                elif ratio_change < -thresholds.get('trend_ratio_change_threshold', 0.2):
                    trend_interpretations.append("卖压增强")

        current_large_count = metrics.get('large_trades_count')
        if prev_metrics and current_large_count is not None:
             prev_large_count = prev_metrics.get('large_trades_count')
             if prev_large_count is not None and prev_large_count > 0: # 只有上一次有大单才比较趋势
                 count_change = (current_large_count - prev_large_count) / prev_large_count
                 if count_change > thresholds.get('trend_large_count_change_threshold', 0.3):
                     trend_interpretations.append("大单数量增加")
                 elif count_change < -thresholds.get('trend_large_count_change_threshold', 0.3):
                     trend_interpretations.append("大单数量减少")
             elif current_large_count > 0: # 上次没有，这次有
                 trend_interpretations.append("出现大单")

        current_large_vol = metrics.get('large_total_quote_volume')
        if prev_metrics and current_large_vol is not None:
             prev_large_vol = prev_metrics.get('large_total_quote_volume')
             if prev_large_vol is not None and prev_large_vol > 0:
                 volume_change = (current_large_vol - prev_large_vol) / prev_large_vol
                 if volume_change > thresholds.get('trend_large_volume_change_threshold', 0.3):
                     trend_interpretations.append("大单金额放大")
                 elif volume_change < -thresholds.get('trend_large_volume_change_threshold', 0.3):
                     trend_interpretations.append("大单金额萎缩")
             elif current_large_vol > 0: # 上次没有，这次有
                 trend_interpretations.append("出现大额成交") # 与数量的解读略区别

        current_freq = metrics.get('trades_per_second')
        if prev_metrics and current_freq is not None:
            prev_freq = prev_metrics.get('trades_per_second')
            if prev_freq is not None and prev_freq > 0:
                freq_change = (current_freq - prev_freq) / prev_freq
                if freq_change > thresholds.get('trend_frequency_change_threshold', 0.3):
                    trend_interpretations.append("交易频率加快")
                elif freq_change < -thresholds.get('trend_frequency_change_threshold', 0.3):
                    trend_interpretations.append("交易频率放缓")

        # --- 新增：趋势 5: 平均成交额变化 ---
        current_avg_size = metrics.get('avg_trade_size_quote')
        if prev_metrics and current_avg_size is not None:
            prev_avg_size = prev_metrics.get('avg_trade_size_quote')
            if prev_avg_size is not None and prev_avg_size > 0:
                size_change = (current_avg_size - prev_avg_size) / prev_avg_size
                threshold = thresholds.get('trend_avg_trade_size_change_threshold', 0.25)
                if size_change > threshold:
                    trend_interpretations.append("平均成交额增大")
                elif size_change < -threshold:
                    trend_interpretations.append("平均成交额减小")

        # --- 组合和添加解读，并进行评分 --- 
        # 1. 解读整体主动买卖量 (基础解读)
        base_interpretation = "→ 买卖力量均衡"
        base_score_adj = 0
        if current_ratio is not None:
             if current_ratio > thresholds['taker_vol_strong_buy']: 
                 base_interpretation = "↑ 主动买盘强劲"
                 base_score_adj = 2
             elif current_ratio > thresholds['taker_vol_weak_buy']: 
                 base_interpretation = "↑ 主动买盘占优"
                 base_score_adj = 1
             elif current_ratio < thresholds['taker_vol_strong_sell']: 
                 base_interpretation = "↓ 主动卖压沉重"
                 base_score_adj = -2
             elif current_ratio < thresholds['taker_vol_weak_sell']: 
                 base_interpretation = "↓ 主动卖压占优"
                 base_score_adj = -1
        scope_interpretations.append(base_interpretation)
        scope_score += base_score_adj

        # --- 新增：解读价格变化与成交量关系 (可以影响评分) ---
        price_change_pct = metrics.get('price_change_pct')
        price_relation_interp = ""
        price_score_adj = 0
        if price_change_pct is not None and current_ratio is not None:
            price_threshold = thresholds.get('price_change_significant_pct', 0.1)
            price_moved_up = price_change_pct > price_threshold
            price_moved_down = price_change_pct < -price_threshold

            if base_interpretation.startswith("↑") and price_moved_down:
                 price_relation_interp = "-> 买盘强劲但价格受阻下跌(↓!)"
                 price_score_adj = -1 # 价格行为与量能背离，降低看涨评分
            elif base_interpretation.startswith("↓") and price_moved_up:
                 price_relation_interp = "-> 卖压沉重但价格反向上涨(↑!)"
                 price_score_adj = 1 # 价格行为与量能背离，降低看跌评分
            elif base_interpretation.startswith("↑") and price_moved_up:
                 price_relation_interp = "-> 买盘推动价格上涨(↑)"
                 price_score_adj = 0.5 # 量价配合，略微增加看涨评分
            elif base_interpretation.startswith("↓") and price_moved_down:
                 price_relation_interp = "-> 卖压导致价格下跌(↓)"
                 price_score_adj = -0.5 # 量价配合，略微增加看跌评分
            if price_relation_interp:
                scope_interpretations.append(price_relation_interp)
        scope_score += price_score_adj

        # 2. 解读大单情况 (增加评分逻辑)
        large_trade_score_adj = 0
        if 'large_trades_analysis' in metrics and metrics['large_trades_analysis']:
            primary_percentile = getattr(配置, 'TRADE_FLOW_PRIMARY_PERCENTILE', 98) # 使用主要百分位评分
            if primary_percentile in metrics['large_trades_analysis']:
                large_metrics = metrics['large_trades_analysis'][primary_percentile]
                # --- 大单方向评分 --- 
                large_trades_count = large_metrics.get('large_trades_count', 0)
                if large_trades_count > 0:
                    large_ratio = large_metrics.get('large_taker_volume_ratio')
                    if large_ratio is not None:
                        # 大单评分权重更高
                        if large_ratio > thresholds['large_taker_vol_strong_buy']: large_trade_score_adj = 1.5
                        elif large_ratio > thresholds['large_taker_vol_weak_buy']: large_trade_score_adj = 0.75
                        elif large_ratio < thresholds['large_taker_vol_strong_sell']: large_trade_score_adj = -1.5
                        elif large_ratio < thresholds['large_taker_vol_weak_sell']: large_trade_score_adj = -0.75
            # ... (其他百分位的解读文本逻辑保持不变) ...
        scope_score += large_trade_score_adj

        # 3. 添加趋势解读 (如果有)
        if trend_interpretations:
             scope_interpretations.append(f"趋势: {', '.join(trend_interpretations)}")

        # --- 新增：初步的 Delta 散度判断 --- 
        current_delta = metrics.get('delta_volume')
        current_price_change = metrics.get('price_change_pct')
        current_last_price = metrics.get('last_price') # 需要当前价格来判断高低
        delta_divergence_interp = None
        delta_divergence_score_adj = 0

        if prev_metrics and current_delta is not None and current_price_change is not None and current_last_price is not None:
            prev_delta = prev_metrics.get('delta_volume')
            prev_price_change = prev_metrics.get('price_change_pct')
            prev_last_price = prev_metrics.get('last_price') # 需要前一个价格

            if prev_delta is not None and prev_price_change is not None and prev_last_price is not None:
                # 定义价格高低点判断的微小阈值 (避免完全相等的情况)
                price_diff_threshold = 0.0001 * current_last_price 
                
                # 看涨背离条件: 价格创新低或持平低位，但 Delta 改善
                price_lower = current_last_price < prev_last_price - price_diff_threshold
                price_equal_low = abs(current_last_price - prev_last_price) <= price_diff_threshold and current_price_change < 0 # 持平低位需要价格是下跌的
                delta_higher = current_delta > prev_delta
                
                if (price_lower or price_equal_low) and delta_higher:
                    delta_divergence_interp = "⚠️ 检测到看涨 Delta 背离 (底?)"
                    delta_divergence_score_adj = 1.0 # 背离是较强信号

                # 看跌背离条件: 价格创新高或持平高位，但 Delta 减弱
                price_higher = current_last_price > prev_last_price + price_diff_threshold
                price_equal_high = abs(current_last_price - prev_last_price) <= price_diff_threshold and current_price_change > 0 # 持平高位需要价格是上涨的
                delta_lower = current_delta < prev_delta
                
                if (price_higher or price_equal_high) and delta_lower:
                    delta_divergence_interp = "⚠️ 检测到看跌 Delta 背离 (顶?)"
                    delta_divergence_score_adj = -1.0 # 背离是较强信号
        
        if delta_divergence_interp:
            scope_interpretations.append(delta_divergence_interp)
        scope_score += delta_divergence_score_adj
        # ------------------------------------

        # --- 计算并存储当前范围的结果 --- 
        # 限制单范围分数
        scope_score = max(-3, min(3, round(scope_score, 2))) # 单范围评分限制在 -3 到 +3
        interpretation_details_by_scope[scope] = {'details': scope_interpretations, 'score': scope_score}
        
        # --- 更新加权总分 --- 
        weight = scope_weights.get(scope, 0.5) # 默认权重 0.5
        weighted_score_sum += scope_score * weight
        total_weight += weight

    # --- 计算最终加权平均 bias_score --- 
    if total_weight > 0:
        bias_score = round(weighted_score_sum / total_weight, 2)
    else:
        bias_score = 0 # 没有有效范围，评分为0

    # --- 生成整体摘要和冲突判断 --- 
    # 选取最重要的时间窗口解读（例如 60s 或 300s）作为主要参考
    primary_scope = '60s' if '60s' in interpretation_details_by_scope else ('300s' if '300s' in interpretation_details_by_scope else 'overall')
    if primary_scope in interpretation_details_by_scope:
        overall_summary = interpretation_details_by_scope[primary_scope]['details'][:2] # 取前两句作为摘要
        overall_details = interpretation_details_by_scope[primary_scope]['details']
    
    # 判断精细冲突：如果不同时间窗口的 scope_score 符号相反且绝对值都较大
    scores = [d['score'] for d in interpretation_details_by_scope.values() if d.get('score') is not None]
    if len(scores) >= 2:
        max_score = max(scores)
        min_score = min(scores)
        if max_score > 1.0 and min_score < -1.0: # 例如，一个强看涨窗口和一个强看跌窗口
            is_conflicting_refined = True
            overall_summary.append("!!注意：不同时间窗口信号存在显著冲突!!")

    # 限制最终 bias_score 在 -2 到 +2 之间 (与订单簿和微观趋势对齐)
    final_bias_score = max(-2, min(2, round(bias_score))) # 取整并限制

    # 返回最终结果字典
    return {
        'overall': {'summary': overall_summary, 'details': overall_details},
        'bias_score': final_bias_score, # 返回计算和限制后的评分
        'is_conflicting_refined': is_conflicting_refined,
        'time_segments': interpretation_details_by_scope # 包含每个时间段的解读和分数
    }

# --- 辅助函数：打印分析结果 ---
def _print_analysis_metrics(metrics, title, requested_window_sec=None):
    """辅助函数，用于格式化打印单个分析结果字典 (紧凑格式)。"""
    if not metrics:
        print(f"\n--- {title} ---")
        print("  (无数据或分析失败)")
        return

    print(f"\n--- {title} ---") # 窗口标题
    # 时间范围和覆盖警告
    actual_start_time = metrics.get('start_time')
    actual_end_time = metrics.get('end_time')
    actual_span_sec = metrics.get('time_span_seconds', 0)
    time_info = "  时间范围: N/A"
    if actual_start_time and actual_end_time:
        time_info = f"  数据时间: {actual_start_time.strftime('%H:%M:%S')} -> {actual_end_time.strftime('%H:%M:%S')} ({actual_span_sec:.1f}s)" # 简化时间格式
        if requested_window_sec is not None and requested_window_sec > 0:
            if actual_span_sec > 0:
                coverage_ratio = actual_span_sec / requested_window_sec
                if coverage_ratio < 0.95:
                    time_info += f" [⚠警告: 覆盖率 {coverage_ratio:.1%}]"
            else:
                time_info += f" [⚠警告: {requested_window_sec}s 内无数据]"
    print(time_info)

    # 整体成交统计
    total_volume = metrics.get('total_quote_volume', 0)
    total_trades = metrics.get('total_trades', 0)
    t_buy_vol = metrics.get('taker_buy_quote_volume')
    t_sell_vol = metrics.get('taker_sell_quote_volume')
    t_buy_trades = metrics.get('taker_buy_trades')
    t_sell_trades = metrics.get('taker_sell_trades')
    last_price = metrics.get('last_price') # 用于 VWAP 对比

    t_buy_vol_str = f'{t_buy_vol:.2f}' if t_buy_vol is not None else '-'
    t_sell_vol_str = f'{t_sell_vol:.2f}' if t_sell_vol is not None else '-'
    buy_vol_pct_str = f"({t_buy_vol/total_volume*100:.1f}%)" if total_volume > 0 and t_buy_vol is not None else ""
    sell_vol_pct_str = f"({t_sell_vol/total_volume*100:.1f}%)" if total_volume > 0 and t_sell_vol is not None else ""
    t_buy_trades_str = str(t_buy_trades) if t_buy_trades is not None else '-'
    t_sell_trades_str = str(t_sell_trades) if t_sell_trades is not None else '-'
    buy_trade_pct_str = f"({t_buy_trades/total_trades*100:.0f}%)" if total_trades > 0 and t_buy_trades is not None else ""
    sell_trade_pct_str = f"({t_sell_trades/total_trades*100:.0f}%)" if total_trades > 0 and t_sell_trades is not None else ""

    print(f"  [📈整体] 总额: {total_volume:.2f} | 笔数: {total_trades}")
    print(f"    买/卖额: {t_buy_vol_str}{buy_vol_pct_str} / {t_sell_vol_str}{sell_vol_pct_str}")
    print(f"    买/卖笔: {t_buy_trades_str}{buy_trade_pct_str} / {t_sell_trades_str}{sell_trade_pct_str}")

    # --- 内部辅助函数 Start ---
    def get_vwap_diff_str(vwap, ref_price):
        if vwap is None or ref_price is None or ref_price == 0: return ""
        diff_pct = (vwap - ref_price) / ref_price * 100
        sign = '+' if diff_pct >= 0 else ''
        return f" ({sign}{diff_pct:.3f}%)"

    def get_price_decimals(ref_p, default=2):
        decimals = default
        if ref_p is not None:
            try:
                p_str = f"{ref_p:.8f}"
                if '.' in p_str: decimals = max(default, len(p_str.split('.')[1].rstrip('0')))
            except Exception: pass
        return decimals
    # --- 内部辅助函数 End ---

    # --- 打印精简的主要百分位大单分析 --- 
    primary_percentile_printed = False
    if 'large_trades_analysis' in metrics and metrics['large_trades_analysis']:
        primary_percentile = getattr(配置, 'TRADE_FLOW_PRIMARY_PERCENTILE', None)
        if primary_percentile and primary_percentile in metrics['large_trades_analysis']:
            primary_percentile_printed = True
            large_metrics = metrics['large_trades_analysis'][primary_percentile]
            large_threshold = large_metrics.get('large_order_threshold_quote', 0)
            large_trades_count = large_metrics.get('large_trades_count', 0)
            large_total_vol = large_metrics.get('large_total_quote_volume', 0.0)
            large_buy_vwap = large_metrics.get('large_taker_buy_vwap')
            large_sell_vwap = large_metrics.get('large_taker_sell_vwap')

            large_trade_pct_str = f"({large_trades_count / total_trades * 100:.1f}%笔)" if total_trades > 0 else ""
            large_vol_pct_str = f"({large_total_vol / total_volume * 100:.1f}%额)" if total_volume > 0 else ""
            price_decimals = get_price_decimals(last_price if last_price is not None else (large_buy_vwap if large_buy_vwap is not None else large_sell_vwap))
            buy_vwap_diff_str = get_vwap_diff_str(large_buy_vwap, last_price)
            sell_vwap_diff_str = get_vwap_diff_str(large_sell_vwap, last_price)
            buy_vwap_str = f'{large_buy_vwap:.{price_decimals}f}' if large_buy_vwap is not None else '-'
            sell_vwap_str = f'{large_sell_vwap:.{price_decimals}f}' if large_sell_vwap is not None else '-'

            print(f"  [🐋大单(P{primary_percentile})] 阈值: {large_threshold:.2f}Q | 笔数: {large_trades_count}{large_trade_pct_str} | 贡献: {large_total_vol:.2f}{large_vol_pct_str}")
            print(f"    VWAP: 买{buy_vwap_str}{buy_vwap_diff_str} | 卖{sell_vwap_str}{sell_vwap_diff_str}")

    # --- 打印详细的多百分位大单分析 (仅在必要时显示) ---
    if 'large_trades_analysis' in metrics and metrics['large_trades_analysis']:
        percentiles_to_print = sorted(metrics['large_trades_analysis'].keys())
        primary_p = getattr(配置, 'TRADE_FLOW_PRIMARY_PERCENTILE', None)
        # 只有当存在多个百分位，或者唯一百分位不是主要百分位时，才显示这个详细块
        show_detailed_block = len(percentiles_to_print) > 1 or (len(percentiles_to_print) == 1 and percentiles_to_print[0] != primary_p)
        
        if show_detailed_block:
            print("  --- (详细百分位) ---")
            for percentile in percentiles_to_print:
                # 如果主要百分位已在精简块打印，则跳过详细块中的重复打印
                if percentile == primary_p and primary_percentile_printed:
                    continue 
                    
                large_metrics = metrics['large_trades_analysis'][percentile]
                large_threshold = large_metrics.get('large_order_threshold_quote', 0)
                large_trades_count = large_metrics.get('large_trades_count', 0)
                large_total_vol = large_metrics.get('large_total_quote_volume', 0.0)
                large_buy_vwap = large_metrics.get('large_taker_buy_vwap')
                large_sell_vwap = large_metrics.get('large_taker_sell_vwap')
                large_buy_vol = large_metrics.get('large_taker_buy_quote_volume')
                large_sell_vol = large_metrics.get('large_taker_sell_quote_volume')
                large_vol_ratio = large_metrics.get('large_taker_volume_ratio')
                large_trade_ratio = large_metrics.get('large_taker_trade_ratio')

                large_trade_pct_str = f"({large_trades_count / total_trades * 100:.1f}%笔)" if total_trades > 0 else ""
                large_vol_pct_str = f"({large_total_vol / total_volume * 100:.1f}%额)" if total_volume > 0 else ""
                price_decimals = get_price_decimals(last_price if last_price is not None else (large_buy_vwap if large_buy_vwap is not None else large_sell_vwap))
                buy_vwap_diff_str = get_vwap_diff_str(large_buy_vwap, last_price)
                sell_vwap_diff_str = get_vwap_diff_str(large_sell_vwap, last_price)
                buy_vwap_str = f'{large_buy_vwap:.{price_decimals}f}' if large_buy_vwap is not None else '-'
                sell_vwap_str = f'{large_sell_vwap:.{price_decimals}f}' if large_sell_vwap is not None else '-'
                large_buy_vol_str = f'{large_buy_vol:.2f}' if large_buy_vol is not None else '-'
                large_sell_vol_str = f'{large_sell_vol:.2f}' if large_sell_vol is not None else '-'
                large_vol_ratio_str = f'{large_vol_ratio:.4f}' if large_vol_ratio is not None else '-'
                large_trade_ratio_str = f'{large_trade_ratio:.4f}' if large_trade_ratio is not None else '-'
                 
                # 压缩详细信息到2行
                print(f"    P{percentile}(>{large_threshold:.2f}Q): 数量:{large_trades_count}{large_trade_pct_str} | 贡献:{large_total_vol:.2f}{large_vol_pct_str}")
                print(f"      买/卖额: {large_buy_vol_str}/{large_sell_vol_str} | VWAP: {buy_vwap_str}{buy_vwap_diff_str}/{sell_vwap_str}{sell_vwap_diff_str} | 比率(V/T): {large_vol_ratio_str}/{large_trade_ratio_str}")

    # 函数末尾不再打印分隔线

# --- 测试代码 --- (增加合约测试和趋势模拟)
if __name__ == '__main__':
    # 从配置模块导入参数
    try:
        test_percentiles = 配置.TRADE_FLOW_LARGE_ORDER_PERCENTILES
        test_windows = 配置.TRADE_FLOW_ANALYSIS_WINDOWS
        logger.info(f"使用配置：大单百分位={test_percentiles}, 时间窗口={test_windows}s")
    except AttributeError:
        logger.warning("在 配置.py 中未找到成交流分析参数，使用默认值。")
        test_percentiles = [95, 98, 99]
        test_windows = [60, 300, 900]

    test_scenarios = [
        {'symbol': 'BTCUSDT', 'market_type': 'spot'},
        {'symbol': 'BTCUSDT', 'market_type': 'futures'},
    ]

    previous_results = {} # 存储上一次所有场景的分析结果
    num_iterations = 2 # 模拟运行两次以便比较
    iteration_delay_seconds = 5 # 每次迭代间隔秒数

    for i in range(num_iterations):
        logger.info(f"\n<<<<<<<<<< 模拟迭代 {i+1}/{num_iterations} >>>>>>>>>>")
        current_iteration_results = {} # 存储当前迭代结果，传给下一次

        for scenario in test_scenarios:
            symbol = scenario['symbol']
            market_type = scenario['market_type']
            scenario_key = f"{symbol}_{market_type}" # 用于区分存储的结果

            logger.info(f"\n===== 测试场景: {symbol} ({market_type.upper()}) - 迭代 {i+1} ====")
            logger.info(f"--- 测试获取、处理、分析并解读 {symbol} ({market_type}) --- ")

            # 使用配置中定义的获取数量
            fetch_limit = getattr(配置, 'TRADE_FLOW_FETCH_LIMIT', 1000) # 默认1000以防万一
            processed_trades = 获取并处理近期成交(symbol, limit=fetch_limit, market_type=market_type)

            if processed_trades is not None and not processed_trades.empty:
                print(f"\n成功获取并处理了 {len(processed_trades)} 条成交记录.")
                print(f"  (数据实际时间范围: {processed_trades['timestamp'].min()} -> {processed_trades['timestamp'].max()})")

                # 1. 分析
                trade_flow_analysis = 分析成交流(symbol, market_type, fetch_limit, test_percentiles, test_windows)

                if trade_flow_analysis:
                    # 获取这个场景上一次的分析结果
                    prev_scenario_analysis = previous_results.get(scenario_key)

                    # 2. 解读 (传入上一次的结果)
                    interpretations = 解读成交流分析(trade_flow_analysis, previous_analysis=prev_scenario_analysis)

                    print(f"\n=== 时间窗口分析与解读 ({market_type.upper()}) - 迭代 {i+1} ===")
                    if 'windows' in trade_flow_analysis and trade_flow_analysis['windows']:
                        for window_key, window_metrics in trade_flow_analysis['windows'].items():
                            requested_sec = int(window_key[:-1])
                            market_name_cn = "合约" if market_type == 'futures' else "现货"
                            title = f"--- {market_name_cn}市场 成交数据分析 - 时间窗口 {window_key} ({requested_sec//60} 分钟) ---"
                            _print_analysis_metrics(window_metrics, title, requested_window_sec=requested_sec)

                            # 修正：从 interpretations['time_segments'] 获取解读 (第二次修正)
                            scope_interpretations = interpretations.get('time_segments', {}).get(window_key, {})
                            details_list = scope_interpretations.get('details')

                            if details_list: # 检查列表是否非空
                                 print("  解读:")
                                 for line in details_list: # 修正：直接迭代 details_list
                                     print(f"    - {line}")
                            else:
                                 print("  (无解读信息)")
                            print("----------------------------------")
                    else:
                        print("  未请求或未生成任何时间窗口的分析结果。")

                    # 存储当前结果供下一次迭代使用
                    current_iteration_results[scenario_key] = trade_flow_analysis

                else:
                    print("\n未能生成成交流分析结果。")
                    current_iteration_results[scenario_key] = None # 标记失败

            elif processed_trades is not None and processed_trades.empty:
                print(f"\n近期 {symbol} ({market_type}) 没有成交记录或处理后为空。")
                current_iteration_results[scenario_key] = None
            else:
                print(f"\n获取或处理 {symbol} ({market_type}) 成交记录失败。")
                current_iteration_results[scenario_key] = None

        # 更新 previous_results 为当前迭代的结果
        previous_results = current_iteration_results

        # 如果不是最后一次迭代，则等待
        if i < num_iterations - 1:
            logger.info(f"迭代 {i+1} 完成，等待 {iteration_delay_seconds} 秒...")
            time.sleep(iteration_delay_seconds)

    logger.info("--- 成交流分析模块所有场景及迭代测试结束 ---")
