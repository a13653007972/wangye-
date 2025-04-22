print("!!! 正在执行这个版本的 订单簿分析.py 文件 !!!")

# -*- coding: utf-8 -*-
"""短线数据分析模块：基于订单簿进行分析"""

import logging
import pandas as pd
import numpy as np
import time
from copy import deepcopy # 用于复制历史结果，避免直接修改

# --- 创建独立的 Logger --- 
# 不再复用 data_logger，确保配置独立
logger = logging.getLogger(__name__) 

# --- 强制设置日志级别为 DEBUG --- (确保调试信息能输出)
logger.setLevel(logging.DEBUG)
# 确保至少有一个 Handler 处理 DEBUG 级别的日志
if not logger.hasHandlers():
    # 如果没有 Handler，添加一个 StreamHandler 输出到控制台
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s [%(levelname)s] - %(message)s') # 稍微修改格式以区分
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.info("订单簿分析模块 Logger 未找到 Handler，已添加 StreamHandler (独立)。")
else:
    # 如果有 Handler，确保至少有一个 Handler 的级别不高于 DEBUG
    has_debug_handler = False
    for h in logger.handlers:
        if h.level <= logging.DEBUG:
            has_debug_handler = True
            break
    if not has_debug_handler:
        # 如果所有现有 Handler 的级别都高于 DEBUG，也添加一个
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s [%(levelname)s] - %(message)s') # 稍微修改格式以区分
        handler.setFormatter(formatter)
        handler.setLevel(logging.DEBUG) # 明确设置 Handler 级别
        logger.addHandler(handler)
        logger.info("订单簿分析模块 现有 Handler 级别过高，已添加 DEBUG StreamHandler (独立)。")

logger.info("订单簿分析模块 Logger Level 确认设置为 DEBUG (独立)。")
# --- 日志级别设置完毕 ---

# 尝试从数据获取模块导入功能 (不再导入 logger)
try:
    # 导入现货和合约的订单簿获取函数 和 client
    from 数据获取模块 import 获取订单簿深度, 获取合约订单簿深度, client as binance_client, 获取交易所信息
    # from 数据获取模块 import logger as data_logger # 不再导入 data_logger
except ImportError as e:
    # 使用我们自己定义的 logger 记录错误
    logger.critical(f"无法导入 '数据获取模块' 或其部分功能: {e}. 请确保该文件存在且路径正确。", exc_info=True)
    # 模拟一个不存在的函数，以便后续检查
    def 获取订单簿深度(*args, **kwargs):
        logger.error("获取订单簿深度 功能不可用，因为无法导入'数据获取模块'。")
        return None
    def 获取合约订单簿深度(*args, **kwargs):
        logger.error("获取合约订单簿深度 功能不可用，因为无法导入'数据获取模块'。")
        return None
    def 获取交易所信息(*args, **kwargs):
        logger.error("获取交易所信息 功能不可用，因为无法导入'数据获取模块'。")
        return None
    binance_client = None

# 尝试从配置模块导入配置 (虽然此模块目前可能不直接需要)
try:
    import 配置
except ImportError:
    logger.warning("无法导入 '配置' 模块。将使用默认值（如果需要）。")
    # 定义可能需要的默认值
    # class 配置:
    #     DEFAULT_SYMBOL = 'BTCUSDT'

# 导入配置，并设置默认阈值以防配置缺失
try:
    import 配置
    # 使用 getattr 安全地获取阈值，如果不存在则使用默认值
    INTERPRETATION_THRESHOLDS = {
        "OIR_STRONG": getattr(配置, 'INTERPRETATION_OIR_STRONG', 0.4),
        "OIR_WEAK": getattr(配置, 'INTERPRETATION_OIR_WEAK', 0.1),
        "CUM_RATIO_STRONG": getattr(配置, 'INTERPRETATION_CUM_RATIO_STRONG', 1.8),
        "CUM_RATIO_WEAK": getattr(配置, 'INTERPRETATION_CUM_RATIO_WEAK', 1.3),
        "LARGE_ORDER_SIG_FACTOR": getattr(配置, 'INTERPRETATION_LARGE_ORDER_SIG_FACTOR', 0.1),
        "LIQUIDITY_GAP_FACTOR": getattr(配置, 'INTERPRETATION_LIQUIDITY_GAP_FACTOR', 5.0),
        # 新增：区分现货和合约的裂口因子
        "SPOT_LIQUIDITY_GAP_FACTOR": getattr(配置, 'SPOT_LIQUIDITY_GAP_FACTOR', 5.0), # 默认 5
        "FUTURES_LIQUIDITY_GAP_FACTOR": getattr(配置, 'FUTURES_LIQUIDITY_GAP_FACTOR', 15.0) # 默认 15 (波动更大)
    }
    # 新增：测试循环配置
    TEST_LOOP_ITERATIONS = getattr(配置, 'TEST_LOOP_ITERATIONS', 2) # 默认循环2次以便对比
    TEST_LOOP_INTERVAL = getattr(配置, 'TEST_LOOP_INTERVAL', 10) # 默认间隔10秒
    # 加载 Tick Sizes 配置
    CONFIG_TICK_SIZES = getattr(配置, 'TICK_SIZES', {})
    logger.info("成功加载指标解读阈值配置和TickSizes配置。")
except ImportError:
    logger.warning("无法导入 '配置' 模块。将使用默认解读阈值和测试循环设置，以及空TickSizes配置。")
    INTERPRETATION_THRESHOLDS = {
        "OIR_STRONG": 0.4,
        "OIR_WEAK": 0.1,
        "CUM_RATIO_STRONG": 1.8,
        "CUM_RATIO_WEAK": 1.3,
        "LARGE_ORDER_SIG_FACTOR": 0.1,
        "LIQUIDITY_GAP_FACTOR": 5.0, # 保留一个通用默认值
        "SPOT_LIQUIDITY_GAP_FACTOR": 5.0,
        "FUTURES_LIQUIDITY_GAP_FACTOR": 15.0
    }
    TEST_LOOP_ITERATIONS = 2
    TEST_LOOP_INTERVAL = 10
    CONFIG_TICK_SIZES = {}
except Exception as e:
    logger.error(f"加载解读阈值配置和TickSizes配置时出错: {e}", exc_info=True)
    # 保留默认值
    INTERPRETATION_THRESHOLDS = {
        "OIR_STRONG": 0.4,
        "OIR_WEAK": 0.1,
        "CUM_RATIO_STRONG": 1.8,
        "CUM_RATIO_WEAK": 1.3,
        "LARGE_ORDER_SIG_FACTOR": 0.1,
        "LIQUIDITY_GAP_FACTOR": 5.0,
        "SPOT_LIQUIDITY_GAP_FACTOR": 5.0,
        "FUTURES_LIQUIDITY_GAP_FACTOR": 15.0
    }
    TEST_LOOP_ITERATIONS = 2
    TEST_LOOP_INTERVAL = 10
    CONFIG_TICK_SIZES = {}

# --- 辅助计算函数 ---

def calculate_order_imbalance_ratio(best_bid_qty, best_ask_qty):
    """计算订单不平衡比率 (Order Imbalance Ratio, OIR)
    OIR = (B_qty - A_qty) / (B_qty + A_qty)
    返回 OIR，范围 [-1, 1]。接近 1 表示买方压力大，接近 -1 表示卖方压力大。
    """
    if best_bid_qty + best_ask_qty == 0:
        return 0.0 # 避免除以零
    return (best_bid_qty - best_ask_qty) / (best_bid_qty + best_ask_qty)

