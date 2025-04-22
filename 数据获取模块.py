'''
数据获取模块

负责与币安 API 交互，获取市场数据、账户数据和交易所信息。
'''

import os
import logging
from pathlib import Path
import functools # 导入 functools 用于装饰器
import numpy as np # 用于 percentile 计算
from datetime import datetime, timezone, timedelta # 导入 timedelta 用于缓存有效期

# 从配置模块导入必要的配置
import 配置

# 配置日志记录器
log_level = getattr(logging, 配置.LOG_LEVEL.upper(), logging.INFO) # 从配置读取级别，默认为 INFO
log_file = Path(配置.LOG_FILE) # 使用 Path 对象处理路径
log_file.parent.mkdir(parents=True, exist_ok=True) # 确保日志目录存在

log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 文件处理器
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.DEBUG) # 文件始终记录 DEBUG 及以上信息

# 控制台处理器
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(log_formatter)
stream_handler.setLevel(log_level) # 控制台使用配置的级别 (通常是 INFO)

# 获取根日志记录器并添加处理器
logger = logging.getLogger(__name__) # 使用模块名作为日志记录器名称
logger.setLevel(log_level) # 设置记录器本身的级别
# 检查是否已有处理器，避免重复添加
if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

logger.info("数据获取模块日志记录器初始化完成。")

# --- Binance API 客户端初始化 ---
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
import pandas as pd
import time
from datetime import datetime, timezone

# 使用从配置模块加载的 API 密钥
client = None
try:
    logger.info("初始化币安客户端...")
    client = Client(配置.BINANCE_API_KEY, 配置.BINANCE_API_SECRET)
    # 尝试获取服务器时间以验证 API 连接和密钥
    server_time = client.get_server_time()
    logger.info(f"成功连接到币安服务器，服务器时间：{pd.to_datetime(server_time['serverTime'], unit='ms')}")
except (BinanceAPIException, BinanceRequestException) as e:
    logger.error(f"连接币安 API 时出错: {e}")
    # 尝试记录更详细的错误信息
    if hasattr(e, 'code'):
        logger.error(f"币安错误代码: {e.code}")
    if "Invalid API-key" in str(e) or "Signature for this request is not valid" in str(e):
        logger.error("错误：API 密钥无效或配置不正确。请检查 .env 文件或环境变量。")
    client = None # 将客户端设为 None，以便后续函数可以检查
    logger.warning("币安客户端未能成功初始化，依赖API的功能将不可用。")
except Exception as e:
    logger.critical(f"初始化币安客户端时发生意外错误: {e}", exc_info=True) # 记录堆栈信息
    client = None

# --- 缓存配置 --- 
_exchange_info_cache = None # 用于缓存交易所信息
CACHE_DIR = Path("./kline_cache") # 定义K线缓存目录
CACHE_DIR.mkdir(parents=True, exist_ok=True) # 确保缓存目录存在
CACHE_EXPIRY_MINUTES = 60 # K线缓存有效期（分钟），可根据需要调整

# --- 辅助函数 --- 

# 定义可重试的币安错误代码
RETRYABLE_ERROR_CODES = [-1003, -1015] # Rate limits
# 定义最大重试次数和重试间隔（秒）
MAX_RETRIES = 3
RETRY_DELAY = 1

