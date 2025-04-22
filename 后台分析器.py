# -*- coding: utf-8 -*-
"""
后台独立分析脚本

定期分析主流币种并将结果保存到 JSON 文件，供网页应用读取。
"""
import time
import json
import os
import logging
import traceback
from threading import Lock
import pandas as pd
import operator # 用于排序

# --- 导入依赖 ---
print("--- 后台分析器：脚本开始 ---")
try:
    print("--- 后台分析器：准备导入 k线分析模块 ---")
    import k线分析模块
    print("--- 后台分析器：导入 k线分析模块 成功 ---")
except ImportError as e:
    print(f"!!! 后台分析器：导入 k线分析模块 失败: {e} !!!")
    k线分析模块 = None
except Exception as e:
    print(f"!!! 后台分析器：导入 k线分析模块 时发生未知错误: {e} !!!")
    print(traceback.format_exc())
    k线分析模块 = None

try:
    print("--- 后台分析器：准备导入 数据获取模块 ---")
    import 数据获取模块 # 即使 k线分析模块 会导入，这里也显式导入以检查
    from 数据获取模块 import logger as data_logger # 尝试获取 logger
    print("--- 后台分析器：导入 数据获取模块 成功 ---")
except ImportError as e:
    print(f"!!! 后台分析器：导入 数据获取模块 失败: {e} !!!")
    数据获取模块 = None
    data_logger = None
except Exception as e:
    print(f"!!! 后台分析器：导入 数据获取模块 时发生未知错误: {e} !!!")
    print(traceback.format_exc())
    数据获取模块 = None
    data_logger = None

try:
    print("--- 后台分析器：准备导入 schedule ---")
    import schedule
    print("--- 后台分析器：导入 schedule 成功 ---")
except ImportError as e:
    print(f"!!! 后台分析器：导入 schedule 失败: {e} !!!")
    print("请确保已安装 schedule 库: pip install schedule")
    schedule = None
except Exception as e:
    print(f"!!! 后台分析器：导入 schedule 时发生未知错误: {e} !!!")
    print(traceback.format_exc())
    schedule = None

try:
    print("--- 后台分析器：准备导入 配置 ---")
    import 配置
    print("--- 后台分析器：导入 配置 成功 ---")
except ImportError as e:
    print(f"!!! 后台分析器：导入 配置 失败: {e} !!!")
    配置 = None
except Exception as e:
    print(f"!!! 后台分析器：导入 配置 时发生未知错误: {e} !!!")
    print(traceback.format_exc())
    配置 = None

try:
    print("--- 后台分析器：准备导入 Client ---")
    from binance.client import Client
    print("--- 后台分析器：导入 Client 成功 ---")
except ImportError as e:
    print(f"!!! 后台分析器：导入 Client 失败: {e} !!!")
    print("请确保已安装 python-binance 库: pip install python-binance")
    Client = None
except Exception as e:
    print(f"!!! 后台分析器：导入 Client 时发生未知错误: {e} !!!")
    print(traceback.format_exc())
    Client = None

# --- 日志记录器配置 ---
if data_logger:
    logger = data_logger
    logger.info("后台分析器 复用 数据获取模块 logger")
else:
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    log_handler = logging.StreamHandler()
    log_handler.setFormatter(log_formatter)
    logger = logging.getLogger("后台分析器")
    logger.setLevel(logging.INFO)
    if not logger.hasHandlers():
        logger.addHandler(log_handler)
    logger.warning("后台分析器 未能复用数据获取模块 logger，创建了独立的 logger")

# --- 配置 ---
# 不再需要硬编码的主流币列表
# MAIN_COINS = [...]
TOP_N_SYMBOLS = 20 # 获取交易量前 N 的币种
MARKET_TYPE_AUTO = 'futures'
UPDATE_INTERVAL_MINUTES = 5
RESULTS_FILE = 'auto_analysis_results.json'
file_lock = Lock()
binance_client = None # 全局币安客户端实例

