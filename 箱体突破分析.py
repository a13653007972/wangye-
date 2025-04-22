import logging
import pandas as pd
from typing import Union
from 数据获取模块 import 获取K线数据
from 配置 import BOX_BREAKOUT_CONFIG

# 设置日志 (确保主模块或其他地方已经设置了 DEBUG 级别才能看到 debug 日志)
# logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')
# 通常日志配置在主入口完成，这里只获取 logger
logger = logging.getLogger(__name__)

# --- 辅助计算函数 (重命名变量，调整量能计算逻辑) ---

def _calculate_main_box_and_volume(main_klines_df: pd.DataFrame, config: dict) -> tuple:
    """计算主时间周期箱体和相关量能指标。"""
    main_len = config['main_box_length']
    vol_len = config['volume_ma_length']
    main_tf = config['main_box_timeframe'] # 获取主时间周期用于日志
    
    main_high, main_low = None, None
    volume_avg_main, volume_last_main, volume_ratio = None, None, None

    # 计算箱体 (使用最近 main_len 根完整K线)
    if len(main_klines_df) >= main_len:
        relevant_klines = main_klines_df.iloc[-(main_len + 1):-1] # 假设最后一根未完成
        if len(relevant_klines) < main_len:
             relevant_klines = main_klines_df.iloc[-main_len:]
        
        if not relevant_klines.empty:
            main_high = relevant_klines['high'].max()
            main_low = relevant_klines['low'].min()
            logger.debug(f"Calculated main box ({main_tf}): High={main_high}, Low={main_low} from {len(relevant_klines)} bars.")
    else:
        logger.warning(f"主周期({main_tf})数据不足 {main_len} 根，无法计算主箱体。")

    # 计算量能 (基于主时间周期K线)
    if len(main_klines_df) >= vol_len + 1:
        vol_klines = main_klines_df.iloc[-(vol_len + 1):-1] # 用于计算均值的K线
        volume_avg_main = vol_klines['volume'].mean()
        volume_last_main = main_klines_df['volume'].iloc[-2] # 上一根完整K线的成交量
        
        if volume_avg_main is not None and volume_avg_main > 0:
            volume_ratio = volume_last_main / volume_avg_main
        logger.debug(f"Calculated volume ({main_tf}): Avg={volume_avg_main}, Last={volume_last_main}, Ratio={volume_ratio}")
    else:
        logger.warning(f"主周期({main_tf})数据不足 {vol_len + 1} 根，无法计算 {vol_len} 周期成交量均线及比率。")

    return main_high, main_low, volume_avg_main, volume_last_main, volume_ratio

def _calculate_secondary_box(secondary_klines_df: pd.DataFrame, config: dict) -> tuple:
    """计算次级时间周期箱体。"""
    secondary_len = config['secondary_box_length']
    secondary_tf = config['secondary_box_timeframe']
    secondary_high, secondary_low = None, None

    if len(secondary_klines_df) >= secondary_len:
        relevant_klines = secondary_klines_df.iloc[-secondary_len:]
        secondary_high = relevant_klines['high'].max()
        secondary_low = relevant_klines['low'].min()
        logger.debug(f"Calculated secondary box ({secondary_tf}): High={secondary_high}, Low={secondary_low}")
    else:
        logger.warning(f"次级周期({secondary_tf})数据不足 {secondary_len} 根，无法计算次级箱体。")
        
    return secondary_high, secondary_low

def _calculate_fibonacci_levels(main_high: Union[float, None], main_low: Union[float, None], config: dict) -> dict:
    """计算基于主箱体的斐波那契水平。"""
    fib_levels = {}
    fib_levels_pct = config['fibonacci_levels']

    if main_high is not None and main_low is not None and main_high > main_low:
        box_range = main_high - main_low
        for level_pct in fib_levels_pct:
            level_val = main_low + box_range * (level_pct / 100.0)
            fib_levels[f'{level_pct:.1f}'] = round(level_val, 2)
        logger.debug(f"Calculated Fibonacci levels based on main box: {fib_levels}")
    else:
        logger.debug("Cannot calculate Fibonacci levels due to invalid main box range.")
    return fib_levels

