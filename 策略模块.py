# -*- coding: utf-8 -*-
"""
策略模块

定义和执行交易策略。
"""

import logging
import pandas as pd
import math # 用于计算订单大小

# --- 日志配置 (可以复用或独立配置) ---
logger = logging.getLogger(__name__)
# 确保日志处理器已在主程序或其他地方配置好
# 例如: logging.basicConfig(...) 或从配置模块获取
logger.info("策略模块加载。")

# === 辅助函数 ===

def _提取K线偏向(分析数据: dict) -> tuple[str, str]:
    """从分析数据中提取 K 线偏向和理由。"""
    kline_bias = "未知"
    kline_reason = "无K线分析理由"
    kline_analysis_data = 分析数据.get('kline_analysis')
    kline_raw_text = ""

    if isinstance(kline_analysis_data, dict):
        kline_bias = kline_analysis_data.get('bias', "未知")
        kline_reason = kline_analysis_data.get('reason', "")
        if kline_bias == "未知" and isinstance(kline_analysis_data.get('summary'), str):
            kline_raw_text = kline_analysis_data.get('summary', '')
    elif isinstance(kline_analysis_data, str):
        kline_raw_text = kline_analysis_data
    else:
        # logger.debug("未提供 K 线分析数据或格式未知。") # 减少日志噪音
        pass

    if kline_bias == "未知" and kline_raw_text and 'K线分析偏向:' in kline_raw_text:
        # logger.debug(f"尝试从文本解析 K 线偏向: {kline_raw_text}") # 减少日志噪音
        try:
            bias_part = kline_raw_text.split('K线分析偏向:')[1].split('(')[0].strip()
            if '看涨' in bias_part or 'Bullish' in bias_part:
                kline_bias = '看涨'
            elif '看跌' in bias_part or 'Bearish' in bias_part:
                kline_bias = '看跌'
            elif '冲突' in bias_part or 'Neutral' in bias_part or 'Conflict' in bias_part:
                kline_bias = '冲突'
            else:
                kline_bias = "解析失败"
            
            if '理由:' in kline_raw_text:
                reason_part = kline_raw_text.split('理由:')[1].split(')')[0].strip()
                kline_reason = reason_part
        except Exception as e:
            logger.warning(f"解析 K 线分析文本失败: {kline_raw_text}, 错误: {e}")
            kline_bias = "解析异常"
            
    return kline_bias, kline_reason

def _处理无仓位情况(分析数据: dict, 策略参数: dict, current_price: float) -> tuple:
    """处理没有持仓时的初始开仓逻辑。"""
    signal = 'HOLD'
    size = 0.0
    entry_price = None
    stop_loss = None
    take_profit = None
    reason = "默认无信号"
    next_level = None # 初始开仓后级别为 1

    kline_bias, kline_reason = _提取K线偏向(分析数据)
    base_order_value = 策略参数['base_order_value']
    take_profit_pct = 策略参数['take_profit_pct_from_avg']

    if kline_bias == '看涨':
        signal = 'LONG'
        entry_price = current_price
        size = base_order_value / entry_price
        take_profit = entry_price * (1 + take_profit_pct / 100)
        reason = f"初始开仓：K线偏向看涨 ({kline_reason})"
        next_level = 1 # 开仓后是第一级
    elif kline_bias == '看跌':
        signal = 'SHORT'
        entry_price = current_price
        size = base_order_value / entry_price
        take_profit = entry_price * (1 - take_profit_pct / 100)
        reason = f"初始开仓：K线偏向看跌 ({kline_reason})"
        next_level = 1
    else:
        reason = f"无初始开仓信号 (K线偏向: {kline_bias})"
        # logger.debug(f"无初始开仓信号，K线分析偏向为: {kline_bias} (理由: {kline_reason})") # 减少日志噪音

    return signal, size, reason, entry_price, stop_loss, take_profit, next_level

