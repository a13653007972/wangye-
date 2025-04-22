# -*- coding: utf-8 -*-
"""
深度分析模块 (基于多层级成交流分析)

分析近期成交记录，根据成交额大小将交易分层（小单、中单、大单），
统计各层级的主动买卖行为，判断不同体量资金的动向。
"""

import logging
import pandas as pd
import numpy as np
import time
from typing import Dict, Any, List

# --- 导入依赖 ---
try:
    # 导入数据获取函数和配置
    import 数据获取模块
    from 数据获取模块 import 获取近期成交记录, 获取合约近期成交记录, logger as data_logger
    import 配置
    # 从配置导入相关设置 (如果需要的话，例如分位数阈值)
    DEPTH_ANALYSIS_CONFIG = getattr(配置, 'DEPTH_ANALYSIS_CONFIG', {})
except ImportError as e:
    logging.critical(f"无法导入必要的模块或配置: {e}. 请确保 '数据获取模块.py' 和 '配置.py' 文件存在且路径正确。", exc_info=True)
    # 提供 fallback
    数据获取模块 = None
    获取近期成交记录 = None
    获取合约近期成交记录 = None
    DEPTH_ANALYSIS_CONFIG = {}
    data_logger = None

# --- 日志记录器配置 ---
# 可以复用数据获取模块的 logger，或创建独立的 logger
if data_logger:
    logger = data_logger # 复用
    logger.info("深度分析模块 复用 数据获取模块 logger")
else:
    logger = logging.getLogger(__name__)
    if not logger.hasHandlers():
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger.info("深度分析模块 创建了独立的 logger")

# --- 默认配置 ---
DEFAULT_FETCH_LIMIT = DEPTH_ANALYSIS_CONFIG.get('fetch_limit', 1000) # 获取多少条成交记录
DEFAULT_SMALL_TRADE_PERCENTILE = DEPTH_ANALYSIS_CONFIG.get('small_trade_percentile', 25) # 小单阈值百分位
DEFAULT_LARGE_TRADE_PERCENTILE = DEPTH_ANALYSIS_CONFIG.get('large_trade_percentile', 75) # 大单阈值百分位
DEFAULT_MIN_QUOTE_VALUE_THRESHOLD = DEPTH_ANALYSIS_CONFIG.get('min_quote_value_threshold', 100) # 过滤掉过小的成交额 (可选)