def _determine_breakout_status(current_price: Union[float, None], 
                             main_high: Union[float, None], main_low: Union[float, None], 
                             secondary_high: Union[float, None], secondary_low: Union[float, None], 
                             volume_ratio: Union[float, None], 
                             fib_levels: dict, 
                             config: dict) -> tuple[str, str]:
    """根据输入数据判断主箱体突破状态和理由。"""
    status = '数据不足无法判断'
    reason_parts = []
    vol_ratio_threshold = config['volume_ratio_threshold']
    breakout_pct = config['breakout_confirmation_pct'] / 100.0
    main_tf = config['main_box_timeframe']
    secondary_tf = config['secondary_box_timeframe']

    if main_high is None or main_low is None or current_price is None:
        reason_parts.append(f"缺少关键价格数据（主周期{main_tf}箱体或当前价）。")
        logger.debug("Determined status: Insufficient data.")
        return status, ' '.join(reason_parts)
        
    if main_high <= main_low:
         status = f'主周期({main_tf})箱体无效'
         reason_parts.append(f"主周期最高价 {main_high} <= 最低价 {main_low}。")
         logger.debug("Determined status: Invalid main box.")
         return status, ' '.join(reason_parts)

    breakout_up_confirm_price = main_high * (1 + breakout_pct)
    breakout_down_confirm_price = main_low * (1 - breakout_pct)
    is_volume_boosted = volume_ratio is not None and volume_ratio >= vol_ratio_threshold
    volume_info = f"(Vol Ratio: {volume_ratio:.2f})" if volume_ratio is not None else "(Vol Ratio: N/A)"

    logger.debug(f"Checking status for Current Price: {current_price}, Main Box ({main_tf}): [{main_low}, {main_high}], Confirm Points: [{breakout_down_confirm_price}, {breakout_up_confirm_price}], Volume Boosted: {is_volume_boosted}")

    if current_price > main_high:
        logger.debug(f"Price is above main box ({main_tf}) high.")
        if current_price >= breakout_up_confirm_price:
            logger.debug("Price is at or above upward confirmation level.")
            status = f'主周期({main_tf})向上突破确认'
            reason_parts.append(f"当前价 {current_price:.2f} >= 突破确认点 {breakout_up_confirm_price:.2f} ({breakout_pct*100}%).")
            if is_volume_boosted:
                 status += ' (放量)'
                 reason_parts.append(f"且上一周期成交量放大 {volume_info} >= {vol_ratio_threshold:.2f}." )
            else:
                 status += ' (缩量)'
                 reason_parts.append(f"但上一周期成交量未明显放大 {volume_info} < {vol_ratio_threshold:.2f}." )
        else:
            logger.debug("Price is above high, but below upward confirmation level.")
            status = f'主周期({main_tf})向上突破尝试中'
            reason_parts.append(f"当前价 {current_price:.2f} > 主周期上沿 {main_high:.2f}, 但 < 突破确认点 {breakout_up_confirm_price:.2f}.")
            if is_volume_boosted:
                 reason_parts.append(f"伴随上一周期成交量放大 {volume_info}." )
            else:
                 reason_parts.append(f"但上一周期成交量未明显放大 {volume_info}." )

    elif current_price < main_low:
        logger.debug(f"Price is below main box ({main_tf}) low.")
        if current_price <= breakout_down_confirm_price:
            logger.debug("Price is at or below downward confirmation level.")
            status = f'主周期({main_tf})向下突破确认'
            reason_parts.append(f"当前价 {current_price:.2f} <= 突破确认点 {breakout_down_confirm_price:.2f} ({breakout_pct*100}%).")
            if is_volume_boosted:
                 status += ' (放量)'
                 reason_parts.append(f"且上一周期成交量放大 {volume_info} >= {vol_ratio_threshold:.2f}." )
            else:
                 status += ' (缩量)'
                 reason_parts.append(f"但上一周期成交量未明显放大 {volume_info} < {vol_ratio_threshold:.2f}." )
        else:
            logger.debug("Price is below low, but above downward confirmation level.")
            status = f'主周期({main_tf})向下突破尝试中'
            reason_parts.append(f"当前价 {current_price:.2f} < 主周期下沿 {main_low:.2f}, 但 > 突破确认点 {breakout_down_confirm_price:.2f}.")
            if is_volume_boosted:
                 reason_parts.append(f"伴随上一周期成交量放大 {volume_info}." )
            else:
                 reason_parts.append(f"但上一周期成交量未明显放大 {volume_info}." )
    else:
        logger.debug(f"Price is inside the main box ({main_tf}).")
        status = f'主周期({main_tf})箱体内盘整'
        reason_parts.append(f"当前价 {current_price:.2f} 在主周期箱体 [{main_low:.2f}, {main_high:.2f}] 内部。")
        # 结合次级箱体判断位置
        if secondary_high is not None and secondary_low is not None:
             logger.debug(f"Checking relative position to secondary box ({secondary_tf}) [{secondary_low}, {secondary_high}]")
             if current_price > secondary_high:
                  reason_parts.append(f"且高于次级({secondary_tf})箱体上沿 {secondary_high:.2f}。")
             elif current_price < secondary_low:
                  reason_parts.append(f"且低于次级({secondary_tf})箱体下沿 {secondary_low:.2f}。")
             else:
                  reason_parts.append(f"位于次级({secondary_tf})箱体 [{secondary_low:.2f}, {secondary_high:.2f}] 内部。")
        else:
             logger.debug(f"Secondary box ({secondary_tf}) data not available for relative positioning.")
        # 判断靠近哪个斐波那契水平
        if fib_levels:
            closest_fib = min(fib_levels.items(), key=lambda item: abs(item[1] - current_price))
            reason_parts.append(f"当前靠近斐波那契 {closest_fib[0]}% ({closest_fib[1]:.2f}) 水平。")
            logger.debug(f"Closest Fibonacci level: {closest_fib[0]}% ({closest_fib[1]}).")
        else:
             logger.debug("Fibonacci levels not available for proximity check.")

    return status, ' '.join(reason_parts)