# --- 初始化币安客户端 (移到全局，方便复用) ---
def initialize_binance_client():
    global binance_client
    if not Client:
        logger.critical("Binance Client 未成功导入，无法初始化。")
        return False
    if not 配置:
        logger.critical("配置模块 未成功导入，无法读取 API 密钥。")
        return False

    try:
        api_key = 配置.BINANCE_API_KEY
        api_secret = 配置.BINANCE_API_SECRET
        if api_key == "YOUR_API_KEY_PLACEHOLDER" or api_secret == "YOUR_API_SECRET_PLACEHOLDER" or not api_key or not api_secret:
            logger.error("API 密钥未正确配置或为空。请检查 .env 或 配置.py 文件。")
            return False

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
            logger.info(f"后台分析器将使用代理: {proxy_url}")

        binance_client = Client(api_key=api_key, api_secret=api_secret, requests_params=requests_params)
        binance_client.ping() # 测试连接
        logger.info("后台分析器 币安客户端初始化成功并测试连接通过。")
        return True
    except AttributeError as e:
        logger.error(f"配置模块 '配置.py' 中缺少必要的配置项: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"后台分析器 初始化币安客户端时发生错误: {e}", exc_info=True)
        binance_client = None # 初始化失败则重置
        return False

# --- 辅助函数：获取 Top N 交易对 ---
def get_top_n_symbols() -> list[str]:
    """获取 U 本位合约交易量前 N 的交易对符号列表。"""
    if not binance_client:
        logger.error("币安客户端未初始化，无法获取 Top N 交易对。")
        return [] # 返回空列表表示失败

    try:
        logger.info(f"正在从币安 API 获取 U 本位合约 Tickers 以确定 Top {TOP_N_SYMBOLS} 交易对...")
        tickers = binance_client.futures_ticker() # 获取所有 tickers
        logger.info(f"获取到 {len(tickers)} 个 Tickers。")

        # 筛选 USDT 交易对并转换为包含浮点数交易额的列表
        usdt_tickers = []
        for ticker in tickers:
            if ticker['symbol'].endswith('USDT'):
                try:
                    quote_volume = float(ticker['quoteVolume'])
                    usdt_tickers.append({'symbol': ticker['symbol'], 'quoteVolume': quote_volume})
                except (ValueError, KeyError) as e:
                    logger.warning(f"处理 ticker {ticker.get('symbol', '?')} 时出错 (跳过): {e}")
                    continue

        if not usdt_tickers:
            logger.error("未能找到任何 USDT 交易对的 Ticker 数据。")
            return []

        # 按交易额 (quoteVolume) 降序排序
        usdt_tickers.sort(key=operator.itemgetter('quoteVolume'), reverse=True)

        # 提取前 N 个交易对符号
        top_symbols = [ticker['symbol'] for ticker in usdt_tickers[:TOP_N_SYMBOLS]]
        logger.info(f"成功筛选并排序 Top {len(top_symbols)} USDT 交易对 (按交易量): {', '.join(top_symbols)}")
        return top_symbols

    except Exception as e:
        logger.error(f"获取或处理 Top N 交易对时发生错误: {e}", exc_info=True)
        return [] # 出错时返回空列表

# --- 辅助函数：转换 Timestamp (保持不变) ---
def convert_timestamps(obj):
    """递归遍历字典/列表，将 Pandas Timestamp 转换为 ISO 格式字符串。"""
    if isinstance(obj, dict):
        return {k: convert_timestamps(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_timestamps(elem) for elem in obj]
    elif isinstance(obj, pd.Timestamp):
        try:
            return obj.isoformat()
        except Exception as e:
            logger.warning(f"转换 Timestamp 时出错: {e}, 将返回原始对象。")
            return obj
    else:
        return obj

# --- 核心分析函数 ---
def perform_and_save_analysis():
    """
    获取 Top N 交易对，执行分析，并将结果保存到 JSON 文件。
    """
    global binance_client # 确保使用的是全局客户端
    # 检查核心模块
    if not k线分析模块 or not hasattr(k线分析模块, '分析K线结构与形态'):
        logger.error("k线分析模块 未正确加载或缺少 '分析K线结构与形态' 函数，无法执行分析。")
        return

    # 检查并初始化币安客户端（如果尚未初始化或连接丢失）
    if not binance_client:
        logger.warning("币安客户端未初始化，尝试重新初始化...")
        if not initialize_binance_client():
             logger.error("币安客户端初始化失败，跳过本次分析。")
             return
    else:
        # 可选：每次运行时都测试一下连接
        try:
            binance_client.ping()
        except Exception as ping_e:
            logger.warning(f"币安客户端 ping 失败 ({ping_e})，尝试重新初始化...")
            if not initialize_binance_client():
                logger.error("币安客户端重新初始化失败，跳过本次分析。")
                return

    # 获取 Top N 交易对列表
    symbols_to_analyze = get_top_n_symbols()
    if not symbols_to_analyze:
        logger.error(f"未能获取到 Top {TOP_N_SYMBOLS} 交易对列表，跳过本次分析。")
        return # 没有交易对，直接返回

    logger.info(f"开始对获取到的 Top {len(symbols_to_analyze)} 交易对执行自动分析...")
    results = {}
    success_count = 0
    error_count = 0

    # 使用动态获取的列表进行分析
    for symbol in symbols_to_analyze:
        logger.info(f"正在分析 {symbol} ({MARKET_TYPE_AUTO})...")
        try:
            # 调用分析函数
            analysis_return = k线分析模块.分析K线结构与形态(
                symbol=symbol,
                market_type=MARKET_TYPE_AUTO
            )

            # --- 新增：严格检查返回值格式 ---
            analysis_result = None
            if isinstance(analysis_return, tuple) and len(analysis_return) >= 1 and isinstance(analysis_return[0], dict):
                 analysis_result = analysis_return[0] # 获取包含分析结果的字典
            else:
                 # 如果返回格式不符合预期 (不是包含字典的元组)
                 err_msg = f"分析函数为 {symbol} 返回了非预期的格式: {type(analysis_return)}"
                 logger.error(err_msg)
                 results[symbol] = {
                     'error': err_msg,
                     'last_updated': time.strftime('%Y-%m-%d %H:%M:%S')
                 }
                 error_count += 1
                 time.sleep(0.5) # 短暂休眠后继续下一个
                 continue # 跳过当前循环，处理下一个币种
            # --- 返回值检查结束 ---

            # 现在确认 analysis_result 是一个字典，检查其内容
            analysis_data = analysis_result # 使用提取出的字典

            # 检查字典中是否包含错误信息 (由分析模块内部生成)
            internal_error = analysis_data.get('error')
            if internal_error is not None:
                 logger.error(f"分析 {symbol} 时模块内部返回错误: {internal_error}")
                 # 结果字典已包含错误，无需额外处理，但计入错误数
                 error_count += 1
            else:
                 # 如果没有错误键，或者错误键的值是 None，视为成功
                 logger.info(f"完成 {symbol} 的分析。")
                 success_count += 1

            # 保存结果 (无论是包含成功数据还是内部错误信息的字典)
            results[symbol] = {
                **analysis_data,
                'last_updated': time.strftime('%Y-%m-%d %H:%M:%S')
            }

        except Exception as e:
            # 这是在调用分析函数本身或处理结果时发生的外部异常
            logger.error(f"调用分析函数分析 {symbol} 时发生外部错误: {e}", exc_info=True)
            results[symbol] = {
                'error': f"调用分析函数时发生外部错误: {str(e)}", # 明确是外部错误
                'traceback': traceback.format_exc(),
                'last_updated': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            error_count += 1

        # 控制请求频率，防止 API 限制
        time.sleep(1) # 每次分析后休息 1 秒

    logger.info(f"所有目标交易对分析完成。成功: {success_count}, 失败: {error_count}。")

    # --- 转换 Timestamp 和保存文件的逻辑保持不变 ---
    logger.info("开始转换结果中的 Timestamp 对象...")
    try:
        serializable_results = convert_timestamps(results)
        logger.info("Timestamp 对象转换完成。")
    except Exception as e:
        logger.error(f"转换 Timestamp 时发生严重错误: {e}", exc_info=True)
        serializable_results = results
        logger.warning("由于转换错误，将尝试保存未经 Timestamp 转换的结果。")

    logger.info(f"准备将结果写入文件: {RESULTS_FILE}")
    with file_lock:
        try:
            with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(serializable_results, f, ensure_ascii=False, indent=4)
            logger.info(f"分析结果已成功保存到 {RESULTS_FILE}")
        except IOError as e:
            logger.error(f"写入结果文件 {RESULTS_FILE} 时发生 IO 错误: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"写入结果文件 {RESULTS_FILE} 时发生未知错误: {e}", exc_info=True)

# --- 主程序与调度 ---
if __name__ == "__main__":
    # 检查依赖库
    if not schedule:
        logger.critical("无法加载 schedule 库，后台分析器无法按计划运行。")
        exit(1)
    if not k线分析模块 or not hasattr(k线分析模块, '分析K线结构与形态'):
        logger.critical("k线分析模块 未正确加载或缺少必要函数，无法启动分析。")
        exit(1)
    if not Client:
        logger.critical("python-binance Client 未加载，无法获取交易对。")
        exit(1)
    if not 配置:
        logger.critical("配置模块 未加载，无法获取 API 密钥。")
        exit(1)

    logger.info("后台分析器启动。")

    # --- 启动时初始化币安客户端 ---
    if not initialize_binance_client():
        logger.critical("启动时初始化币安客户端失败，后台分析器无法运行。")
        exit(1)
    # -------------------------------

    logger.info(f"分析结果将保存到: {os.path.abspath(RESULTS_FILE)}")
    logger.info(f"目标分析数量: Top {TOP_N_SYMBOLS} 交易对")
    logger.info(f"分析间隔设置为: {UPDATE_INTERVAL_MINUTES} 分钟")

    # 立即执行一次分析
    logger.info("首次执行分析...")
    perform_and_save_analysis()

    # 设置定时任务
    logger.info(f"设置定时任务，每 {UPDATE_INTERVAL_MINUTES} 分钟执行一次分析。")
    schedule.every(UPDATE_INTERVAL_MINUTES).minutes.do(perform_and_save_analysis)

    logger.info("进入主循环，等待定时任务触发...")
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到退出信号 (KeyboardInterrupt)，后台分析器正在关闭...")
            break
        except Exception as e:
            logger.error(f"主循环发生未捕获错误: {e}", exc_info=True)
            logger.info("将在 15 秒后尝试继续运行...") # 增加等待时间
            time.sleep(15)

    logger.info("后台分析器已停止。")
    print("--- 后台分析器：脚本执行结束 ---")