# --- 主分析函数 ---
def 分析多层级成交量(symbol: str,
                     market_type: str = 'spot',
                     limit: int = DEFAULT_FETCH_LIMIT,
                     small_percentile: int = DEFAULT_SMALL_TRADE_PERCENTILE,
                     large_percentile: int = DEFAULT_LARGE_TRADE_PERCENTILE,
                     min_quote_value: float = DEFAULT_MIN_QUOTE_VALUE_THRESHOLD
                     ) -> Dict[str, Any]:
    """
    执行多层级成交量分析。

    Args:
        symbol (str): 交易对，例如 'BTCUSDT'.
        market_type (str): 市场类型 ('spot' 或 'futures').
        limit (int): 获取近期成交记录的数量.
        small_percentile (int): 定义小单的成交额百分位数上限 (0-100).
        large_percentile (int): 定义大单的成交额百分位数下限 (0-100).
        min_quote_value (float): 过滤掉成交额低于此值的记录.

    Returns:
        Dict[str, Any]: 包含分析结果的字典。
                        键包括 'parameters', 'tier_metrics', 'interpretation', 'error'。
                        'tier_metrics' 是一个字典，键为 'small', 'medium', 'large'，
                        值为对应层级的指标字典。
                        如果失败，返回包含 'error' 键的字典。
    """
    start_time = time.time()
    results = {
        'parameters': {
            'symbol': symbol,
            'market_type': market_type,
            'limit': limit,
            'small_percentile': small_percentile,
            'large_percentile': large_percentile,
            'min_quote_value': min_quote_value,
        },
        'tier_metrics': {
            'small': None,
            'medium': None,
            'large': None,
            'overall': None, # 添加一个总体统计
        },
        'interpretation': None,
        'error': None
    }

    logger.info(f"开始对 {symbol} ({market_type}) 进行多层级成交量分析 (最近 {limit} 条)...")

    # --- 1. 检查依赖 ---
    if not 数据获取模块 or not 获取近期成交记录 or not 获取合约近期成交记录:
        results['error'] = "数据获取模块或所需函数未能加载。"
        logger.error(results['error'])
        return results
    if not (0 <= small_percentile < large_percentile <= 100):
         results['error'] = f"百分位阈值设置无效: small={small_percentile}, large={large_percentile}"
         logger.error(results['error'])
         return results

    # --- 2. 获取数据 ---
    get_trades_func = 获取合约近期成交记录 if market_type == 'futures' else 获取近期成交记录
    raw_trades = get_trades_func(symbol=symbol, limit=limit)

    # --- 移除调试日志 ---
    # logger.debug(f"[深度分析-调试] raw_trades 类型: {type(raw_trades)}")
    # if isinstance(raw_trades, (list, pd.DataFrame)):
    #      logger.debug(f"[深度分析-调试] raw_trades 长度: {len(raw_trades)}")
    # --- 调试日志结束 ---

    # --- 修改检查逻辑：接受 DataFrame 并检查是否为空 ---
    if raw_trades is None or (isinstance(raw_trades, (list, pd.DataFrame)) and len(raw_trades) == 0):
        results['error'] = f"未能获取到 {symbol} ({market_type}) 的近期成交记录或返回为空。"
        logger.warning(f"{results['error']} 返回类型: {type(raw_trades)}") 
        return results

    # --- 3. 数据预处理和分档 ---
    try:
        # --- 确保输入给 DataFrame 构造函数的是合适的类型 --- 
        if isinstance(raw_trades, list): # 如果是列表，需要转换为 DataFrame
            df_trades = pd.DataFrame(raw_trades)
        elif isinstance(raw_trades, pd.DataFrame): # 如果已经是 DataFrame，直接用
            df_trades = raw_trades 
        else:
            # 如果是其他意外类型，记录错误并退出
            results['error'] = f"从数据获取模块接收到的成交记录类型不受支持: {type(raw_trades)}。"
            logger.error(results['error'])
            return results

        # 标准化列名 (根据币安 API 返回调整)
        df_trades.rename(columns={
            'price': 'price',
            'qty': 'quantity',
            'quoteQty': 'quote_volume', # 成交额
            'time': 'timestamp',
            'isBuyerMaker': 'is_buyer_maker'
        }, inplace=True)

        # 确保数据类型正确
        df_trades['price'] = pd.to_numeric(df_trades['price'], errors='coerce')
        df_trades['quantity'] = pd.to_numeric(df_trades['quantity'], errors='coerce')
        df_trades['quote_volume'] = pd.to_numeric(df_trades['quote_volume'], errors='coerce')
        df_trades['timestamp'] = pd.to_datetime(df_trades['timestamp'], unit='ms', errors='coerce')
        df_trades['is_buyer_maker'] = df_trades['is_buyer_maker'].astype(bool)

        # 删除包含 NaN 的行 (数据质量问题)
        df_trades.dropna(subset=['price', 'quantity', 'quote_volume', 'timestamp', 'is_buyer_maker'], inplace=True)

        # 过滤掉成交额过小的记录
        if min_quote_value > 0:
            df_trades = df_trades[df_trades['quote_volume'] >= min_quote_value]

        if df_trades.empty:
            results['error'] = f"过滤后没有有效的成交记录 (limit={limit}, min_quote_value={min_quote_value})."
            logger.warning(results['error'])
            return results

        # 计算百分位阈值
        quote_vol_threshold_small = np.percentile(df_trades['quote_volume'], small_percentile)
        quote_vol_threshold_large = np.percentile(df_trades['quote_volume'], large_percentile)
        logger.info(f"成交额分档阈值: Small (<{quote_vol_threshold_small:.2f}), "
                    f"Medium ({quote_vol_threshold_small:.2f}-{quote_vol_threshold_large:.2f}), "
                    f"Large (>{quote_vol_threshold_large:.2f})")

        # 定义分档函数
        def classify_trade(quote_vol):
            if quote_vol < quote_vol_threshold_small:
                return 'small'
            elif quote_vol <= quote_vol_threshold_large:
                return 'medium'
            else:
                return 'large'

        # 应用分档
        df_trades.loc[:, 'tier'] = df_trades['quote_volume'].apply(classify_trade)

        # 确定主动买卖方向 (Taker perspective)
        # isBuyerMaker = False -> Taker是买方 -> 主动买入
        # isBuyerMaker = True  -> Taker是卖方 -> 主动卖出
        df_trades.loc[:, 'taker_action'] = np.where(df_trades['is_buyer_maker'] == False, 'buy', 'sell')

    except Exception as e:
        results['error'] = f"数据预处理或分档时出错: {e}"
        logger.error(results['error'], exc_info=True)
        return results

    # --- 4. 计算各档指标 ---
    try:
        grouped = df_trades.groupby(['tier', 'taker_action'])

        # 提前准备存储结构
        tier_metrics = {
            'small': {'buy': {}, 'sell': {}},
            'medium': {'buy': {}, 'sell': {}},
            'large': {'buy': {}, 'sell': {}},
            'overall': {'buy': {}, 'sell': {}} # 添加总体
        }

        # 计算核心聚合指标
        agg_metrics = grouped.agg(
            total_quote_volume=('quote_volume', 'sum'),
            total_base_volume=('quantity', 'sum'),
            trade_count=('timestamp', 'count'),
            # 计算 VWAP 需要分子 (price * quantity)
            vwap_numerator=('price', lambda x: (x * df_trades.loc[x.index, 'quantity']).sum())
        ).unstack(fill_value=0) # 将 taker_action (buy/sell) 变为列

        # 计算并填充各层级的指标
        for tier in ['small', 'medium', 'large']:
            if tier in agg_metrics.index:
                for action in ['buy', 'sell']:
                    action_prefix = f"{'taker_buy' if action == 'buy' else 'taker_sell'}"
                    metrics = {}
                    metrics[f'{action_prefix}_quote_volume'] = agg_metrics.loc[tier, ('total_quote_volume', action)]
                    metrics[f'{action_prefix}_base_volume'] = agg_metrics.loc[tier, ('total_base_volume', action)]
                    metrics[f'{action_prefix}_count'] = agg_metrics.loc[tier, ('trade_count', action)]

                    # 计算 VWAP
                    numerator = agg_metrics.loc[tier, ('vwap_numerator', action)]
                    denominator = metrics[f'{action_prefix}_base_volume']
                    metrics[f'{action_prefix}_vwap'] = numerator / denominator if denominator > 0 else None

                    tier_metrics[tier][action] = metrics
            else:
                 logger.warning(f"在聚合结果中未找到层级 '{tier}'，可能该层级没有交易数据。")

        # 计算总体指标 (方法类似，但不分组)
        overall_grouped = df_trades.groupby('taker_action')
        overall_agg = overall_grouped.agg(
            total_quote_volume=('quote_volume', 'sum'),
            total_base_volume=('quantity', 'sum'),
            trade_count=('timestamp', 'count'),
            vwap_numerator=('price', lambda x: (x * df_trades.loc[x.index, 'quantity']).sum())
        )
        for action in ['buy', 'sell']:
            if action in overall_agg.index:
                 action_prefix = f"{'taker_buy' if action == 'buy' else 'taker_sell'}"
                 metrics = {}
                 metrics[f'{action_prefix}_quote_volume'] = overall_agg.loc[action, 'total_quote_volume']
                 metrics[f'{action_prefix}_base_volume'] = overall_agg.loc[action, 'total_base_volume']
                 metrics[f'{action_prefix}_count'] = overall_agg.loc[action, 'trade_count']
                 numerator = overall_agg.loc[action, 'vwap_numerator']
                 denominator = metrics[f'{action_prefix}_base_volume']
                 metrics[f'{action_prefix}_vwap'] = numerator / denominator if denominator > 0 else None
                 tier_metrics['overall'][action] = metrics
            else:
                 logger.warning(f"在总体聚合结果中未找到 Taker Action '{action}'。")


        # 计算衍生指标 (净额，比例等) - 避免除零错误
        for tier in ['small', 'medium', 'large', 'overall']:
            buy_metrics = tier_metrics[tier].get('buy', {})
            sell_metrics = tier_metrics[tier].get('sell', {})

            buy_quote = buy_metrics.get('taker_buy_quote_volume', 0)
            sell_quote = sell_metrics.get('taker_sell_quote_volume', 0)

            tier_metrics[tier]['net_quote_volume'] = buy_quote - sell_quote
            tier_metrics[tier]['pressure_ratio_quote'] = buy_quote / sell_quote if sell_quote > 0 else np.inf if buy_quote > 0 else np.nan

            buy_count = buy_metrics.get('taker_buy_count', 0)
            sell_count = sell_metrics.get('taker_sell_count', 0)
            tier_metrics[tier]['pressure_ratio_count'] = buy_count / sell_count if sell_count > 0 else np.inf if buy_count > 0 else np.nan


        results['tier_metrics'] = tier_metrics

    except Exception as e:
        results['error'] = f"计算各档指标时出错: {e}"
        logger.error(results['error'], exc_info=True)
        return results

    # --- 5. 结果解读与建议生成 ---
    try:
        interpretation_details = []
        suggestion = "建议观望。"
        confidence = "中"

        # 获取各层级指标 (确保有默认值)
        large_metrics = results['tier_metrics'].get('large', {})
        medium_metrics = results['tier_metrics'].get('medium', {})
        small_metrics = results['tier_metrics'].get('small', {})
        overall_metrics = results['tier_metrics'].get('overall', {})

        # 提取关键数值
        large_net = large_metrics.get('net_quote_volume', 0)
        medium_net = medium_metrics.get('net_quote_volume', 0)
        small_net = small_metrics.get('net_quote_volume', 0)
        overall_net = overall_metrics.get('net_quote_volume', 0)
        large_pressure_q = large_metrics.get('pressure_ratio_quote', np.nan)
        overall_pressure_q = overall_metrics.get('pressure_ratio_quote', np.nan)
        large_buy_vwap = large_metrics.get('buy', {}).get('taker_buy_vwap')
        large_sell_vwap = large_metrics.get('sell', {}).get('taker_sell_vwap')

        # 定义强度判断的简单阈值 (可后续优化或移至配置)
        strong_pressure_ratio_buy = 1.5
        strong_pressure_ratio_sell = 1 / strong_pressure_ratio_buy # ~0.67

        # 1. 分析大单方向和强度
        large_direction = "不明" 
        large_strength = "弱"
        if large_net > 0:
            large_direction = "净买入"
            if not np.isnan(large_pressure_q) and large_pressure_q >= strong_pressure_ratio_buy:
                large_strength = "强"
            interpretation_details.append(f"大单{large_strength}{large_direction}(净额:{large_net:.2f}, 买/卖比:{large_pressure_q:.2f}x)。")
        elif large_net < 0:
            large_direction = "净卖出"
            if not np.isnan(large_pressure_q) and large_pressure_q <= strong_pressure_ratio_sell:
                large_strength = "强"
            interpretation_details.append(f"大单{large_strength}{large_direction}(净额:{large_net:.2f}, 买/卖比:{large_pressure_q:.2f}x)。")
        else:
            interpretation_details.append("大单买卖均衡。")

        # 2. 对比大单与中小单行为 (寻找确认或分歧)
        small_direction = "不明"
        if small_net > 0: small_direction = "净买入"
        elif small_net < 0: small_direction = "净卖出"
        
        medium_direction = "不明"
        if medium_net > 0: medium_direction = "净买入"
        elif medium_net < 0: medium_direction = "净卖出"

        is_confirming = False
        is_diverging = False
        if large_direction == "净买入" and small_direction == "净买入": # and medium_direction == "净买入":
             interpretation_details.append("中小单行为确认大单买入方向。")
             is_confirming = True
        elif large_direction == "净卖出" and small_direction == "净卖出": # and medium_direction == "净卖出":
             interpretation_details.append("中小单行为确认大单卖出方向。")
             is_confirming = True
        elif large_direction == "净买入" and small_direction == "净卖出":
             interpretation_details.append("注意：大单买入，小单卖出，可能存在分歧或吸筹。")
             is_diverging = True
        elif large_direction == "净卖出" and small_direction == "净买入":
             interpretation_details.append("注意：大单卖出，小单买入，可能存在分歧或派发。")
             is_diverging = True
        elif large_direction != "不明": # 大单有方向，但小单方向不一致或不明
             interpretation_details.append(f"中小单方向({medium_direction}/{small_direction})与大单({large_direction})不完全一致。")
             # 可以视为弱分歧或信号减弱
        else: # 大单均衡
             interpretation_details.append(f"大单均衡，关注中小单({medium_direction}/{small_direction})动向。")
             
        # 3. 查看总体情况
        overall_direction = "不明"
        if overall_net > 0: overall_direction = "净买入"
        elif overall_net < 0: overall_direction = "净卖出"
        interpretation_details.append(f"总体成交{overall_direction}(净额:{overall_net:.2f}, 买/卖比:{overall_pressure_q:.2f}x)。")

        # 4. 生成建议和置信度
        if large_direction == "净买入":
            if is_confirming:
                suggestion = "主要由大单推动且中小单跟随，短期看涨倾向较强，可考虑寻找低位做多机会。"
                confidence = "高" if large_strength == "强" else "中"
            elif is_diverging: # 大买 小卖
                suggestion = "大单买入但小单抛售，市场或存分歧，需警惕假突破风险，若价格坚挺或为吸筹，可谨慎试多。"
                confidence = "低"
            else: # 大买 中小不明确
                suggestion = "大单倾向买入，但市场整体跟随度不高，看涨信号有所减弱，建议谨慎偏多或观望。"
                confidence = "中"
        elif large_direction == "净卖出":
            if is_confirming:
                suggestion = "主要由大单推动且中小单跟随，短期看跌倾向较强，可考虑寻找高位做空机会。"
                confidence = "高" if large_strength == "强" else "中"
            elif is_diverging: # 大卖 小买
                suggestion = "大单卖出但小单承接，市场或存分歧，需警惕诱空风险，若价格疲软或为派发，可谨慎试空。"
                confidence = "低"
            else: # 大卖 中小不明确
                suggestion = "大单倾向卖出，但市场整体跟随度不高，看跌信号有所减弱，建议谨慎偏空或观望。"
                confidence = "中"
        else: # 大单不明
            suggestion = "大单方向不明，市场缺乏明确主导力量，建议保持观望，等待更清晰信号。"
            confidence = "低"
            
        # 添加VWAP观察 (可选)
        if large_buy_vwap and large_sell_vwap:
             if large_buy_vwap > large_sell_vwap:
                 interpretation_details.append(f"大单买方均价({large_buy_vwap:.2f})高于卖方均价({large_sell_vwap:.2f})，买方更积极。")
             elif large_buy_vwap < large_sell_vwap:
                 interpretation_details.append(f"大单买方均价({large_buy_vwap:.2f})低于卖方均价({large_sell_vwap:.2f})，卖方压价更明显。")

        # 保存解读和建议
        results['interpretation'] = {
            'details': interpretation_details, # 详细分析点
            'suggestion': suggestion, # 综合建议
            'confidence': confidence   # 置信度 (高/中/低)
        }
        logger.info(f"多层级成交量分析解读完成。建议: {suggestion} (置信度: {confidence})" )

    except Exception as e:
        results['error'] = f"生成结果解读或建议时出错: {e}"
        logger.error(results['error'], exc_info=True)
        # 保留已计算的指标，只标记解读错误
        results['interpretation'] = {
            'details': [f"Error during interpretation: {e}"],
            'suggestion': "因解读错误，建议观望。",
            'confidence': "低"
        }

    end_time = time.time()
    logger.info(f"多层级成交量分析完成 for {symbol} ({market_type}). 耗时: {end_time - start_time:.2f} 秒")
    return results