def _retry_on_api_error(func):
    """装饰器：在遇到特定 API 错误时自动重试函数调用。"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        retries = 0
        while retries <= MAX_RETRIES:
            try:
                return func(*args, **kwargs) # 尝试执行原始函数
            except BinanceRequestException as e: # 网络相关错误
                logger.warning(f"函数 {func.__name__} 遭遇网络错误: {e}. 尝试次数 {retries+1}/{MAX_RETRIES+1}")
                retries += 1
                if retries > MAX_RETRIES:
                    logger.error(f"函数 {func.__name__} 在 {MAX_RETRIES+1} 次尝试后因网络错误最终失败。")
                    # 可以选择是否在这里调用 _handle_api_exception 记录，或者直接返回 None
                    # _handle_api_exception(e, func.__name__)
                    return None 
                time.sleep(RETRY_DELAY)
            except BinanceAPIException as e: # API 返回的错误
                if e.code in RETRYABLE_ERROR_CODES:
                    logger.warning(f"函数 {func.__name__} 遭遇可重试 API 错误 (代码 {e.code}): {e}. 尝试次数 {retries+1}/{MAX_RETRIES+1}")
                    retries += 1
                    if retries > MAX_RETRIES:
                        logger.error(f"函数 {func.__name__} 在 {MAX_RETRIES+1} 次尝试后因 API 错误 {e.code} 最终失败。")
                        # _handle_api_exception(e, func.__name__)
                        return None
                    time.sleep(RETRY_DELAY)
                else:
                    # 对于不可重试的 API 错误，直接记录并失败
                    logger.error(f"函数 {func.__name__} 遭遇不可重试 API 错误 (代码 {e.code}): {e}")
                    # 可以选择调用 _handle_api_exception 或直接返回
                    _handle_api_exception(e, func.__name__, symbol=kwargs.get('symbol')) # 尝试传递 symbol
                    return None
            except Exception as e:
                 # 捕获其他非预期的异常
                 logger.error(f"函数 {func.__name__} 执行时发生未知错误: {e}", exc_info=True)
                 return None
    return wrapper

def _to_milliseconds(dt):
    """将 datetime 对象转换为毫秒时间戳"""
    return int(dt.timestamp() * 1000)

def _parse_time_input(time_input):
    """尝试将多种时间输入格式转换为毫秒时间戳"""
    if isinstance(time_input, (int, float)):
        return int(time_input) # 假设已经是毫秒时间戳
    elif isinstance(time_input, datetime):
        return _to_milliseconds(time_input)
    elif isinstance(time_input, str):
        try:
            # 尝试多种常用格式解析
            dt = pd.to_datetime(time_input).to_pydatetime()
            return _to_milliseconds(dt)
        except ValueError as e:
            logger.error(f"无法解析时间字符串 '{time_input}': {e}")
            return None
    else:
        logger.warning(f"不支持的时间输入类型: {type(time_input)}")
        return None

def _handle_api_exception(e, function_name, symbol=None):
    """统一处理 API 异常并记录日志 (现在主要处理最终失败或不可重试的错误)"""
    error_message = f"{function_name} 执行失败"
    if symbol:
        error_message += f" (Symbol: {symbol})"
    error_message += f": {e}"
    logger.error(error_message)
    if hasattr(e, 'code'):
        logger.error(f"币安错误代码: {e.code}")
        # 移除之前的速率限制警告，因为重试装饰器会处理
        if e.code == -1121: # 无效交易对
             logger.warning(f"交易对 {symbol} 可能无效。")
        elif "Invalid API-key" in str(e) or "Signature for this request is not valid" in str(e):
            logger.error("API 密钥无效或权限不足。")
    # 不再返回 None，因为调用它的地方（装饰器或 try-except 块）会处理返回值
    # return None 

# --- 核心市场数据 --- 

# 币安 API 的 K 线限制（现货和合约通常不同，这里取一个保守的通用值）
BINANCE_KLINE_LIMIT = 1000

INTERVAL_MAP_MILLISECONDS = {
    '1m': 60 * 1000,
    '3m': 3 * 60 * 1000,
    '5m': 5 * 60 * 1000,
    '15m': 15 * 60 * 1000,
    '30m': 30 * 60 * 1000,
    '1h': 60 * 60 * 1000,
    '2h': 2 * 60 * 60 * 1000,
    '4h': 4 * 60 * 60 * 1000,
    '6h': 6 * 60 * 60 * 1000,
    '8h': 8 * 60 * 60 * 1000,
    '12h': 12 * 60 * 60 * 1000,
    '1d': 24 * 60 * 60 * 1000,
    '3d': 3 * 24 * 60 * 60 * 1000,
    '1w': 7 * 24 * 60 * 60 * 1000,
    '1M': 30 * 24 * 60 * 60 * 1000 # 近似值，币安可能按日历月处理
}

@_retry_on_api_error # 应用装饰器
def 获取K线数据(symbol, interval=配置.DEFAULT_INTERVAL, limit=500, start_time=None, end_time=None, market_type='spot', force_refresh=False): # <--- 添加 force_refresh 参数
    '''获取指定交易对的K线/蜡烛图数据 (支持现货和期货)，并实现文件缓存。
       如果提供了 start_time，则会尝试获取从 start_time 到 end_time (或当前时间) 的所有数据，忽略 limit 参数。
       缓存逻辑：
       - 仅缓存不带 start_time/end_time 的请求（即获取最近 limit 条数据）。
       - 缓存文件名为: {symbol}_{market_type}_{interval}.parquet。
       - 检查缓存文件是否存在且未过期 (CACHE_EXPIRY_MINUTES)。
       - 如果缓存有效，直接加载。
       - 否则，从 API 获取，保存到缓存，再返回。

    Args:
        symbol (str): 交易对，例如 'BTCUSDT'。
        interval (str): K线时间间隔, 例如 '1m', '5m', '1h', '1d'。
        limit (int): 在没有指定 start_time 时，返回的 K 线数量上限。
        start_time (int|float|str|datetime, optional): 开始时间。
        end_time (int|float|str|datetime, optional): 结束时间。
        market_type (str): 市场类型 ('spot' 或 'futures'). 默认为 'spot'。
        force_refresh (bool): 是否强制刷新缓存，忽略现有缓存。

    Returns:
        pd.DataFrame or None: 包含 K 线数据的 DataFrame，失败时返回 None。
    '''
    if not client:
        logger.error("获取K线数据失败：币安客户端未初始化。")
        return None

    # --- 缓存逻辑 (仅对非历史数据请求生效) ---
    # 只有当不指定 start_time 时才启用缓存
    use_cache = (start_time is None and end_time is None)
    cache_file_path = None
    if use_cache:
        cache_filename = f"{symbol.upper()}_{market_type}_{interval}.parquet"
        cache_file_path = CACHE_DIR / cache_filename
        logger.debug(f"检查缓存文件: {cache_file_path}")

        if not force_refresh and cache_file_path.exists():
            try:
                # 检查文件修改时间是否在有效期内
                file_mod_time = datetime.fromtimestamp(cache_file_path.stat().st_mtime, tz=timezone.utc)
                expiry_time = datetime.now(timezone.utc) - timedelta(minutes=CACHE_EXPIRY_MINUTES)
                
                if file_mod_time > expiry_time:
                    logger.info(f"从缓存加载 K 线数据: {cache_filename}")
                    df = pd.read_parquet(cache_file_path)
                    # 简单验证数据格式 (可选)
                    if not df.empty and 'timestamp' in df.columns and 'close' in df.columns:
                         # 如果 limit 小于缓存数量，只返回需要的 limit 条
                         if limit and limit < len(df):
                              return df.iloc[-limit:].copy() # 返回最后 limit 条
                         else:
                              return df.copy() # 返回整个缓存
                    else:
                         logger.warning(f"缓存文件 {cache_filename} 格式无效，将重新获取。")
                         cache_file_path.unlink() # 删除无效缓存
                else:
                    logger.info(f"缓存文件 {cache_filename} 已过期 (有效期 {CACHE_EXPIRY_MINUTES} 分钟)，将重新获取。")
            except Exception as e:
                logger.warning(f"读取或检查缓存文件 {cache_filename} 时出错: {e}。将重新获取数据。")
                try:
                    if cache_file_path.exists(): cache_file_path.unlink() # 尝试删除损坏的缓存
                except OSError as unlink_e:
                     logger.error(f"删除损坏的缓存文件 {cache_file_path} 失败: {unlink_e}")
        elif force_refresh:
             logger.info(f"强制刷新缓存，将从 API 获取数据。")
    # --- 缓存逻辑结束 ---

    # --- 如果缓存未命中或不使用缓存，则从 API 获取 --- 
    all_klines_data = []
    standard_columns = [
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trade_count',
        'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
    ]

    # 处理时间参数 (这部分逻辑保持不变)
    start_ms = _parse_time_input(start_time) if start_time else None
    end_ms = _parse_time_input(end_time) if end_time else None
    if start_ms and not end_ms:
        end_ms = _parse_time_input(datetime.now(timezone.utc))

    # 选择API调用方法 (这部分逻辑保持不变)
    api_call = None
    market_label = ""
    if market_type == 'futures':
        # 检查客户端是否有期货方法 (增加健壮性)
        if hasattr(client, 'futures_klines'):
             api_call = client.futures_klines
             market_label = "(期货)"
        elif hasattr(client, 'futures_historical_klines'): # 备选方法名
             api_call = client.futures_historical_klines
             market_label = "(期货-历史)"
        else:
            logger.error(f"客户端对象缺少获取期货 K 线的方法 (如 futures_klines)。无法处理 market_type='futures'。")
            return None
    else: # 默认或明确指定 spot
        if hasattr(client, 'get_klines'):
             api_call = client.get_klines
             market_label = "(现货)"
        else:
             logger.error(f"客户端对象缺少获取现货 K 线的方法 (get_klines)。无法处理 market_type='spot'。")
             return None
    if api_call is None:
         return None # 如果上面选择失败，提前返回

    logger.info(f"开始从 API 获取 K 线数据{market_label}: {symbol}, {interval}, limit={limit if not start_ms else 'N/A (历史数据)'}")

    # 情况一：指定了开始时间，分页获取 (逻辑保持不变)
    if start_ms:
        interval_ms = INTERVAL_MAP_MILLISECONDS.get(interval)
        if not interval_ms:
            logger.error(f"无效的 K 线时间间隔: {interval}。无法进行分页获取。")
            return None
        
        logger.info(f"开始分页获取K线数据{market_label}: {symbol}, {interval}, 从 {pd.to_datetime(start_ms, unit='ms')} 到 {pd.to_datetime(end_ms, unit='ms')}")
        
        current_start_ms = start_ms
        fetch_count = 0
        max_fetch_attempts = 100 # 添加一个最大尝试次数以防无限循环

        while current_start_ms < end_ms and fetch_count < max_fetch_attempts:
            # 计算本次请求的结束时间 (最多请求 BINANCE_KLINE_LIMIT 条)
            # 注意：币安 endTime 是包含的
            loop_end_ms = min(current_start_ms + (BINANCE_KLINE_LIMIT * interval_ms) - 1, end_ms)
            
            params = {
                'symbol': symbol,
                'interval': interval,
                'startTime': current_start_ms,
                'endTime': loop_end_ms,
                'limit': BINANCE_KLINE_LIMIT # 即使指定了时间，也传递 limit 确保不超过单次限制
            }
            logger.debug(f"分页请求 {fetch_count + 1}{market_label}: startTime={current_start_ms}, endTime={loop_end_ms}")
            
            try:
                klines = api_call(**params) # <--- 使用选择的 API 调用
                if not klines:
                    logger.info(f"在时间 {pd.to_datetime(current_start_ms, unit='ms')} 之后的请求没有返回数据，获取结束。")
                    break # 没有更多数据了
                
                all_klines_data.extend(klines)
                last_kline_close_time = klines[-1][6] # 获取最后一根 K 线的关闭时间
                
                # 更新下一次请求的开始时间
                current_start_ms = last_kline_close_time + 1 # 下一根 K 线的理论开始时间
                
                fetch_count += 1
                # 添加一个小的延时避免触发速率限制 (可选，_retry_on_api_error 会处理)
                # time.sleep(0.1) 
                
            except BinanceAPIException as e:
                logger.error(f"分页获取 K 线时发生 API 错误{market_label} (尝试 {fetch_count + 1}): {e}")
                _handle_api_exception(e, "获取K线数据(分页)", symbol)
                # 遇到错误时可以选择中断或继续 (这里选择中断)
                return None
            except Exception as e:
                logger.error(f"分页获取 K 线时发生未知错误{market_label} (尝试 {fetch_count + 1}): {e}", exc_info=True)
                return None
                
        if fetch_count >= max_fetch_attempts:
             logger.warning(f"获取K线数据达到最大尝试次数 {max_fetch_attempts}，可能未能获取所有数据。")

    # --- 情况二：未指定开始时间，获取最新的 limit 条 --- 
    else:
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit
        }
        if end_ms: # 如果只指定了结束时间
            params['endTime'] = end_ms
            logger.info(f"获取最新的 {limit} 条 K 线数据{market_label}: {symbol}, {interval}, 结束于 {pd.to_datetime(end_ms, unit='ms')}")
        else:
            logger.info(f"获取最新的 {limit} 条 K 线数据{market_label}: {symbol}, {interval}")
        
        try:
            all_klines_data = api_call(**params) # <--- 使用选择的 API 调用
        except BinanceAPIException as e:
            logger.error(f"获取最新 K 线时发生 API 错误{market_label}: {e}")
            _handle_api_exception(e, "获取K线数据(最新)", symbol)
            return None
        except Exception as e:
            logger.error(f"获取最新 K 线时发生未知错误{market_label}: {e}", exc_info=True)
            return None

    # --- 整合并返回 DataFrame --- 
    if all_klines_data:
        # --- 修改：在创建 DataFrame 时指定标准列名 --- 
        df = pd.DataFrame(all_klines_data, columns=standard_columns) 
        
        # --- 修改：转换数据类型 --- 
        try:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
            numeric_cols = ['open', 'high', 'low', 'close', 'volume',
                            'quote_volume', 'trade_count',
                            'taker_buy_base_volume', 'taker_buy_quote_volume']
            for col in numeric_cols:
                 df[col] = pd.to_numeric(df[col], errors='coerce')
            # 不需要再删除 'ignore' 列，因为它已经是最后一列且通常无用
            # df = df.drop(columns=['ignore'], errors='ignore') 
            logger.info(f"成功获取并处理了 {len(df)} 条 K 线数据{market_label} for {symbol}, {interval}")
            return df
        except Exception as e:
            logger.error(f"转换K线数据类型时出错 for {symbol}, {interval}: {e}", exc_info=True)
            # 即使转换失败，也尝试返回带有正确列名的 DataFrame，但可能类型不正确
            return df # 或者返回 None 强制失败
    else:
        logger.warning(f"未能获取到任何 K 线数据{market_label} for {symbol}, {interval}")
        return None

@_retry_on_api_error # 应用装饰器
def 获取最新价格(symbol=None):
    '''获取指定交易对或所有交易对的最新价格。返回单个ticker字典或所有tickers的DataFrame'''
    if not client:
        logger.error("获取最新价格失败：币安客户端未初始化。")
        return None
    try:
        if symbol:
            logger.debug(f"获取最新价格: symbol={symbol}")
            ticker = client.get_symbol_ticker(symbol=symbol)
            logger.info(f"成功获取 {symbol} 最新价格: {ticker['price']}")
            # 对单个 symbol，仍返回字典
            return ticker
        else:
            logger.debug("获取所有交易对最新价格...")
            tickers = client.get_all_tickers()
            if not tickers:
                logger.warning("未能获取任何交易对的最新价格。")
                return pd.DataFrame() # 返回空 DataFrame
            df = pd.DataFrame(tickers)
            df['price'] = pd.to_numeric(df['price'])
            logger.info(f"成功获取所有 {len(df)} 个交易对的最新价格，并转换为DataFrame。")
            return df # 返回 DataFrame
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取最新价格", symbol)
    except Exception as e:
        logger.error(f"处理最新价格数据时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取24小时价格变化统计(symbol=None):
    '''获取指定交易对或所有交易对过去24小时价格变化统计。返回单个统计字典或所有统计的DataFrame'''
    if not client:
        logger.error("获取24小时价格变化统计失败：币安客户端未初始化。")
        return None
    try:
        if symbol:
            stats = client.get_ticker(symbol=symbol)
            logger.info(f"成功获取 {symbol} 的24小时统计。")
            # 对单个 symbol，仍返回字典
            return stats
        else:
            stats = client.get_ticker() # 不传 symbol 获取所有
            if not stats:
                 logger.warning("未能获取任何交易对的24小时统计。")
                 return pd.DataFrame()
            df = pd.DataFrame(stats)
            # 转换常见数值列
            numeric_cols = ['priceChange', 'priceChangePercent', 'weightedAvgPrice', 'prevClosePrice', 
                            'lastPrice', 'lastQty', 'bidPrice', 'bidQty', 'askPrice', 'askQty', 
                            'openPrice', 'highPrice', 'lowPrice', 'volume', 'quoteVolume']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col])
            # 转换时间戳
            time_cols = ['openTime', 'closeTime']
            for col in time_cols:
                 if col in df.columns:
                    df[col] = pd.to_datetime(df[col], unit='ms')
            logger.info(f"成功获取所有 {len(df)} 个交易对的24小时统计，并转换为DataFrame。")
            return df
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取24小时价格变化统计", symbol)
    except Exception as e:
        logger.error(f"处理24小时价格变化统计时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取订单簿深度(symbol, limit=100):
    '''获取订单簿深度 (买卖盘)'''
    if not client:
        logger.error("获取订单簿深度失败：币安客户端未初始化。")
        return None
    try:
        depth = client.get_order_book(symbol=symbol, limit=limit)
        # depth 包含 'lastUpdateId', 'bids' (买盘 [[price, qty]]), 'asks' (卖盘 [[price, qty]])
        logger.info(f"成功获取 {symbol} 的订单簿深度 (前 {limit} 档)。")
        return depth
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取订单簿深度", symbol)
    except Exception as e:
        logger.error(f"处理订单簿深度时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取合约订单簿深度(symbol, limit=100):
    """获取 U 本位合约订单簿深度 (买卖盘)"""
    if not client:
        logger.error("获取合约订单簿深度失败：币安客户端未初始化。")
        return None
    try:
        # 注意: python-binance 使用 futures_order_book 获取 U 本位合约深度
        depth = client.futures_order_book(symbol=symbol, limit=limit)
        # depth 结构与现货类似: {'lastUpdateId', 'E', 'T', 'bids': [[price, qty]], 'asks': [[price, qty]]}
        logger.info(f"成功获取合约 {symbol} 的订单簿深度 (前 {limit} 档)。")
        return depth
    except (BinanceAPIException, BinanceRequestException) as e:
        # 特别处理合约不存在的错误
        if e.code == -1121: # Invalid symbol for futures
            logger.warning(f"获取合约订单簿深度失败: 交易对 {symbol} 在合约市场可能不存在或格式错误。")
            return None
        return _handle_api_exception(e, "获取合约订单簿深度", symbol)
    except Exception as e:
        logger.error(f"处理合约订单簿深度时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取近期成交记录(symbol, limit=500):
    '''获取最近的公开成交记录。返回 DataFrame'''
    if not client:
        logger.error("获取近期成交记录失败：币安客户端未初始化。")
        return None
    try:
        trades = client.get_recent_trades(symbol=symbol, limit=limit)
        if not trades:
            logger.warning(f"未能获取 {symbol} 的近期成交记录。")
            return pd.DataFrame()
        df = pd.DataFrame(trades)
        numeric_cols = ['price', 'qty', 'quoteQty']
        for col in numeric_cols:
            if col in df.columns:
                 df[col] = pd.to_numeric(df[col])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        # 可以设置 time 为索引
        # df.set_index('time', inplace=True)
        logger.info(f"成功获取 {symbol} 的最近 {len(df)} 条成交记录，并转换为DataFrame。")
        return df
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取近期成交记录", symbol)
    except Exception as e:
        logger.error(f"处理近期成交记录时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取合约近期成交记录(symbol, limit=500):
    """获取 U 本位合约最近的公开成交记录。返回 DataFrame"""
    if not client:
        logger.error("获取合约近期成交记录失败：币安客户端未初始化。")
        return None
    try:
        # 使用 futures_recent_trades 获取合约成交记录
        trades = client.futures_recent_trades(symbol=symbol, limit=limit)
        if not trades:
            logger.warning(f"未能获取合约 {symbol} 的近期成交记录。")
            return pd.DataFrame()
        df = pd.DataFrame(trades)
        # 注意：合约成交记录的列名和类型可能与现货略有不同，但基础字段通常一致
        numeric_cols = ['price', 'qty', 'quoteQty']
        for col in numeric_cols:
            if col in df.columns:
                 df[col] = pd.to_numeric(df[col], errors='coerce') # 添加 errors='coerce'
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'], unit='ms', errors='coerce') # 添加 errors='coerce'

        # 清理转换失败的数据
        df = df.dropna(subset=numeric_cols + ['time'] if 'time' in df.columns else numeric_cols)

        # isBuyerMaker 字段在合约成交中通常不存在，但 trade_type 需要在分析模块计算
        # 确认 isMaker 字段是否存在（有时合约成交用 isMaker）
        # if 'isMaker' in df.columns and 'isBuyerMaker' not in df.columns:
        #    df.rename(columns={'isMaker': 'isBuyerMaker'}, inplace=True) # 注意 isMaker 和 isBuyerMaker 意义相反

        logger.info(f"成功获取合约 {symbol} 的最近 {len(df)} 条成交记录，并转换为DataFrame。")
        return df
    except (BinanceAPIException, BinanceRequestException) as e:
        # 特别处理合约不存在的错误
        if e.code == -1121: # Invalid symbol for futures
            logger.warning(f"获取合约近期成交记录失败: 交易对 {symbol} 在合约市场可能不存在或格式错误。")
            return None
        return _handle_api_exception(e, "获取合约近期成交记录", symbol)
    except Exception as e:
        logger.error(f"处理合约近期成交记录时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取聚合交易记录(symbol, limit=500):
    '''获取聚合交易记录。返回 DataFrame'''
    if not client:
        logger.error("获取聚合交易记录失败：币安客户端未初始化。")
        return None
    try:
        agg_trades = client.get_aggregate_trades(symbol=symbol, limit=limit)
        if not agg_trades:
            logger.warning(f"未能获取 {symbol} 的聚合交易记录。")
            return pd.DataFrame()
        df = pd.DataFrame(agg_trades)
        # 重命名字段以便理解
        df.rename(columns={'a': 'agg_trade_id', 'p': 'price', 'q': 'quantity', 
                           'f': 'first_trade_id', 'l': 'last_trade_id', 
                           'T': 'timestamp', 'm': 'is_buyer_maker', 'M': 'is_best_match'}, inplace=True)
        numeric_cols = ['price', 'quantity']
        for col in numeric_cols:
            if col in df.columns:
                 df[col] = pd.to_numeric(df[col])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        # df.set_index('timestamp', inplace=True)
        logger.info(f"成功获取 {symbol} 的最近 {len(df)} 条聚合交易记录，并转换为DataFrame。")
        return df
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取聚合交易记录", symbol)
    except Exception as e:
        logger.error(f"处理聚合交易记录时发生未知错误: {e}", exc_info=True)
        return None

# --- 期货/合约市场数据 (公开) ---

@_retry_on_api_error # 应用装饰器
def 获取标记价格(symbol):
    '''获取指定 U 本位合约的标记价格和指数价格。返回包含标记价格信息的字典。'''
    if not client:
        logger.error("获取标记价格失败：币安客户端未初始化。")
        return None
    try:
        # 注意：确保 symbol 是 U 本位合约交易对，例如 "BTCUSDT"
        mark_price_info = client.futures_mark_price(symbol=symbol)
        # 返回列表，通常只有一个元素: {'symbol', 'markPrice', 'indexPrice', 
        #                          'estimatedSettlePrice', 'lastFundingRate', 'nextFundingTime', 
        #                          'interestRate', 'time'}
        if mark_price_info:
            # 如果只需要最新的，可以取列表第一个（通常也是唯一一个）
            # 或者直接返回列表，让调用者处理
            latest_mark_price = mark_price_info[0] if isinstance(mark_price_info, list) else mark_price_info
            logger.info(f"成功获取 {symbol} 标记价格: {latest_mark_price.get('markPrice')}, 指数价格: {latest_mark_price.get('indexPrice')}")
            return latest_mark_price
        else:
            logger.warning(f"未能获取 {symbol} 的标记价格信息。")
            return None
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取标记价格", symbol)
    except Exception as e:
        logger.error(f"处理标记价格时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取资金费率历史(symbol, limit=100):
    '''获取指定 U 本位合约的历史资金费率。返回 DataFrame'''
    if not client:
        logger.error("获取资金费率历史失败：币安客户端未初始化。")
        return None
    try:
        funding_rate_history = client.futures_funding_rate(symbol=symbol, limit=limit)
        if not funding_rate_history:
            logger.warning(f"未能获取 {symbol} 的资金费率历史。")
            return pd.DataFrame()
        df = pd.DataFrame(funding_rate_history)
        numeric_cols = ['fundingRate', 'markPrice']
        for col in numeric_cols:
            if col in df.columns:
                 df[col] = pd.to_numeric(df[col])
        df['fundingTime'] = pd.to_datetime(df['fundingTime'], unit='ms')
        # df.set_index('fundingTime', inplace=True)
        logger.info(f"成功获取 {symbol} 的最近 {len(df)} 条资金费率历史，并转换为DataFrame。")
        return df
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取资金费率历史", symbol)
    except Exception as e:
        logger.error(f"处理资金费率历史时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取当前资金费率与指数(symbol):
    '''获取指定 U 本位合约的当前标记价格、指数价格、预估结算价、最新资金费率、下次资金时间等。返回包含信息的字典。'''
    # 这个接口比 futures_mark_price 返回的信息更全，包含了预测费率相关信息
    if not client:
        logger.error("获取当前资金费率与指数失败：币安客户端未初始化。")
        return None
    try:
        premium_index_info = client.futures_premium_index(symbol=symbol)
        # 返回列表，通常只有一个元素: {'symbol', 'markPrice', 'indexPrice', 
        #                          'estimatedSettlePrice', 'lastFundingRate', 'nextFundingTime', 
        #                          'interestRate', 'time'}
        if premium_index_info:
            latest_info = premium_index_info[0] if isinstance(premium_index_info, list) else premium_index_info
            logger.info(f"成功获取 {symbol} 当前资金/指数信息。下次资金时间: {pd.to_datetime(latest_info.get('nextFundingTime'), unit='ms')}, 预测费率: {latest_info.get('lastFundingRate')}")
            return latest_info
        else:
            logger.warning(f"未能获取 {symbol} 的当前资金/指数信息。")
            return None
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取当前资金费率与指数", symbol)
    except Exception as e:
        logger.error(f"处理当前资金费率与指数时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取持仓量(symbol):
    '''获取指定 U 本位合约的总持仓量。返回包含持仓量信息的字典。'''
    if not client:
        logger.error("获取持仓量失败：币安客户端未初始化。")
        return None
    try:
        open_interest = client.futures_open_interest(symbol=symbol)
        # 返回: {'symbol', 'openInterest', 'time'}
        logger.info(f"成功获取 {symbol} 持仓量: {open_interest.get('openInterest')}")
        return open_interest
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取持仓量", symbol)
    except Exception as e:
        logger.error(f"处理持仓量时发生未知错误: {e}", exc_info=True)
        return None

# --- 账户数据 (需要有效的 API Key 权限) --- 

def 获取账户余额():
    '''获取现货账户余额。返回 DataFrame'''
    if not client:
        logger.error("获取账户余额失败：币安客户端未初始化。")
        return None
    try:
        account_info = client.get_account()
        balances = account_info.get('balances', [])
        if not balances:
             logger.warning("账户余额信息为空。")
             return pd.DataFrame()
        df = pd.DataFrame(balances)
        numeric_cols = ['free', 'locked']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col])
        # 过滤掉余额为0的资产 (可选)
        df_nonzero = df[(df['free'] > 0) | (df['locked'] > 0)].copy()
        logger.info(f"成功获取账户余额，共有 {len(df_nonzero)} 种非零资产，已转换为DataFrame。")
        return df_nonzero # 返回过滤后的 DataFrame
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取账户余额")
    except Exception as e:
        logger.error(f"处理账户余额时发生未知错误: {e}", exc_info=True)
        return None

def 获取合约账户余额():
    '''获取 U 本位合约账户余额。返回 DataFrame'''
    if not client:
        logger.error("获取合约账户余额失败：币安客户端未初始化。")
        return None
    try:
        futures_balances = client.futures_account_balance()
        if not futures_balances:
            logger.warning("合约账户余额信息为空。")
            return pd.DataFrame()
        df = pd.DataFrame(futures_balances)
        numeric_cols = ['balance', 'crossWalletBalance', 'crossUnPnl', 'availableBalance', 'maxWithdrawAmount']
        for col in numeric_cols:
            if col in df.columns:
                 df[col] = pd.to_numeric(df[col])
        if 'updateTime' in df.columns:
            df['updateTime'] = pd.to_datetime(df['updateTime'], unit='ms')
        
        df_nonzero = df[df['balance'].astype(float) != 0].copy()
        logger.info(f"成功获取 U 本位合约账户余额信息 ({len(df_nonzero)} 种非零资产)，并转换为DataFrame。")
        return df_nonzero
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取合约账户余额")
    except Exception as e:
        logger.error(f"处理合约账户余额时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取当前挂单(symbol=None):
    '''获取当前未成交的现货挂单。返回 DataFrame'''
    if not client:
        logger.error("获取当前挂单失败：币安客户端未初始化。")
        return None
    try:
        if symbol:
            open_orders = client.get_open_orders(symbol=symbol)
            count = len(open_orders)
            log_msg = f"成功获取 {symbol} 的 {count} 个当前挂单"
        else:
            open_orders = client.get_open_orders()
            count = len(open_orders)
            log_msg = f"成功获取所有交易对的 {count} 个当前挂单"
        
        if not open_orders:
            logger.info(log_msg + " (无挂单)。")
            return pd.DataFrame()
        
        df = pd.DataFrame(open_orders)
        numeric_cols = ['price', 'origQty', 'executedQty', 'cummulativeQuoteQty', 'stopPrice', 'icebergQty']
        for col in numeric_cols:
             if col in df.columns:
                 df[col] = pd.to_numeric(df[col])
        time_cols = ['time', 'updateTime']
        for col in time_cols:
             if col in df.columns:
                 df[col] = pd.to_datetime(df[col], unit='ms')
        logger.info(log_msg + "，并转换为DataFrame。")
        return df
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取当前挂单", symbol)
    except Exception as e:
        logger.error(f"处理当前挂单时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取合约当前挂单(symbol=None):
    '''获取当前未成交的 U 本位合约挂单。返回 DataFrame'''
    if not client:
        logger.error("获取合约当前挂单失败：币安客户端未初始化。")
        return None
    try:
        if symbol:
            open_orders = client.futures_get_open_orders(symbol=symbol)
            count = len(open_orders)
            log_msg = f"成功获取合约 {symbol} 的 {count} 个当前挂单"
        else:
            open_orders = client.futures_get_open_orders()
            count = len(open_orders)
            log_msg = f"成功获取所有合约交易对的 {count} 个当前挂单"
        
        if not open_orders:
            logger.info(log_msg + " (无挂单)。")
            return pd.DataFrame()
        
        df = pd.DataFrame(open_orders)
        numeric_cols = ['price', 'origQty', 'executedQty', 'cumQuote', 'avgPrice', 'stopPrice', 'activatePrice', 'priceRate']
        for col in numeric_cols:
            if col in df.columns:
                 df[col] = pd.to_numeric(df[col])
        time_cols = ['time', 'updateTime']
        for col in time_cols:
            if col in df.columns:
                 df[col] = pd.to_datetime(df[col], unit='ms')
        logger.info(log_msg + "，并转换为DataFrame。")
        return df
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取合约当前挂单", symbol)
    except Exception as e:
        logger.error(f"处理合约当前挂单时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取现货所有订单历史(symbol, limit=500):
    '''获取指定现货交易对的所有订单历史。返回 DataFrame'''
    if not client:
        logger.error("获取现货所有订单历史失败：币安客户端未初始化。")
        return None
    try:
        all_orders = client.get_all_orders(symbol=symbol, limit=limit)
        if not all_orders:
            logger.warning(f"未能获取 {symbol} 的订单历史。")
            return pd.DataFrame()
        df = pd.DataFrame(all_orders)
        numeric_cols = ['price', 'origQty', 'executedQty', 'cummulativeQuoteQty', 'stopPrice', 'icebergQty']
        for col in numeric_cols:
             if col in df.columns:
                 df[col] = pd.to_numeric(df[col])
        time_cols = ['time', 'updateTime']
        for col in time_cols:
             if col in df.columns:
                 df[col] = pd.to_datetime(df[col], unit='ms')
        logger.info(f"成功获取 {symbol} 的最近 {len(df)} 条订单历史，并转换为DataFrame。")
        return df
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取现货所有订单历史", symbol)
    except Exception as e:
        logger.error(f"处理现货所有订单历史时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取合约所有订单历史(symbol, limit=500):
    '''获取指定 U 本位合约的所有订单历史。返回 DataFrame'''
    if not client:
        logger.error("获取合约所有订单历史失败：币安客户端未初始化。")
        return None
    try:
        all_orders = client.futures_get_all_orders(symbol=symbol, limit=limit)
        if not all_orders:
            logger.warning(f"未能获取合约 {symbol} 的订单历史。")
            return pd.DataFrame()
        df = pd.DataFrame(all_orders)
        numeric_cols = ['price', 'origQty', 'executedQty', 'cumQuote', 'avgPrice', 'stopPrice', 'activatePrice', 'priceRate']
        for col in numeric_cols:
            if col in df.columns:
                 df[col] = pd.to_numeric(df[col])
        time_cols = ['time', 'updateTime']
        for col in time_cols:
            if col in df.columns:
                 df[col] = pd.to_datetime(df[col], unit='ms')
        logger.info(f"成功获取合约 {symbol} 的最近 {len(df)} 条订单历史，并转换为DataFrame。")
        return df
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取合约所有订单历史", symbol)
    except Exception as e:
        logger.error(f"处理合约所有订单历史时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取成交历史(symbol, limit=500):
    '''获取指定现货交易对的账户成交历史。返回 DataFrame'''
    if not client:
        logger.error("获取成交历史失败：币安客户端未初始化。")
        return None
    try:
        my_trades = client.get_my_trades(symbol=symbol, limit=limit)
        if not my_trades:
            logger.warning(f"未能获取 {symbol} 的成交历史。")
            return pd.DataFrame()
        df = pd.DataFrame(my_trades)
        numeric_cols = ['price', 'qty', 'quoteQty', 'commission']
        for col in numeric_cols:
            if col in df.columns:
                 df[col] = pd.to_numeric(df[col])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        # df.set_index('time', inplace=True)
        logger.info(f"成功获取 {symbol} 的最近 {len(df)} 条成交历史，并转换为DataFrame。")
        return df
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取成交历史", symbol)
    except Exception as e:
        logger.error(f"处理成交历史时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取合约成交历史(symbol, limit=500):
    '''获取指定 U 本位合约的账户成交历史。返回 DataFrame'''
    if not client:
        logger.error("获取合约成交历史失败：币安客户端未初始化。")
        return None
    try:
        my_trades = client.futures_account_trades(symbol=symbol, limit=limit)
        if not my_trades:
             logger.warning(f"未能获取合约 {symbol} 的成交历史。")
             return pd.DataFrame()
        df = pd.DataFrame(my_trades)
        numeric_cols = ['price', 'qty', 'quoteQty', 'realizedPnl', 'commission']
        for col in numeric_cols:
            if col in df.columns:
                 df[col] = pd.to_numeric(df[col])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        # df.set_index('time', inplace=True)
        logger.info(f"成功获取合约 {symbol} 的最近 {len(df)} 条成交历史，并转换为DataFrame。")
        return df
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取合约成交历史", symbol)
    except Exception as e:
        logger.error(f"处理合约成交历史时发生未知错误: {e}", exc_info=True)
        return None

# --- 交易所信息 --- 

def 获取交易所信息():
    '''获取交易所的交易规则和交易对信息 (使用缓存)'''
    global _exchange_info_cache
    if _exchange_info_cache is not None:
        logger.info("从缓存获取交易所信息。")
        return _exchange_info_cache
        
    if not client:
        logger.error("获取交易所信息失败：币安客户端未初始化。")
        return None
    try:
        logger.info("正在从 API 获取交易所信息...")
        exchange_info = client.get_exchange_info()
        logger.info(f"成功获取交易所信息，包含 {len(exchange_info.get('symbols', []))} 个交易对规则。")
        _exchange_info_cache = exchange_info # 缓存结果
        logger.info("交易所信息已缓存。")
        return exchange_info
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取交易所信息")
    except Exception as e:
        logger.error(f"处理交易所信息时发生未知错误: {e}", exc_info=True)
        return None

# 可选：提供一个函数来强制刷新缓存
def 刷新交易所信息缓存():
    '''清除交易所信息缓存，下次调用将重新从API获取'''
    global _exchange_info_cache
    _exchange_info_cache = None
    logger.info("交易所信息缓存已清除。")

@_retry_on_api_error # 应用装饰器
def 获取服务器时间():
    '''获取币安服务器时间'''
    if not client:
        logger.error("获取服务器时间失败：币安客户端未初始化。")
        return None
    try:
        time_res = client.get_server_time()
        server_time_ms = time_res['serverTime']
        logger.info(f"币安服务器时间戳: {server_time_ms} (毫秒)")
        return server_time_ms
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取服务器时间")
    except Exception as e:
        logger.error(f"处理服务器时间时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 应用装饰器
def 获取系统状态():
    '''获取币安系统维护状态'''
    # 注意：此接口在 python-binance 中可能需要通过 client.get_system_status() 调用
    # 或者直接请求 /sapi/v1/system/status
    if not client:
        logger.error("获取系统状态失败：币安客户端未初始化。")
        return None
    try:
        status = client.get_system_status()
        # 返回: {'status': 0/1, 'msg': 'normal'/'system maintenance'}
        status_code = status.get('status')
        status_msg = status.get('msg')
        if status_code == 0:
            logger.info(f"系统状态正常: {status_msg}")
        else:
            logger.warning(f"警告：系统正在维护! 状态码: {status_code}, 消息: {status_msg}")
        return status
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "获取系统状态")
    except Exception as e:
        logger.error(f"处理系统状态时发生未知错误: {e}", exc_info=True)
        return None

# --- 下单/撤单等交易操作 (需要交易权限的 API Key) ---

def 创建订单(symbol, side, type, quantity=None, price=None, timeInForce=None, quoteOrderQty=None):
    '''创建一个新的交易订单 (需要交易权限)'''
    if not client:
        logger.error("创建订单失败：币安客户端未初始化。")
        return None
    if not 配置.ENABLE_REAL_TRADING:
        logger.info(f"模拟下单：{side} {quantity or quoteOrderQty} {symbol} @ {price or '市价'} (类型: {type})")
        # 可以返回一个模拟的订单信息结构
        return {'symbol': symbol, 'orderId': f'simulated_{int(time.time())}', 'status': 'FILLED', 'side': side, 'type': type, 'price': price or 'N/A', 'origQty': quantity or 'N/A', 'executedQty': quantity or 'N/A', 'cummulativeQuoteQty': quoteOrderQty or 'N/A', 'isSimulated': True}
        
    logger.info(f"准备创建真实订单：{side} {quantity or quoteOrderQty} {symbol} @ {price or '市价'} (类型: {type})")
    # 构建订单参数字典
    order_params = {
        'symbol': symbol,
        'side': side, # 'BUY' or 'SELL'
        'type': type, # 'LIMIT', 'MARKET', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT' 等
    }
    if quantity is not None:
        order_params['quantity'] = quantity
    if price is not None:
        order_params['price'] = price
    if timeInForce is not None: # 对于 LIMIT 订单通常需要, 如 'GTC' (Good 'Til Canceled)
        order_params['timeInForce'] = timeInForce
    if quoteOrderQty is not None: # 市价单买入时用 quoteOrderQty 指定花费多少计价货币
        order_params['quoteOrderQty'] = quoteOrderQty
        
    try:
        # !!! 警告：这将执行真实交易 !!!
        order = client.create_order(**order_params)
        logger.info(f"成功创建订单: {order}")
        return order
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "创建订单", symbol)
    except Exception as e:
        logger.error(f"处理订单创建时发生未知错误: {e}", exc_info=True)
        return None

@_retry_on_api_error # 查询订单可以添加重试
def 查询订单(symbol, orderId):
    '''查询特定订单的状态'''
    if not client:
        logger.error("查询订单失败：币安客户端未初始化。")
        return None
    try:
        order_status = client.get_order(symbol=symbol, orderId=orderId)
        logger.info(f"成功查询订单 {orderId} ({symbol}): 状态 {order_status.get('status')}")
        return order_status
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "查询订单", symbol)
    except Exception as e:
        logger.error(f"处理查询订单时发生未知错误: {e}", exc_info=True)
        return None

def 取消订单(symbol, orderId):
    '''取消一个未成交的订单'''
    if not client:
        logger.error("取消订单失败：币安客户端未初始化。")
        return None
    if not 配置.ENABLE_REAL_TRADING:
        logger.info(f"模拟撤单：订单ID {orderId} ({symbol})")
        # 可以返回一个模拟的撤单信息
        return {'symbol': symbol, 'orderId': orderId, 'status': 'CANCELED', 'isSimulated': True}

    logger.info(f"准备取消真实订单：订单ID {orderId} ({symbol})")
    try:
        # !!! 警告：这将执行真实撤单 !!!
        result = client.cancel_order(symbol=symbol, orderId=orderId)
        logger.info(f"成功取消订单 {orderId} ({symbol}): {result}")
        return result
    except (BinanceAPIException, BinanceRequestException) as e:
        return _handle_api_exception(e, "取消订单", symbol)
    except Exception as e:
        logger.error(f"处理订单取消时发生未知错误: {e}", exc_info=True)
        return None

# --- 大单识别 (基于历史聚合交易) ---

@_retry_on_api_error # 应用装饰器，因为内部调用了 API 函数
def 识别大单交易(symbol, lookback_limit=1000, threshold_method='percentile', percentile=95, avg_multiplier=10, min_quote_value=None):
    """分析近期聚合交易，识别成交额较大的'大单'。

    Args:
        symbol (str): 交易对。
        lookback_limit (int, optional): 回溯的聚合交易记录数量。 Defaults to 1000。
        threshold_method (str, optional): 计算大单阈值的方法。
            'percentile': 基于成交额的百分位数 (由 percentile 参数指定)。
            'multiple_avg': 基于平均成交额的倍数 (由 avg_multiplier 参数指定)。
            'fixed_quote': 使用固定的成交额 (由 min_quote_value 参数指定)。
            Defaults to 'percentile'.
        percentile (int, optional): 当 method='percentile' 时使用的百分位 (0-100)。 Defaults to 95.
        avg_multiplier (int | float, optional): 当 method='multiple_avg' 时使用的倍数。 Defaults to 10.
        min_quote_value (int | float, optional): 当 method='fixed_quote' 时使用的最小成交额。 Defaults to None.

    Returns:
        pd.DataFrame or None: 包含识别出的大单交易信息的 DataFrame，包含原始交易信息及计算出的 'quote_volume' 和 'threshold' 列。
                              如果获取数据失败、数据不足或未识别到大单，则返回 None 或空 DataFrame。
    """
    logger.info(f"开始识别 {symbol} 的大单交易 (回溯 {lookback_limit} 条, 方法: {threshold_method}) ...")
    
    # 1. 获取聚合交易数据 (注意: 获取聚合交易记录 已被装饰器包裹)
    # agg_trades_df = 获取聚合交易记录(symbol, limit=lookback_limit)
    # 直接调用，让装饰器处理重试和基本异常
    # 需要注意 获取聚合交易记录 返回的是 DataFrame
    agg_trades_df = 获取聚合交易记录(symbol, limit=lookback_limit) 

    if agg_trades_df is None or agg_trades_df.empty:
        logger.warning(f"未能获取或 {symbol} 近期无聚合交易记录，无法识别大单。")
        return None

    # 确保有足够的列进行计算
    if not all(col in agg_trades_df.columns for col in ['price', 'quantity']):
         logger.error(f"获取到的聚合交易数据缺少 'price' 或 'quantity' 列。")
         return None
         
    # 2. 计算成交金额 (quote_volume)
    try:
        # 确保 price 和 quantity 是数值类型
        agg_trades_df['price'] = pd.to_numeric(agg_trades_df['price'])
        agg_trades_df['quantity'] = pd.to_numeric(agg_trades_df['quantity'])
        agg_trades_df['quote_volume'] = agg_trades_df['price'] * agg_trades_df['quantity']
    except Exception as e:
        logger.error(f"计算成交金额时出错: {e}", exc_info=True)
        return None

    # 3. 计算阈值
    threshold = None
    if threshold_method == 'percentile':
        if not agg_trades_df['quote_volume'].empty:
            try:
                threshold = np.percentile(agg_trades_df['quote_volume'], percentile)
                logger.info(f"计算得到阈值 ({percentile}百分位): {threshold:.4f}")
            except Exception as e:
                 logger.error(f"计算百分位阈值时出错: {e}", exc_info=True)
                 return None
        else:
             logger.warning("成交金额数据为空，无法计算百分位阈值。")
             return None
    elif threshold_method == 'multiple_avg':
        if not agg_trades_df['quote_volume'].empty:
            try:
                avg_quote_volume = agg_trades_df['quote_volume'].mean()
                threshold = avg_quote_volume * avg_multiplier
                logger.info(f"计算得到阈值 (平均值 {avg_quote_volume:.4f} * {avg_multiplier}): {threshold:.4f}")
            except Exception as e:
                logger.error(f"计算平均值倍数阈值时出错: {e}", exc_info=True)
                return None
        else:
             logger.warning("成交金额数据为空，无法计算平均值倍数阈值。")
             return None
    elif threshold_method == 'fixed_quote':
        if min_quote_value is not None and min_quote_value > 0:
            threshold = float(min_quote_value)
            logger.info(f"使用固定阈值: {threshold:.4f}")
        else:
            logger.error("方法为 'fixed_quote'，但未提供有效 'min_quote_value'。")
            return None
    else:
        logger.error(f"未知的大单阈值计算方法: {threshold_method}")
        return None

    if threshold is None:
        logger.error("未能成功计算大单阈值。")
        return None

    # 4. 筛选大单
    large_trades_df = agg_trades_df[agg_trades_df['quote_volume'] >= threshold].copy()
    
    if large_trades_df.empty:
        logger.info(f"在最近 {lookback_limit} 条记录中未发现成交额 >= {threshold:.4f} 的大单。")
        return pd.DataFrame() # 返回空 DataFrame
    else:
        large_trades_df['threshold'] = threshold # 添加阈值列
        logger.info(f"识别到 {len(large_trades_df)} 笔大单交易 (成交额 >= {threshold:.4f})。")
        return large_trades_df

# --- 主函数 (用于测试模块功能) ---
if __name__ == '__main__':
    logger.info("\n--- 开始测试数据获取模块 ---")
    
    # 在开始执行任何操作前，先检查客户端是否有效
    if not client:
        logger.critical("币安客户端未成功初始化，无法执行测试。程序将退出。")
        import sys
        sys.exit(1) # 退出程序，因为后续操作都依赖 client

    # 示例：获取 BTCUSDT 的 K 线数据
    logger.info("测试: 获取 BTCUSDT 现货 1小时 K线...")
    btc_klines = 获取K线数据("BTCUSDT", interval="1h", limit=10)
    if btc_klines is not None:
        logger.info("成功: 获取到 BTC K 线数据。")
        logger.debug("BTC K 线数据 (前5条):\n%s", btc_klines.head().to_string())
    else:
         logger.warning("失败: 未能获取 BTC K 线数据。")
    logger.info("-" * 20)

    # 示例：获取 ETHUSDT 最新价格
    logger.info("测试: 获取 ETHUSDT 最新价格...")
    eth_price = 获取最新价格("ETHUSDT")
    if eth_price:
        logger.info(f"成功: ETHUSDT 最新价格: {eth_price['price']}")
        logger.debug("ETH 价格 Ticker 详情: %s", eth_price)
    else:
        logger.warning("失败: 未能获取 ETH 最新价格。")
    logger.info("-" * 20)
    
    # 测试获取账户余额 (返回 DataFrame)
    logger.info("测试: 获取账户余额 (DataFrame)...")
    balances_df = 获取账户余额()
    if balances_df is not None and not balances_df.empty:
        logger.info(f"成功: 获取到 {len(balances_df)} 种非零现货资产。")
        logger.debug("账户余额 (部分):\n%s", balances_df.head().to_string())
    elif balances_df is not None: # 空 DataFrame
         logger.info("成功: 账户中无非零资产。")
    else: # 获取失败返回 None
        logger.warning("失败: 未能获取账户余额。")
    logger.info("-" * 20)

    # 测试获取合约账户余额 (返回 DataFrame)
    logger.info("测试: 获取合约账户余额 (DataFrame)...")
    futures_balances_df = 获取合约账户余额()
    if futures_balances_df is not None and not futures_balances_df.empty:
        logger.info(f"成功: 获取到 {len(futures_balances_df)} 种非零合约资产。")
        logger.debug("合约账户余额 (部分):\n%s", futures_balances_df.head().to_string())
    elif futures_balances_df is not None:
         logger.info("成功: 合约账户中无非零资产。")
    else:
        logger.warning("失败: 未能获取合约账户余额。")
    logger.info("-" * 20)

    # 测试获取合约订单历史 (返回 DataFrame)
    logger.info("测试: 获取 ETHUSDT 合约订单历史 (DataFrame)...")
    futures_orders_df = 获取合约所有订单历史("ETHUSDT", limit=10)
    if futures_orders_df is not None and not futures_orders_df.empty:
        logger.info(f"成功: 获取到 {len(futures_orders_df)} 条合约订单历史。")
        logger.debug("合约订单历史 (部分):\n%s", futures_orders_df.head().to_string())
    elif futures_orders_df is not None:
         logger.info("成功: 无合约订单历史。")
    else:
        logger.warning("失败: 未能获取合约订单历史。")
    logger.info("-" * 20)

    # 新增测试：获取 ETHUSDT 现货 5分钟 K线
    logger.info("测试: 获取 ETHUSDT 现货 5分钟 K线...")
    eth_klines_5m = 获取K线数据("ETHUSDT", interval="5m", limit=5)
    if eth_klines_5m is not None:
        logger.info("成功: 获取到 ETH 5m K线数据。")
        logger.debug("ETH 5m K线 (前5条):\n%s", eth_klines_5m.head().to_string())
    else:
        logger.warning("失败: 未能获取 ETH 5m K线。")
    logger.info("-" * 20)

    # 新增测试：获取 BTCUSDT 合约 K线 (使用与现货相同的 symbol 格式)
    logger.info("测试: 获取 BTCUSDT 合约 1小时 K线...")
    # 注意：`获取K线数据` 函数内部使用 client.get_klines，对于合约交易对，
    # python-binance 会尝试自动路由到 futures klines 接口，但这可能不稳定或取决于库版本。
    # 如果此调用失败，可能需要显式调用 client.futures_klines。
    btc_futures_klines = 获取K线数据("BTCUSDT", interval="1h", limit=5)
    if btc_futures_klines is not None:
        logger.info("成功: 获取到 BTC 合约 1h K线数据。")
        logger.debug("BTC 合约 1h K线 (前5条):\n%s", btc_futures_klines.head().to_string())
    else:
        logger.warning("失败: 未能获取 BTC 合约 K线。")
    logger.info("-" * 20)

    # 新增测试：获取 BTCUSDT 现货订单簿深度
    logger.info("测试: 获取 BTCUSDT 现货订单簿深度...")
    btc_order_book = 获取订单簿深度("BTCUSDT", limit=5) # 获取前5档
    if btc_order_book:
        logger.info("成功: 获取到 BTC 订单簿深度。")
        logger.debug("BTC 订单簿买盘 (Bids): %s", btc_order_book.get('bids'))
        logger.debug("BTC 订单簿卖盘 (Asks): %s", btc_order_book.get('asks'))
    else:
        logger.warning("失败: 未能获取 BTC 订单簿深度。")
    logger.info("-" * 20)

    # 新增测试：按时间范围获取K线数据 (例如，获取昨天 1h K线)
    logger.info("测试: 按时间范围获取 BTCUSDT 现货 1h K线...")
    try:
        yesterday = pd.Timestamp.now().normalize() - pd.Timedelta(days=1)
        start_dt_str = yesterday.strftime('%Y-%m-%d 00:00:00')
        end_dt_str = yesterday.strftime('%Y-%m-%d 23:59:59')
        logger.debug(f"计算的时间范围: {start_dt_str} 到 {end_dt_str}")
        
        btc_klines_range = 获取K线数据("BTCUSDT", interval="1h", start_time=start_dt_str, end_time=end_dt_str)
        
        if btc_klines_range is not None and not btc_klines_range.empty:
            logger.info(f"成功: 获取到时间范围内的 BTC 1h K线数据 ({len(btc_klines_range)} 条)。")
            logger.debug(f"第一条时间: {btc_klines_range.index[0]}, 最后一条时间: {btc_klines_range.index[-1]}")
            logger.debug("时间范围 K线 (部分):\n%s", btc_klines_range.head().to_string())
        elif btc_klines_range is not None: # 空 DataFrame
            logger.info("成功: 指定时间范围内无 K 线数据。")
        else:
            logger.warning("失败: 按时间范围获取 BTC K 线数据。")
    except Exception as e:
        logger.error(f"测试按时间范围获取K线时发生错误: {e}", exc_info=True)
    logger.info("-" * 20)

    # 新增测试：识别大单交易
    logger.info("测试: 识别 BTCUSDT 大单交易 (默认百分位法)...")
    btc_large_trades = 识别大单交易("BTCUSDT", lookback_limit=500, percentile=98) # 使用 98 百分位
    if btc_large_trades is not None and not btc_large_trades.empty:
        logger.info(f"成功识别到 {len(btc_large_trades)} 笔 BTC 大单。")
        # 打印识别到的大单的部分信息 (成交时间、价格、数量、成交额、阈值、买方是maker)
        logger.debug("识别到的大单 (部分):\n%s", 
                     btc_large_trades[['timestamp', 'price', 'quantity', 'quote_volume', 'threshold', 'is_buyer_maker']].head().to_string())
    elif btc_large_trades is not None: # 返回空 DataFrame
         logger.info("在回溯范围内未发现符合条件的大单。")
    else:
        logger.warning("识别 BTC 大单失败。")
    logger.info("-" * 20)

    logger.info("测试: 识别 ETHUSDT 大单交易 (固定金额法)...")
    eth_large_trades = 识别大单交易("ETHUSDT", lookback_limit=500, threshold_method='fixed_quote', min_quote_value=50000) # 假设大于 50k USDT 算大单
    if eth_large_trades is not None and not eth_large_trades.empty:
        logger.info(f"成功识别到 {len(eth_large_trades)} 笔 ETH 大单 (成交额 >= 50000)。")
        logger.debug("识别到的大单 (部分):\n%s", 
                     eth_large_trades[['timestamp', 'price', 'quantity', 'quote_volume', 'threshold', 'is_buyer_maker']].head().to_string())
    elif eth_large_trades is not None:
         logger.info("在回溯范围内未发现符合条件的大单。")
    else:
        logger.warning("识别 ETH 大单失败。")
    logger.info("-" * 20)

    logger.info("\n--- 数据获取模块测试结束 ---") 