import streamlit as st
import pandas as pd
# 移除导入 load_config, get_config
# from 配置 import load_config, get_config 
# 直接导入需要的配置变量
import 配置 
from data_fetcher import DataFetcher
from kline_analysis_module import KlineAnalysisModule
import logging
import json
import os
from datetime import datetime

# --- 全局配置 ---
MAIN_COINS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'DOGEUSDT', 'XRPUSDT', 'ADAUSDT', 'LINKUSDT', 'MATICUSDT']
RESULTS_FILE = 'analysis_results.json'
MARKET_TYPE_AUTO = 'futures'

# 初始化 session state
if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None

# 尝试导入自定义模块
try:
    import k线分析模块
    import 数据获取模块  # 直接导入整个模块，不导入setup_logging
    MODULE_LOAD_ERROR = None
    # 直接获取数据获取模块的logger，不需要setup_logging
    logger = logging.getLogger('数据获取模块')
    logger.info("网页应用正在启动，使用数据获取模块的logger")
except ImportError as e:
    MODULE_LOAD_ERROR = e
    logger = None  # 如果导入失败，logger设为None

# --- Streamlit 页面设置 ---
st.set_page_config(page_title="多周期K线协同分析", layout="wide")
st.title("📈 多周期 K 线协同分析工具")

# 如果模块加载失败，显示错误并停止
if MODULE_LOAD_ERROR:
    st.sidebar.error(f"关键模块加载失败: {MODULE_LOAD_ERROR}")
    st.error(f"应用程序核心功能可能无法使用，模块加载失败: {MODULE_LOAD_ERROR}")
    st.stop()  # 停止执行后续代码

# --- 创建标签页 ---
tab_manual_analysis, tab_auto_report = st.tabs(["手动分析", f"主流币报告 ({MARKET_TYPE_AUTO.capitalize()})"])

# --- 标签页1: 手动分析 ---
with tab_manual_analysis:
    st.sidebar.header("手动分析设置")
    symbol_manual = st.sidebar.text_input("输入交易对 (例如 BTCUSDT):", "BTCUSDT")
    market_type_manual = st.sidebar.selectbox("选择市场类型:", ['futures', 'spot'], index=0)
    analyze_button = st.sidebar.button("开始分析")

    st.header(f"手动分析结果: {symbol_manual} ({market_type_manual})")
    if analyze_button:
        try:
            st.info(f"正在分析 {symbol_manual} ({market_type_manual})，请稍候...")
            analysis_result_dict, klines_data_manual = k线分析模块.分析K线结构与形态(
                symbol=symbol_manual,
                market_type=market_type_manual
            )
            if isinstance(analysis_result_dict, dict) and 'error' in analysis_result_dict:
                st.error(f"分析出错: {analysis_result_dict['error']}")
            elif isinstance(analysis_result_dict, dict) and 'confluence_summary' in analysis_result_dict and 'timeframe_analysis' in analysis_result_dict:
                logger.info("进入手动分析结果显示分支 (elif)")
                st.subheader("协同分析总结:")
                st.write("尝试显示协同分析总结...")
                try:
                    bias = analysis_result_dict.get('confluence_summary', {}).get('bias', '未找到 Bias')
                    st.write(f"总结偏向: {bias}")
                except Exception as e:
                    st.write(f"显示总结时出错: {e}")
                
                st.subheader("各周期详情:")
                st.write("尝试显示各周期详情...")
                try:
                    tf_3m_data = analysis_result_dict.get('timeframe_analysis', {}).get('3m', '未找到 3m 数据')
                    st.write(f"3m 周期数据: {tf_3m_data}")
                except Exception as e:
                    st.write(f"显示详情时出错: {e}")
            else:
                logger.warning("未进入预期的手动分析结果显示分支，将显示原始字典。")
                st.warning("分析函数返回的数据格式不符合预期。")
                st.write(analysis_result_dict)
        except Exception as e:
            st.error(f"执行手动分析时出错: {e}")
            if logger:
                logger.error(f"手动分析 {symbol_manual} ({market_type_manual}) 失败: {e}", exc_info=True)
            st.exception(e)  # 显示详细的错误信息
    else:
        st.info("请在左侧边栏输入参数并点击'开始分析'。")

