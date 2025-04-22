import logging
from typing import Dict, Any, List
import time # Import time for timestamp
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse # 导入 argparse

# --- 导入依赖模块 --- 
try:
    import 数据获取模块
except ImportError:
    logging.error("无法导入 数据获取模块。")
    数据获取模块 = None

try:
    import 订单簿分析 as 订单簿分析模块
    # 确认主分析函数名
    from 订单簿分析 import 分析订单簿
except ImportError:
    logging.error("无法导入 订单簿分析 模块。")
    分析订单簿 = None
    订单簿分析模块 = None

try:
    import 成交流分析 as 成交流模块
    # 确认主分析函数名和数据准备函数名
    from 成交流分析 import 获取并处理近期成交, 分析成交流
except ImportError:
    logging.error("无法导入 成交流分析 模块。")
    获取并处理近期成交 = None
    分析成交流 = None
    成交流模块 = None

try:
    import 微观趋势动量
    from 微观趋势动量 import 执行多周期分析, 整合多周期信号 
except ImportError:
    logging.error("无法导入 微观趋势动量 模块或其函数。")
    微观趋势动量 = None
    执行多周期分析 = None
    整合多周期信号 = None

try:
    import 箱体突破分析
    from 箱体突破分析 import 分析箱体突破
except ImportError:
    logging.error("无法导入 箱体突破分析 模块。")
    分析箱体突破 = None

try:
    import 配置
    # 导入所有需要的配置字典
    from 配置 import MICRO_TREND_CONFIG, TRADE_FLOW_CONFIG, ORDER_BOOK_CONFIG 
    from 配置 import INTEGRATED_ANALYSIS_CONFIG
    from 配置 import BOX_BREAKOUT_CONFIG # <--- 添加导入
    # 确保导入成交流阈值 (如果 TRADE_FLOW_CONFIG 包含它则无需单独导入)
    # from 配置 import TRADE_FLOW_INTERPRETATION_THRESHOLDS # 假设它在 TRADE_FLOW_CONFIG 内
except ImportError:
    logging.error("无法导入 配置 模块或所需配置。")
    配置 = None
    MICRO_TREND_CONFIG = {}
    TRADE_FLOW_CONFIG = {} # TRADE_FLOW_INTERPRETATION_THRESHOLDS 通常嵌套在这里
    ORDER_BOOK_CONFIG = {}
    INTEGRATED_ANALYSIS_CONFIG = {}
    BOX_BREAKOUT_CONFIG = {} # <--- 在 except 块中也提供默认值

# --- 日志配置 --- 
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- 综合分析函数 --- 
def 执行综合分析(symbol: str, market_type: str = 'spot') -> Dict[str, Any]:
    """
    执行对指定交易对的综合市场分析，整合订单簿、成交流和微观趋势信息。

    Args:
        symbol (str): 要分析的交易对，例如 "BTCUSDT"。
        market_type (str): 市场类型，'spot' 或 'futures'。

    Returns:
        Dict[str, Any]: 包含各项分析结果的字典。
                        键可能包括 'symbol', 'market_type', 'timestamp', 
                        'order_book_analysis', 'trade_flow_analysis', 
                        'micro_trend_mtf', 'micro_trend_integrated', 'box_breakout'。
                        如果某个模块分析失败，对应的值可能为 None 或包含错误信息。
    """
    logger.info(f"开始对 {symbol} ({market_type}) 进行综合分析...")
    start_time = time.time()
    analysis_results = {
        "symbol": symbol,
        "market_type": market_type,
        "timestamp": pd.Timestamp.now(tz='Asia/Shanghai'), # 记录分析时间
        "order_book_analysis": None,
        "trade_flow_analysis": None,
        "micro_trend_mtf": None,
        "micro_trend_integrated": None,
        "box_breakout": None, # <--- 添加新模块结果的占位符
        "error": None # 用于记录顶层错误
    }

    # --- 检查模块依赖 --- 
    if not all([数据获取模块, 分析订单簿, 获取并处理近期成交, 分析成交流, 执行多周期分析, 整合多周期信号, 分析箱体突破]):
        error_msg = "一个或多个分析函数未能从依赖模块导入，无法执行完整分析。"
        logger.error(error_msg)
        analysis_results["error"] = error_msg
        return analysis_results
    if not all([MICRO_TREND_CONFIG, TRADE_FLOW_CONFIG, ORDER_BOOK_CONFIG]):
        logger.warning("一个或多个模块的配置字典未加载或为空，分析可能使用默认值。")

    try:
        # --- 1. 数据获取 (根据需要获取) --- 
        # 订单簿可能需要最新深度数据
        # 成交流可能需要近期成交记录
        # 微观趋势需要K线数据 (由其内部函数获取)
        # 这里可以先获取一个基础数据，例如最新价格，并记录时间戳
        # (具体获取逻辑需要根据下面分析模块的需求细化)
        logger.info("步骤 1: 获取基础数据 (占位符)...")
        # current_price_info = 数据获取模块.获取当前价格(symbol, market_type) # 假设有此函数
        # results["timestamp"] = current_price_info.get('timestamp') # 记录分析时间点
        # results["latest_price"] = current_price_info.get('price')

        # --- 2. 使用线程池并行执行IO密集型任务 (如API调用) --- 
        # 注意：分析函数本身如果是CPU密集型，线程池效果有限，可考虑进程池
        tasks = {}
        # 为微观趋势分析准备参数
        intervals = MICRO_TREND_CONFIG.get('ANALYSIS_INTERVALS', ['1m', '5m', '15m', '1h'])
        if not intervals:
            intervals = ['1m', '5m', '15m', '1h']
            logger.warning(f"未在配置中找到 ANALYSIS_INTERVALS，使用默认值: {intervals}")
        micro_trend_config_dict = MICRO_TREND_CONFIG 

        logger.info("步骤 2: 并行执行核心分析模块...")
        with ThreadPoolExecutor(max_workers=4) as executor:
            # 提交订单簿分析 (使用关键字参数传递 market_type 和 depth_limit)
            if 分析订单簿:
                # 从配置获取 depth_limit 和 n_levels_analysis
                ob_depth_limit = ORDER_BOOK_CONFIG.get('depth_limit', 100)
                ob_n_levels = ORDER_BOOK_CONFIG.get('n_levels_analysis', 20) # <-- 获取配置值，默认 20
                # [调试] 添加详细日志，显示订单簿分析的参数
                logger.warning(f"[调试] 提交订单簿分析任务，参数: symbol={symbol}, depth_limit={ob_depth_limit}, n_levels_analysis={ob_n_levels}, market_type={market_type}") # <-- 修改日志
                tasks[executor.submit(分析订单簿, symbol, depth_limit=ob_depth_limit, n_levels_analysis=ob_n_levels, market_type=market_type)] = 'order_book_analysis' # <-- 传递参数
            
            # 提交成交流分析 (内部获取数据)
            if 分析成交流:
                 # 从配置获取 limit
                 tf_limit = TRADE_FLOW_CONFIG.get('fetch_limit', 1000)
                 logger.debug(f"Submitting 成交流分析 with limit={tf_limit} and market_type={market_type}")
                 tasks[executor.submit(分析成交流, symbol, market_type=market_type, limit=tf_limit)] = 'trade_flow_analysis'
            
            # 提交多周期微观趋势分析 (传递正确参数)
            if 执行多周期分析:
                 logger.debug(f"Submitting 多周期分析 with intervals={intervals} and market_type={market_type}")
                 tasks[executor.submit(执行多周期分析, symbol, market_type, intervals=intervals, config=micro_trend_config_dict)] = 'micro_trend_mtf'
            
            # 提交箱体突破分析
            if 分析箱体突破:
                 logger.debug(f"Submitting 箱体突破分析 with market_type={market_type}")
                 tasks[executor.submit(分析箱体突破, symbol, market_type=market_type)] = 'box_breakout'
            # 注意：整合多周期信号 已移除并行提交

            # 收集结果
            for future in as_completed(tasks):
                module_name = tasks[future]
                try:
                    result = future.result()
                    analysis_results[module_name] = result
                    
                    # [调试] 特别记录订单簿分析结果的结构
                    if module_name == 'order_book_analysis':
                        logger.warning(f"[调试] 订单簿分析结果类型: {type(result)}")
                        if isinstance(result, dict):
                            # 记录顶级键
                            logger.warning(f"[调试] 订单簿分析结果顶级键: {list(result.keys())}")
                            # 检查是否有解读部分
                            if 'interpretation' in result:
                                logger.warning(f"[调试] 订单簿分析包含解读数据，解读键: {list(result['interpretation'].keys())}")
                            else:
                                logger.warning(f"[调试] 订单簿分析结果中没有找到 'interpretation' 键")
                            # 检查是否有错误
                            if result.get('error'):
                                logger.warning(f"[调试] 订单簿分析返回了错误: {result['error']}")
                        else:
                            logger.warning(f"[调试] 订单簿分析结果不是字典类型")
                    
                    logger.info(f"并行模块 '{module_name}' 分析完成。")
                except Exception as e:
                    logger.error(f"并行模块 '{module_name}' 分析失败: {e}", exc_info=True) # 增加异常信息
                    analysis_results[module_name] = {'error': str(e)}
        
        # [调试] 在所有并行任务完成后检查订单簿分析结果是否正确存储
        if 'order_book_analysis' in analysis_results:
            ob_result = analysis_results['order_book_analysis']
            logger.warning(f"[调试] 最终存储的订单簿分析结果类型: {type(ob_result)}")
            if isinstance(ob_result, dict):
                if 'interpretation' in ob_result:
                    logger.warning(f"[调试] 最终存储的订单簿解读键: {list(ob_result['interpretation'].keys())}")
                    # 尝试从订单簿解读中获取关键信息并打印，以验证数据
                    bias_score = ob_result['interpretation'].get('bias_score')
                    if bias_score is not None:
                        logger.warning(f"[调试] 订单簿偏向分数: {bias_score}")
                else:
                    logger.warning(f"[调试] 最终存储的订单簿分析中没有 'interpretation' 键")
        else:
            logger.warning(f"[调试] 最终结果中没有 'order_book_analysis' 键")

        # --- 3. 顺序执行依赖于之前结果的任务 (整合多周期信号) --- 
        logger.info("步骤 3: 整合多周期信号...")
        mtf_results = analysis_results.get('micro_trend_mtf')
        # 检查微观趋势多周期分析是否成功执行且有结果
        if mtf_results and isinstance(mtf_results, dict) and not mtf_results.get('error') and 整合多周期信号:
            try:
                # 确保传递的是 mtf_results 字典本身，而不是其错误信息
                integrated_signal_result = 整合多周期信号(
                    mtf_results=mtf_results, # 传递多周期分析结果
                    config=micro_trend_config_dict # 传递配置字典
                )
                analysis_results["micro_trend_integrated"] = integrated_signal_result
                logger.info("模块 'micro_trend_integrated' 分析完成。")
            except Exception as e:
                 logger.error(f"模块 'micro_trend_integrated' 分析失败: {e}", exc_info=True)
                 analysis_results["micro_trend_integrated"] = {'error': str(e)}
        elif analysis_results.get('micro_trend_mtf') and analysis_results['micro_trend_mtf'].get('error'):
             logger.warning(f"跳过微观趋势整合，因为步骤 'micro_trend_mtf' 失败: {analysis_results['micro_trend_mtf'].get('error')}")
             analysis_results["micro_trend_integrated"] = {'error': '依赖的多周期分析失败'}
        elif not 整合多周期信号:
             logger.error("无法执行微观趋势整合，因为 '整合多周期信号' 函数未成功导入。")
             analysis_results["micro_trend_integrated"] = {'error': '整合函数未导入'}
        else:
             logger.warning("跳过微观趋势整合，因为缺少 'micro_trend_mtf' 的有效结果。")
             analysis_results["micro_trend_integrated"] = {'error': '缺少多周期分析结果'}
             
        # --- 4. 生成最终摘要 --- 
        logger.info("步骤 4: 生成综合摘要...")
        analysis_results['integrated_summary'] = _generate_summary(analysis_results)

    except Exception as e:
        logger.error(f"执行综合分析时发生顶层错误: {e}", exc_info=True)
        analysis_results["error"] = f"综合分析顶层异常: {e}"
        
    end_time = time.time()
    logger.info(f"综合分析完成 for {symbol} ({market_type}). 总耗时: {end_time - start_time:.2f} 秒")
    return analysis_results