# --- 主分析函数 (更新变量名和日志) ---

def 分析箱体突破(symbol: str, market_type: str = 'spot') -> dict:
    """
    分析基于配置时间周期的主/次箱体突破策略。
    (其他文档字符串保持不变，但需更新示例)
    返回字典示例需更新键名： month_high -> main_high etc.
    """
    logger.info(f"开始分析 {symbol} ({market_type}) 的箱体突破情况 (配置: {BOX_BREAKOUT_CONFIG['main_box_timeframe']}/{BOX_BREAKOUT_CONFIG['secondary_box_timeframe']})...")
    results = {
        'symbol': symbol,
        'market_type': market_type,
        'status': '数据不足或错误',
        'reason': '',
        'main_high': None, # <--- 更改键名
        'main_low': None,  # <--- 更改键名
        'secondary_high': None, # <--- 更改键名
        'secondary_low': None,  # <--- 更改键名
        'current_price': None,
        'fib_levels': {},
        'volume_avg_main': None, # <--- 更改键名
        'volume_last_main': None, # <--- 更改键名
        'volume_ratio': None,
    }

    try:
        # --- 1. 获取配置 ---
        config = BOX_BREAKOUT_CONFIG
        main_tf = config['main_box_timeframe']
        main_len = config['main_box_length']
        secondary_tf = config['secondary_box_timeframe']
        secondary_len = config['secondary_box_length']
        vol_len = config['volume_ma_length']
        
        # --- 2. 获取K线数据 ---
        # 主周期数据
        limit_main = main_len + vol_len + 1 
        logger.debug(f"获取 {limit_main} 根 {main_tf} K线数据 for {symbol} ({market_type})...")
        main_klines_df = 获取K线数据(symbol, main_tf, limit=limit_main, market_type=market_type)
        if main_klines_df is None or len(main_klines_df) < main_len:
            results['reason'] = f"获取或解析主周期({main_tf})K线数据失败或数据不足 ({len(main_klines_df) if main_klines_df is not None else 0} < {main_len})。"
            logger.warning(results['reason'])
            return results # 主周期数据失败则无法继续
        
        # 次级周期数据 + 当前价格
        limit_secondary = secondary_len + 5
        logger.debug(f"获取 {limit_secondary} 根 {secondary_tf} K线数据 for {symbol} ({market_type})...")
        secondary_klines_df = 获取K线数据(symbol, secondary_tf, limit=limit_secondary, market_type=market_type)
        if secondary_klines_df is None or secondary_klines_df.empty:
            logger.warning(f"获取或解析次级周期({secondary_tf})K线数据失败，将无法获取当前价和次级箱体。")
            current_price = None # 无法获取当前价
        else:
             # 使用次级周期最后一根收盘价作为当前价 (更实时)
            current_price = secondary_klines_df['close'].iloc[-1]
            results['current_price'] = current_price
            # 如果需要，也可以用主周期最后一根K线收盘价 current_price = main_klines_df['close'].iloc[-1]

        # --- 3. 计算指标 (调用辅助函数) ---
        main_high, main_low, vol_avg, vol_last, vol_ratio = _calculate_main_box_and_volume(main_klines_df, config)
        results.update({
            'main_high': main_high,
            'main_low': main_low,
            'volume_avg_main': vol_avg,
            'volume_last_main': vol_last,
            'volume_ratio': vol_ratio
        })

        if secondary_klines_df is not None and not secondary_klines_df.empty:
             secondary_high, secondary_low = _calculate_secondary_box(secondary_klines_df, config)
             results.update({'secondary_high': secondary_high, 'secondary_low': secondary_low})
        else:
             secondary_high, secondary_low = None, None

        fib_levels = _calculate_fibonacci_levels(main_high, main_low, config)
        results['fib_levels'] = fib_levels

        # --- 4. 判断状态 (调用辅助函数) ---
        status, reason = _determine_breakout_status(
            current_price, main_high, main_low, secondary_high, secondary_low, vol_ratio, fib_levels, config
        )
        results['status'] = status
        results['reason'] = reason
        logger.info(f"箱体突破分析完成 for {symbol}: {status}")

    except ImportError as e:
        logger.error(f"导入错误: {e}. 请确保 '数据获取模块' 和 '配置' 文件存在且路径正确。", exc_info=True)
        results['status'] = '导入错误'
        results['reason'] = f"ImportError: {e}"
    except KeyError as e:
        logger.error(f"配置错误: 缺少键 {e}。请检查 '配置.py' 中的 BOX_BREAKOUT_CONFIG。", exc_info=True)
        results['status'] = '配置错误'
        results['reason'] = f"KeyError: Missing config key {e}"
    except Exception as e:
        logger.error(f"分析箱体突破时发生未知错误 for {symbol}: {e}", exc_info=True)
        results['status'] = '分析函数内部错误'
        results['reason'] = f"Error: {type(e).__name__}: {e}"

    return results