def calculate_weighted_average_price(best_bid_price, best_bid_qty, best_ask_price, best_ask_qty):
    """计算加权平均价格 (Weighted Average Price, WAP)
    WAP = (BestBidPrice * BestAskQty + BestAskPrice * BestBidQty) / (BestBidQty + BestAskQty)
    反映了成交的可能性价格。
    """
    if best_bid_qty + best_ask_qty == 0:
        return (best_bid_price + best_ask_price) / 2 # 如果数量为零，返回中间价
    return (best_bid_price * best_ask_qty + best_ask_price * best_bid_qty) / (best_bid_qty + best_ask_qty)

def calculate_multi_level_oir(bids_n, asks_n):
    """计算 N 档订单不平衡比率 (Multi-Level Order Imbalance Ratio)
    OIR_N = (Sum(BidQty_N) - Sum(AskQty_N)) / (Sum(BidQty_N) + Sum(AskQty_N))
    Args:
        bids_n (pd.DataFrame): 前 N 档买单 (包含 'quantity' 列)
        asks_n (pd.DataFrame): 前 N 档卖单 (包含 'quantity' 列)
    Returns:
        float: N 档 OIR
    """
    if bids_n.empty or asks_n.empty:
        return 0.0
    sum_bid_qty = bids_n['quantity'].sum()
    sum_ask_qty = asks_n['quantity'].sum()
    denominator = sum_bid_qty + sum_ask_qty
    if denominator == 0:
        return 0.0
    return (sum_bid_qty - sum_ask_qty) / denominator

def calculate_multi_level_wap(bids_n, asks_n):
    """计算 N 档加权平均价格 (Multi-Level Weighted Average Price)
    WAP_N = Sum(BidPrice_i * AskQty_i + AskPrice_i * BidQty_i) / Sum(BidQty_i + AskQty_i) for i over N levels
    (More standard definition might be based on volume at levels)
    Alternative WAP (Micro-price): Sum(BidPrice_i * BidQty_i + AskPrice_i * AskQty_i) / Sum(BidQty_i + AskQty_i)
    Let's use the one similar to Level 1 WAP logic extended:
    WAP_N = Sum(BidPrice_i * AskQty_i + AskPrice_i * BidQty_i) / Sum(BidQty_i + AskQty_i)

    Args:
        bids_n (pd.DataFrame): 前 N 档买单 (包含 'price', 'quantity' 列)
        asks_n (pd.DataFrame): 前 N 档卖单 (包含 'price', 'quantity' 列)
    Returns:
        float: N 档 WAP
    """
    if bids_n.empty or asks_n.empty:
        # Fallback to mid-price of best bid/ask if available
        best_bid = bids_n['price'].iloc[0] if not bids_n.empty else 0
        best_ask = asks_n['price'].iloc[0] if not asks_n.empty else 0
        return (best_bid + best_ask) / 2 if (best_bid + best_ask) > 0 else 0

    # Ensure N is the minimum of len(bids_n), len(asks_n)
    n_levels = min(len(bids_n), len(asks_n))
    if n_levels == 0: return 0.0 # Should not happen if check above passed
    
    bids_n = bids_n.head(n_levels)
    asks_n = asks_n.head(n_levels)

    numerator = (bids_n['price'] * asks_n['quantity'] + asks_n['price'] * bids_n['quantity']).sum()
    denominator = (bids_n['quantity'] + asks_n['quantity']).sum()

    if denominator == 0:
        # Fallback to mid-price of best bid/ask
        return (bids_n['price'].iloc[0] + asks_n['price'].iloc[0]) / 2
    
    return numerator / denominator

def identify_large_orders(orders_df, quantity_column='quantity', percentile=95):
    """识别大单并计算总数量和VWAP (已修正 VWAP 计算)。"""
    default_return = (pd.DataFrame(), 0.0, 0.0, 0.0)
    if orders_df is None or orders_df.empty: return default_return
    try:
        orders_df[quantity_column] = pd.to_numeric(orders_df[quantity_column], errors='coerce')
        orders_df = orders_df.dropna(subset=[quantity_column])
    except Exception as e: logger.error(f"转换大单数量列出错: {e}"); return default_return
    if orders_df.empty: return default_return
    try:
        threshold = np.percentile(orders_df[quantity_column], percentile)
        large_orders = orders_df[orders_df[quantity_column] >= threshold].copy()
    except Exception as e: logger.error(f"计算百分位或筛选大单出错: {e}"); return default_return
    if large_orders.empty: return (pd.DataFrame(), threshold, 0.0, 0.0)
    
    total_quantity = large_orders[quantity_column].sum()
    vwap = 0.0
    if total_quantity > 0:
        try:
            # 正确的 VWAP 计算: (价格 * 数量) 的总和 / 总数量
            total_value = (large_orders['price'] * large_orders[quantity_column]).sum()
            vwap = total_value / total_quantity
        except Exception as e:
            logger.error(f"计算大单 VWAP 时出错: {e}")
            # 保留 vwap 为 0.0
            pass
    
    return large_orders, threshold, total_quantity, vwap