# --- (可选) 简要总结生成函数 ---
def _generate_summary(results: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据订单簿、成交流和微观趋势的分析结果，生成一个综合判断总结。
    (已优化，考虑整合信号类型、内部冲突、OB vs TF 冲突)

    Args:
        results (Dict[str, Any]): 包含所有分析结果的字典。

    Returns:
        Dict[str, Any]: 包含综合判断信号和理由的字典。
    """
    # [调试] 记录传入的结果字典键
    logger.warning(f"[调试-摘要] 传入_generate_summary的结果字典键: {list(results.keys())}")
    
    summary = {
        'verdict': 'Unknown',
        'reason': [],
        'confidence': 0,
        'details': {}
    }

    # --- 1. 从结果字典中提取所需信息 --- 
    ob_analysis = results.get('order_book_analysis')
    tf_analysis = results.get('trade_flow_analysis')
    mt_integrated = results.get('micro_trend_integrated')
    box_breakout = results.get('box_breakout')
    
    # [调试] 检查提取的订单簿分析
    logger.warning(f"[调试-摘要] 订单簿分析类型: {type(ob_analysis)}")
    if ob_analysis is None:
        logger.warning(f"[调试-摘要] 订单簿分析为 None")
    elif isinstance(ob_analysis, dict):
        logger.warning(f"[调试-摘要] 订单簿分析顶层键: {list(ob_analysis.keys())}")
        if 'interpretation' in ob_analysis:
            interp = ob_analysis['interpretation']
            logger.warning(f"[调试-摘要] 订单簿interpretation类型: {type(interp)}")
            if isinstance(interp, dict):
                logger.warning(f"[调试-摘要] 订单簿interpretation键: {list(interp.keys())}")
            else:
                logger.warning(f"[调试-摘要] 订单簿interpretation不是字典")
        else:
            logger.warning(f"[调试-摘要] 订单簿分析中没有找到'interpretation'键")
    else:
        logger.warning(f"[调试-摘要] 订单簿分析不是字典: {ob_analysis}")

    # --- 2. 检查数据完整性 --- 
    modules_available = {
        'order_book': ob_analysis and not ob_analysis.get('error'),
        'trade_flow': tf_analysis and not tf_analysis.get('error'),
        'micro_trend': mt_integrated and not mt_integrated.get('error'),
        'box_breakout': box_breakout and not box_breakout.get('error'), # <--- 检查箱体模块
    }
    if not all(modules_available.values()): # 如果有任何一个模块失败
        summary['verdict'] = 'Incomplete Data'
        failed_modules = [name for name, available in modules_available.items() if not available]
        summary['reason'].append(f"部分模块分析失败或数据不足: {', '.join(failed_modules)}。")
        # 尝试从可用模块提取信息补充理由
        if modules_available['micro_trend']:
            trend_type = mt_integrated.get('type', 'Unknown')
            trend_score = mt_integrated.get('score')
            score_str = f"{trend_score:.2f}" if trend_score is not None else "N/A"
            summary['reason'].append(f"(可用)微观趋势: {trend_type} (Score: {score_str}).")
        if modules_available['box_breakout']:
             box_status = box_breakout.get('status', '未知')
             summary['reason'].append(f"(可用)箱体状态: {box_status}.")
        # ... 可以为 OB 和 TF 添加类似逻辑 ...
        
        summary['confidence'] = 0.0 # 数据不完整，置信度为0
        return summary

    # --- 3. 提取关键指标 --- 
    # [调试] 跟踪从订单簿分析中提取关键指标
    logger.warning(f"[调试-摘要] 准备从订单簿中提取关键指标")
    
    ob_bias = 0  # 默认值
    ob_support_strong = False  # 默认值
    ob_support_weak = False  # 默认值
    ob_pressure_strong = False  # 默认值
    ob_pressure_weak = False  # 默认值
    
    try:
        if modules_available['order_book']:
            ob_interp = ob_analysis.get('interpretation', {})
            logger.warning(f"[调试-摘要] 提取到的订单簿interpretation: {ob_interp}")
            
            ob_bias = ob_interp.get('bias_score', 0)
            ob_support_strong = ob_interp.get('support_strong', False)
            ob_pressure_strong = ob_interp.get('pressure_strong', False)
            
            # 恢复原始的弱支撑和弱压力计算逻辑
            ob_support_weak = ob_analysis.get('oir_5') is not None and ob_analysis.get('oir_5') > 0
            ob_pressure_weak = ob_analysis.get('oir_5') is not None and ob_analysis.get('oir_5') < 0
            
            logger.warning(f"[调试-摘要] 提取的订单簿指标: 偏向分数={ob_bias}, 强支撑={ob_support_strong}, 弱支撑={ob_support_weak}, 强压力={ob_pressure_strong}, 弱压力={ob_pressure_weak}")
    except Exception as e:
        logger.error(f"[调试-摘要] 从订单簿提取指标时出错: {e}", exc_info=True)
        ob_bias = 0
        ob_support_strong = False
        ob_support_weak = False
        ob_pressure_strong = False
        ob_pressure_weak = False
    
    # 提取成交流相关指标，增强决策权重
    tf_bias = tf_analysis.get('interpretation', {}).get('bias_score', 0)
    tf_is_conflicting_refined = tf_analysis.get('interpretation', {}).get('is_conflicting_refined', False)
    
    # 新增：提取成交流更多关键指标
    tf_buy_pressure = tf_analysis.get('buy_pressure', 0)
    tf_sell_pressure = tf_analysis.get('sell_pressure', 0)
    tf_large_trades_bias = tf_analysis.get('large_trades_bias', 0)
    
    # 新增：解析成交流总体解读信息
    tf_has_strong_buy = False
    tf_has_strong_sell = False
    tf_overall = tf_analysis.get('interpretation', {}).get('overall', {})
    tf_summary = tf_overall.get('summary', []) if isinstance(tf_overall, dict) else []
    
    # 分析成交流总结信息，寻找强烈的买卖信号
    for summary_item in tf_summary:
        if isinstance(summary_item, str):
            if '主动买入' in summary_item or '大单买入' in summary_item:
                tf_has_strong_buy = True
                logger.info(f"[决策权重] 成交流检测到强买入信号: {summary_item}")
            elif '主动卖出' in summary_item or '大单卖出' in summary_item:
                tf_has_strong_sell = True
                logger.info(f"[决策权重] 成交流检测到强卖出信号: {summary_item}")
                
    # 根据成交流的强信号调整总偏向分数
    tf_weight_multiplier = 1.0  # 默认权重
    
    # 如果有大单信息，增加成交流权重
    if tf_large_trades_bias != 0:
        tf_weight_multiplier = 1.5
        logger.info(f"[决策权重] 检测到大单偏向 ({tf_large_trades_bias})，增加成交流权重")
        
    # 根据主动买卖压力进一步调整
    if tf_has_strong_buy or tf_has_strong_sell:
        tf_weight_multiplier = 2.0
        logger.info(f"[决策权重] 检测到主动买卖压力，显著增加成交流权重")
        
    # 调整后的总偏向计算
    adjusted_tf_bias = tf_bias * tf_weight_multiplier
    total_bias = ob_bias + adjusted_tf_bias
    
    logger.info(f"[决策权重] 原始成交流偏向: {tf_bias}, 权重: {tf_weight_multiplier}x, 调整后: {adjusted_tf_bias}")
    logger.info(f"[决策权重] 订单簿偏向: {ob_bias}, 总偏向分数: {total_bias}")
    
    # 恢复微观趋势类型提取
    trend_type = mt_integrated.get('type', 'Unknown') 
    trend_score = mt_integrated.get('score')
    
    # <--- 提取箱体状态 --->
    box_status = box_breakout.get('status', '未知')
    box_reason = box_breakout.get('reason', '') # 获取箱体的具体理由
    box_main_high = box_breakout.get('main_high')
    box_main_low = box_breakout.get('main_low')

    # --- 4. 计算总偏向分数 (可选，未来可加入箱体影响) --- 
    # total_bias = ob_bias + tf_bias + box_bias_contribution 

    # --- 5. 定义状态映射和阈值 --- 
    trend_type_map = {
        'Conflicting': '信号冲突',
        'StrongConfirmation': '强力确认',
        'WeakConfirmation': '弱确认',
        'Neutral': '中性',
        'TrendConfirmation': '趋势确认', # 兼容旧的或可能的类型
        'Inconsistent': '信号不一致', # 兼容旧的或可能的类型
        'Error': '错误',
        'Unknown': '未知'
    }
    trend_type_cn = trend_type_map.get(trend_type, trend_type)

    # --- 6. 生成基础状态描述 (添加到 reasons 列表) --- 
    reasons = []
    score_str = f"{trend_score:.2f}" if trend_score is not None else "N/A"
    reasons.append(f"微观趋势: {trend_type_cn} (Score: {score_str}).")

    # 修正 ob_desc 生成逻辑
    if ob_bias >= 1.5: # 强支撑 (例如 >= 1.5)
        ob_desc = "订单簿强力支撑"
    elif ob_bias >= 0.5: # 弱支撑 (例如 0.5 到 1.5 之间)
        ob_desc = "订单簿偏向支撑"
    elif ob_bias <= -1.5: # 强压力 (例如 <= -1.5)
        ob_desc = "订单簿强力施压"
    elif ob_bias <= -0.5: # 弱压力 (例如 -0.5 到 -1.5 之间)
        ob_desc = "订单簿偏向施压"
    else: # 中性 (例如 -0.5 到 0.5 之间)
        ob_desc = "订单簿信号中性"
    reasons.append(f"{ob_desc} (偏向分数:{ob_bias}).")

    tf_desc = "成交流状态未知"
    if tf_bias >= 1.5: tf_desc = "成交流强力看涨"
    elif tf_bias >= 0.5: tf_desc = "成交流偏向看涨"
    elif tf_bias <= -1.5: tf_desc = "成交流强力看跌"
    elif tf_bias <= -0.5: tf_desc = "成交流偏向看跌"
    else:
         tf_desc = "成交流信号冲突" if tf_is_conflicting_refined else "成交流信号中性"
    reasons.append(f"{tf_desc} (偏向分数:{tf_bias}).")
    if tf_is_conflicting_refined and "冲突" not in tf_desc:
         reasons.append("(注意：成交流内部存在信号冲突)")

    # --- 7. 核心判断逻辑 --- 
    # 初始化 verdict
    verdict = "Neutral" 
    # 读取配置阈值
    trend_score_strong_threshold = INTEGRATED_ANALYSIS_CONFIG.get('trend_score_strong_threshold', 2.5)
    bias_threshold = INTEGRATED_ANALYSIS_CONFIG.get('bias_threshold', 2) 
    strong_bias_threshold = INTEGRATED_ANALYSIS_CONFIG.get('strong_bias_threshold', 3)
    ob_tf_conflict_strength_threshold = INTEGRATED_ANALYSIS_CONFIG.get('ob_tf_conflict_strength_threshold', 3)
    
    # 计算核心冲突标志
    is_ob_tf_strong_conflict = (ob_bias * tf_bias < 0) and (abs(ob_bias) + abs(tf_bias) >= ob_tf_conflict_strength_threshold)

    # --- 7a. 计算基于 Trend/OB/TF 的初步 Verdict --- 
    if is_ob_tf_strong_conflict:
        # 尝试从配置读取，若无则使用默认值 1.5 并打印警告
        ob_tf_conflict_trend_score_threshold = INTEGRATED_ANALYSIS_CONFIG.get('ob_tf_conflict_trend_score_threshold', 1.5) 
        if ob_tf_conflict_trend_score_threshold == 1.5:
             logger.warning("[Config] Did not find 'ob_tf_conflict_trend_score_threshold' in INTEGRATED_ANALYSIS_CONFIG, using default 1.5")
             
        trend_score_str = f"(MTF评分:{trend_score:.2f})" if trend_score is not None else ""
        if trend_score is not None and trend_score <= -ob_tf_conflict_trend_score_threshold:
            verdict = 'OB/TF Conflict (High Tension - Bearish Trend Context)'
            reasons.append(f"!! 订单簿支撑与成交流卖压强烈冲突 {trend_score_str}，发生在看跌趋势背景下，警惕支撑被有效跌破风险 !!")
        elif trend_score is not None and trend_score >= ob_tf_conflict_trend_score_threshold:
             verdict = 'OB/TF Conflict (High Tension - Bullish Trend Context)'
             reasons.append(f"!! 订单簿压力与成交流买盘强烈冲突 {trend_score_str}，发生在看涨趋势背景下，关注压力能否被有效突破 !!")
        else:
             verdict = 'OB/TF Conflict (High Tension - Neutral Trend Context)'
             reasons.append(f"!! 订单簿与成交流信号强烈冲突 {trend_score_str}，趋势背景中性或不明，关注区间突破方向 !!")
    elif trend_type_cn == '信号冲突':
        # ... (趋势冲突逻辑 - 确保为 verdict 赋值)
        if total_bias >= strong_bias_threshold and trend_score is not None and trend_score >= trend_score_strong_threshold and not tf_is_conflicting_refined:
            verdict = '强力看涨'
            reasons.append(f"尽管趋势信号冲突，但OB/TF和趋势评分均强力看涨 (总偏向分数:{total_bias})。")
        elif total_bias <= -strong_bias_threshold and trend_score is not None and trend_score <= -trend_score_strong_threshold and not tf_is_conflicting_refined:
             verdict = '强力看跌'
             reasons.append(f"尽管趋势信号冲突，但OB/TF和趋势评分均强力看跌 (总偏向分数:{total_bias})。")
        elif total_bias >= strong_bias_threshold:
             verdict = 'Conflicting Trend (Strong Bullish Bias)'
             reasons.append(f"订单簿与成交流均发出强看涨信号 (总偏向分数:{total_bias})，主导当前偏向。")
        elif total_bias <= -strong_bias_threshold:
             verdict = 'Conflicting Trend (Strong Bearish Bias)'
             reasons.append(f"订单簿与成交流均发出强看跌信号 (总偏向分数:{total_bias})，主导当前偏向。")
        elif total_bias >= bias_threshold:
             verdict = 'Conflicting Trend (Bullish Bias)'
             reasons.append(f"综合偏向看涨 (总偏向分数:{total_bias})，但趋势冲突仍需注意。")
        elif total_bias <= -bias_threshold:
             verdict = 'Conflicting Trend (Bearish Bias)'
             reasons.append(f"综合偏向看跌 (总偏向分数:{total_bias})，但趋势冲突仍需注意。")
        else:
             verdict = 'Conflicting Trend (Highly Uncertain)'
             reasons.append(f"综合偏向不足 (总偏向分数:{total_bias})，方向高度不确定。")
    elif trend_type_cn == '强力确认':
         # ... (强力确认逻辑 - 确保为 verdict 赋值)
         if total_bias >= bias_threshold and not tf_is_conflicting_refined:
              verdict = '强力看涨'
              reasons.append(f"获得订单簿/成交流确认 (总偏向分数:{total_bias})。")
         elif total_bias <= -bias_threshold: # 修正: 检查反向偏向
              verdict = '冲突 (强趋势 vs 反向OB/TF)' # 新的 Verdict 类型
              reasons.append(f"!! 强确认趋势与显著反向OB/TF偏向 ({total_bias}) 冲突 !!")
         else:
              verdict = '强力看涨' # 默认强确认即强力，即使OB/TF不强 (除非反向)
              reasons.append("强确认趋势，但OB/TF信号中性或偏弱。")
    elif trend_type_cn == '弱确认':
         # ... (弱确认逻辑 - 确保为 verdict 赋值)
         if total_bias >= strong_bias_threshold and not tf_is_conflicting_refined:
              verdict = '看涨' # 弱确认+强偏向=普通看涨
              reasons.append(f"获得强劲的订单簿/成交流确认 (总偏向分数:{total_bias})。")
         elif total_bias >= bias_threshold and not tf_is_conflicting_refined:
              verdict = '看涨'
              reasons.append(f"获得订单簿/成交流确认 (总偏向分数:{total_bias})。")
         elif total_bias <= -bias_threshold: # 修正: 检查反向偏向
              verdict = '冲突 (弱趋势 vs 反向OB/TF)' # 新的 Verdict 类型
              reasons.append(f"!! 弱确认趋势与显著反向OB/TF偏向 ({total_bias}) 冲突 !!")
         else:
              verdict = '谨慎看涨'
              reasons.append(f"但订单簿/成交流信号确认不足 (总偏向分数:{total_bias})。")
    elif trend_type_cn == '中性':
        # ... (中性逻辑 - 确保为 verdict 赋值)
        if total_bias >= bias_threshold:
             verdict = '谨慎看涨 (趋势中性)'
             reasons.append(f"基于订单簿/成交流偏向看涨 (总偏向分数:{total_bias})。")
        elif total_bias <= -bias_threshold:
             verdict = '谨慎看跌 (趋势中性)'
             reasons.append(f"基于订单簿/成交流偏向看跌 (总偏向分数:{total_bias})。")
        elif tf_is_conflicting_refined and tf_desc == "成交流信号冲突": 
             verdict = '中性 (资金流混乱)'
             reasons.append("成交流内部信号冲突导致方向不明。") # 补充理由
        else:
             verdict = '中性' # 默认中性
             reasons.append(f"综合信号不足或中性 (总偏向分数:{total_bias})。")
    else: # 其他情况或未知 TrendType
        logger.warning(f"未知的微观趋势类型 '{trend_type_cn}' (原始: {trend_type}) 或未覆盖的判断条件，默认维持 '{verdict}'")
        if abs(total_bias) >= bias_threshold:
             verdict = '看涨倾向' if total_bias > 0 else '看跌倾向'
             reasons.append(f"基于OB/TF偏向 ({total_bias})，但趋势类型不明或复杂 ({trend_type_cn})。")
        # else: verdict 保持 'Neutral'
        
    # --- 7b. 保存初步 Verdict 并根据箱体状态进行调整 --- 
    initial_verdict = verdict # 保存基于 Trend/OB/TF 的初步结论
    logger.debug(f"Initial verdict based on Trend/OB/TF: {initial_verdict}")

    # (粘贴原 7b 逻辑块) 
    if box_status != '未知' and box_status != '数据不足无法判断' and box_status != '分析函数内部错误' and box_status != '主周期箱体无效':
        is_breakout_up_confirmed_vol = '向上突破确认 (放量)' in box_status
        is_breakout_down_confirmed_vol = '向下突破确认 (放量)' in box_status
        is_breakout_up_attempt_no_vol = ('向上突破尝试中' in box_status or '向上突破确认 (缩量)' in box_status)
        is_breakout_down_attempt_no_vol = ('向下突破尝试中' in box_status or '向下突破确认 (缩量)' in box_status)
        is_in_box = '箱体内盘整' in box_status
        
        logger.debug(f"Box Status Checks: UpConfirmVol={is_breakout_up_confirmed_vol}, DownConfirmVol={is_breakout_down_confirmed_vol}, UpAttemptNoVol={is_breakout_up_attempt_no_vol}, DownAttemptNoVol={is_breakout_down_attempt_no_vol}, InBox={is_in_box}")

        # 规则 1: 强力确认
        if (initial_verdict in ['强力看涨', '看涨', '谨慎看涨', '看涨倾向']) and is_breakout_up_confirmed_vol:
            verdict = '强力看涨' 
            reasons.append("[箱体确认]：放量向上突破确认，强化看涨信号。")
            logger.debug(f"Verdict upgraded/confirmed to Strong Bullish due to volume breakout up.")
        elif (initial_verdict in ['强力看跌', '看跌', '谨慎看跌', '看跌倾向']) and is_breakout_down_confirmed_vol:
            verdict = '强力看跌' 
            reasons.append("[箱体确认]：放量向下突破确认，强化看跌信号。")
            logger.debug(f"Verdict upgraded/confirmed to Strong Bearish due to volume breakout down.")
            
        # 规则 2: 动能不足 
        elif initial_verdict in ['看涨', '谨慎看涨', '看涨倾向'] and is_breakout_up_attempt_no_vol:
            verdict = '谨慎看涨' 
            reasons.append("[箱体注意]：向上突破尝试中但缩量/未确认，动能不足需谨慎。")
            logger.debug(f"Verdict changed/kept Cautious Bullish due to low volume breakout attempt up.")
        elif initial_verdict in ['看跌', '谨慎看跌', '看跌倾向'] and is_breakout_down_attempt_no_vol:
            verdict = '谨慎看跌' 
            reasons.append("[箱体注意]：向下突破尝试中但缩量/未确认，动能不足需谨慎。")
            logger.debug(f"Verdict changed/kept Cautious Bearish due to low volume breakout attempt down.")
            
        # 规则 4: 箱体盘整影响
        elif is_in_box and initial_verdict in ['强力看涨', '强力看跌', '看涨', '看跌']:
             reasons.append(f"[箱体背景]：当前仍在 {BOX_BREAKOUT_CONFIG['main_box_timeframe']} 箱体内盘整，等待有效突破。")
             logger.debug(f"Strong/Normal signal ({initial_verdict}) occurred while still inside the box.")
        elif is_in_box and initial_verdict in ['谨慎看涨', '谨慎看跌', '看涨倾向', '看跌倾向']:
             verdict = '中性 (箱体内盘整)' 
             reasons.append(f"[箱体背景]：信号偏弱且当前在 {BOX_BREAKOUT_CONFIG['main_box_timeframe']} 箱体内盘整，倾向中性。")
             logger.debug(f"Weak signal ({initial_verdict}) occurred inside the box, verdict set to Neutral.")
        # ... (如果 initial_verdict 是 Neutral 且 is_in_box，verdict 保持 Neutral)
             
    logger.info(f"Final Verdict after considering Box Status: {verdict}")

    # --- 8. 计算置信度 --- 
    confidence = 0.5 
    logger.debug(f"[Confidence Calc] Initial confidence: {confidence}")

    # --- 8b. 原有的置信度调整逻辑 --- 
    # a) OB vs TF 强冲突
    if is_ob_tf_strong_conflict:
        confidence -= 0.3 
        logger.debug(f"[Confidence Calc][OB/TF] OB vs TF strong conflict adjustment: -0.3 -> {confidence:.2f}")
    # b) 趋势类型影响 (使用修正后的 trend_type_cn)
    elif trend_type_cn == '信号冲突': # <-- 使用中文判断
        confidence -= 0.1
        logger.debug(f"[Confidence Calc][Trend] Trend type '信号冲突' adjustment: -0.1 -> {confidence:.2f}")
    elif trend_type_cn == '强力确认': # <-- 使用中文判断 (假设映射正确)
        confidence += 0.15 
        logger.debug(f"[Confidence Calc][Trend] Trend type '强力确认' adjustment: +0.15 -> {confidence:.2f}")
    elif trend_type_cn == '弱确认': # <-- 使用中文判断 (假设映射正确)
        confidence += 0.05 
        logger.debug(f"[Confidence Calc][Trend] Trend type '弱确认' adjustment: +0.05 -> {confidence:.2f}")
    # 注意：这里可能需要为 '中性', '错误', '未知' 等其他类型添加调整

    # c) 内部信号冲突
    # ... (内部冲突调整逻辑不变) ...

    # d) 最终结论强度加成/惩罚 (!! 完善列表 !!) 
    if verdict in ['Strong Bullish', '强力看涨']: 
        if trend_type == 'StrongConfirmation':
             confidence += 0.05 
             logger.debug(f"[Confidence Calc][Verdict] Strong verdict (with StrongConfirmation) adjustment: +0.05 -> {confidence:.2f}")
        else:
             confidence += 0.1 
             logger.debug(f"[Confidence Calc][Verdict] Strong verdict (without StrongConfirmation) adjustment: +0.1 -> {confidence:.2f}")
    elif verdict in ['Strong Bearish', '强力看跌']:
        # (类似逻辑，简化：统一加成，不再区分 trend_type)
        confidence += 0.1 
        logger.debug(f"[Confidence Calc][Verdict] Strong Bearish verdict adjustment: +0.1 -> {confidence:.2f}")
        
    elif verdict in ['Conflicting Trend (Strong Bullish Bias)', 'Conflicting Trend (Strong Bearish Bias)',
                   'Conflicting Trend (Bullish Bias)', 'Conflicting Trend (Bearish Bias)',
                   'Conflicting Trend (Highly Uncertain)', # <--- 添加 Highly Uncertain
                   '趋势冲突 (强力偏向看涨)', '趋势冲突 (强力偏向看跌)', 
                   '趋势冲突 (偏向看涨)', '趋势冲突 (偏向看跌)', 
                   '趋势冲突 (高度不确定)']: # <--- 添加中文 Highly Uncertain
         confidence -= 0.1 
         logger.debug(f"[Confidence Calc][Verdict] Conflicting Trend verdict adjustment: -0.1 -> {confidence:.2f}")
         
    elif verdict in ['Potential Reversal (Top?)', 'Potential Reversal (Bottom?)', # <--- 占位符，实际逻辑可能没有生成这些
                   '谨慎看涨', '谨慎看跌', 
                   '谨慎看涨 (趋势中性)', '谨慎看跌 (趋势中性)', 
                   '看涨倾向', '看跌倾向']: # <--- 添加倾向
        confidence -= 0.15
        logger.debug(f"[Confidence Calc][Verdict] Potential Reversal/Cautious/Tendency verdict adjustment: -0.15 -> {confidence:.2f}")
        
    elif verdict in ['OB/TF Conflict (High Tension - Bearish Trend Context)', 
                   'OB/TF Conflict (High Tension - Bullish Trend Context)', 
                   'OB/TF Conflict (High Tension - Neutral Trend Context)', 
                   '冲突 (强趋势 vs 反向OB/TF)', '冲突 (弱趋势 vs 反向OB/TF)', # <--- 添加新的冲突类型
                   '冲突 (看涨趋势 vs OB/TF)', '冲突 (看跌趋势 vs OB/TF)']: # <--- 已包含旧的
         confidence -= 0.2 
         logger.debug(f"[Confidence Calc][Verdict] Explicit conflict verdict adjustment: -0.2 -> {confidence:.2f}")
         
    elif verdict == '中性 (箱体内盘整)':
         confidence -= 0.1 
         logger.debug(f"[Confidence Calc][Verdict] Neutral (In Box) verdict adjustment: -0.1 -> {confidence:.2f}")
         
    elif verdict == '中性 (资金流混乱)': # 单独处理
        confidence -= 0.15 # 比普通中性更不可信
        logger.debug(f"[Confidence Calc][Verdict] Neutral (TF Conflict) verdict adjustment: -0.15 -> {confidence:.2f}")
        
    # 对于普通的 'Neutral'/'中性'，暂时不增减，保持基础分或前面的调整
    
    confidence = max(0, min(1, confidence)) # Clamp
    logger.debug(f"[Confidence Calc] Final confidence (clamped): {confidence:.2f}")
    summary['confidence'] = confidence

    # --- 9. 生成最终摘要 --- 
    # 恢复原始的中文映射逻辑
    summary['verdict_en'] = verdict  # 保留英文/内部 verdict
    
    # 更新中文映射，加入可能的新 Verdict
    verdict_cn_map = {
        # --- 基础判断 ---
        'Normal Bullish': '📈 看涨',
        'Normal Bearish': '📉 看跌',
        'Strong Bullish': '🚀 强力看涨',
        'Strong Bearish': '💥 强力看跌',
        'Consolidation': '⚖️ 盘整',
        'Unknown': '❓ 未知判断',

        # --- 潜在反转 ---
        'Potential Reversal (Bullish)': '⚠️ 潜在反转 (看涨? 底?)',
        'Potential Reversal (Bearish)': '⚠️ 潜在反转 (看跌? 顶?)',

        # --- 趋势冲突 (基础) ---
        'Conflicting Trend': '❓ 趋势冲突',
        'Conflicting Trend (Highly Uncertain)': '❓❓ 趋势冲突 (高度不确定)',

        # --- 趋势冲突 (带偏向) ---
        'Conflicting Trend (Strong Bullish Bias)': '❓📈 趋势冲突 (强偏看涨)', # <-- 新增
        'Conflicting Trend (Strong Bearish Bias)': '❓📉 趋势冲突 (强偏看跌)', # <-- 新增
        'Conflicting Trend (Bullish Bias)': '❓📈 趋势冲突 (偏向看涨)', # <-- 新增 (日志报过这个)
        'Conflicting Trend (Bearish Bias)': '❓📉 趋势冲突 (偏向看跌)', # <-- 新增

        # --- 内部冲突 ---
        'Conflict (Strong Trend vs Counter OB/TF)': '⚔️ 冲突 (强趋势 vs 反向OB/TF)',
        'Conflict (Strong OB vs Counter TF)': '⚔️ 冲突 (强OB vs 反向TF)',
        'Conflict (Strong TF vs Counter OB)': '⚔️ 冲突 (强TF vs 反向OB)',
        # 可能还有其他内部冲突类型，可以后续补充

        # --- 确保旧的强力映射也存在 --- 
        '强力看涨': '🚀 强力看涨',
        '强力看跌': '💥 强力看跌',

        # --- 可能的其他情况 (如有需要可添加) ---
        # 'Box Consolidation': '📦 箱体内盘整',
        # 'Breakout Watch': '👀 箱体突破观察',
        # ...

    }

    # 8c. 获取最终中文判断和置信度文本
    verdict_cn = verdict_cn_map.get(verdict, verdict_cn_map['Unknown']) # 使用 .get() 安全获取
    # 检查是否因为映射缺失而回退到了 Unknown
    if verdict_cn == verdict_cn_map['Unknown'] and verdict != 'Unknown':
        logger.warning(f"Verdict '{verdict}' not found in verdict_cn_map. Using default '{verdict_cn_map['Unknown']}'.")

    confidence_text = f"{confidence:.2f}" if confidence is not None else "N/A"
    
    # --- 10. 增加可操作性建议和决断 ---
    # 根据verdict确定基础操作建议
    trading_action = "观望"  # 默认建议观望
    stop_loss_suggestion = ""
    # --- 新增：初始化支撑和阻力位 --- 
    support_level = None
    resistance_level = None
    # -----------------------------
    
    if '强力看涨' in verdict_cn:
        trading_action = "可考虑做多"
        # 如果能获取到当前价格和支撑位，计算止损位
        if modules_available['order_book'] and support_level is not None:
            stop_loss_suggestion = f"止损参考: 低于支撑位 {support_level} 附近"
    elif '强力看跌' in verdict_cn:
        trading_action = "可考虑做空"
        # 如果能获取到当前价格和压力位，计算止损位
        if modules_available['order_book'] and resistance_level is not None:
            stop_loss_suggestion = f"止损参考: 高于压力位 {resistance_level} 附近"
    elif '看涨' in verdict_cn:
        trading_action = "偏向做多"
    elif '看跌' in verdict_cn:
        trading_action = "偏向做空"
    elif '冲突' in verdict_cn or '不明确' in verdict_cn:
        # 在信号冲突时，使用加权平均方法分析短周期趋势
        logger.info(f"[倾向分析] 检测到趋势冲突，开始分析短周期趋势...")
        
        # 尝试从多周期分析中找出短周期的整体偏向
        mt_mtf = results.get('micro_trend_mtf', {})
        if isinstance(mt_mtf, dict) and len(mt_mtf) > 0:
            # 定义短周期及其权重 (1分钟权重最高，依次递减)
            short_periods_weights = {'1m': 0.5, '5m': 0.3, '15m': 0.2}
            available_periods = {}
            total_weight = 0
            weighted_score_sum = 0
            
            # 收集所有可用周期的分数
            for period, weight in short_periods_weights.items():
                if period in mt_mtf and isinstance(mt_mtf[period], dict):
                    score = mt_mtf[period].get('score')
                    signal = mt_mtf[period].get('combined_signal', '未知')
                    
                    if score is not None:
                        available_periods[period] = {
                            'score': score,
                            'signal': signal,
                            'weight': weight
                        }
                        weighted_score_sum += score * weight
                        total_weight += weight
                        
                        logger.info(f"[倾向分析] 周期={period}, 分数={score:.2f}, 信号={signal}")
            
            # 计算加权平均分数
            if total_weight > 0:
                avg_score = weighted_score_sum / total_weight
                logger.info(f"[倾向分析] 短周期加权平均分数: {avg_score:.2f}")
                
                # 检查短周期之间是否有严重冲突
                has_severe_conflict = False
                if len(available_periods) >= 2:  # 至少需要两个周期才能检查冲突
                    periods_list = list(available_periods.keys())
                    for i in range(len(periods_list)):
                        for j in range(i+1, len(periods_list)):
                            p1, p2 = periods_list[i], periods_list[j]
                            s1, s2 = available_periods[p1]['score'], available_periods[p2]['score']
                            
                            # 如果两个周期的分数差异超过1.0，或一个为正一个为负，则视为严重冲突
                            if (s1 * s2 < 0 and abs(s1) > 0.3 and abs(s2) > 0.3) or abs(s1 - s2) > 1.0:
                                has_severe_conflict = True
                                logger.info(f"[倾向分析] 检测到周期严重冲突: {p1}={s1:.2f} vs {p2}={s2:.2f}")
                
                # 根据加权平均分数和冲突状态确定短期偏向
                if has_severe_conflict:
                    trading_action = "多周期信号严重冲突，建议观望等待趋势明朗"
                elif avg_score > 0.3:
                    strength = "较强" if avg_score > 0.7 else "轻微"
                    trading_action = f"信号冲突，但短期偏{strength}看涨 (分数:{avg_score:.2f})"
                    # 只有在分数足够高且没有严重冲突时才建议交易
                    if avg_score > 0.5:
                        trading_action += "，可小仓位试探做多"
                elif avg_score < -0.3:
                    strength = "较强" if avg_score < -0.7 else "轻微"
                    trading_action = f"信号冲突，但短期偏{strength}看跌 (分数:{avg_score:.2f})"
                    # 只有在分数足够低且没有严重冲突时才建议交易
                    if avg_score < -0.5:
                        trading_action += "，可小仓位试探做空"
                else:
                    trading_action = f"信号冲突，短期偏中性 (分数:{avg_score:.2f})，建议观望"
            else:
                # 没有有效的短周期数据
                trading_action = "信号冲突，无有效短周期数据，建议观望"
        else:
            # 没有多周期分析数据
            # 使用总偏向分数作为最后判断依据
            if total_bias > 1:
                trading_action = "信号冲突，但偏向做多"
            elif total_bias < -1:
                trading_action = "信号冲突，但偏向做空"
            else:
                trading_action = "信号高度冲突，建议观望"
    
    # 添加支撑/阻力位信息
    support_resistance_info = ""
    support_level = None
    resistance_level = None
    
    if modules_available['order_book']:
        # 尝试从订单簿获取支撑/阻力位
        support_level = ob_analysis.get('support_level')
        resistance_level = ob_analysis.get('resistance_level')
        
        # 如果订单簿未提供支撑/阻力位，尝试从其他数据推断
        if support_level is None or resistance_level is None:
            logger.info("[支撑阻力] 订单簿未提供完整支撑/阻力位，尝试从其他数据推断")
            
            # 从微观趋势模块获取最近的低点和高点作为替代
            try:
                # 假设微观趋势模块中包含近期K线数据
                mt_data = results.get('micro_trend_mtf', {})
                
                # 尝试从1小时周期数据中提取
                if '1h' in mt_data and isinstance(mt_data['1h'], dict) and 'klines_data' in mt_data['1h']:
                    klines = mt_data['1h']['klines_data']
                    if isinstance(klines, pd.DataFrame) and len(klines) > 0:
                        # 获取最近10根K线的最低和最高价
                        recent_klines = klines.tail(10)
                        lowest = recent_klines['low'].min()
                        highest = recent_klines['high'].max()
                        
                        # 如果订单簿没有提供支撑位，则使用近期低点
                        if support_level is None:
                            support_level = round(lowest, 2)
                            logger.info(f"[支撑阻力] 从K线数据推断支撑位: {support_level}")
                            
                        # 如果订单簿没有提供阻力位，则使用近期高点
                        if resistance_level is None:
                            resistance_level = round(highest, 2)
                            logger.info(f"[支撑阻力] 从K线数据推断阻力位: {resistance_level}")
            except Exception as e:
                logger.error(f"[支撑阻力] 尝试推断支撑/阻力位时出错: {e}")
        
        # 构建支撑/阻力位信息
        if support_level is not None:
            support_resistance_info += f"支撑位: {support_level} "
        if resistance_level is not None:
            support_resistance_info += f"压力位: {resistance_level}"
        
        # 如果仍然无法获取支撑/阻力位，添加说明
        if not support_resistance_info:
            support_resistance_info = "无法获取有效支撑/阻力位信息"
    
    # 添加到理由中
    if support_resistance_info:
        reasons.append(support_resistance_info)
    
    # 止损建议逻辑保持不变，但需要确保即使没有支撑/阻力位也能给出一般性建议
    stop_loss_suggestion = ""
    if '强力看涨' in verdict_cn or '看涨倾向' in verdict_cn:
        if support_level is not None:
            stop_loss_suggestion = f"止损参考: 低于支撑位 {support_level} 附近"
        else:
            stop_loss_suggestion = "止损建议: 设置在近期低点下方"
    elif '强力看跌' in verdict_cn or '看跌倾向' in verdict_cn:
        if resistance_level is not None:
            stop_loss_suggestion = f"止损参考: 高于压力位 {resistance_level} 附近"
        else:
            stop_loss_suggestion = "止损建议: 设置在近期高点上方"
    
    # 添加止损建议到理由
    if stop_loss_suggestion:
        reasons.append(stop_loss_suggestion)
    
    # 添加操作建议到summary
    summary['action_suggestion'] = trading_action
    
    # --- 11. 美化输出格式 (移除多余的 Emoji 判断) ---
    # verdict_cn 已经包含了正确的 Emoji, 无需再单独判断和添加

    # 添加支撑/阻力位信息到details
    summary['details'] = summary.get('details', {})
    if support_level is not None:
        summary['details']['support_level'] = support_level
    if resistance_level is not None:
        summary['details']['resistance_level'] = resistance_level
    
    # 处理理由
    summary['reason'] = list(dict.fromkeys(reasons))  # 去重
    # 更新中性理由判断逻辑
    if len(summary['reason']) >= 4 and verdict_cn == '中性 (箱体内盘整)' and all("中性" in r or "偏向分数:0" in r.replace(" ", "") or "箱体内盘整" in r for r in summary['reason'][:4]):
        summary['reason'] = [f"所有模块信号均为中性或在 {BOX_BREAKOUT_CONFIG['main_box_timeframe']} 箱体内盘整。"] 
    elif len(summary['reason']) >= 3 and verdict_cn == '中性' and all("中性" in r or "偏向分数:0" in r.replace(" ", "") for r in summary['reason'][:3]):
        summary['reason'] = ["所有模块信号均为中性或相互抵消。"]
    elif not summary['reason']:
        summary['reason'].append("未生成明确理由。")
    
    # 直接使用 verdict_cn (已包含Emoji)
    summary['verdict'] = verdict_cn 
    
    # --- 12. 返回总结 ---
    return summary

# --- 主逻辑和测试 --- 
if __name__ == '__main__':
    # 设置参数解析器
    parser = argparse.ArgumentParser(description='执行综合市场分析。')
    parser.add_argument('--symbol', type=str, default='BTCUSDT', help='要分析的交易对 (例如: BTCUSDT)')
    parser.add_argument('--market', type=str, default='futures', choices=['spot', 'futures'], help='市场类型 (spot 或 futures)')
    args = parser.parse_args()
    
    logger.info(f"--- 测试综合分析模块 ({args.symbol}, {args.market}) ---")
    
    analysis_results = 执行综合分析(symbol=args.symbol, market_type=args.market)
    
    # --- 打印结果 --- 
    print("\n--- 综合分析结果 ---")
    print(f"交易对: {analysis_results.get('symbol', 'N/A')} ({analysis_results.get('market_type', 'N/A')})")
    # 使用更友好的时间格式
    timestamp_obj = analysis_results.get('timestamp')
    timestamp_str = timestamp_obj.strftime('%Y-%m-%d %H:%M:%S %Z') if timestamp_obj else 'N/A'
    print(f"分析时间戳: {timestamp_str}")
    print("")

    # 订单簿分析
    ob_analysis = analysis_results.get('order_book_analysis')
    if ob_analysis and isinstance(ob_analysis, dict) and not ob_analysis.get('error'):
        print("-- 订单簿分析 (解读) --")
        ob_interp = ob_analysis.get('interpretation', {})
        ob_bias = ob_interp.get('bias_score', 'N/A')
        ob_support_strong = ob_interp.get('support_strong', False)
        ob_pressure_strong = ob_interp.get('pressure_strong', False)
        print(f"  偏向分数 (基于{ob_analysis.get('analysis_levels','N/A')}档解读): {ob_bias}")
        # 打印OIR (如果存在)
        oir_levels_to_print = [5, 20, 50, 100, 500] # 主要分析层级已在分析时使用
        for L in oir_levels_to_print:
            oir_key = f'oir_{L}'
            oir_val = ob_analysis.get(oir_key)
            if oir_val is not None:
                print(f"  OIR({L}档): {oir_val:.4f}")
            else:
                print(f"  OIR({L}档): N/A")
        # 获取 'oir_max' (如果存在且不为 None)
        oir_max_val = ob_analysis.get('oir_max')
        if oir_max_val is not None:
            print(f"  OIR(最大{ob_analysis.get('depth_limit_actual','N/A')}档): {oir_max_val:.4f}")
        else:
            print(f"  OIR(最大{ob_analysis.get('depth_limit_actual','N/A')}档): N/A")
            
        # --- 修改: 打印基于档位的 VWAP --- 
        vwap_levels_to_print = [5, 20, 50, 100]
        for L in vwap_levels_to_print:
            vwap_bid_key = f'vwap_bid_{L}L'
            vwap_ask_key = f'vwap_ask_{L}L'
            bid_val = ob_analysis.get(vwap_bid_key, 'N/A')
            ask_val = ob_analysis.get(vwap_ask_key, 'N/A')
            # 格式化输出
            bid_str = f"{bid_val:.4f}" if isinstance(bid_val, (int, float)) else bid_val
            ask_str = f"{ask_val:.4f}" if isinstance(ask_val, (int, float)) else ask_val
            print(f"  VWAP(买/卖 前 {L} 档): {bid_str} / {ask_str}")
        # --- VWAP 打印修改结束 ---
            
        print(f"  强支撑 (基于{ob_analysis.get('analysis_levels','N/A')}档解读): {ob_support_strong}")
        print(f"  强压力 (基于{ob_analysis.get('analysis_levels','N/A')}档解读): {ob_pressure_strong}")
        print("")
    elif ob_analysis and ob_analysis.get('error'):
        print("-- 订单簿分析 --")
        print(f"  错误: {ob_analysis['error']}")
        print("")
    else:
        print("-- 订单簿分析: N/A --")
        print("")

    # 成交流分析
    tf_analysis = analysis_results.get('trade_flow_analysis')
    if tf_analysis and isinstance(tf_analysis, dict) and not tf_analysis.get('error'):
        print("-- 成交流分析 (解读) --")
        tf_interp = tf_analysis.get('interpretation', {})
        tf_bias = tf_interp.get('bias_score', 'N/A')
        tf_overall = tf_interp.get('overall', {})
        tf_summary = tf_overall.get('summary', []) if isinstance(tf_overall, dict) else []
        print(f"  偏向分数: {tf_bias}")
        # 打印总体解读
        if isinstance(tf_overall, dict):
            print(f"  -- 总体解读 --")
            print(f"  总结: {tf_overall.get('overall_summary', 'N/A')}")
            print(f"  详情:")
            if tf_summary:
                 for item in tf_summary:
                    print(f"    - {item}")
            else:
                 print("    - N/A")
        else:
            print(f"  总体解读: N/A")
        print("")
    elif tf_analysis and tf_analysis.get('error'):
        print("-- 成交流分析 --")
        print(f"  错误: {tf_analysis['error']}")
        print("")
    else:
        print("-- 成交流分析: N/A --")
        print("")

    # 微观趋势 (多周期)
    mt_mtf = analysis_results.get('micro_trend_mtf')
    if mt_mtf and isinstance(mt_mtf, dict) and not mt_mtf.get('error'):
        print("-- 微观趋势 (多周期) --")
        for interval, result in mt_mtf.items():
            if interval != 'error' and isinstance(result, dict):
                summary = result.get('summary', 'N/A')
                score = result.get('score', 'N/A')
                score_str = f"{score:.1f}" if isinstance(score, (int, float)) else score
                print(f"    {interval:>4s}: {summary} (评分:{score_str})")
        print("")
    elif mt_mtf and mt_mtf.get('error'):
        print("-- 微观趋势 (多周期) --")
        print(f"  错误: {mt_mtf['error']}")
        print("")
    else:
        print("-- 微观趋势 (多周期): N/A --")
        print("")

    # 微观趋势 (整合信号)
    mt_integrated = analysis_results.get('micro_trend_integrated')
    if mt_integrated and isinstance(mt_integrated, dict) and not mt_integrated.get('error'):
        print("-- 微观趋势 (整合信号) --")
        int_type = mt_integrated.get('type', 'N/A')
        int_direction = mt_integrated.get('direction', 'N/A')
        int_intervals = mt_integrated.get('involved_intervals', [])
        int_message = mt_integrated.get('message', 'N/A')
        int_reason = mt_integrated.get('reason', [])
        print(f"  类型: {int_type}")
        print(f"  方向: {int_direction}")
        print(f"  涉及周期: {int_intervals}")
        print(f"  消息: {int_message}")
        if int_reason:
            print(f"{int_type}:")
            for reason_item in int_reason:
                print(f"- {reason_item}")
        print("")
    elif mt_integrated and mt_integrated.get('error'):
        print("-- 微观趋势 (整合信号) --")
        print(f"  错误: {mt_integrated['error']}")
        print("")
    else:
        print("-- 微观趋势 (整合信号): N/A --")
        print("")
        
    # 箱体突破分析
    box_breakout = analysis_results.get('box_breakout')
    if box_breakout and isinstance(box_breakout, dict) and not box_breakout.get('error'):
        print("-- 箱体突破分析 --")
        box_status = box_breakout.get('status', '未知')
        box_reason = box_breakout.get('reason', 'N/A')
        print(f"  状态: {box_status}")
        print(f"  理由: {box_reason}")
        # 可以添加更多箱体细节的打印
        print("")
    elif box_breakout and box_breakout.get('error'):
        print("-- 箱体突破分析 --")
        print(f"  错误: {box_breakout['error']}")
        print("")
    else:
        print("-- 箱体突破分析: N/A --")
        print("")

    # 综合判断
    summary = analysis_results.get('integrated_summary')
    if summary and isinstance(summary, dict):
        print("-- 综合判断 --")
        verdict = summary.get('verdict', 'Unknown')
        recommendation = summary.get('recommendation', 'N/A') # 新增推荐策略
        confidence = summary.get('confidence', 'N/A')
        confidence_str = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else confidence
        reasons = summary.get('reason', [])
        
        # 确定置信度描述
        confidence_desc = ""
        if isinstance(confidence, (int, float)):
            if confidence < 0.4:
                confidence_desc = "⚠️ 低置信度，建议谨慎"
            elif confidence < 0.7:
                confidence_desc = "中等置信度"
            else:
                confidence_desc = "✅ 高置信度"
                
        print(f"  判断结论: {verdict}")
        print(f"  操作建议: {recommendation}") # 打印推荐策略
        print(f"  置 信 度: {confidence_str} {confidence_desc}")
        if reasons:
            print(f"  判断理由:")
            for reason in reasons:
                print(f"    - {reason}")
        print("")
        
        # 最终综合建议
        final_advice = summary.get('final_advice')
        if final_advice and isinstance(final_advice, dict):
             print("-- 最终综合建议 --")
             market_direction = final_advice.get('direction_advice', 'N/A')
             strategy = final_advice.get('strategy_advice', 'N/A')
             sl_info = final_advice.get('sl_info', 'N/A')
             tp_info = final_advice.get('tp_info', 'N/A')
             print(f"  市场方向: {market_direction}")
             print(f"  推荐策略: {strategy}")
             # 只有当 sl_info 或 tp_info 不是 'N/A' 时才打印
             if sl_info != 'N/A' or tp_info != 'N/A':
                 print(f"  参考点位: {sl_info} / {tp_info}") # 打印支撑/阻力
             else:
                 print(f"  ⚠️ 未能获取有效支撑/阻力位信息")
             print("")
        else:
             print("-- 最终综合建议: N/A --")
             print("")
        
    else:
        print("-- 综合判断: N/A --")
        print("")
        print("-- 最终综合建议: N/A --")
        print("")
        
    print("  ⚠️ 风险提示: 以上分析仅供参考，交易有风险，入市需谨慎")