def _处理有仓位情况(持仓状态: dict, 策略参数: dict, current_price: float) -> tuple:
    """处理有持仓时的逻辑。返回 (signal, size, reason, entry_price, stop_loss, take_profit, next_level)"""
    signal = 'HOLD' # 默认是持有
    size = 0.0
    entry_price = None # 仅加仓时设置
    stop_loss = None   # 会被计算出的整体止损覆盖
    take_profit = None # 会被计算出的目标止盈覆盖
    reason = "默认持有"
    next_level = 持仓状态.get('level', 1) # 默认保持当前级别

    # 提取持仓信息
    direction = 持仓状态.get('direction')
    avg_price = 持仓状态.get('avg_price')
    total_size = 持仓状态.get('total_size')
    last_entry_price = 持仓状态.get('last_entry_price', avg_price)
    level = 持仓状态.get('level', 1)

    # 提取策略参数
    overall_sl_pct = 策略参数['overall_stop_loss_pct_from_avg']
    take_profit_pct = 策略参数['take_profit_pct_from_avg']
    level_distance_pct = 策略参数['level_distance_pct']
    max_levels = 策略参数['max_levels']
    base_order_value = 策略参数['base_order_value']
    size_multiplier = 策略参数['size_multiplier']

    if not all([direction, avg_price, total_size]):
         logger.error(f"持仓状态信息不完整: {持仓状态}")
         return 'HOLD', 0.0, "持仓状态错误", None, None, None, level # 返回当前 level

    # 计算当前的止损和止盈目标价
    overall_stop_loss_price = avg_price * (1 - overall_sl_pct / 100) if direction == 'LONG' else avg_price * (1 + overall_sl_pct / 100)
    target_tp_price = avg_price * (1 + take_profit_pct / 100) if direction == 'LONG' else avg_price * (1 - take_profit_pct / 100)
    stop_loss = overall_stop_loss_price # 更新返回值中的止损
    take_profit = target_tp_price     # 更新返回值中的止盈

    # --- 1. 判断整体止损 (最优先) ---
    if (direction == 'LONG' and current_price <= overall_stop_loss_price) or \
       (direction == 'SHORT' and current_price >= overall_stop_loss_price):
        signal = 'CLOSE'
        reason = f"触发整体止损 (均价: {avg_price:.4f}, 止损线: {overall_stop_loss_price:.4f}, 亏损阈值: {overall_sl_pct}%)"
        size = total_size
        entry_price = None # 平仓无入场价
        take_profit = None # 止损了不看止盈
        next_level = None  # 平仓后无级别
        return signal, size, reason, entry_price, stop_loss, take_profit, next_level # 直接返回

    # --- 2. 判断止盈 --- (只有在未触发整体止损时才判断)
    if (direction == 'LONG' and current_price >= target_tp_price) or \
       (direction == 'SHORT' and current_price <= target_tp_price):
        signal = 'CLOSE'
        reason = f"达到止盈目标 (均价: {avg_price:.4f}, 目标: {target_tp_price:.4f})"
        size = total_size
        entry_price = None # 平仓无入场价
        next_level = None  # 平仓后无级别
        return signal, size, reason, entry_price, stop_loss, take_profit, next_level # 直接返回
    
    # --- 3. 判断加仓 --- (只有在未触发整体止损和止盈时才判断)
    if level < max_levels:
        should_add = False
        reason_add = ""
        if direction == 'LONG' and current_price <= last_entry_price * (1 - level_distance_pct / 100):
            should_add = True
            reason_add = f"加仓做多 (L{level+1}): 价格相比上次入场({last_entry_price:.4f})下跌超过 {level_distance_pct}%"
        elif direction == 'SHORT' and current_price >= last_entry_price * (1 + level_distance_pct / 100):
            should_add = True
            reason_add = f"加仓做空 (L{level+1}): 价格相比上次入场({last_entry_price:.4f})上涨超过 {level_distance_pct}%"
        
        if should_add:
            signal = 'ADD_LONG' if direction == 'LONG' else 'ADD_SHORT'
            add_value = base_order_value * (size_multiplier ** level)
            size = add_value / current_price
            entry_price = current_price
            next_level = level + 1 # 计算下一级别
            reason = reason_add + f" | 增加价值: {add_value:.2f} USDT, 数量: {size:.4f}"
            return signal, size, reason, entry_price, stop_loss, take_profit, next_level # 返回加仓信号

    # --- 4. 如果未触发任何操作 --- 
    reason = f"持有 {direction} 仓位 (均价: {avg_price:.4f}, L{level}), 未触发加仓/止盈/止损条件 (TP: {target_tp_price:.4f}, SL: {overall_stop_loss_price:.4f})"
    # 保持当前级别 next_level 不变 (已在函数开头设置)
    return signal, size, reason, entry_price, stop_loss, take_profit, next_level