# --- 测试执行块 ---
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='执行多层级成交量分析。')
    parser.add_argument('--symbol', type=str, default='BTCUSDT', help='要分析的交易对 (例如: BTCUSDT)')
    parser.add_argument('--market', type=str, default='futures', choices=['spot', 'futures'], help='市场类型 (spot 或 futures)')
    parser.add_argument('--limit', type=int, default=DEFAULT_FETCH_LIMIT, help='获取的成交记录数量')
    parser.add_argument('--small', type=int, default=DEFAULT_SMALL_TRADE_PERCENTILE, help='小单百分位阈值')
    parser.add_argument('--large', type=int, default=DEFAULT_LARGE_TRADE_PERCENTILE, help='大单百分位阈值')
    parser.add_argument('--min_quote', type=float, default=DEFAULT_MIN_QUOTE_VALUE_THRESHOLD, help='最小成交额过滤阈值')

    args = parser.parse_args()

    # 确保日志能输出到控制台 (如果 logger 没有 StreamHandler)
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
         handler = logging.StreamHandler()
         formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
         handler.setFormatter(formatter)
         logger.addHandler(handler)
         logger.setLevel(logging.INFO) # 确保INFO级别能输出

    logger.info(f"--- 测试深度分析模块 (多层级成交量) ---")
    logger.info(f"参数: symbol={args.symbol}, market={args.market}, limit={args.limit}, "
                f"small_pct={args.small}, large_pct={args.large}, min_quote={args.min_quote}")

    analysis_result = 分析多层级成交量(
        symbol=args.symbol,
        market_type=args.market,
        limit=args.limit,
        small_percentile=args.small,
        large_percentile=args.large,
        min_quote_value=args.min_quote
    )

    # --- 修改打印逻辑以适应新的结果格式 ---
    print("\n--- 分析结果 ---")
    if analysis_result.get('error'):
        print(f"错误: {analysis_result['error']}")
    else:
        print(f"参数: {analysis_result.get('parameters')}")
        print("\n层级指标 (摘要):") # 只打摘要
        for tier in ['small', 'medium', 'large', 'overall']:
            tier_data = analysis_result.get('tier_metrics', {}).get(tier)
            if tier_data and isinstance(tier_data, dict):
                print(f"  --- {tier.upper()} Tier ---")
                net_quote = tier_data.get('net_quote_volume', 'N/A')
                pressure_q = tier_data.get('pressure_ratio_quote', 'N/A')
                net_quote_str = f"{net_quote:.2f}" if isinstance(net_quote, (int, float)) else str(net_quote)
                pressure_q_str = f"{pressure_q:.2f}x" if isinstance(pressure_q, (int, float)) and not np.isnan(pressure_q) and not np.isinf(pressure_q) else str(pressure_q)
                print(f"    净成交额: {net_quote_str}, 成交额压力比: {pressure_q_str}")
            else:
                print(f"  --- {tier.upper()} Tier ---: 无数据")

        print("\n--- 解读与建议 ---")
        interpretation_result = analysis_result.get('interpretation')
        if interpretation_result and isinstance(interpretation_result, dict):
            # --- 新增：明确分析依据 --- 
            print("  主要依据: 大单动向及中小单确认/分歧情况") 
            # -------------------------
            print("  分析详情:")
            for detail in interpretation_result.get('details', []):
                print(f"    - {detail}")
            print(f"\n  综合建议: {interpretation_result.get('suggestion', 'N/A')}")
            print(f"  置 信 度: {interpretation_result.get('confidence', 'N/A')}")
        else:
            print("  未能生成解读或建议。")

    print("\n--- 测试结束 ---")