def calculate_cumulative_depth(bids_df, asks_df, depth_limit=100):
    """
    计算并聚合订单簿深度数据，包括累计量、OIR、WAP、VWAP等。

    Args:
        bids_df (pd.DataFrame): 买单数据框，包含 'price', 'quantity', 'quoteQty'。
        asks_df (pd.DataFrame): 卖单数据框，包含 'price', 'quantity', 'quoteQty'。
        depth_limit (int): 实际获取和用于计算的深度限制。

    Returns:
        dict: 包含计算结果的字典。
    """
    results = {'depth_limit_actual': depth_limit} # 记录实际使用的深度

    # --- 计算总报价量 ---
    results['total_bid_quote_volume'] = bids_df['quoteQty'].sum()
    results['total_ask_quote_volume'] = asks_df['quoteQty'].sum()

    # --- 计算累计量和OIR ---
    # 假设 'cum_quote_volume' 列已在 process_depth 中计算好
    levels_to_calculate = [5, 20, 50, 100, 500] # 要计算的档位

    # 检查实际深度是否足够计算某个档位
    max_bid_level = len(bids_df)
    max_ask_level = len(asks_df)

    for level in levels_to_calculate:
        if level <= max_bid_level and level <= max_ask_level:
            # 确认 'cum_quote_volume' 列存在
            if 'cum_quote_volume' in bids_df.columns and 'cum_quote_volume' in asks_df.columns:
                bid_vol = bids_df['cum_quote_volume'].iloc[level - 1]
                ask_vol = asks_df['cum_quote_volume'].iloc[level - 1]
                oir = (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else 0
                wap = (bids_df['price'].iloc[level - 1] * ask_vol + asks_df['price'].iloc[level - 1] * bid_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else (bids_df['price'].iloc[level - 1] + asks_df['price'].iloc[level - 1]) / 2

                results[f'oir_{level}'] = oir
                results[f'wap_{level}'] = wap
                results[f'cum_bid_vol_{level}'] = bid_vol
                results[f'cum_ask_vol_{level}'] = ask_vol
            else:
                logger.warning(f"无法计算 {level} 档 OIR/WAP，缺少 'cum_quote_volume' 列。")
                results[f'oir_{level}'] = None
                results[f'wap_{level}'] = None
                results[f'cum_bid_vol_{level}'] = None
                results[f'cum_ask_vol_{level}'] = None
        else:
            # 如果档位超出实际深度，则标记为 None
            results[f'oir_{level}'] = None
            results[f'wap_{level}'] = None
            results[f'cum_bid_vol_{level}'] = None
            results[f'cum_ask_vol_{level}'] = None

    # --- 计算整个深度的OIR/WAP (基于实际深度) ---
    if not bids_df.empty and not asks_df.empty and 'cum_quote_volume' in bids_df.columns and 'cum_quote_volume' in asks_df.columns:
        max_depth_bid_vol = bids_df['cum_quote_volume'].iloc[-1]
        max_depth_ask_vol = asks_df['cum_quote_volume'].iloc[-1]
        max_depth_bid_price = bids_df['price'].iloc[-1]
        max_depth_ask_price = asks_df['price'].iloc[-1]

        results['oir_max'] = (max_depth_bid_vol - max_depth_ask_vol) / (max_depth_bid_vol + max_depth_ask_vol) if (max_depth_bid_vol + max_depth_ask_vol) > 0 else 0
        results['wap_max'] = (max_depth_bid_price * max_depth_ask_vol + max_depth_ask_price * max_depth_bid_vol) / (max_depth_bid_vol + max_depth_ask_vol) if (max_depth_bid_vol + max_depth_ask_vol) > 0 else (max_depth_bid_price + max_depth_ask_price) / 2
    else:
        results['oir_max'] = None
        results['wap_max'] = None

    # --- 计算 VWAP (加权平均价格) 基于 *固定档位* --- 
    vwap_levels = [5, 20, 50, 100] # 定义要计算的档位数
    results.update({f'vwap_bid_{L}L': None for L in vwap_levels}) # 初始化买单 VWAP
    results.update({f'vwap_ask_{L}L': None for L in vwap_levels}) # 初始化卖单 VWAP

    if not bids_df.empty and 'price' in bids_df.columns and 'quantity' in bids_df.columns:
        for L in vwap_levels:
            # 确保档位数不超过实际拥有的买单数量
            if L <= len(bids_df):
                relevant_bids = bids_df.iloc[:L]
                if not relevant_bids.empty:
                    bid_numerator = (relevant_bids['price'] * relevant_bids['quantity']).sum()
                    bid_denominator = relevant_bids['quantity'].sum()
                    if bid_denominator > 0:
                        results[f'vwap_bid_{L}L'] = bid_numerator / bid_denominator
                    # else: # 分母为0，保持 None
            # else: # 请求的档位超过总档数，保持 None
                # logger.debug(f"请求的买单 VWAP 档位 {L}L 超过总档数 {len(bids_df)}，结果为 None")
                
    if not asks_df.empty and 'price' in asks_df.columns and 'quantity' in asks_df.columns:
        for L in vwap_levels:
             # 确保档位数不超过实际拥有的卖单数量
            if L <= len(asks_df):
                relevant_asks = asks_df.iloc[:L]
                if not relevant_asks.empty:
                    ask_numerator = (relevant_asks['price'] * relevant_asks['quantity']).sum()
                    ask_denominator = relevant_asks['quantity'].sum()
                    if ask_denominator > 0:
                        results[f'vwap_ask_{L}L'] = ask_numerator / ask_denominator
                    # else: # 分母为0，保持 None
            # else: # 请求的档位超过总档数，保持 None
                # logger.debug(f"请求的卖单 VWAP 档位 {L}L 超过总档数 {len(asks_df)}，结果为 None")

    # --- (移除旧的基于价格百分比的 VWAP 计算逻辑和日志) ---

    # --- 返回计算结果 ---
    return results

def find_liquidity_gaps(df, side, tick_size, market_type='spot'):
    """查找订单簿中的流动性裂口，返回数量、最大裂口大小及位置信息。"""
    gap_count = 0
    max_gap_size = 0.0
    max_gap_price_after = None # 新增：裂口发生后的价格
    max_gap_price_before = None # 新增：裂口发生前的价格

    if df is None or len(df) < 2 or tick_size <= 0:
        return {'count': gap_count, 'max_gap': max_gap_size, 'max_gap_price_after': None, 'max_gap_price_before': None}

    # 使用 .loc 避免 SettingWithCopyWarning
    df_copy = df.copy()
    df_copy['price_diff'] = df_copy['price'].diff().abs()
    # 记录上一行的价格，用于定位裂口
    df_copy['prev_price'] = df_copy['price'].shift(1)

    # 根据市场类型设置不同的裂口阈值因子
    if market_type == 'futures':
        gap_threshold_factor = INTERPRETATION_THRESHOLDS.get("FUTURES_LIQUIDITY_GAP_FACTOR", 15.0)
    else:
        gap_threshold_factor = INTERPRETATION_THRESHOLDS.get("SPOT_LIQUIDITY_GAP_FACTOR", 5.0)

    gap_threshold = tick_size * gap_threshold_factor

    # 查找裂口
    gaps_df = df_copy[df_copy['price_diff'] > gap_threshold]

    if not gaps_df.empty:
        gap_count = len(gaps_df)
        # 找到最大裂口所在行
        max_gap_row = gaps_df.loc[gaps_df['price_diff'].idxmax()]
        max_gap_size = max_gap_row['price_diff']
        max_gap_price_after = max_gap_row['price'] # 裂口后的价格 (当前行价格)
        max_gap_price_before = max_gap_row['prev_price'] # 裂口前的价格 (上一行价格)

    return {'count': gap_count, 'max_gap': max_gap_size, 'max_gap_price_after': max_gap_price_after, 'max_gap_price_before': max_gap_price_before} # 返回包含位置信息的字典

def calculate_dynamic_indicators(current_analysis, previous_analysis):
    """计算当前分析结果与上一次结果之间的指标变化，包括累计深度变化。"""
    dynamics = {}
    if previous_analysis is None or current_analysis is None:
        return dynamics # 无法比较
       
    try:
        # 比较的字段列表 (确保这些键存在于 analysis_result 中)
        n = current_analysis.get('analysis_levels') # 获取当前分析层数
        
        # 包含主要分析层级和其他固定层级
        levels_to_compare = list(set([5, n if n else None, 100, 500, 'max'])) 
        levels_to_compare = [l for l in levels_to_compare if l is not None] # 移除 None

        fields_to_compare = [
            "large_bids_total_qty", "large_bids_vwap",
            "large_asks_total_qty", "large_asks_vwap",
            "volume_ratio" # 整体买卖量比
        ]
        
        # 添加所有要比较的 OIR 和 WAP 键
        for level in levels_to_compare:
            fields_to_compare.append(f'oir_{level}')
            fields_to_compare.append(f'wap_{level}')
            
        # 添加累计深度数量的字段
        for p_key in current_analysis.keys():
            if p_key.startswith('cum_bid_qty_') or p_key.startswith('cum_ask_qty_'):
                fields_to_compare.append(p_key)
        
        # 移除重复项并过滤掉不存在于 current_analysis 中的键
        fields_to_compare = list(set(fields_to_compare))
        fields_to_compare = [f for f in fields_to_compare if f in current_analysis]
       
        for field in fields_to_compare:
            current_value = current_analysis.get(field)
            previous_value = previous_analysis.get(field)
           
            # 确保值是有效的数值类型才能计算差值
            if isinstance(current_value, (int, float)) and isinstance(previous_value, (int, float)) and np.isfinite(current_value) and np.isfinite(previous_value):
                delta = current_value - previous_value
                dynamics[f"{field}_delta"] = delta
            else:
                dynamics[f"{field}_delta"] = None # 或 0，或标记为无法计算
               
        # 也可以计算大单数量/裂口数量的变化
        dynamics['large_bids_count_delta'] = current_analysis.get('large_bids_count', 0) - previous_analysis.get('large_bids_count', 0)
        dynamics['large_asks_count_delta'] = current_analysis.get('large_asks_count', 0) - previous_analysis.get('large_asks_count', 0)
        # 新增：裂口数量变化
        current_bid_gap_count = current_analysis.get('bid_gap_info', {}).get('count', 0)
        prev_bid_gap_count = previous_analysis.get('bid_gap_info', {}).get('count', 0)
        dynamics['bid_gap_count_delta'] = current_bid_gap_count - prev_bid_gap_count
        
        current_ask_gap_count = current_analysis.get('ask_gap_info', {}).get('count', 0)
        prev_ask_gap_count = previous_analysis.get('ask_gap_info', {}).get('count', 0)
        dynamics['ask_gap_count_delta'] = current_ask_gap_count - prev_ask_gap_count

    except Exception as e:
        logger.error(f"计算动态指标时出错: {e}", exc_info=True)
        # 出错则返回空字典
        return {}
       
    return dynamics

def interpret_analysis(analysis_result, tick_size, dynamic_indicators=None):
    """根据静态和动态指标生成解读和评分，并返回结构化字典。"""
    interpretations = []
    score = 0
    support_strong = False
    pressure_strong = False
    dynamics = dynamic_indicators if dynamic_indicators is not None else {}
    try:
        n = analysis_result.get('analysis_levels', 0)
        if n == 0: return (["指标计算层数不足。"], 0, False, False)

        oir_key = f'oir_{n}'
        wap_key = f'wap_{n}'
        oir = analysis_result.get(oir_key, 0.0)
        wap = analysis_result.get(wap_key, 0.0)
        mid_price = (analysis_result.get('best_bid_price', 0) + analysis_result.get('best_ask_price', 0)) / 2
        th = INTERPRETATION_THRESHOLDS

        # --- 静态解读与评分 (与之前类似，但评分逻辑可能微调) --- 
        static_score = 0
        oir_score_adj = 0 # OIR 对静态评分的直接贡献 (简化计算)
        
        # 1. OIR/WAP (整合动态信息)
        oir_delta_str = "" # 初始化 delta 字符串
        oir_delta_score_adj = 0 # OIR delta 对动态评分的贡献
        oir_delta = dynamics.get(f"{oir_key}_delta")
        if oir_delta is not None:
            oir_threshold_weak = th["OIR_WEAK"] # 使用弱阈值判断变化是否显著
            if oir_delta > oir_threshold_weak * 0.5: 
                oir_delta_str = f" (增强 {oir_delta:+.2f})"
                oir_delta_score_adj = 1 # OIR 显著增强，动态加分
            elif oir_delta < -oir_threshold_weak * 0.5: 
                oir_delta_str = f" (减弱 {oir_delta:+.2f})"
                oir_delta_score_adj = -1 # OIR 显著减弱，动态减分
        
        wap_delta_str = "" # WAP delta 字符串
        wap_delta_score_adj = 0 # WAP delta 对动态评分的贡献
        wap_delta = dynamics.get(f"{wap_key}_delta")
        if wap_delta is not None and mid_price > 0:
            wap_delta_percent = (wap_delta / mid_price) * 100
            wap_delta_threshold_pct = 0.05 # WAP 变化显著性阈值
            if wap_delta_percent > wap_delta_threshold_pct:
                 wap_delta_str = f" (上升 {wap_delta_percent:+.2f}%)"
                 wap_delta_score_adj = 0.5 # WAP 显著上升，动态加分
            elif wap_delta_percent < -wap_delta_threshold_pct:
                 wap_delta_str = f" (下降 {wap_delta_percent:+.2f}%)"
                 wap_delta_score_adj = -0.5 # WAP 显著下降，动态减分
                 
        # 生成 OIR 解读并计算静态 OIR 贡献
        if oir > th["OIR_STRONG"] and wap > mid_price: 
            interpretations.append(f"* OIR({n})强看涨({oir:.2f}){oir_delta_str}, WAP确认{wap_delta_str}")
            oir_score_adj = 1.5 # 强看涨加分较多
        elif oir < -th["OIR_STRONG"] and wap < mid_price: 
            interpretations.append(f"* OIR({n})强看跌({oir:.2f}){oir_delta_str}, WAP确认{wap_delta_str}")
            oir_score_adj = -1.5 # 强看跌减分较多
        elif oir > th["OIR_WEAK"]: 
            interpretations.append(f"* OIR({n})偏买({oir:.2f}){oir_delta_str}, WAP趋势{wap_delta_str}")
            oir_score_adj = 0.5 # 偏买加分
        elif oir < -th["OIR_WEAK"]: 
            interpretations.append(f"* OIR({n})偏卖({oir:.2f}){oir_delta_str}, WAP趋势{wap_delta_str}")
            oir_score_adj = -0.5 # 偏卖减分
        else: 
            interpretations.append(f"* OIR({n})均衡({oir:.2f}){oir_delta_str}, WAP趋势{wap_delta_str}")
            # 均衡状态 OIR 不贡献静态分数
            
        static_score += oir_score_adj # 将 OIR 贡献计入静态评分
        
        # 2. 累计深度 (评分简化)
        cum_score = 0
        # 只关注最近的 0.1% 深度进行评分
        p = 0.1 
        ratio_key = f'cum_volume_ratio_{p}%'
        if ratio_key in analysis_result:
            ratio = analysis_result.get(ratio_key, 1.0)
            txt = None # 初始化解读文本
            if ratio > th["CUM_RATIO_STRONG"]: 
                txt=f"* +/-{p}%累计买量强优(比率:{ratio:.2f})=>支撑?"
                cum_score += 1.0 # 强优加 1 分
            elif ratio < 1/th["CUM_RATIO_STRONG"]: 
                txt=f"* +/-{p}%累计卖量强优(买/卖:{ratio:.2f})=>阻力?"
                cum_score -= 1.0 # 强优减 1 分
            elif ratio > th["CUM_RATIO_WEAK"]:
                txt=f"* +/-{p}%累计买量略优(比率:{ratio:.2f})"
                cum_score += 0.5 # 略优加 0.5 分
            elif ratio < 1/th["CUM_RATIO_WEAK"]:
                txt=f"* +/-{p}%累计卖量略优(买/卖:{ratio:.2f})"
                cum_score -= 0.5 # 略优减 0.5 分
            # 仍然添加所有百分比的解读文本，但只有 0.1% 影响评分
            if txt and txt not in interpretations: interpretations.append(txt)
        # 继续添加其他百分比的解读文本 (不影响评分)
        for p_other in [0.2, 0.5]:
             ratio_key_other = f'cum_volume_ratio_{p_other}%'
             if ratio_key_other in analysis_result:
                 ratio_other = analysis_result.get(ratio_key_other, 1.0)
                 txt_other = None
                 if ratio_other > th["CUM_RATIO_STRONG"]: txt_other=f"* +/-{p_other}%累计买量强优(比率:{ratio_other:.2f})=>支撑?"
                 elif ratio_other < 1/th["CUM_RATIO_STRONG"]: txt_other=f"* +/-{p_other}%累计卖量强优(买/卖:{ratio_other:.2f})=>阻力?"
                 elif ratio_other > th["CUM_RATIO_WEAK"] : txt_other=f"* +/-{p_other}%累计买量略优(比率:{ratio_other:.2f})"
                 elif ratio_other < 1/th["CUM_RATIO_WEAK"] : txt_other=f"* +/-{p_other}%累计卖量略优(买/卖:{ratio_other:.2f})"
                 if txt_other and txt_other not in interpretations: interpretations.append(txt_other)
                 
        static_score += cum_score # 使用简化后的 cum_score
        
        # 3. 大单 (增加评分逻辑)
        large_order_score_adj = 0 # 初始化大单评分调整
        best_bid_price = analysis_result.get('best_bid_price', 0)
        best_ask_price = analysis_result.get('best_ask_price', 0)
        spread = analysis_result.get('spread', tick_size) # 如果 spread 为 0，用 tick_size 代替
        if spread <= 0: spread = tick_size
        # 定义显著差异阈值 (例如 spread 的 30% 或 10 个 tick，取较大者)
        vwap_diff_threshold = max(spread * 0.3, tick_size * 10)
        
        large_bids_qty = analysis_result.get('large_bids_total_qty', 0); large_asks_qty = analysis_result.get('large_asks_total_qty', 0)
        total_bid_vol_n = analysis_result.get('total_bid_quote_vol_n') 
        total_ask_vol_n = analysis_result.get('total_ask_quote_vol_n')
        if total_bid_vol_n is None: total_bid_vol_n = analysis_result.get('total_bid_volume', 1)
        if total_ask_vol_n is None: total_ask_vol_n = analysis_result.get('total_ask_volume', 1)
        if total_bid_vol_n <= 0: total_bid_vol_n = 1 
        if total_ask_vol_n <= 0: total_ask_vol_n = 1

        large_bid_sig = total_bid_vol_n > 0 and (large_bids_qty / total_bid_vol_n > th["LARGE_ORDER_SIG_FACTOR"])
        large_ask_sig = total_ask_vol_n > 0 and (large_asks_qty / total_ask_vol_n > th["LARGE_ORDER_SIG_FACTOR"])
        
        qty_decimals = 4 
        price_decimals_large = 2 
        vwap_bid = analysis_result.get('large_bids_vwap')
        vwap_ask = analysis_result.get('large_asks_vwap')
        if vwap_bid is not None:
            try: price_decimals_large = max(2, len(str(f"{vwap_bid:.8f}").split('.')[1].rstrip('0')))
            except: pass
        elif vwap_ask is not None: 
             try: price_decimals_large = max(2, len(str(f"{vwap_ask:.8f}").split('.')[1].rstrip('0')))
             except: pass
            
        if large_bid_sig: 
            interpretations.append(f"* 显著大买单(占{n}档内 {large_bids_qty/total_bid_vol_n:.1%}), VWAP@{vwap_bid:.{price_decimals_large}f}") 
            # 评分逻辑：如果 VWAP 显著低于 Best Bid，加分
            if vwap_bid is not None and best_bid_price > 0 and (best_bid_price - vwap_bid) > vwap_diff_threshold:
                large_order_score_adj += 0.75 # 加分幅度可调
                interpretations.append(f"  (VWAP 显著低于最优买价，潜在支撑? +{0.75})") # 添加评分说明
        elif large_bids_qty > 0: 
            interpretations.append(f"* 有少量大买单")
            
        if large_ask_sig: 
            interpretations.append(f"* 显著大卖单(占{n}档内 {large_asks_qty/total_ask_vol_n:.1%}), VWAP@{vwap_ask:.{price_decimals_large}f}") 
            # 评分逻辑：如果 VWAP 显著高于 Best Ask，减分
            if vwap_ask is not None and best_ask_price > 0 and (vwap_ask - best_ask_price) > vwap_diff_threshold:
                large_order_score_adj -= 0.75 # 减分幅度可调
                interpretations.append(f"  (VWAP 显著高于最优卖价，潜在压力? -{0.75})") # 添加评分说明
        elif large_asks_qty > 0: 
            interpretations.append(f"* 有少量大卖单")
        
        static_score += large_order_score_adj # 将大单评分调整计入静态评分
            
        # 4. 裂口解读 (修改)
        bid_gap_info = analysis_result.get('bid_gap_info', {'count': 0, 'max_gap': 0.0})
        ask_gap_info = analysis_result.get('ask_gap_info', {'count': 0, 'max_gap': 0.0})
        bid_gap_count = bid_gap_info.get('count', 0)
        ask_gap_count = ask_gap_info.get('count', 0)
        market_type = analysis_result.get('market_type', 'spot') # 获取市场类型
        # 获取裂口阈值因子用于显示
        if market_type == 'futures': gap_threshold_factor = INTERPRETATION_THRESHOLDS.get("FUTURES_LIQUIDITY_GAP_FACTOR", 15.0)
        else: gap_threshold_factor = INTERPRETATION_THRESHOLDS.get("SPOT_LIQUIDITY_GAP_FACTOR", 5.0)
        
        price_decimals = max(2, str(mid_price)[::-1].find('.')) if mid_price > 0 else 2

        if bid_gap_count > 0:
            max_bid_gap = bid_gap_info.get('max_gap', 0.0)
            gap_before = bid_gap_info.get('max_gap_price_before')
            gap_after = bid_gap_info.get('max_gap_price_after')
            location_str = f" 在 {gap_before:.{price_decimals}f}-{gap_after:.{price_decimals}f} 之间" if gap_before and gap_after else ""
            interpretations.append(f"* 注意! 买盘存 {bid_gap_count} 个裂口 (>{gap_threshold_factor}x tick), 最大裂口约 {max_bid_gap:.{price_decimals}f}{location_str}")
        if ask_gap_count > 0:
            max_ask_gap = ask_gap_info.get('max_gap', 0.0)
            gap_before = ask_gap_info.get('max_gap_price_before')
            gap_after = ask_gap_info.get('max_gap_price_after')
            location_str = f" 在 {gap_before:.{price_decimals}f}-{gap_after:.{price_decimals}f} 之间" if gap_before and gap_after else ""
            interpretations.append(f"* 注意! 卖盘存 {ask_gap_count} 个裂口 (>{gap_threshold_factor}x tick), 最大裂口约 {max_ask_gap:.{price_decimals}f}{location_str}")

        # --- 动态解读与评分调整 --- (现在只包含未整合的部分)
        dynamic_score_adj = oir_delta_score_adj + wap_delta_score_adj # 从 OIR/WAP delta 开始累加
        # 获取当前总挂单量作为参考基准 (避免除零)
        total_bid_vol = analysis_result.get('total_bid_volume', 1) 
        total_ask_vol = analysis_result.get('total_ask_volume', 1)
        if total_bid_vol <= 0: total_bid_vol = 1
        if total_ask_vol <= 0: total_ask_vol = 1
        
        # 定义流动性变化显著性的阈值 (例如，变化量占总挂单量的 5%)
        liquidity_change_threshold_pct = 0.05 

        if dynamics:
            # 先从 dynamics 字典获取 delta 值
            oir_delta = dynamics.get(f"{oir_key}_delta")
            wap_delta = dynamics.get(f"{wap_key}_delta")
            large_bid_qty_delta = dynamics.get('large_bids_total_qty_delta') # <-- 获取大单买入总量 delta
            large_ask_qty_delta = dynamics.get('large_asks_total_qty_delta') # <-- 获取大单卖出总量 delta
            bid_gap_delta = dynamics.get('bid_gap_count_delta')
            ask_gap_delta = dynamics.get('ask_gap_count_delta')
            # ... (可以继续获取其他需要的 delta 值) ...
            
            # 大单数量/总量变化 (保留动态评分调整，但移除独立解读)
            large_bid_qty_delta_score = 0
            large_ask_qty_delta_score = 0
            # 现在可以安全使用 large_bid_qty_delta 和 large_ask_qty_delta
            if large_bid_qty_delta is not None: 
                if large_bid_qty_delta > 0: large_bid_qty_delta_score = 0.5
                elif large_bid_qty_delta < 0: large_bid_qty_delta_score = -0.3
            if large_ask_qty_delta is not None:
                 if large_ask_qty_delta > 0: large_ask_qty_delta_score = -0.5
                 elif large_ask_qty_delta < 0: large_ask_qty_delta_score = 0.3
            dynamic_score_adj += large_bid_qty_delta_score + large_ask_qty_delta_score
            # 可以在大单静态解读后附加 delta 信息:
            # e.g., interpretations[-1] += f" (变化 {large_bid_qty_delta:+.{qty_decimals}f})" 
            # (这需要更复杂的逻辑来定位正确的解读行，暂时不加)
                
            # --- 新增：解读累计深度变化 --- (保留动态评分调整，移除独立解读)
            cum_depth_delta_score = 0
            for p in [0.1, 0.2, 0.5]: 
                bid_delta_key = f'cum_bid_qty_{p}%_delta'
                ask_delta_key = f'cum_ask_qty_{p}%_delta'
                bid_delta = dynamics.get(bid_delta_key)
                ask_delta = dynamics.get(ask_delta_key)

                if bid_delta is not None:
                    bid_change_pct = abs(bid_delta) / total_bid_vol
                    if bid_change_pct > liquidity_change_threshold_pct:
                        score_change = 0.5 * (1 - p/0.5*0.8)
                        if bid_delta > 0: cum_depth_delta_score += score_change
                        else: cum_depth_delta_score -= score_change
                if ask_delta is not None:
                    ask_change_pct = abs(ask_delta) / total_ask_vol
                    if ask_change_pct > liquidity_change_threshold_pct:
                        score_change = 0.5 * (1 - p/0.5*0.8)
                        if ask_delta > 0: cum_depth_delta_score -= score_change
                        else: cum_depth_delta_score += score_change
            dynamic_score_adj += cum_depth_delta_score
            # 可以在累计深度静态解读后附加 delta 信息 (同样较复杂，暂不加)
            
            # --- 新增：解读裂口数量变化 --- (保留动态评分调整，移除独立解读)
            gap_delta_score = 0
            if bid_gap_delta is not None and bid_gap_delta != 0:
                if bid_gap_delta > 0: gap_delta_score -= 0.3
                else: gap_delta_score += 0.1
            if ask_gap_delta is not None and ask_gap_delta != 0:
                if ask_gap_delta > 0: gap_delta_score += 0.3 
                else: gap_delta_score -= 0.1
            dynamic_score_adj += gap_delta_score
            # 可以在裂口静态解读后附加 delta 信息 (同样较复杂，暂不加)
            
            # 移除独立的动态变化解读块
            # interpretations.append("--- 动态变化 ---")
            # ... (移除所有在 dynamics 循环中 append 解读的代码) ...

        # 合并评分并限制范围 (在确定强支撑/压力之前计算总分)
        
        # --- 新增：记录评分构成 (DEBUG级别) ---
        logger.debug(f"评分构成: 静态 OIR 贡献(估算)={static_score - cum_score - large_order_score_adj:.2f}, "
                     f"累计深度(0.1%)={cum_score:.2f}, 大单={large_order_score_adj:.2f} -> 静态总分={static_score:.2f}")
        logger.debug(f"评分构成: 动态调整总分={dynamic_score_adj:.2f}")
        # 可以进一步细化动态调整的组成部分，但这会使代码更复杂
        # logger.debug(f"  动态细节: OIR Delta={...}, WAP Delta={...}, Large Qty Delta={...}, Cum Depth Delta={...}, Gap Delta={...}")
        # -----------------------------------
        
        total_score = static_score + dynamic_score_adj
        
        # 新的裂口调整逻辑：根据裂口数量直接加减分
        gap_penalty_bid = 0
        gap_bonus_ask = 0
        if bid_gap_count > 0:
            # 买盘裂口惩罚 (减分)
            gap_penalty_bid = -0.5 * (1 + min(bid_gap_count / 10, 1)) # 裂口越多惩罚越大，最多惩罚 -1 分
            # 修正解读文本的符号
            interpretations.append(f"(评分调整: 买盘裂口 {gap_penalty_bid:.1f})") # 直接显示负号
        if ask_gap_count > 0:
            # 卖盘裂口奖励 (加分)
            gap_bonus_ask = 0.5 * (1 + min(ask_gap_count / 10, 1)) # 裂口越多奖励越大，最多奖励 +1 分
            interpretations.append(f"(评分调整: 卖盘裂口 +{gap_bonus_ask:.1f})")
            
        # 确保正确加减
        total_score += gap_penalty_bid 
        total_score += gap_bonus_ask
        
        # 限制最终评分范围
        final_score = max(-10, min(10, round(total_score)))

        # --- 新增：根据最终评分判断强支撑/压力 ---
        # 可以根据需要调整这里的阈值
        if final_score >= 5: # 例如，评分达到 5 或更高认为是强支撑
            support_strong = True
            interpretations.append("!! 评分显示强力支撑 !!")
        elif final_score <= -5: # 例如，评分达到 -5 或更低认为是强压力
            pressure_strong = True
            interpretations.append("!! 评分显示强力压力 !!")

        if not interpretations or all(i.startswith(f"* OIR({n}) 均衡") for i in interpretations):
            interpretations.append("当前指标组合未显示明确信号。")

    except Exception as e:
        logger.error(f"生成指标解读时出错: {e}", exc_info=True)
        interpretations.append("解读时发生内部错误。")
        final_score = 0
        support_strong = False
        pressure_strong = False

    # 返回结构化字典
    return {
        'interpretations': interpretations,
        'bias_score': final_score,
        'support_strong': support_strong,
        'pressure_strong': pressure_strong
    }

# --- 修改：核心分析函数，只返回静态结果 --- 

CONFIG_TICK_SIZES = getattr(配置, 'TICK_SIZES', {}) # 从配置加载TICK_SIZES

def 获取TickSize(symbol_key): # 参数名改为 symbol_key
    """获取指定交易对(键)的 tickSize，优先从配置读取，失败则尝试API。"""
    # 1. 尝试从配置读取
    if symbol_key in CONFIG_TICK_SIZES: # 使用 symbol_key 查找
        tick_size = CONFIG_TICK_SIZES[symbol_key]
        logger.debug(f"从配置中获取 {symbol_key} 的 tickSize: {tick_size}") # 日志用 symbol_key
        return tick_size
    
    # 2. 配置中没有，尝试调用 API (如果数据获取模块可用)
    # 注意：这里的 API 调用仍然是基于原始 symbol (去掉 _FUTURES 后缀)
    original_symbol = symbol_key.replace('_FUTURES', '')
    logger.info(f"配置中未找到 {symbol_key} 的 tickSize，尝试从 API 获取 {original_symbol} 的信息...")
    if 获取交易所信息 is not None: # 检查函数是否导入成功
        try:
            exchange_info = 获取交易所信息() # 假设此函数有内部缓存机制
            if exchange_info and 'symbols' in exchange_info:
                for s_info in exchange_info['symbols']:
                    if s_info['symbol'] == original_symbol: # 比较原始 symbol
                        for f in s_info['filters']:
                            if f['filterType'] == 'PRICE_FILTER':
                                api_tick_size = float(f['tickSize'])
                                logger.info(f"通过 API 获取到 {original_symbol} 的 tickSize: {api_tick_size}")
                                # 可选：可以将获取到的值更新回 CONFIG_TICK_SIZES 供后续使用？
                                # CONFIG_TICK_SIZES[symbol_key] = api_tick_size 
                                return api_tick_size
                logger.warning(f"通过 API 未找到 {original_symbol} 的 PRICE_FILTER。")
            else:
                logger.warning("通过 API 无法获取有效的交易所信息。")
        except Exception as e:
            logger.error(f"通过 API 获取 {original_symbol} tickSize 时出错: {e}")
    else:
        logger.warning("数据获取模块或 `获取交易所信息` 函数不可用。")

    # 3. 最终回退到默认值
    default_tick_size = 0.01 # 极不准确的默认值!
    logger.warning(f"无法确定 {symbol_key} 的 tickSize，将使用默认值: {default_tick_size}")
    return default_tick_size

def 分析订单簿(symbol,
             depth_limit=500, # 函数默认值也改为 500
             large_order_percentile=95,
             market_type='spot',
             n_levels_analysis=100, # 函数默认值也改为 100 (主要分析层数)
             cumulative_depth_levels=[0.1, 0.2, 0.5]):
    """分析订单簿快照，计算多个指定层级和最大层级的指标。"""
    market_name = "现货" if market_type == 'spot' else "合约"
    logger.info(f"分析 {symbol} {market_name} 快照 (请求深度: {depth_limit}, 主要分析层级: {n_levels_analysis})...")

    # 根据 market_type 构造用于查找 TickSize 的键
    tick_size_key = f"{symbol}_FUTURES" if market_type == 'futures' else symbol
    tick_size = 获取TickSize(tick_size_key) # 使用构造的键
    if tick_size <= 0: tick_size = 0.01 # 保留默认回退

    # 获取订单簿数据 (使用传入的 depth_limit，现在是 500)
    if market_type == 'spot': order_book = 获取订单簿深度(symbol, limit=depth_limit)
    elif market_type == 'futures': order_book = 获取合约订单簿深度(symbol, limit=depth_limit)
    else: logger.error(f"无效市场类型: {market_type}"); return None
    if not order_book or 'bids' not in order_book or 'asks' not in order_book: return None
    timestamp = pd.to_datetime('now', utc=True)

    try:
        bids = pd.DataFrame(order_book['bids'], columns=['price', 'quantity'], dtype=float)
        asks = pd.DataFrame(order_book['asks'], columns=['price', 'quantity'], dtype=float)
    except Exception: return None
    if bids.empty or asks.empty: return None
    bids = bids.sort_values(by='price', ascending=False).reset_index(drop=True)
    asks = asks.sort_values(by='price', ascending=True).reset_index(drop=True)

    # --- 在传入计算函数前，计算必要的列 --- 
    try:
        bids['quoteQty'] = bids['price'] * bids['quantity']
        asks['quoteQty'] = asks['price'] * asks['quantity']
        # 计算累计量 (cumsum)
        bids['cum_quote_volume'] = bids['quoteQty'].cumsum()
        asks['cum_quote_volume'] = asks['quoteQty'].cumsum()
        # 也可以在这里计算累计 quantity (如果其他地方需要)
        # bids['cum_quantity'] = bids['quantity'].cumsum()
        # asks['cum_quantity'] = asks['quantity'].cumsum()
    except Exception as e:
        logger.error(f"计算 quoteQty 或 cum_quote_volume 时出错: {e}")
        return None # 如果计算出错，则无法继续分析
    # --------------------------------------

    # --- 基础信息 --- 
    best_bid_price = bids['price'].iloc[0]; best_bid_qty = bids['quantity'].iloc[0]
    best_ask_price = asks['price'].iloc[0]; best_ask_qty = asks['quantity'].iloc[0]
    spread = best_ask_price - best_bid_price
    spread_percentage = (spread / best_ask_price) * 100 if best_ask_price > 0 else 0
    total_bid_volume = bids['quantity'].sum(); total_ask_volume = asks['quantity'].sum()
    volume_ratio = total_bid_volume / total_ask_volume if total_ask_volume > 0 else np.inf

    # --- 计算多个层级的 OIR/WAP --- 
    actual_depth = min(len(bids), len(asks)) # 实际可用深度
    levels_to_calc = [5, n_levels_analysis, 500] # 目标计算层级 (5, 100, 500)
    oir_results = {}
    wap_results = {}
    total_bid_quote_vol_n = None # 初始化变量
    total_ask_quote_vol_n = None # 初始化变量

    logger.info(f"订单簿实际可用深度: {actual_depth} 层。开始计算 OIR/WAP...")
    for level in sorted(list(set(levels_to_calc))): # 去重并排序
        if actual_depth >= level and level > 0:
            logger.debug(f"计算 {level} 层 OIR/WAP...")
            bids_l, asks_l = bids.head(level), asks.head(level)
            oir_results[f'oir_{level}'] = calculate_multi_level_oir(bids_l, asks_l)
            wap_results[f'wap_{level}'] = calculate_multi_level_wap(bids_l, asks_l)

            # 如果当前计算的层级是主要分析层级，则计算并存储该层级的总报价量
            if level == n_levels_analysis:
                if 'quoteQty' in bids_l.columns:
                    total_bid_quote_vol_n = bids_l['quoteQty'].sum()
                if 'quoteQty' in asks_l.columns:
                    total_ask_quote_vol_n = asks_l['quoteQty'].sum()
        else:
            logger.warning(f"数据不足 ({actual_depth} 层)，无法计算 {level} 层 OIR/WAP。")
            oir_results[f'oir_{level}'] = None
            wap_results[f'wap_{level}'] = None

    # --- 计算最大可用层级的 OIR/WAP --- 
    oir_results['oir_max'] = None
    wap_results['wap_max'] = None
    if actual_depth > 0:
        logger.debug(f"计算最大 {actual_depth} 层 OIR/WAP...")
        bids_max, asks_max = bids.head(actual_depth), asks.head(actual_depth)
        oir_results['oir_max'] = calculate_multi_level_oir(bids_max, asks_max)
        wap_results['wap_max'] = calculate_multi_level_wap(bids_max, asks_max)
    
    # --- 其他指标计算 (保持不变) ---
    large_bids_df, large_bid_threshold, large_bids_total_qty, large_bids_vwap = identify_large_orders(bids, percentile=large_order_percentile)
    large_asks_df, large_ask_threshold, large_asks_total_qty, large_asks_vwap = identify_large_orders(asks, percentile=large_order_percentile)
    cumulative_depth_results = calculate_cumulative_depth(bids, asks, depth_limit)
    bid_gap_info = find_liquidity_gaps(bids, 'bids', tick_size)
    ask_gap_info = find_liquidity_gaps(asks, 'asks', tick_size)

    # --- 组装最终结果字典 --- 
    static_analysis_result = {
        'timestamp': timestamp, 'symbol': symbol, 'market_type': market_type, 
        'depth_limit_requested': depth_limit, # 请求的深度
        'depth_limit_actual': actual_depth,   # 实际可用深度
        'analysis_levels': n_levels_analysis, # 主要分析层级 (用于解读)
        'best_bid_price': best_bid_price, 'best_ask_price': best_ask_price,
        'best_bid_qty': best_bid_qty, 'best_ask_qty': best_ask_qty, 'spread': spread,
        'spread_percentage': spread_percentage, 'total_bid_volume': total_bid_volume,
        'total_ask_volume': total_ask_volume, 'volume_ratio': volume_ratio,
        **oir_results, # 合并所有 OIR 结果
        **wap_results, # 合并所有 WAP 结果
        'large_bids_count': len(large_bids_df), 'large_asks_count': len(large_asks_df),
        'large_bid_threshold': large_bid_threshold, 'large_ask_threshold': large_ask_threshold,
        'large_bids_total_qty': large_bids_total_qty, 'large_bids_vwap': large_bids_vwap,
        'large_asks_total_qty': large_asks_total_qty, 'large_asks_vwap': large_asks_vwap,
        **cumulative_depth_results,
        'bid_gap_info': bid_gap_info,
        'ask_gap_info': ask_gap_info,
        'tick_size': tick_size,
        # 新增：添加主要分析层级的总报价量
        'total_bid_quote_vol_n': total_bid_quote_vol_n,
        'total_ask_quote_vol_n': total_ask_quote_vol_n
    }

    # --- 调用解读函数 (使用主要分析层级 n_levels_analysis 的指标) ---
    # 确保 'oir_100' 等主要指标存在于字典中供解读函数使用
    interpretation_result = interpret_analysis(static_analysis_result, tick_size, dynamic_indicators=None)
    static_analysis_result['interpretation'] = interpretation_result

    # --- 最终返回前的日志 --- 
    logger.debug(f"[分析订单簿-调试] （最终）返回结果字典的键: {list(static_analysis_result.keys())}")

    return static_analysis_result

# --- 重构：测试代码以包含动态分析循环 --- 
if __name__ == '__main__':
    if binance_client is None:
        logger.critical("币安客户端未初始化...")
    else:
        test_symbol = 'BTCUSDT' 
        test_percentile = 98 
        n_levels_to_analyze = 5 
        test_cumulative_levels = [0.1, 0.2, 0.5] 

        test_scenarios = [
            # 将所有测试场景的 depth 改为 500
            {'market': 'spot', 'timeframe': '现货-中线', 'depth': 500},
            {'market': 'futures', 'timeframe': '合约-短线', 'depth': 500},
            {'market': 'futures', 'timeframe': '合约-中线', 'depth': 500},
        ]
        
        previous_analysis_results = {} # 存储上一轮结果
        num_iterations = TEST_LOOP_ITERATIONS
        interval_seconds = TEST_LOOP_INTERVAL

        logger.info(f"\n--- 开始动态订单簿分析测试 ({num_iterations} 次迭代, 间隔 {interval_seconds} 秒) ---")

        for i in range(num_iterations):
            logger.info(f"\n=====>>> 迭代 {i+1}/{num_iterations} <<<=====")
            current_iteration_results = {} # 存储当前轮次给下一轮用
            
            for scenario in test_scenarios:
                market = scenario['market']
                timeframe = scenario['timeframe']
                depth = scenario['depth']
                logger.info(f"--- 分析 {timeframe} (市场: {market}, 深度: {depth}) ---")
                
                # 1. 获取当前静态分析结果
                current_analysis = 分析订单簿(test_symbol, 
                                          depth_limit=depth, 
                                          large_order_percentile=test_percentile, 
                                          market_type=market, 
                                          n_levels_analysis=n_levels_to_analyze,
                                          cumulative_depth_levels=test_cumulative_levels)
                
                if current_analysis:
                    # 2. 获取上一轮结果
                    previous_analysis = previous_analysis_results.get(timeframe)
                    
                    # 3. 计算动态指标
                    dynamic_indicators = calculate_dynamic_indicators(current_analysis, previous_analysis)
                    
                    # 4. 生成解读和评分 (传入动态指标)
                    tick_size = current_analysis.get('tick_size', 0.01) # 从结果中获取tick_size
                    # 更新调用方式：接收字典
                    interpretation_result = interpret_analysis(current_analysis, tick_size, dynamic_indicators=dynamic_indicators)
                    # 从字典中提取所需信息
                    score = interpretation_result.get('bias_score', 0) # 使用 bias_score 作为评分
                    interpretation_list = interpretation_result.get('interpretations', []) # 获取解读列表
                    
                    # 5. 打印结果
                    print(f"\n---------- {timeframe} (市场: {market}, 深度: {depth}) - 迭代 {i+1} ----------")
                    # 打印静态指标 (可以封装成一个函数简化)
                    n_analyzed = current_analysis['analysis_levels']
                    oir_key = f'oir_{n_analyzed}'; wap_key = f'wap_{n_analyzed}'
                    price_decimals = str(current_analysis['best_ask_price'])[::-1].find('.'); price_decimals = max(2, price_decimals)
                    qty_decimals = 4 
                    print(f"时间戳: {current_analysis['timestamp']}")
                    print(f"最佳 L1: 买 {current_analysis['best_bid_price']:.{price_decimals}f}({current_analysis['best_bid_qty']:.{qty_decimals}f}) / 卖 {current_analysis['best_ask_price']:.{price_decimals}f}({current_analysis['best_ask_qty']:.{qty_decimals}f}) | 价差: {current_analysis['spread']:.{price_decimals}f} ({current_analysis['spread_percentage']:.4f}%)")
                    print(f"OIR({n_analyzed}): {current_analysis.get(oir_key, 'N/A'):.4f} | WAP({n_analyzed}): {current_analysis.get(wap_key, 'N/A'):.{price_decimals}f}")
                    # --- 修改：打印累计深度指标 --- 
                    print(f"累计深度(报价量):") # 标签改为按档位
                    calculated_levels = [5, 20, 50, 100, 500] # 实际计算的档位
                    for level in calculated_levels:
                        ckey_b = f'cum_bid_vol_{level}' # 正确的 Key
                        ckey_a = f'cum_ask_vol_{level}' # 正确的 Key
                        ckey_oir = f'oir_{level}' # 获取对应档位的OIR

                        bq = current_analysis.get(ckey_b) # 获取买盘累计报价量
                        aq = current_analysis.get(ckey_a) # 获取卖盘累计报价量
                        oir = current_analysis.get(ckey_oir) # 获取OIR

                        # 安全格式化
                        bq_s = f"{bq:.{qty_decimals}f}" if isinstance(bq, (int, float)) and np.isfinite(bq) else str(bq if bq is not None else 'N/A')
                        aq_s = f"{aq:.{qty_decimals}f}" if isinstance(aq, (int, float)) and np.isfinite(aq) else str(aq if aq is not None else 'N/A')
                        oir_s = f"{oir:.4f}" if isinstance(oir, (int, float)) and np.isfinite(oir) else str(oir if oir is not None else 'N/A')

                        print(f"  {level}档: 买={bq_s}, 卖={aq_s}, OIR={oir_s}") # 打印格式化后的字符串
                    # ------------------------------
                    print(f"大单(>{test_percentile}%):")
                    bv=current_analysis['large_bids_vwap'];bdec=str(bv)[::-1].find('.');bdec=max(2,bdec);bv_s=f"{bv:.{bdec}f}" if current_analysis['large_bids_total_qty']>0 else 'N/A'
                    av=current_analysis['large_asks_vwap'];adec=str(av)[::-1].find('.');adec=max(2,adec);av_s=f"{av:.{adec}f}" if current_analysis['large_asks_total_qty']>0 else 'N/A'
                    print(f"  买: {current_analysis['large_bids_count']}笔, 总量={current_analysis['large_bids_total_qty']:.{qty_decimals}f}, VWAP={bv_s} (阈>{current_analysis['large_bid_threshold']:.{qty_decimals}f})")
                    print(f"  卖: {current_analysis['large_asks_count']}笔, 总量={current_analysis['large_asks_total_qty']:.{qty_decimals}f}, VWAP={av_s} (阈>{current_analysis['large_ask_threshold']:.{qty_decimals}f})")
                    # 打印动态指标 (如果存在)
                    if dynamic_indicators:
                        print("--- 动态指标 (与上一轮比) ---")
                        for key, value in dynamic_indicators.items():
                            if value is not None:
                                # 动态格式化小数位数
                                delta_decimals = qty_decimals # 默认使用数量小数位
                                if 'vwap' in key or 'wap' in key or 'ratio' in key or 'oir' in key: # 价格或比率相关的 delta
                                    # 对于价格相关的 delta，尝试使用价格小数位
                                    # 对于比率或OIR，使用固定小数位（例如4位）
                                    if 'vwap' in key or 'wap' in key: 
                                        delta_decimals = price_decimals
                                    else: # OIR, ratio
                                        delta_decimals = 4 
                                print(f"  {key}: {value:+.{delta_decimals}f}") 
                        print("-----------------------------")
                    # 打印解读和评分
                    print(f"综合评分: {score} | 解读:")
                    for interp in interpretation_list:
                        print(f"  {interp}")
                    print("-----------------------------------------------------------")
                    
                    # 6. 存储当前结果供下一轮使用 (用 deepcopy 避免引用问题)
                    current_iteration_results[timeframe] = deepcopy(current_analysis) 
                else:
                    print(f"未能完成 {test_symbol} 的 {timeframe} (市场: {market}, 深度: {depth}) 分析。")
                    current_iteration_results[timeframe] = None # 标记失败
           
            # 更新上一轮结果
            previous_analysis_results = current_iteration_results
           
            # 如果不是最后一次迭代，则等待间隔时间
            if i < num_iterations - 1:
                logger.info(f"迭代 {i+1} 完成，等待 {interval_seconds} 秒...")
                time.sleep(interval_seconds)

        logger.info("动态订单簿分析测试结束。")