# --- 单元测试 (更新以匹配新的配置和键名) ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - [%(name)s:%(funcName)s] - %(message)s')
    
    # 确保能加载配置
    try:
        from 配置 import BOX_BREAKOUT_CONFIG
    except ImportError:
         logger.critical("CRITICAL: 无法从 '配置.py' 导入 BOX_BREAKOUT_CONFIG。单元测试无法进行。")
         # 如果希望即使导入失败也用默认值测试，可以在这里重新定义，但最好是解决导入问题
         exit() # 或者抛出异常
         # BOX_BREAKOUT_CONFIG = { ... } # 备用
    
    test_symbol = 'BTCUSDT' 
    test_market_type = 'spot' 

    print(f"\n--- 测试箱体突破分析模块 ({test_symbol} - {test_market_type}) ---")
    logger.info(f"--- Starting Box Breakout Analysis Test ({BOX_BREAKOUT_CONFIG['main_box_timeframe']}/{BOX_BREAKOUT_CONFIG['secondary_box_timeframe']}) ---")
    box_analysis_result = 分析箱体突破(test_symbol, market_type=test_market_type)
    
    print("\n箱体突破分析结果:")
    for key, value in box_analysis_result.items():
        if isinstance(value, dict):
             print(f"  {key}:")
             for sub_key, sub_value in value.items():
                  print(f"    {sub_key}: {sub_value}")
        elif isinstance(value, float) and value is not None:
             print(f"  {key}: {value:.4f}")
        else:
             print(f"  {key}: {value}")

    logger.info("--- Box Breakout Analysis Test Finished ---")
    print("--- 测试结束 ---") 