# --- 标签页2: 主流币报告 ---
with tab_auto_report:
    st.subheader("主流币市场分析报告")
    st.caption(f"以下报告基于 {MARKET_TYPE_AUTO} 市场，由后台程序定时更新。")

    results_from_file = None
    error_reading_file = None

    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, 'r', encoding='utf-8') as f:
                results_from_file = json.load(f)
        except Exception as e:
            error_reading_file = f"读取结果文件 {RESULTS_FILE} 时出错: {e}"
            if logger:
                logger.error(error_reading_file, exc_info=True)
    else:
        error_reading_file = f"结果文件 {RESULTS_FILE} 不存在。请确保后台分析器正在运行。"

    if error_reading_file:
        st.warning(error_reading_file)
    elif results_from_file:
        latest_update_time = None
        for coin_data in results_from_file.values():
            if isinstance(coin_data, dict) and 'last_updated' in coin_data:
                try:
                    current_dt = datetime.strptime(coin_data['last_updated'], '%Y-%m-%d %H:%M:%S')
                    if latest_update_time is None or current_dt > latest_update_time:
                        latest_update_time = current_dt
                except ValueError:
                    pass
        if latest_update_time:
            st.info(f"报告数据最后更新时间: {latest_update_time.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            st.info("结果文件中未找到有效的更新时间戳。")

        displayed_count = 0
        for coin in MAIN_COINS:
            result_data = results_from_file.get(coin)
            if result_data:
                displayed_count += 1
                st.subheader(f"{coin} 分析报告")
                if isinstance(result_data, dict) and 'error' in result_data:
                    st.error(f"后台分析 {coin} 时出错: {result_data['error']}")
                    if 'traceback' in result_data:
                        st.expander("详细错误信息:").code(result_data['traceback'])
                elif isinstance(result_data, dict) and 'analysis' in result_data and isinstance(result_data['analysis'], dict) \
                     and 'confluence_summary' in result_data['analysis'] and 'timeframe_analysis' in result_data['analysis']:
                    try:
                        st.subheader("协同分析总结:")
                        st.json(result_data['analysis']['confluence_summary'])
                        st.subheader("各周期详情:")
                        st.json(result_data['analysis']['timeframe_analysis'])
                    except Exception as display_e:
                        st.error(f"显示 {coin} 报告时出错: {display_e}")
                        if logger:
                            logger.error(f"显示 {coin} 报告失败: {display_e}", exc_info=True)
                        st.exception(display_e)
                else:
                    st.warning(f"结果文件中 {coin} 的数据格式不完整或未知。")
                    st.json(result_data)
                st.divider()
        if displayed_count == 0:
            st.info("结果文件中目前没有主流币的有效分析数据。")
    else:
        st.info("正在等待后台分析器生成第一个结果文件...")

# --- 页脚 ---
st.markdown("---")
st.caption("加密货币市场风险高，本工具分析结果仅供参考，不构成投资建议。")

# 加载配置
# config = load_config()
config = load_config()
# 初始化 DataFetcher 和 KlineAnalysisModule
try:
    # 直接从 配置 模块获取 API 密钥
    api_key = 配置.BINANCE_API_KEY
    api_secret = 配置.BINANCE_API_SECRET
    
    # 检查密钥是否有效 (非占位符)
    if api_key == "YOUR_API_KEY_PLACEHOLDER" or api_secret == "YOUR_API_SECRET_PLACEHOLDER" or not api_key or not api_secret:
        st.error("API 密钥未正确配置或为空。请检查 .env 文件或 配置.py 文件。")
        logger.error("API 密钥为占位符或为空，无法初始化 DataFetcher。")
        st.stop()

    # 代理配置 - 尝试从环境变量读取 (与 配置.py 逻辑类似)
    # 如果环境变量没有，检查 配置 模块中是否有定义
    use_proxy_env = os.getenv('USE_PROXY', 'false').lower() == 'true'
    use_proxy_config = getattr(配置, 'USE_PROXY', False)
    use_proxy = use_proxy_env or use_proxy_config # 优先使用环境变量
    
    proxy_url_env = os.getenv('PROXY_URL', None)
    proxy_url_config = getattr(配置, 'PROXY_URL', None)
    proxy_url = proxy_url_env if proxy_url_env else proxy_url_config # 优先使用环境变量
    
    proxies = {'http': proxy_url, 'https': proxy_url} if use_proxy and proxy_url else None
    
    if use_proxy and not proxy_url:
        logger.warning("配置为使用代理，但未提供代理 URL (环境变量 PROXY_URL 或 配置.py 中的 PROXY_URL)。")
    elif use_proxy:
        logger.info(f"使用代理服务器: {proxy_url}")

    # 使用获取到的配置初始化 DataFetcher
    fetcher = DataFetcher(api_key, api_secret, proxies=proxies)
    analyzer = KlineAnalysisModule(fetcher) # 将 fetcher 实例传递给分析模块
    logger.info("DataFetcher 和 KlineAnalysisModule 初始化完成。")
except AttributeError as e:
    # 捕获访问 配置.py 中不存在的属性错误 (例如 BINANCE_API_KEY)
    st.error(f"配置模块 '配置.py' 中缺少必要的配置项: {e}")
    logger.error(f"读取配置项失败: {e}", exc_info=True)
    st.stop()
except Exception as e:
    st.error(f"初始化数据获取或分析模块时发生未知错误: {e}")
    logger.error(f"初始化失败: {e}", exc_info=True)
    st.stop() # 初始化失败则停止应用

def perform_manual_analysis(symbol, timeframes, market_type):
    """执行手动分析并返回结果字典"""
    try:
        analysis_result = analyzer.analyze_symbol(symbol, timeframes, market_type)
        logger.info(f"手动分析 {symbol} ({market_type}) 完成，返回结果。")
        # 确保分析函数总是返回字典
        if not isinstance(analysis_result, dict):
             logger.error(f"分析函数 analyze_symbol 未返回字典，实际返回类型: {type(analysis_result)}")
             return {"error": f"分析函数内部错误，返回类型非字典: {type(analysis_result)}"}
        return analysis_result
    except Exception as e:
        logger.error(f"手动分析 {symbol} ({market_type}) 时发生异常: {e}", exc_info=True)
        # 确保错误情况也返回字典
        return {"error": f"执行分析时发生意外错误: {e}"}

# --- Streamlit 界面 ---
st.set_page_config(layout="wide")
st.title("多时间周期 K 线协同分析工具")

# 标签页
tab1, tab2 = st.tabs(["实时分析看板 (暂未实现)", "手动分析"])

# --- 手动分析标签页 ---
with tab2:
    st.header("手动触发多周期分析")

    # 用户输入
    symbol = st.text_input("输入交易对 (例如 BTCUSDT):", "BTCUSDT").upper()
    market_type_options = {'现货': 'spot', 'U本位合约': 'futures'}
    selected_market_type_display = st.selectbox("选择市场类型:", list(market_type_options.keys()))
    market_type = market_type_options[selected_market_type_display]

    available_timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"]
    selected_timeframes = st.multiselect("选择要分析的时间周期:", available_timeframes, default=["3m", "5m", "15m", "1h", "4h", "1d"])

    if not selected_timeframes:
        st.warning("请至少选择一个时间周期。")

    # 分析按钮
    if st.button("开始分析", key="manual_analysis_button"):
        if symbol and selected_timeframes and market_type:
            with st.spinner(f"正在分析 {symbol} ({selected_market_type_display}) 的 {', '.join(selected_timeframes)} 周期..."):
                # Store result in session state - OK
                st.session_state.analysis_result = perform_manual_analysis(symbol, selected_timeframes, market_type)
                # Rerun to update UI immediately - OK
                st.rerun()
        else:
            st.error("请输入交易对并至少选择一个时间周期。")
            st.session_state.analysis_result = None # Clear state on input error - OK

    # Display Results Logic (outside button click)
    result_placeholder = st.empty() # OK

    # 首先检查 session_state 中是否有结果
    if st.session_state.analysis_result is not None: # 使用 is not None 更明确
        analysis_result_dict = st.session_state.analysis_result
        
        # 在尝试显示前记录详细信息
        logger.info(f"尝试显示 session_state 中的结果。类型: {type(analysis_result_dict)}")
        if isinstance(analysis_result_dict, dict):
             logger.info(f"结果字典键: {list(analysis_result_dict.keys())}")
        else:
             logger.warning("Session state 中的结果不是字典类型!")

        with result_placeholder.container():
            st.markdown("---")
            st.subheader(f"分析结果: {symbol} ({selected_market_type_display})")

            # 核心逻辑: 检查结果类型和内容
            # 1. 检查是否为字典
            if not isinstance(analysis_result_dict, dict):
                logger.error(f"Session state 包含非字典类型结果: {type(analysis_result_dict)}")
                st.error(f"分析结果格式错误 (非字典类型: {type(analysis_result_dict)})。请检查终端日志获取详细信息。")
                st.write("原始结果内容:", analysis_result_dict) # 尝试显示原始值以供调试
            
            # 2. 如果是字典，检查是否有 'error' 键
            elif 'error' in analysis_result_dict:
                logger.error(f"分析过程返回错误: {analysis_result_dict['error']}")
                st.error(f"分析失败: {analysis_result_dict['error']}")
            
            # 3. 如果是字典且无错误，检查是否包含预期的 'confluence_summary' 和 'timeframe_analysis' 键
            elif 'confluence_summary' in analysis_result_dict and 'timeframe_analysis' in analysis_result_dict:
                logger.info("检测到有效的分析结果结构，准备显示总结和详情。")

                st.subheader("协同分析总结:")
                try:
                    # 优先尝试用 st.json 显示，格式更清晰
                    st.json(analysis_result_dict['confluence_summary'], expanded=True)
                except Exception as e_json_summary:
                    logger.error(f"使用 st.json 显示协同分析总结失败: {e_json_summary}", exc_info=True)
                    st.warning(f"无法使用 st.json 显示总结 ({e_json_summary})，尝试使用 st.write 作为后备方案...")
                    try:
                        # 如果 st.json 失败，回退到 st.write
                        st.write(analysis_result_dict['confluence_summary'])
                    except Exception as e_write_summary:
                        logger.critical(f"使用 st.write 显示协同分析总结也失败: {e_write_summary}", exc_info=True)
                        st.error(f"连 st.write 也无法显示总结内容 ({e_write_summary})。数据可能存在严重问题，请检查日志。")

                st.subheader("各周期详情:")
                try:
                    # 优先尝试用 st.json 显示
                    st.json(analysis_result_dict['timeframe_analysis'], expanded=False) # 详情默认折叠
                except Exception as e_json_details:
                    logger.error(f"使用 st.json 显示各周期详情失败: {e_json_details}", exc_info=True)
                    st.warning(f"无法使用 st.json 显示详情 ({e_json_details})，尝试使用 st.write 作为后备方案...")
                    try:
                        # 如果 st.json 失败，回退到 st.write
                        st.write(analysis_result_dict['timeframe_analysis'])
                    except Exception as e_write_details:
                        logger.critical(f"使用 st.write 显示各周期详情也失败: {e_write_details}", exc_info=True)
                        st.error(f"连 st.write 也无法显示详情内容 ({e_write_details})。数据可能存在严重问题，请检查日志。")
            
            # 4. 如果是字典，但键不匹配上述任何情况
            else:
                logger.warning(f"结果字典键不匹配预期格式 ('error' 或 'confluence_summary'/'timeframe_analysis'): {list(analysis_result_dict.keys())}")
                st.warning("分析结果格式未知或不完整。请检查终端日志。")
                st.write("原始分析结果字典:")
                try:
                    # 尝试显示这个未知结构的字典
                    st.write(analysis_result_dict)
                except Exception as e_write_unknown:
                    logger.error(f"显示未知格式字典失败: {e_write_unknown}", exc_info=True)
                    st.error(f"尝试显示未知格式结果时出错: ({e_write_unknown})")
       else:
        # 如果 session_state 中没有结果 (初始状态或输入错误后)
        with result_placeholder.container():
            st.info("点击“开始分析”以生成报告。") # <-- 已修正引号

# --- 实时分析看板 (占位) ---
with tab1:
    st.header("实时分析看板")
    st.info("此功能正在开发中...")
    st.markdown("""
    **计划功能:**
    *   自动后台轮询分析指定交易对。
    *   通过 WebSocket 或类似技术实时更新分析结果。
    *   可配置的警报通知。
    *   更丰富的可视化图表展示。
    """)

# 页脚
st.markdown("---")
st.caption("加密货币市场风险高，本工具分析结果仅供参考，不构成投资建议。")