def _计算信号输出(signal, size, reason, entry_price, stop_loss, take_profit, next_level=None) -> dict:
    """统一格式化输出字典，增加 next_level。"""
    signal_output = {
        'signal': signal,
        'size': round(size, 6) if size > 0 else 0.0,
        'reason': reason,
        'entry_price': round(entry_price, 4) if entry_price is not None else None,
        'stop_loss': round(stop_loss, 4) if stop_loss is not None else None,
        'take_profit': round(take_profit, 4) if take_profit is not None else None,
        'next_level': next_level # 添加下一级别信息 (可能为 None)
    }
    # 减少日志噪音，只记录非 HOLD 信号
    if signal != 'HOLD':
        logger.info(f"马丁格尔策略输出: {signal_output}")
    else:
        logger.debug(f"马丁格尔策略输出: {signal_output}") # HOLD 信号使用 DEBUG 级别
    return signal_output

def _验证策略参数(策略参数: dict) -> bool:
    """验证策略参数的有效性。"""
    required_keys = [
        'base_order_value', 'level_distance_pct', 'size_multiplier',
        'max_levels', 'take_profit_pct_from_avg', 'overall_stop_loss_pct_from_avg'
    ]
    for key in required_keys:
        if key not in 策略参数:
            logger.error(f"策略参数错误：缺少键 '{key}'")
            return False
        value = 策略参数[key]
        if not isinstance(value, (int, float)):
            logger.error(f"策略参数错误：'{key}' 的值必须是数字，但得到 {type(value)}")
            return False
        # 基础检查
        if ('pct' in key or 'multiplier' in key) and value <= 0:
             logger.error(f"策略参数错误：'{key}' ({value}) 必须是正数")
             return False
        if key == 'max_levels' and value < 1:
             logger.error(f"策略参数错误：'{key}' ({value}) 必须至少为 1")
             return False
        if key == 'base_order_value' and value <= 0:
             logger.error(f"策略参数错误：'{key}' ({value}) 必须是正数")
             return False
            
    return True

# --- 马丁格尔加仓策略 (主函数) ---

def 马丁格尔加仓策略(分析数据: dict, 持仓状态: dict = None, 策略参数_输入: dict = None) -> dict:
    """
    简化的马丁格尔加仓策略（亏损加仓摊平成本）。
    接收外部策略参数进行配置。
    注意：此函数是无状态的，需要外部管理 持仓状态。
    风险极高，仅供演示和研究，不建议直接用于实盘。

    Args:
        分析数据 (dict): 包含分析结果和当前价格的字典。
                       **必须包含 'current_price' 键，值为浮点数。**
                       例如: {
                           'symbol': 'BTCUSDT',
                           'market_type': 'futures',
                           'current_price': 50000.50,
                           'kline_analysis': { ... } 
                       }
        持仓状态 (dict, optional): 描述当前持仓的字典。
        策略参数_输入 (dict, optional): 包含策略参数的字典，用于覆盖默认值。
                                       例如: {
                                           'level_distance_pct': 1.5,
                                           'max_levels': 7
                                       }

    Returns:
        dict: 包含交易信号和下一级别信息的字典。
    """
    logger.debug(f"执行马丁格尔加仓策略: {分析数据.get('symbol', 'N/A')}, 持仓: {持仓状态 is not None}")

    # --- 定义默认策略参数 --- 
    默认策略参数 = {
        'base_order_value': 10,           # 基础订单价值 (USDT)
        'level_distance_pct': 1.0,        # 加仓距离 (%),
        'size_multiplier': 2.0,           # 加仓倍数
        'max_levels': 5,                  # 最大加仓次数
        'take_profit_pct_from_avg': 1.5,  # 止盈百分比 (基于均价)
        'initial_stop_loss_pct': 2.0,     # 初始止损百分比 (当前未使用)
        'overall_stop_loss_pct_from_avg': 5.0 # 整体止损百分比 (基于均价)
    }
    
    # --- 合并输入参数与默认参数 --- 
    # 创建一个新字典，以默认参数为基础，然后用输入参数覆盖
    策略参数 = 默认策略参数.copy() # 重要：创建副本，不修改默认值
    if 策略参数_输入:
        策略参数.update(策略参数_输入) # 使用输入参数更新 (覆盖)
        logger.debug(f"使用外部传入的部分策略参数覆盖默认值: {策略参数_输入}")
    else:
        logger.debug("未使用外部策略参数，全部使用默认值。")
    
    logger.debug(f"当前生效的策略参数: {策略参数}")
    
    # --- 参数验证 --- 
    if not _验证策略参数(策略参数):
        return _计算信号输出('HOLD', 0.0, "策略参数无效", None, None, None, None)

    # --- 获取并验证当前价格 --- 
    current_price = 分析数据.get('current_price')
    if current_price is None or not isinstance(current_price, (int, float)) or current_price <= 0:
        logger.warning(f"策略执行中止：分析数据中缺少有效的 'current_price'。 数据: {分析数据}")
        return _计算信号输出('HOLD', 0.0, "缺少有效的当前价格", None, None, None, None)

    # --- 根据持仓状态调用不同逻辑 --- 
    if 持仓状态 is None or not 持仓状态:
        signal, size, reason, entry_price, stop_loss, take_profit, next_level = \
            _处理无仓位情况(分析数据, 策略参数, current_price)
    else:
        signal, size, reason, entry_price, stop_loss, take_profit, next_level = \
            _处理有仓位情况(持仓状态, 策略参数, current_price)

    # --- 统一格式化输出 ---
    return _计算信号输出(signal, size, reason, entry_price, stop_loss, take_profit, next_level)

