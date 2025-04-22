#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
后台成交流分析器

定期获取热门交易对，执行成交流分析，并将结果保存到 JSON 文件，
供前端网页应用读取。
"""

import logging
import time
import json
import os
import schedule
import traceback
from datetime import datetime
from binance.client import Client
from binance.exceptions import BinanceAPIException
import numpy as np

# 导入自定义模块
try:
    import 配置
    import 数据获取模块 # 虽然不直接用获取函数，但可能需要其 Client 或错误处理
    import 成交流分析 # 导入主分析模块
    MODULE_LOAD_ERROR = None
except ImportError as e:
    MODULE_LOAD_ERROR = e
    print(f"[ERROR] 核心自定义模块加载失败: {e}。请确保所需 .py 文件存在且无误。脚本退出。")
    exit(1)

# --- 全局常量 ---
RESULT_FILE = 'auto_volume_analysis_results.json' # 结果输出文件
TOP_N_SYMBOLS = getattr(配置, 'TOP_N_SYMBOLS', 20) # 从配置读取，默认为 20
INTERVAL_MINUTES = getattr(配置, 'AUTO_ANALYSIS_INTERVAL_MINUTES', 5) # 从配置读取，默认为 5
MARKET_TYPE = getattr(配置, 'AUTO_ANALYSIS_MARKET_TYPE', 'futures') # 默认为 U 本位合约
RETRY_DELAY_SECONDS = getattr(配置, 'RETRY_DELAY_SECONDS', 60) # API 失败重试延迟
MAX_RETRIES = getattr(配置, 'MAX_RETRIES', 3) # 最大重试次数

# --- 日志配置 (与网页应用类似，但可独立配置) ---
log_file_path = os.path.join(os.path.dirname(__file__), 'logs', 'background_volume_analyzer.log')
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
logger = logging.getLogger("后台成交流分析器")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    # 控制台输出
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO) # 控制台级别可设为 INFO
    logger.addHandler(stream_handler)
    # 文件输出
    file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG) # 文件记录 DEBUG 级别
    logger.addHandler(file_handler)
    logger.propagate = False
logger.info(f"后台成交流分析器启动，日志初始化完成。分析间隔: {INTERVAL_MINUTES} 分钟，目标数量: {TOP_N_SYMBOLS}，市场: {MARKET_TYPE}")

# --- 初始化币安客户端 ---
binance_client = None
try:
    api_key = 配置.BINANCE_API_KEY
    api_secret = 配置.BINANCE_API_SECRET
    if api_key == "YOUR_API_KEY_PLACEHOLDER" or api_secret == "YOUR_API_SECRET_PLACEHOLDER" or not api_key or not api_secret:
        logger.error("API 密钥未正确配置或为空。脚本退出。")
        exit(1)

    use_proxy_env = os.getenv('USE_PROXY', 'false').lower() == 'true'
    use_proxy_config = getattr(配置, 'USE_PROXY', False)
    use_proxy = use_proxy_env or use_proxy_config

    proxy_url_env = os.getenv('PROXY_URL', None)
    proxy_url_config = getattr(配置, 'PROXY_URL', None)
    proxy_url = proxy_url_env if proxy_url_env else proxy_url_config

    proxies = {'http': proxy_url, 'https': proxy_url} if use_proxy and proxy_url else None
    requests_params = {'proxies': proxies} if proxies else None

    if use_proxy and not proxy_url:
        logger.warning("配置为使用代理，但未提供代理 URL。")
    elif use_proxy:
        logger.info(f"使用代理服务器: {proxy_url}")

    binance_client = Client(api_key=api_key, api_secret=api_secret, requests_params=requests_params)
    binance_client.ping()
    server_time = binance_client.get_server_time()
    logger.info(f"成功连接到币安服务器，服务器时间: {datetime.fromtimestamp(server_time['serverTime']/1000)}")

except AttributeError as e:
    logger.error(f"配置模块 '配置.py' 中缺少必要的配置项: {e}。脚本退出。", exc_info=True)
    exit(1)
except BinanceAPIException as e:
    logger.error(f"连接币安 API 失败: {e}。脚本退出。", exc_info=True)
    exit(1)
except Exception as e:
    logger.error(f"初始化币安客户端时发生未知错误: {e}。脚本退出。", exc_info=True)
    exit(1)

# --- 辅助函数：获取热门币种 ---
def get_top_symbols(client, market_type='futures', top_n=20):
    """获取指定市场按24小时交易额排序的Top N交易对。"""
    logger.info(f"开始获取 {market_type} 市场 Top {top_n} 交易对...")
    for attempt in range(MAX_RETRIES):
        try:
            if market_type == 'futures':
                tickers = client.futures_ticker() # U本位合约
            elif market_type == 'spot':
                tickers = client.get_ticker() # 现货
            else:
                logger.error(f"不支持的市场类型: {market_type}")
                return []

            # 筛选USDT交易对 (或 BUSD, TUSD 等稳定币对，根据需要调整)
            # 并确保 'quoteVolume' 和 'symbol' 存在
            valid_tickers = [
                t for t in tickers
                if isinstance(t, dict) and
                   'symbol' in t and t['symbol'].endswith('USDT') and
                   'quoteVolume' in t
            ]

            # 尝试将 quoteVolume 转换为浮点数，处理可能的错误
            def safe_float(v):
                try:
                    return float(v)
                except (ValueError, TypeError):
                    return 0.0 # 转换失败的交易量视为 0

            # 按交易额降序排序
            sorted_tickers = sorted(valid_tickers, key=lambda x: safe_float(x.get('quoteVolume', 0)), reverse=True)

            top_symbols = [t['symbol'] for t in sorted_tickers[:top_n]]
            logger.info(f"成功获取 Top {len(top_symbols)} 交易对: {top_symbols}")
            return top_symbols

        except BinanceAPIException as e:
            logger.warning(f"获取 Tickers 失败 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                logger.info(f"{RETRY_DELAY_SECONDS} 秒后重试...")
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                logger.error("获取 Tickers 达到最大重试次数，本次分析跳过获取热门币种。")
                return [] # 返回空列表
        except Exception as e:
            logger.error(f"获取 Tickers 时发生未知错误: {e}", exc_info=True)
            return [] # 返回空列表
    return [] # 所有重试失败后返回空列表

# --- 主要分析任务 ---
def run_analysis_job():
    """执行一次完整的自动分析流程。"""
    start_time = time.time()
    logger.info(f"===== 开始执行自动成交流分析任务 (Market: {MARKET_TYPE}) =====")

    top_symbols = get_top_symbols(binance_client, market_type=MARKET_TYPE, top_n=TOP_N_SYMBOLS)
    if not top_symbols:
        logger.warning("未能获取到热门交易对，本次分析任务中止。")
        return

    results = {}
    for i, symbol in enumerate(top_symbols):
        logger.info(f"[{i + 1}/{len(top_symbols)}] 开始分析交易对: {symbol}")
        try:
            # 调用成交流分析模块的主函数
            # 假设它返回一个包含分析结果或错误的字典
            # 我们使用默认参数，如果需要特定参数（如 limit），在这里传递
            analysis_result = 成交流分析.分析成交流(
                symbol=symbol,
                market_type=MARKET_TYPE
                # limit=1000, # 例如，如果需要指定 limit
                # time_windows_seconds=[60, 300, 900] # 例如，如果需要指定时间窗口
            )
            results[symbol] = analysis_result
            logger.debug(f"完成分析: {symbol}，结果键: {list(analysis_result.keys()) if isinstance(analysis_result, dict) else '非字典结果'}")

        except AttributeError as e:
            err_msg = f"分析失败: {symbol} - 无法找到 '成交流分析.分析成交流' 函数。请检查模块。"
            logger.error(err_msg, exc_info=True)
            results[symbol] = {'error': err_msg, 'traceback': traceback.format_exc()}
            # 如果是关键函数缺失，可能后续都会失败，可以选择中断
            # logger.critical("关键分析函数缺失，中止本次任务。")
            # break 
        except BinanceAPIException as e:
            err_msg = f"分析失败: {symbol} - 币安 API 错误: {e}"
            logger.error(err_msg)
            results[symbol] = {'error': err_msg, 'traceback': traceback.format_exc()}
            # 可以考虑短暂休眠后继续分析其他币种
            # time.sleep(5)
        except Exception as e:
            err_msg = f"分析失败: {symbol} - 未知错误: {type(e).__name__} - {e}"
            logger.error(err_msg, exc_info=True)
            results[symbol] = {'error': err_msg, 'traceback': traceback.format_exc()}
        # 短暂间隔，避免过于频繁的 API 请求 (如果分析函数内部没有处理)
        # time.sleep(1)

    # --- 保存结果到 JSON 文件 ---
    try:
        # 使用 ensure_ascii=False 以正确保存中文字符
        # 使用 indent=4 以获得格式化的 JSON 输出，便于阅读
        # 处理无法直接 JSON 序列化的对象 (如 Timestamp, numpy types)
        def default_serializer(obj):
            if isinstance(obj, datetime):
                return obj.isoformat() # 将 datetime 对象转为 ISO 格式字符串
            # --- 新增：处理 NumPy 数字类型 ---
            elif isinstance(obj, (np.int_, np.intc, np.intp, np.int8, np.int16, np.int32, np.int64, np.uint8, np.uint16, np.uint32, np.uint64)):
                return int(obj) # 将 NumPy 整数转为 Python int
            elif isinstance(obj, (np.float_, np.float16, np.float32, np.float64)):
                # 可以选择转为 float 或 str，转 float 更常用
                # 注意：如果需要精确的小数位数，可能需要更复杂的处理或转为 str
                return float(obj) # 将 NumPy 浮点数转为 Python float
            elif isinstance(obj, (np.ndarray,)):
                return obj.tolist() # 将 NumPy 数组转为 Python list
            elif isinstance(obj, (np.bool_)):
                 return bool(obj) # 将 NumPy 布尔值转为 Python bool
            elif isinstance(obj, (np.void)):
                 return None # 处理 np.void 类型，例如 pd.NaT
            # --- NumPy 处理结束 ---
            # 可以继续添加对其他类型的处理，例如 Decimal 等
            
            # 如果以上都不是，则尝试默认行为或抛出错误
            try:
                # 尝试调用默认的 JSON 编码器看能否处理
                # 注意：这行可能不是必须的，取决于 json 库的行为
                # json.JSONEncoder().encode(obj) # 这行只是测试，不返回值
                # return obj # 如果上面测试通过，可以直接返回 obj ? (不确定) 
                # 最佳实践是明确处理已知类型，对未知类型抛出错误
                pass # 暂时跳过默认处理尝试
            except TypeError:
                 pass # 如果默认也处理不了，则执行下面的 raise
                 
            raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable and not handled by custom serializer")

        # 在 json.dump 中使用自定义的序列化函数
        with open(RESULT_FILE, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=4, default=default_serializer)
        logger.info(f"分析结果已成功保存到文件: {RESULT_FILE}")
    except TypeError as e:
        logger.error(f"保存结果到 JSON 时发生序列化错误: {e}")
        # 错误信息现在会更明确是哪个类型无法处理
        # logger.error("请检查分析函数返回的数据类型是否包含无法序列化的对象 (例如 Timestamp、Decimal 等)。")
    except Exception as e:
        logger.error(f"保存结果到 JSON 文件时发生错误: {e}", exc_info=True)

    end_time = time.time()
    logger.info(f"===== 自动成交流分析任务完成，耗时: {end_time - start_time:.2f} 秒 =====")

# --- 调度任务 ---
logger.info(f"设置任务调度：每 {INTERVAL_MINUTES} 分钟运行一次分析。")
schedule.every(INTERVAL_MINUTES).minutes.do(run_analysis_job)

# --- 立即执行一次 --- 
logger.info("首次运行：立即执行一次分析任务...")
run_analysis_job()
logger.info("首次运行完成。等待下一次调度...")

# --- 运行调度器 --- 
while True:
    schedule.run_pending()
    time.sleep(1) 