# --- 主执行/测试函数 (需要更新以演示参数传递) ---
if __name__ == '__main__':
    print("执行策略模块测试...")
    logging.basicConfig(level=logging.DEBUG) # 测试时用 DEBUG 方便看参数
    
    # --- 默认参数测试 ---
    print("\n--- 测试 1: 使用默认参数开多仓 ---")
    analysis1 = {
        'symbol': 'BTCUSDT', 
        'market_type': 'futures', 
        'current_price': 50000,
        'kline_analysis': {'bias': '看涨', 'reason': 'MA金叉'}
    }
    signal1 = 马丁格尔加仓策略(analysis1, None) # 不传递参数，使用默认值
    import json
    print(json.dumps(signal1, indent=2, ensure_ascii=False))
    
    # --- 传递部分参数测试 ---
    print("\n--- 测试 2: 传递部分参数 (修改加仓距离和最大层数) 开空仓 ---")
    analysis2 = {
        'symbol': 'ETHUSDT', 
        'market_type': 'futures', 
        'current_price': 3000,
        'kline_analysis': {'bias': '看跌', 'reason': '跌破支撑'}
    }
    custom_params = {
        'level_distance_pct': 1.5, # 加仓距离改为 1.5%
        'max_levels': 7,          # 最大层数改为 7
        # 其他参数将使用默认值
    }
    signal2 = 马丁格尔加仓策略(analysis2, None, 策略参数_输入=custom_params)
    print(json.dumps(signal2, indent=2, ensure_ascii=False))
    
    # --- 传递参数进行加仓测试 ---
    print("\n--- 测试 3: 传递参数进行加仓 (接测试2, 价格上涨触发加仓) ---")
    position3 = {'direction': 'SHORT', 'avg_price': 3000, 'total_size': 0.00333, 'last_entry_price': 3000, 'level': 1} # 假设已开空仓
    analysis3 = {
        'symbol': 'ETHUSDT', 
        'market_type': 'futures',
        'current_price': 3000 * (1 + 1.5 / 100) + 1 # 价格上涨超过 1.5%
    }
    # 确保使用与开仓时相同的自定义参数进行后续判断
    signal3 = 马丁格尔加仓策略(analysis3, position3, 策略参数_输入=custom_params)
    print(json.dumps(signal3, indent=2, ensure_ascii=False))
    
    # --- 无效参数测试 --- 
    print("\n--- 测试 9: 无效策略参数 (通过输入传递) ---")
    invalid_params = { 'max_levels': -1 } # 无效参数
    signal9 = 马丁格尔加仓策略(analysis1, None, 策略参数_输入=invalid_params)
    print(json.dumps(signal9, indent=2, ensure_ascii=False)) 