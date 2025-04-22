#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Streamlit K线与成交流分析网页应用

提供手动和自动 K 线及成交流分析功能。
手动分析带有基于时间的缓存，避免短期内重复请求。
自动分析依赖后台脚本定时生成结果文件。
"""

import streamlit as st
import pandas as pd
import logging
import json
import os
from datetime import datetime, timedelta
import time
from binance.client import Client # 用于获取 Top 20 交易对

# 导入自定义模块
try:
    # 移除 '配置' 模块的导入，因为密钥将从 st.secrets 获取
    # import 配置
    import 数据获取模块 as data_fetcher_module # 使用中文名导入，并使用别名
    import k线分析模块 as kline_analysis_module # 使用中文名导入，并使用别名
    import 成交流分析 as 成交流网页分析 # 导入成交流分析模块，使用中文别名
    MODULE_LOAD_ERROR = None
except ImportError as e:
    MODULE_LOAD_ERROR = e
    # 在应用早期处理，避免后续因模块缺失引发更多错误
    st.error(f"核心自定义模块加载失败: {e}。请确保所需 .py 文件存在且无误。")
    st.stop()

# --- 全局常量 ---
AUTO_KLINE_RESULTS_FILE = 'auto_analysis_results.json' # K线后台脚本写入结果的文件名
AUTO_VOLUME_RESULTS_FILE = 'auto_volume_analysis_results.json' # 成交流后台脚本写入结果的文件名
TOP_N_SYMBOLS = 20 # 自动分析的目标数量
CACHE_TTL_SECONDS = 60 # 手动分析缓存时间 (秒)
AUTO_ANALYSIS_INTERVAL_MINUTES = 5 # 自动分析的间隔时间 (分钟)

# --- 初始化 Session State ---
# 用于存储手动分析的结果，使其在 rerun 后保留
if 'manual_kline_analysis_result' not in st.session_state:
    st.session_state.manual_kline_analysis_result = None
if 'manual_volume_analysis_result' not in st.session_state: # 新增：成交量手动分析结果
    st.session_state.manual_volume_analysis_result = None

# 记录上次分析的参数（用于跨 Tab 预填输入）
if 'last_analyzed_symbol' not in st.session_state: # 新增初始化
    st.session_state.last_analyzed_symbol = None
if 'last_analyzed_market' not in st.session_state: # 新增初始化
    st.session_state.last_analyzed_market = None

# 新增：记录上次成交量分析的参数
if 'last_analyzed_volume_symbol' not in st.session_state:
    st.session_state.last_analyzed_volume_symbol = None
if 'last_analyzed_volume_market' not in st.session_state:
    st.session_state.last_analyzed_volume_market = None

# --- 日志配置 ---
log_file_path = os.path.join(os.path.dirname(__file__), 'logs', 'app.log')
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
logger = logging.getLogger("分析网页功能") # 使用独立的 logger 名称
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    # 控制台输出
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.DEBUG)
    logger.addHandler(stream_handler)
    # 文件输出
    file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.propagate = False
logger.info("分析网页功能应用启动，日志初始化完成 (Debug Level Enabled)。")

# --- 初始化核心模块 ---
# ... (币安 Client 初始化修改如下) ...
binance_client = None # 用于获取行情数据

try:
    # 1. 从 Streamlit Secrets 获取 API 密钥
    #    假设你在 Streamlit Cloud 上配置的 Secrets 名称是 BINANCE_API_KEY 和 BINANCE_API_SECRET
    #    如果不是，请在 Cloud 上创建它们，或修改这里的键名
    api_key = st.secrets.get("BINANCE_API_KEY")
    api_secret = st.secrets.get("BINANCE_API_SECRET")

    if not api_key or not api_secret:
        # 如果在 Streamlit Cloud 运行但未设置 Secrets，或本地运行且无 secrets.toml 文件
        st.error("无法获取币安 API 密钥。请检查 Streamlit Cloud 的 Secrets 配置或本地的 .streamlit/secrets.toml 文件。")
        logger.error("未找到 API 密钥 (st.secrets)。")
        st.stop()
    elif api_key == "YOUR_API_KEY_PLACEHOLDER" or api_secret == "YOUR_API_SECRET_PLACEHOLDER":
        # (可选) 增加对占位符的检查，虽然理论上 Secrets 不应设为占位符
        st.warning("检测到 API 密钥或 Secret 为占位符字符串，请在 Streamlit Cloud Secrets 中更新为真实值。")
        logger.warning("API 密钥/Secret 值为占位符。")
        # 不停止运行，但给出警告

    # 2. 处理代理 (从环境变量或 '配置' 模块读取 - '配置' 模块仍需用于代理设置)
    #    注意：如果代理设置也希望通过 Secrets 管理，需要进一步修改
    try:
        import 配置 # 仅为代理设置导入配置
        use_proxy_config = getattr(配置, 'USE_PROXY', False)
        proxy_url_config = getattr(配置, 'PROXY_URL', None)
    except ImportError:
        # 如果 配置.py 不存在或无法导入，则仅依赖环境变量
        use_proxy_config = False
        proxy_url_config = None
        logger.info("未找到 '配置.py' 文件，代理设置将仅依赖环境变量。")

    use_proxy_env = os.getenv('USE_PROXY', 'false').lower() == 'true'
    use_proxy = use_proxy_env or use_proxy_config

    proxy_url_env = os.getenv('PROXY_URL', None)
    proxy_url = proxy_url_env if proxy_url_env else proxy_url_config

    proxies = {'http': proxy_url, 'https': proxy_url} if use_proxy and proxy_url else None
    requests_params = {'proxies': proxies} if proxies else None

    if use_proxy and not proxy_url:
        logger.warning("配置为使用代理，但未提供代理 URL。")
    elif use_proxy:
        logger.info(f"使用代理服务器: {proxy_url}")

    # 3. 初始化 Binance Client (使用从 st.secrets 获取的密钥)
    binance_client = Client(api_key=api_key, api_secret=api_secret, requests_params=requests_params)
    binance_client.ping() # 测试连接
    server_time = binance_client.get_server_time()
    logger.info(f"成功使用 Streamlit Secrets 中的密钥连接到币安服务器，服务器时间: {datetime.fromtimestamp(server_time['serverTime']/1000)}")

    # 4. 移除 DataFetcher 和 KlineAnalysisModule 的实例化 (保持不变)
    logger.info("核心模块检查和币安连接测试完成。成交流分析模块已导入。")

# 移除对配置模块 Attribute Error 的捕获，因为密钥不再从那里读取
# except AttributeError as e:
#     st.error(f"配置模块 '配置.py' 中缺少必要的配置项: {e}")
#     logger.error(f"读取配置项失败: {e}", exc_info=True)
#     st.stop()
except Exception as e:
    # 通用错误处理保持不变
    st.error(f"初始化或连接币安时发生错误: {e}")
    logger.error(f"初始化失败: {e}", exc_info=True)
    st.stop()

# --- 缓存的分析函数 ---

# K 线分析缓存函数 (保持不变，重命名 session_state 变量)
@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_manual_kline_analysis_cached(symbol: str, market_type: str, timeframes: tuple, cache_key_minute: str):
    logger.info(f"K线缓存未命中或已过期 (Key: {symbol}/{market_type}/{cache_key_minute})。执行K线分析...")
    try:
        # 调用 k线分析模块
        analysis_result_tuple = kline_analysis_module.分析K线结构与形态(
            symbol=symbol,
            market_type=market_type,
            timeframes=list(timeframes)
        )
        # ... (错误处理和日志保持不变) ...
        if isinstance(analysis_result_tuple, tuple) and len(analysis_result_tuple) > 0:
            analysis_result_dict = analysis_result_tuple[0]
            if not isinstance(analysis_result_dict, dict):
                err_msg = f"K线分析函数内部错误: 返回的第一个元素不是字典 (类型: {type(analysis_result_dict)})"
                logger.error(err_msg)
                return {"error": err_msg}
            logger.info(f"K线分析成功完成，返回字典的键: {list(analysis_result_dict.keys())}")
            return analysis_result_dict
        else:
            err_msg = f"K线分析函数内部错误: 返回格式非预期 tuple (类型: {type(analysis_result_tuple)}, 值: {repr(analysis_result_tuple)[:100]}...)"
            logger.error(err_msg)
            return {"error": err_msg}
    except Exception as e:
        err_msg = f"K线分析执行时发生错误: {type(e).__name__} - {repr(e)}"
        logger.error(f"执行缓存K线分析 {symbol} ({market_type}) 时捕获到异常: {repr(e)}", exc_info=True)
        return {"error": err_msg}

# 新增：成交流分析缓存函数
@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_manual_volume_analysis_cached(symbol: str, market_type: str, cache_key_minute: str):
    """
    带缓存的成交流手动分析函数。
    调用 成交流网页分析.分析成交流(symbol, market_type)，使用模块内的默认参数。
    """
    # 移除 timeframes 参数，更新日志信息
    logger.info(f"成交量缓存未命中或已过期 (Key: {symbol}/{market_type}/{cache_key_minute})。执行成交量分析 (使用默认limit)...")
    try:
        # 调用 成交流分析 模块的函数，函数名改为 分析成交流
        # 不再传递 timeframes，让函数使用默认 limit 或 time_windows
        analysis_result = 成交流网页分析.分析成交流(
            symbol=symbol,
            market_type=market_type
            # 假设函数内部有默认 limit 或 time_windows
        )

        # 假设返回的是一个字典 (后续逻辑不变)
        if isinstance(analysis_result, dict):
            logger.info(f"成交量分析成功完成，返回字典的键: {list(analysis_result.keys())}")
            return analysis_result
        else:
            err_msg = f"成交量分析函数返回格式未知或非预期: {type(analysis_result)}。请检查 '成交流分析.py'。"
            logger.error(err_msg + f" 返回内容 (前100字符): {repr(analysis_result)[:100]}...")
            return {"raw_result": analysis_result, "warning": err_msg}

    except AttributeError:
         # 更新错误信息，函数名已改为 分析成交流
         err_msg = f"无法在 '成交流分析.py' 模块中找到名为 '分析成交流' 的函数。请检查模块实现。"
         logger.error(err_msg, exc_info=True)
         return {"error": err_msg}
    except Exception as e:
        err_msg = f"成交量分析执行时发生错误: {type(e).__name__} - {repr(e)}"
        logger.error(f"执行缓存成交量分析 {symbol} ({market_type}) 时捕获到异常: {repr(e)}", exc_info=True)
        return {"error": err_msg}

# --- Streamlit 应用界面 ---
st.set_page_config(page_title="K线与成交流分析", layout="wide") # 修改页面标题
st.title("📈 K线与成交流分析工具") # 修改应用标题

# 创建四个 Tab 页
tab_kline_manual, tab_kline_auto, tab_volume_manual, tab_volume_auto = st.tabs([
    "🔍 K线手动分析",
    "⏱️ K线自动报告",
    "📊 成交流手动分析",
    "⏱️ 成交流自动报告"
])

# --- K线手动分析标签页 (基本保持不变，修改 session_state 变量名) ---
with tab_kline_manual:
    st.header("手动触发单币种 K 线分析")
    st.markdown(f"分析结果将在 **{CACHE_TTL_SECONDS}秒** 内为相同参数缓存。")

    POPULAR_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT", "MATICUSDT", "DOTUSDT"]
    SELECTBOX_PLACEHOLDER = "--- 或选择常用交易对 ---"

    col1_km, col2_km = st.columns([2, 1])
    with col1_km:
        symbol_input_km = st.text_input("输入交易对 (例如 BTCUSDT):", "", key="kline_manual_symbol_input").upper()
        symbol_selected_km = st.selectbox("或选择常用交易对:",
                                       options=[SELECTBOX_PLACEHOLDER] + sorted(POPULAR_SYMBOLS),
                                       index=0,
                                       key="kline_manual_symbol_select")
    with col2_km:
        market_type_options_km = {'U本位合约': 'futures', '现货': 'spot'}
        selected_mt_display_km = st.selectbox("选择市场类型:", list(market_type_options_km.keys()), key="kline_manual_market_type")
        market_type_km = market_type_options_km[selected_mt_display_km]

    available_timeframes_km = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"]
    default_timeframes_km = ["3m", "5m", "15m", "1h", "4h", "1d"]
    selected_timeframes_km = st.multiselect("选择要分析的时间周期:", available_timeframes_km, default=default_timeframes_km, key="kline_manual_timeframes")

    analyze_button_km = st.button("开始 K 线分析", key="kline_manual_analyze_button")

    symbol_to_analyze_km = None
    if analyze_button_km:
        if symbol_selected_km != SELECTBOX_PLACEHOLDER:
            symbol_to_analyze_km = symbol_selected_km
        elif symbol_input_km:
            symbol_to_analyze_km = symbol_input_km

        if not symbol_to_analyze_km:
            st.warning("请输入或选择一个交易对。")
        elif not selected_timeframes_km:
            st.warning("请至少选择一个时间周期。")
        else:
            current_minute_str_km = datetime.now().strftime("%Y-%m-%d %H:%M")
            timeframes_tuple_km = tuple(sorted(selected_timeframes_km))

            with st.spinner(f"正在分析 K 线 {symbol_to_analyze_km} ({market_type_km}) 时间周期: {', '.join(selected_timeframes_km)}..."):
                # 调用带缓存的函数，结果存入 manual_kline_analysis_result
                st.session_state.manual_kline_analysis_result = get_manual_kline_analysis_cached(
                    symbol_to_analyze_km,
                    market_type_km,
                    timeframes_tuple_km,
                    current_minute_str_km
                )
                # 更新用于显示的变量 (如果分析成功启动)
                st.session_state.last_analyzed_symbol = symbol_to_analyze_km
                st.session_state.last_analyzed_market = selected_mt_display_km

    # 显示 K 线手动分析结果 (保持不变，读取 session_state.manual_kline_analysis_result)
    manual_kline_result_placeholder = st.empty()

    logger.debug(f"准备显示手动 K 线结果。Session state 内容: {st.session_state.get('manual_kline_analysis_result')}")

    if st.session_state.manual_kline_analysis_result:
        result_dict_km = st.session_state.manual_kline_analysis_result
        display_symbol_km = st.session_state.get('last_analyzed_symbol', '未知币种')
        display_market_km = st.session_state.get('last_analyzed_market', '未知市场')

        with manual_kline_result_placeholder.container():
            st.markdown("---")
            st.subheader(f"K 线分析结果: {display_symbol_km} ({display_market_km})")

            if isinstance(result_dict_km, dict) and 'error' in result_dict_km and result_dict_km['error'] is not None:
                logger.error(f"显示 K 线分析失败结果: {result_dict_km['error']}")
                st.error(f"K 线分析失败: {result_dict_km['error']}")
            elif isinstance(result_dict_km, dict) and 'confluence_summary' in result_dict_km and 'timeframe_analysis' in result_dict_km:
                logger.info("显示有效的 K 线手动分析结果。")
                # ... (这里省略了显示 K 线结果的详细代码，保持和之前一致) ...
                # --- 总结显示 ---
                summary_km = result_dict_km['confluence_summary']
                details_km = result_dict_km['timeframe_analysis']
                st.subheader("K线协同分析总结:")
                col1_km_res, col2_km_res, col3_km_res, col4_km_res = st.columns(4)
                col1_km_res.metric("偏向 (Bias)", summary_km.get('bias', 'N/A'))
                col2_km_res.metric("置信度 (Confidence)", summary_km.get('confidence', 'N/A'))
                score_km = summary_km.get('weighted_score', 'N/A')
                score_display_km = f"{score_km:.1f}" if isinstance(score_km, (int, float)) else 'N/A'
                col3_km_res.metric("加权分数 (Score)", score_display_km)
                current_price_km = result_dict_km.get('last_price', 'N/A')
                price_display_km = 'N/A'
                # (价格格式化逻辑)
                if isinstance(current_price_km, (int, float)):
                    if current_price_km > 1000: price_display_km = f"{current_price_km:.2f}"
                    elif current_price_km > 1: price_display_km = f"{current_price_km:.4f}"
                    else: price_display_km = f"{current_price_km:.6f}"
                elif isinstance(current_price_km, str):
                    try:
                        price_float_km = float(current_price_km)
                        if price_float_km > 1000: price_display_km = f"{price_float_km:.2f}"
                        elif price_float_km > 1: price_display_km = f"{price_float_km:.4f}"
                        else: price_display_km = f"{price_float_km:.6f}"
                    except (ValueError, TypeError): price_display_km = current_price_km
                else: price_display_km = str(current_price_km)
                col4_km_res.metric("当前价格", price_display_km)
                if summary_km.get('reasoning'):
                    st.markdown("**主要理由:**")
                    reasoning_text_km = "\n".join([f"- {reason}" for reason in summary_km['reasoning']])
                    st.markdown(reasoning_text_km)
                if summary_km.get('warnings'):
                    st.markdown("**注意:**")
                    for warning in summary_km['warnings']: st.warning(warning)
                st.divider()
                # --- 关键信号表 ---
                st.subheader("各周期关键信号:")
                # ... (省略 K 线信号表代码) ...
                key_signals_data_km = []
                if isinstance(details_km, dict):
                    try:
                        def sort_key_km(tf): num = int(tf[:-1]); unit = tf[-1]; unit_map = {'m': 1, 'h': 60, 'd': 1440, 'w': 10080, 'M': 43200}; return unit_map.get(unit, 0) * num
                        sorted_timeframes_for_table_km = sorted(details_km.keys(), key=sort_key_km)
                    except Exception: sorted_timeframes_for_table_km = list(details_km.keys())
                    for tf_km in sorted_timeframes_for_table_km:
                         if tf_km in details_km:
                             tf_data_km = details_km[tf_km]
                             if isinstance(tf_data_km, dict):
                                 # (省略 K线信号表行数据提取代码)
                                 row_data_km = {"周期": tf_km}
                                 row_data_km["MA趋势"] = tf_data_km.get('trend_ma', '-')
                                 macd_data_km = tf_data_km.get('trend_macd', {}); row_data_km["MACD方向"] = macd_data_km.get('status', '-')
                                 macd_hist_str_km = macd_data_km.get('histogram'); macd_momentum_km = '-'
                                 try:
                                     if macd_hist_str_km is not None: macd_hist_float_km = float(macd_hist_str_km); macd_momentum_km = "正向" if macd_hist_float_km > 0 else ("负向" if macd_hist_float_km < 0 else "零轴")
                                 except (ValueError, TypeError): pass
                                 row_data_km["MACD动量"] = macd_momentum_km
                                 dmi_data_km = tf_data_km.get('trend_dmi', {}); dmi_status_km = dmi_data_km.get('status', '-'); dmi_strength_km = dmi_data_km.get('strength', '-'); row_data_km["DMI方向"] = f"{dmi_status_km}, {dmi_strength_km}" if dmi_status_km != '-' and dmi_strength_km != '-' else (dmi_status_km if dmi_status_km != '-' else dmi_strength_km)
                                 adx_value_str_km = dmi_data_km.get('ADX'); adx_display_km = '-'
                                 try:
                                     if adx_value_str_km is not None: adx_value_float_km = float(adx_value_str_km); adx_display_km = f"{adx_value_float_km:.1f}"
                                 except (ValueError, TypeError): adx_display_km = str(adx_value_str_km) if adx_value_str_km else '-'
                                 row_data_km["ADX"] = adx_display_km
                                 vol_data_km = tf_data_km.get('volatility', {}); row_data_km["波动状态"] = vol_data_km.get('status', '-')
                                 atr_value_str_km = vol_data_km.get('atr'); atr_display_km = '-'
                                 try:
                                     if atr_value_str_km is not None: atr_value_float_km = float(atr_value_str_km); atr_display_km = f"{atr_value_float_km:.2f}"
                                 except (ValueError, TypeError): atr_display_km = str(atr_value_str_km) if atr_value_str_km else '-'
                                 row_data_km["ATR"] = atr_display_km
                                 pp_value_str_km = tf_data_km.get('pivot_point'); pp_display_km = '-'
                                 try:
                                     if pp_value_str_km is not None: pp_value_float_km = float(pp_value_str_km); pp_display_km = f"{pp_value_float_km:.2f}"
                                 except (ValueError, TypeError): pp_display_km = str(pp_value_str_km) if pp_value_str_km else '-'
                                 row_data_km["枢轴点(PP)"] = pp_display_km
                                 patterns_km = tf_data_km.get('patterns', []); pattern_display_km = patterns_km[0].get('name', '-') if patterns_km else "-"; pattern_implication_km = f" ({patterns_km[0].get('implication', '?')})" if patterns_km else ""; row_data_km["主要形态"] = f"{pattern_display_km}{pattern_implication_km}".strip()
                                 key_signals_data_km.append(row_data_km)
                if key_signals_data_km:
                    key_signals_df_km = pd.DataFrame(key_signals_data_km)
                    display_columns_km = ["周期", "MA趋势", "MACD方向", "MACD动量", "DMI方向", "ADX", "波动状态", "ATR", "枢轴点(PP)", "主要形态"]
                    valid_columns_km = [col for col in display_columns_km if col in key_signals_df_km.columns]
                    st.dataframe(key_signals_df_km[valid_columns_km], use_container_width=True, hide_index=True)
                else: st.info("未能提取K线关键信号数据以生成摘要表。")
                st.divider()
                # --- K线周期详情 (不折叠) ---
                st.subheader("各周期详细分析:")
                if isinstance(details_km, dict):
                     # ... (省略 K 线周期详情显示代码) ...
                    try:
                        def sort_key_exp_km(tf): num = int(tf[:-1]); unit = tf[-1]; unit_map = {'m': 1, 'h': 60, 'd': 1440, 'w': 10080, 'M': 43200}; return unit_map.get(unit, 0) * num
                        sorted_timeframes_exp_km = sorted(details_km.keys(), key=sort_key_exp_km)
                    except Exception: sorted_timeframes_exp_km = list(details_km.keys())
                    for tf_km_exp in sorted_timeframes_exp_km:
                         if tf_km_exp in details_km:
                             tf_data_km_exp = details_km[tf_km_exp]
                             st.subheader(f"{tf_km_exp} 周期")
                             if isinstance(tf_data_km_exp, dict):
                                 col1_exp_km, col2_exp_km, col3_exp_km = st.columns(3)
                                 with col1_exp_km: # MA & MACD
                                      st.markdown("**MA & MACD**")
                                      st.markdown(f"- **趋势:** {tf_data_km_exp.get('trend_ma', '-')}")
                                      macd_data_km_exp = tf_data_km_exp.get('trend_macd', {}); macd_direction_km_exp = macd_data_km_exp.get('status', '-'); macd_hist_str_km_exp = macd_data_km_exp.get('histogram'); macd_momentum_km_exp = '-'
                                      try:
                                           if macd_hist_str_km_exp is not None: macd_hist_float_km_exp = float(macd_hist_str_km_exp); macd_momentum_km_exp = "正向" if macd_hist_float_km_exp > 0 else ("负向" if macd_hist_float_km_exp < 0 else "零轴")
                                      except (ValueError, TypeError): pass
                                      st.markdown(f"- **方向:** {macd_direction_km_exp}")
                                      st.markdown(f"- **动量:** {macd_momentum_km_exp}")
                                 with col2_exp_km: # DMI & 波动率
                                      st.markdown("**DMI & 波动率**")
                                      dmi_data_km_exp = tf_data_km_exp.get('trend_dmi', {}); dmi_status_km_exp = dmi_data_km_exp.get('status', '-'); dmi_strength_km_exp = dmi_data_km_exp.get('strength', '-'); dmi_display_km_exp = f"{dmi_status_km_exp}, {dmi_strength_km_exp}" if dmi_status_km_exp != '-' and dmi_strength_km_exp != '-' else (dmi_status_km_exp if dmi_status_km_exp != '-' else dmi_strength_km_exp); adx_value_str_km_exp = dmi_data_km_exp.get('ADX'); adx_display_km_exp = '-'
                                      try:
                                           if adx_value_str_km_exp is not None: adx_value_float_km_exp = float(adx_value_str_km_exp); adx_display_km_exp = f"{adx_value_float_km_exp:.1f}"
                                      except (ValueError, TypeError): adx_display_km_exp = str(adx_value_str_km_exp) if adx_value_str_km_exp else '-'
                                      st.markdown(f"- **方向:** {dmi_display_km_exp}")
                                      st.markdown(f"- **ADX:** {adx_display_km_exp}")
                                      vol_data_km_exp = tf_data_km_exp.get('volatility', {}); st.markdown(f"- **状态:** {vol_data_km_exp.get('status', '-')}")
                                 with col3_exp_km: # ATR, PP & 形态
                                      st.markdown("**ATR, PP & 形态**")
                                      vol_data_km_exp_atr = tf_data_km_exp.get('volatility', {}); atr_value_str_km_exp = vol_data_km_exp_atr.get('atr'); atr_display_km_exp_atr = '-'
                                      try:
                                           if atr_value_str_km_exp is not None: atr_value_float_km_exp = float(atr_value_str_km_exp); atr_display_km_exp_atr = f"{atr_value_float_km_exp:.2f}"
                                      except (ValueError, TypeError): atr_display_km_exp_atr = str(atr_value_str_km_exp) if atr_value_str_km_exp else '-'
                                      st.markdown(f"- **ATR:** {atr_display_km_exp_atr}")
                                      pp_value_str_km_exp = tf_data_km_exp.get('pivot_point'); pp_display_km_exp = '-'
                                      try:
                                           if pp_value_str_km_exp is not None: pp_value_float_km_exp = float(pp_value_str_km_exp); pp_display_km_exp = f"{pp_value_float_km_exp:.2f}"
                                      except (ValueError, TypeError): pp_display_km_exp = str(pp_value_str_km_exp) if pp_value_str_km_exp else '-'
                                      st.markdown(f"- **PP:** {pp_display_km_exp}")
                                      patterns_km_exp = tf_data_km_exp.get('patterns', []); st.markdown("**形态:**")
                                      if patterns_km_exp:
                                           for p_km in patterns_km_exp: st.markdown(f"  - {p_km.get('name', '未知')}")
                                      else: st.markdown("  - 无")
                             else: st.write(tf_data_km_exp)
                             st.divider()
                         else: st.warning("K线时间周期详细数据格式错误。")
                         st.divider()
                         # --- K线原始 JSON (不折叠) ---
                         st.subheader("原始K线JSON数据:")
                         st.json(result_dict_km)
                    else:
                         st.warning("K 线分析数据不完整或格式错误。")
                         st.subheader("原始K线JSON数据:")
                         st.json(result_dict_km)
            elif isinstance(result_dict_km, dict) and (explicit_error_ka_detail := result_dict_km.get('error')):
                 # 显示错误，但不使用 expander
                 st.error(f"分析 {symbol_km_detail} 时出错: {explicit_error_ka_detail}")
                 tb_ka = result_dict_km.get('traceback')
                 if tb_ka:
                     with st.expander("查看错误详情 (Traceback)", expanded=False):
                          st.code(tb_ka, language='python')

# --- K线自动报告标签页 (基本保持不变，修改文件名常量) ---
with tab_kline_auto:
    st.header(f"K 线自动分析报告 (Top {TOP_N_SYMBOLS} 交易量)")
    st.markdown(f"**重要提示:** 此功能依赖一个独立的**后台 K 线分析脚本**每 {AUTO_ANALYSIS_INTERVAL_MINUTES} 分钟运行一次，并将结果写入 `{AUTO_KLINE_RESULTS_FILE}` 文件。") # 使用新常量
    st.markdown("请确保该后台脚本已正确配置并正在运行。")

    if st.button("手动刷新 K 线报告", key="kline_auto_refresh_button"):
        st.rerun()

    auto_kline_results_data = None
    last_kline_update_time_str = "未知"
    kline_file_error = None

    if os.path.exists(AUTO_KLINE_RESULTS_FILE): # 使用新常量
        try:
            kline_file_mod_time = os.path.getmtime(AUTO_KLINE_RESULTS_FILE)
            last_kline_update_time = datetime.fromtimestamp(kline_file_mod_time)
            if datetime.now() - last_kline_update_time > timedelta(minutes=AUTO_ANALYSIS_INTERVAL_MINUTES * 3):
                 st.warning(f"K 线结果文件 `{AUTO_KLINE_RESULTS_FILE}` 最后更新于 {last_kline_update_time.strftime('%Y-%m-%d %H:%M:%S')}，可能已过期。")
            last_kline_update_time_str = last_kline_update_time.strftime('%Y-%m-%d %H:%M:%S')
            with open(AUTO_KLINE_RESULTS_FILE, 'r', encoding='utf-8') as f:
                auto_kline_results_data = json.load(f)
        except json.JSONDecodeError as e:
            kline_file_error = f"读取 K 线结果文件 `{AUTO_KLINE_RESULTS_FILE}` 时 JSON 解析失败: {e}"
            logger.error(kline_file_error)
        except Exception as e:
            kline_file_error = f"读取 K 线结果文件 `{AUTO_KLINE_RESULTS_FILE}` 时发生错误: {e}"
            logger.error(kline_file_error, exc_info=True)
    else:
        kline_file_error = f"K 线结果文件 `{AUTO_KLINE_RESULTS_FILE}` 不存在。请启动后台 K 线分析脚本。"

    st.caption(f"K 线报告数据最后更新时间: {last_kline_update_time_str}")

    if kline_file_error:
        st.error(kline_file_error)
    elif not auto_kline_results_data or not isinstance(auto_kline_results_data, dict):
         st.warning("未找到有效的 K 线自动分析结果或结果格式不正确。")
         logger.warning(f"K 线自动分析结果文件内容无效或非字典: {type(auto_kline_results_data)}")
    else:
        # K 线摘要表逻辑 (保持不变)
        summary_kline_data_list = []
        failed_kline_symbols = []
        # ... (省略 K 线摘要数据准备代码) ...
        logger.info("开始为 K 线自动报告准备摘要数据...")
        for symbol_ka, result_dict_ka in auto_kline_results_data.items():
             if isinstance(result_dict_ka, dict):
                 explicit_error_ka = result_dict_ka.get('error')
                 if explicit_error_ka is None and 'confluence_summary' in result_dict_ka and isinstance(result_dict_ka['confluence_summary'], dict):
                     summary_ka = result_dict_ka['confluence_summary']
                     bias_ka = summary_ka.get('bias', 'N/A')
                     confidence_ka = summary_ka.get('confidence', 'N/A')
                     score_ka = summary_ka.get('weighted_score', 'N/A')
                     score_display_ka = f"{score_ka:.1f}" if isinstance(score_ka, (int, float)) else str(score_ka)
                     current_price_ka = result_dict_ka.get('last_price', 'N/A')
                     price_display_ka = 'N/A'
                     # (价格格式化逻辑)
                     if isinstance(current_price_ka, (int, float)):
                         if current_price_ka > 1000: price_display_ka = f"{current_price_ka:.2f}"
                         elif current_price_ka > 1: price_display_ka = f"{current_price_ka:.4f}"
                         else: price_display_ka = f"{current_price_ka:.6f}"
                     elif isinstance(current_price_ka, str):
                         try:
                             price_float_ka = float(current_price_ka)
                             if price_float_ka > 1000: price_display_ka = f"{price_float_ka:.2f}"
                             elif price_float_ka > 1: price_display_ka = f"{price_float_ka:.4f}"
                             else: price_display_ka = f"{price_float_ka:.6f}"
                         except (ValueError, TypeError): price_display_ka = current_price_ka
                     else: price_display_ka = str(current_price_ka)
                     summary_kline_data_list.append({
                         "交易对": symbol_ka,
                         "偏向": bias_ka,
                         "置信度": confidence_ka,
                         "分数": score_display_ka,
                         "最近价格": price_display_ka,
                         "原始分数": score_ka if isinstance(score_ka, (int, float)) else -999
                     })
                 else:
                     failed_kline_symbols.append(symbol_ka)
             else:
                 failed_kline_symbols.append(symbol_ka)
        logger.info(f"K 线摘要数据准备完成。成功: {len(summary_kline_data_list)}, 失败/跳过: {len(failed_kline_symbols)}.")

        st.markdown("---")
        st.subheader("📈 K 线自动分析摘要")
        if summary_kline_data_list:
            summary_kline_df = pd.DataFrame(summary_kline_data_list)
            # 可以添加排序和样式
            st.dataframe(summary_kline_df, use_container_width=True, hide_index=True)
        else:
            st.info("当前没有可用的 K 线成功分析摘要。")
        if failed_kline_symbols:
             st.caption(f"注意: 以下交易对 K 线分析失败或数据不完整: {', '.join(failed_kline_symbols)}")

        # 成交流详细分析 (折叠) 逻辑 (占位符)
        st.divider()
        st.subheader("🔍 各交易对 K 线详细分析")
        for symbol_ka_detail, result_dict_ka_detail in auto_kline_results_data.items():
            if symbol_ka_detail not in failed_kline_symbols and isinstance(result_dict_ka_detail, dict):
                with st.expander(f"**{symbol_ka_detail}** K 线详细分析", expanded=False):
                     # --- 显示成交量详情 (需要你定义) ---
                     st.info(f"显示 {symbol_ka_detail} 的 K 线详细分析结果。")
                     # 示例：显示 confluence_summary
                     if 'confluence_summary' in result_dict_ka_detail:
                          st.write(result_dict_ka_detail['confluence_summary'])
                     # 显示原始 JSON
                     st.subheader("原始 K 线 JSON 数据:")
                     st.json(result_dict_ka_detail)
                     # --- 显示结束 ---
            elif isinstance(result_dict_ka_detail, dict) and (explicit_error_ka_detail := result_dict_ka_detail.get('error')):
                 st.error(f"分析 {symbol_ka_detail} 时出错: {explicit_error_ka_detail}")
                 tb_ka = result_dict_ka_detail.get('traceback')
                 if tb_ka:
                     with st.expander("查看错误详情 (Traceback)", expanded=False):
                          st.code(tb_ka, language='python')
        # --- 占位符结束 ---


# --- 新增：成交量手动分析标签页 ---
with tab_volume_manual:
    st.header("手动触发单币种成交流分析")
    st.markdown(f"分析结果将在 **{CACHE_TTL_SECONDS}秒** 内为相同参数缓存。")

    # 复用 K 线的常用币种列表和占位符
    POPULAR_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT", "MATICUSDT", "DOTUSDT"]
    SELECTBOX_PLACEHOLDER = "--- 或选择常用交易对 ---"

    col1_vm, col2_vm = st.columns([2, 1])
    with col1_vm:
        # 使用 .get() 安全地获取上次 K 线分析的币种作为默认值
        last_k_symbol = st.session_state.get('last_analyzed_symbol')
        symbol_input_vm = st.text_input("输入交易对 (例如 BTCUSDT):", last_k_symbol if last_k_symbol else '', key="volume_manual_symbol_input").upper()
        
        # 计算 selectbox 的默认 index 时，也要安全地检查 last_k_symbol
        default_symbol_index_vm = 0 # 默认为占位符
        if last_k_symbol and last_k_symbol in POPULAR_SYMBOLS:
            try:
                default_symbol_index_vm = POPULAR_SYMBOLS.index(last_k_symbol) + 1 # +1 因为 options 里第一项是占位符
            except ValueError:
                 pass # 如果不在列表中，保持默认值

        symbol_selected_vm = st.selectbox("或选择常用交易对:",
                                       options=[SELECTBOX_PLACEHOLDER] + sorted(POPULAR_SYMBOLS),
                                       index=default_symbol_index_vm, # 使用安全计算的 index
                                       key="volume_manual_symbol_select")
    with col2_vm:
        # 使用 .get() 安全地获取上次 K 线分析的市场类型
        last_k_market = st.session_state.get('last_analyzed_market')
        market_type_options_vm = {'U本位合约': 'futures', '现货': 'spot'}
        market_keys_list_vm = list(market_type_options_vm.keys())
        default_market_index_vm = 0
        if last_k_market and last_k_market in market_keys_list_vm:
             try:
                 default_market_index_vm = market_keys_list_vm.index(last_k_market)
             except ValueError:
                 pass # 保持默认
                 
        selected_mt_display_vm = st.selectbox("选择市场类型:",
                                           market_keys_list_vm,
                                           index=default_market_index_vm, # 使用安全计算的 index
                                           key="volume_manual_market_type")
        market_type_vm = market_type_options_vm[selected_mt_display_vm]

    analyze_button_vm = st.button("开始成交流分析", key="volume_manual_analyze_button")

    symbol_to_analyze_vm = None
    if analyze_button_vm:
        if symbol_selected_vm != SELECTBOX_PLACEHOLDER:
            symbol_to_analyze_vm = symbol_selected_vm
        elif symbol_input_vm:
            symbol_to_analyze_vm = symbol_input_vm

        if not symbol_to_analyze_vm:
            st.warning("请输入或选择一个交易对。")
        # 移除对 selected_timeframes_vm 的检查
        # elif not selected_timeframes_vm: 
        #     st.warning("请至少选择一个时间周期。")
        else:
            current_minute_str_vm = datetime.now().strftime("%Y-%m-%d %H:%M")
            # timeframes_tuple_vm = tuple(sorted(selected_timeframes_vm)) # 不再需要

            # 更新 spinner 提示信息
            with st.spinner(f"正在分析成交流 {symbol_to_analyze_vm} ({market_type_vm})..."): 
                # 调用成交量分析的缓存函数，不再传递 timeframes_tuple_vm
                st.session_state.manual_volume_analysis_result = get_manual_volume_analysis_cached(
                    symbol_to_analyze_vm,
                    market_type_vm,
                    # timeframes_tuple_vm, # 移除
                    current_minute_str_vm
                )
                # 更新用于显示的变量 (保持不变)
                st.session_state.last_analyzed_volume_symbol = symbol_to_analyze_vm
                st.session_state.last_analyzed_volume_market = selected_mt_display_vm

    # 显示成交量手动分析结果 (占位符逻辑)
    manual_volume_result_placeholder = st.empty()

    logger.debug(f"准备显示手动成交量结果。Session state 内容: {st.session_state.get('manual_volume_analysis_result')}")

    if st.session_state.manual_volume_analysis_result:
        result_dict_vm = st.session_state.manual_volume_analysis_result
        display_symbol_vm = st.session_state.get('last_analyzed_volume_symbol', '未知币种')
        display_market_vm = st.session_state.get('last_analyzed_volume_market', '未知市场')

        with manual_volume_result_placeholder.container():
            st.markdown("---")
            st.subheader(f"成交流分析结果: {display_symbol_vm} ({display_market_vm})")

            if isinstance(result_dict_vm, dict) and result_dict_vm.get('error'): # 检查 error 键
                logger.error(f"显示成交量分析失败结果: {result_dict_vm['error']}")
                st.error(f"成交量分析失败: {result_dict_vm['error']}")
            elif isinstance(result_dict_vm, dict):
                # --- 根据实际返回的 JSON 结构显示结果 ---
                
                # --- 1. 评分 & 分析详情 (保持) ---
                score_value = None
                try:
                    score_value = result_dict_vm.get('interpretation', {}).get('bias_score')
                except AttributeError as e:
                    logger.error(f"访问评分 interpretation['bias_score'] 时出错: {e}")
                if score_value is not None:
                    score_display = f"{score_value:.1f}" if isinstance(score_value, (int, float)) else str(score_value)
                    st.metric("评分 (Bias Score)", score_display)
                else:
                    st.metric("评分", "N/A")
                    logger.warning(f"未能在 interpretation['bias_score'] 找到评分。实际顶层键: {list(result_dict_vm.keys())}")
                
                details_list = None
                try:
                    details_list = result_dict_vm.get('interpretation', {}).get('overall', {}).get('details')
                except AttributeError as e:
                    logger.error(f"访问细节 interpretation['overall']['details'] 时出错: {e}")
                if isinstance(details_list, list) and details_list:
                    st.subheader("分析详情:")
                    for item in details_list:
                        if isinstance(item, str):
                            cleaned_item = item.split(" : ", 1)[-1] if " : " in item else item
                            st.markdown(f"- {cleaned_item}")
                        else:
                            st.markdown(f"- {item}")
                else:
                    st.info("未找到有效的分析详情。")
                    logger.warning(f"未能在 interpretation['overall']['details'] 找到详情列表。实际顶层键: {list(result_dict_vm.keys())}")
                st.divider()
                
                # --- 2. 新增：关键指标展示 (从 overall 提取) ---
                st.subheader("关键指标:")
                overall_metrics = result_dict_vm.get('overall', {}) # 安全获取 overall 字典
                
                col_m1, col_m2, col_m3 = st.columns(3)
                
                # Delta 成交量
                delta_vol = overall_metrics.get('delta_volume')
                delta_display = f"{delta_vol:,.2f}" if isinstance(delta_vol, (int, float)) else "N/A"
                col_m1.metric("Delta 成交量", delta_display)
                
                # 主动买卖量比
                taker_vol_ratio = overall_metrics.get('taker_volume_ratio')
                tvr_display = f"{taker_vol_ratio:.2f}" if isinstance(taker_vol_ratio, (int, float)) else "N/A"
                col_m2.metric("主动买卖量比 (买/卖)", tvr_display)

                # 主动买卖笔数比
                taker_trade_ratio = overall_metrics.get('taker_trade_ratio')
                ttr_display = f"{taker_trade_ratio:.2f}" if isinstance(taker_trade_ratio, (int, float)) else "N/A"
                col_m3.metric("主动买卖笔数比 (买/卖)", ttr_display)

                col_m4, col_m5, col_m6 = st.columns(3)

                # 总成交额
                total_vol = overall_metrics.get('total_quote_volume')
                total_vol_display = f"{total_vol:,.2f}" if isinstance(total_vol, (int, float)) else "N/A"
                col_m4.metric("总成交额", total_vol_display)

                # 每秒成交笔数
                trades_ps = overall_metrics.get('trades_per_second')
                tps_display = f"{trades_ps:.2f}" if isinstance(trades_ps, (int, float)) else "N/A"
                col_m5.metric("每秒成交笔数", tps_display)

                # 平均每笔成交额
                avg_trade_size = overall_metrics.get('avg_trade_size_quote')
                avg_trade_display = f"{avg_trade_size:,.2f}" if isinstance(avg_trade_size, (int, float)) else "N/A"
                col_m6.metric("平均每笔成交额", avg_trade_display)
                
                # 价格变动
                price_change = overall_metrics.get('price_change_pct')
                price_change_display = f"{price_change:.4f}%" if isinstance(price_change, (int, float)) else "N/A"
                st.metric("价格变动百分比", price_change_display)
                st.divider()
                
                # --- 3. 新增：大单分析展示 (从 overall -> large_trades_analysis 提取) ---
                st.subheader("大单分析 (P98):") # 假设只显示 P98
                large_analysis_all = overall_metrics.get('large_trades_analysis', {})
                # --- 修正：使用字符串 "98" 作为键访问 --- 
                p98_analysis = large_analysis_all.get("98", {}) # 安全获取 P98 分析字典 (使用字符串键)
                
                if p98_analysis and not p98_analysis.get('error'): # 确保有数据且没有错误
                    col_l1, col_l2, col_l3 = st.columns(3)
                    
                    threshold = p98_analysis.get('large_order_threshold_quote')
                    th_display = f"{threshold:,.2f}" if isinstance(threshold, (int, float)) else "N/A"
                    col_l1.metric("P98 大单阈值", th_display)
                    
                    count = p98_analysis.get('large_trades_count')
                    col_l2.metric("P98 大单数量", str(count) if count is not None else "N/A")
                    
                    large_vol = p98_analysis.get('large_total_quote_volume')
                    lv_display = f"{large_vol:,.2f}" if isinstance(large_vol, (int, float)) else "N/A"
                    col_l3.metric("P98 大单总额", lv_display)
                    
                    col_l4, col_l5, col_l6 = st.columns(3)
                    
                    large_tvr = p98_analysis.get('large_taker_volume_ratio')
                    ltvr_display = f"{large_tvr:.2f}" if isinstance(large_tvr, (int, float)) else "N/A"
                    col_l4.metric("P98 大单买卖量比", ltvr_display)
                    
                    buy_vwap = p98_analysis.get('large_taker_buy_vwap')
                    bvwap_display = f"{buy_vwap:.2f}" if isinstance(buy_vwap, (int, float)) else "N/A"
                    col_l5.metric("P98 大单买方VWAP", bvwap_display)
                    
                    sell_vwap = p98_analysis.get('large_taker_sell_vwap')
                    svwap_display = f"{sell_vwap:.2f}" if isinstance(sell_vwap, (int, float)) else "N/A"
                    col_l6.metric("P98 大单卖方VWAP", svwap_display)
                    
                else:
                    st.info("未找到有效的 P98 大单分析数据。")

                st.divider()
                
                # --- 4. 原始 JSON (保持) ---
                with st.expander("查看原始成交量JSON数据", expanded=False):
                    st.json(result_dict_vm)
                # --- 显示结束 ---
            elif result_dict_vm.get('warning'): # 处理可能的警告信息
                 st.warning(result_dict_vm['warning'])
                 with st.expander("查看原始返回内容", expanded=False):
                      st.write(result_dict_vm.get('raw_result'))
            else:
                 # 处理未知返回类型
                 st.warning("成交量分析返回数据格式未知或无法解析。")
                 st.write("原始返回内容:", result_dict_vm)


# --- 新增：成交量自动报告标签页 ---
with tab_volume_auto:
    st.header(f"成交流自动分析报告 (Top {TOP_N_SYMBOLS} 交易量)")
    st.markdown(f"**重要提示:** 此功能依赖一个独立的**后台成交流分析脚本**每 {AUTO_ANALYSIS_INTERVAL_MINUTES} 分钟运行一次，并将结果写入 `{AUTO_VOLUME_RESULTS_FILE}` 文件。") # 使用新常量
    st.markdown("请确保该后台脚本已正确配置并正在运行。")

    if st.button("手动刷新成交流报告", key="volume_auto_refresh_button"):
        st.rerun()

    auto_volume_results_data = None
    last_volume_update_time_str = "未知"
    volume_file_error = None

    if os.path.exists(AUTO_VOLUME_RESULTS_FILE): # 使用新常量
        try:
            volume_file_mod_time = os.path.getmtime(AUTO_VOLUME_RESULTS_FILE)
            last_volume_update_time = datetime.fromtimestamp(volume_file_mod_time)
            if datetime.now() - last_volume_update_time > timedelta(minutes=AUTO_ANALYSIS_INTERVAL_MINUTES * 3):
                 st.warning(f"成交流结果文件 `{AUTO_VOLUME_RESULTS_FILE}` 最后更新于 {last_volume_update_time.strftime('%Y-%m-%d %H:%M:%S')}，可能已过期。")
            last_volume_update_time_str = last_volume_update_time.strftime('%Y-%m-%d %H:%M:%S')
            with open(AUTO_VOLUME_RESULTS_FILE, 'r', encoding='utf-8') as f:
                auto_volume_results_data = json.load(f)
        except json.JSONDecodeError as e:
            volume_file_error = f"读取成交流结果文件 `{AUTO_VOLUME_RESULTS_FILE}` 时 JSON 解析失败: {e}"
            logger.error(volume_file_error)
        except Exception as e:
            volume_file_error = f"读取成交流结果文件 `{AUTO_VOLUME_RESULTS_FILE}` 时发生错误: {e}"
            logger.error(volume_file_error, exc_info=True)
    else:
        volume_file_error = f"成交流结果文件 `{AUTO_VOLUME_RESULTS_FILE}` 不存在。请启动后台成交流分析脚本。"

    st.caption(f"成交流报告数据最后更新时间: {last_volume_update_time_str}")

    if volume_file_error:
        st.error(volume_file_error)
    elif not auto_volume_results_data or not isinstance(auto_volume_results_data, dict):
         st.warning("未找到有效的成交流自动分析结果或结果格式不正确。")
         logger.warning(f"成交流自动分析结果文件内容无效或非字典: {type(auto_volume_results_data)}")
    else:
        # --- 更新：准备成交量摘要数据 ---
        summary_volume_data_list = []
        failed_volume_symbols = []
        logger.info("开始为成交流自动报告准备摘要数据...")
        
        for symbol_va, result_dict_va in auto_volume_results_data.items():
            if isinstance(result_dict_va, dict):
                explicit_error_va = result_dict_va.get('error')
                
                # --- 更新成功判断条件 --- 
                # 检查没有错误，并且包含表示成功的关键键 (例如 interpretation 和 overall)
                if explicit_error_va is None and 'interpretation' in result_dict_va and 'overall' in result_dict_va:
                    try:
                         # --- 提取成交量摘要信息 (使用正确的路径) ---
                         interpretation_data = result_dict_va.get('interpretation', {})
                         overall_data = result_dict_va.get('overall', {})
                         
                         score_va = interpretation_data.get('bias_score', 'N/A')
                         score_display_va = f"{score_va:.1f}" if isinstance(score_va, (int, float)) else str(score_va)
                         
                         delta_vol_va = overall_data.get('delta_volume')
                         delta_display_va = f"{delta_vol_va:,.2f}" if isinstance(delta_vol_va, (int, float)) else "N/A"
                         
                         tvr_va = overall_data.get('taker_volume_ratio')
                         tvr_display_va = f"{tvr_va:.2f}" if isinstance(tvr_va, (int, float)) else "N/A"
                         
                         # 从 interpretation -> overall -> details 提取第一条详情作为摘要
                         details_list_va = interpretation_data.get('overall', {}).get('details', [])
                         primary_detail_va = ""
                         if details_list_va and isinstance(details_list_va[0], str):
                              cleaned_detail = details_list_va[0].split(" : ", 1)[-1] if " : " in details_list_va[0] else details_list_va[0]
                              primary_detail_va = cleaned_detail
                         # --- 提取结束 --- 
                              
                         summary_volume_data_list.append({
                             "交易对": symbol_va,
                             "评分": score_display_va,
                             "主要详情": primary_detail_va, # 使用提取的第一条详情
                             "Delta成交量": delta_display_va,
                             "主动买卖量比": tvr_display_va,
                             # 可以根据需要添加更多列 (如总成交额等)
                             "原始评分": score_va if isinstance(score_va, (int, float)) else -999 # 用于排序
                         })
                    except Exception as e: # 捕获提取数据时的意外错误
                         logger.error(f"为 {symbol_va} 提取摘要数据时出错: {e}", exc_info=True)
                         failed_volume_symbols.append(symbol_va) # 提取失败也算失败
                else:
                    # 如果有错误或缺少关键键，则标记为失败
                    failed_volume_symbols.append(symbol_va)
                    if explicit_error_va:
                         logger.warning(f"自动报告摘要跳过 {symbol_va}: 分析返回错误 '{explicit_error_va}'")
                    else:
                         logger.warning(f"自动报告摘要跳过 {symbol_va}: 缺少 interpretation 或 overall 键。")
            else:
                 # 如果顶层不是字典，标记为失败
                 failed_volume_symbols.append(symbol_va)
                 logger.error(f"自动报告摘要跳过 {symbol_va}: 顶层数据不是字典。")
                 
        logger.info(f"成交流摘要数据准备完成。成功: {len(summary_volume_data_list)}, 失败/跳过: {len(failed_volume_symbols)}.")

        # --- 更新：显示成交量摘要表 ---
        st.markdown("---")
        st.subheader("📊 成交流自动分析摘要")
        if summary_volume_data_list:
            summary_volume_df = pd.DataFrame(summary_volume_data_list)
            # 按评分排序 (可选)
            summary_volume_df = summary_volume_df.sort_values(by="原始评分", ascending=False).drop(columns=["原始评分"])
            # (可以添加样式函数，例如根据评分高亮)
            display_cols_va = ["交易对", "评分", "主要详情", "Delta成交量", "主动买卖量比"]
            valid_cols_va = [col for col in display_cols_va if col in summary_volume_df.columns]
            st.dataframe(summary_volume_df[valid_cols_va], use_container_width=True, hide_index=True)
        else:
            st.info("当前没有可用的成交流成功分析摘要。")
        if failed_volume_symbols:
             # 更新提示信息，只显示真正失败或数据不完整的
             st.caption(f"注意: 以下交易对成交流分析失败或数据不完整: {', '.join(failed_volume_symbols)}")

        # --- 更新：成交量详细分析 (折叠) 逻辑 ---
        st.divider()
        st.subheader("🔍 各交易对成交流详细分析")
        for symbol_va_detail, result_dict_va_detail in auto_volume_results_data.items():
            # 只为真正成功的币种显示展开区域
            if symbol_va_detail not in failed_volume_symbols and isinstance(result_dict_va_detail, dict):
                with st.expander(f"**{symbol_va_detail}** 成交流详细分析", expanded=False):
                     # --- 更新：显示成交量详情 (复用手动分析的逻辑) ---
                     # st.info(f"显示 {symbol_va_detail} 的成交流详细分析结果。") # 移除旧提示
                     
                     # 1. 评分 & 分析详情
                     score_va_d = None
                     try: score_va_d = result_dict_va_detail.get('interpretation', {}).get('bias_score')
                     except AttributeError: pass
                     if score_va_d is not None: st.metric("评分 (Bias Score)", f"{score_va_d:.1f}" if isinstance(score_va_d, (int, float)) else str(score_va_d))
                     else: st.metric("评分", "N/A")
                     
                     details_list_va_d = None
                     try: details_list_va_d = result_dict_va_detail.get('interpretation', {}).get('overall', {}).get('details')
                     except AttributeError: pass
                     if isinstance(details_list_va_d, list) and details_list_va_d:
                         st.subheader("分析详情:")
                         for item_d in details_list_va_d:
                              if isinstance(item_d, str): cleaned_item_d = item_d.split(" : ", 1)[-1] if " : " in item_d else item_d; st.markdown(f"- {cleaned_item_d}")
                              else: st.markdown(f"- {item_d}")
                     else: st.info("未找到分析详情。")
                     st.divider()
                     
                     # 2. 关键指标
                     st.subheader("关键指标:")
                     overall_metrics_d = result_dict_va_detail.get('overall', {})
                     # ... (省略与手动分析类似的 st.columns 和 st.metric 代码来显示关键指标) ...
                     col_m1d, col_m2d, col_m3d = st.columns(3)
                     delta_vol_d = overall_metrics_d.get('delta_volume'); delta_display_d = f"{delta_vol_d:,.2f}" if isinstance(delta_vol_d, (int, float)) else "N/A"; col_m1d.metric("Delta 成交量", delta_display_d)
                     tvr_d = overall_metrics_d.get('taker_volume_ratio'); tvr_display_d = f"{tvr_d:.2f}" if isinstance(tvr_d, (int, float)) else "N/A"; col_m2d.metric("主动买卖量比 (买/卖)", tvr_display_d)
                     ttr_d = overall_metrics_d.get('taker_trade_ratio'); ttr_display_d = f"{ttr_d:.2f}" if isinstance(ttr_d, (int, float)) else "N/A"; col_m3d.metric("主动买卖笔数比 (买/卖)", ttr_display_d)
                     col_m4d, col_m5d, col_m6d = st.columns(3)
                     total_vol_d = overall_metrics_d.get('total_quote_volume'); total_vol_display_d = f"{total_vol_d:,.2f}" if isinstance(total_vol_d, (int, float)) else "N/A"; col_m4d.metric("总成交额", total_vol_display_d)
                     trades_ps_d = overall_metrics_d.get('trades_per_second'); tps_display_d = f"{trades_ps_d:.2f}" if isinstance(trades_ps_d, (int, float)) else "N/A"; col_m5d.metric("每秒成交笔数", tps_display_d)
                     avg_trade_size_d = overall_metrics_d.get('avg_trade_size_quote'); avg_trade_display_d = f"{avg_trade_size_d:,.2f}" if isinstance(avg_trade_size_d, (int, float)) else "N/A"; col_m6d.metric("平均每笔成交额", avg_trade_display_d)
                     price_change_d = overall_metrics_d.get('price_change_pct'); price_change_display_d = f"{price_change_d:.4f}%" if isinstance(price_change_d, (int, float)) else "N/A"; st.metric("价格变动百分比", price_change_display_d)
                     st.divider()
                     
                     # 3. 大单分析 (P98)
                     st.subheader("大单分析 (P98):")
                     large_analysis_all_d = overall_metrics_d.get('large_trades_analysis', {})
                     # --- 修正：使用字符串 "98" 作为键访问 --- 
                     p98_analysis_d = large_analysis_all_d.get("98", {}) # (使用字符串键)
                     if p98_analysis_d and not p98_analysis_d.get('error'):
                         # ... (内部显示逻辑保持不变) ...
                         col_l1d, col_l2d, col_l3d = st.columns(3)
                         threshold_d = p98_analysis_d.get('large_order_threshold_quote'); th_display_d = f"{threshold_d:,.2f}" if isinstance(threshold_d, (int, float)) else "N/A"; col_l1d.metric("P98 大单阈值", th_display_d)
                         count_d = p98_analysis_d.get('large_trades_count'); col_l2d.metric("P98 大单数量", str(count_d) if count_d is not None else "N/A")
                         large_vol_d = p98_analysis_d.get('large_total_quote_volume'); lv_display_d = f"{large_vol_d:,.2f}" if isinstance(large_vol_d, (int, float)) else "N/A"; col_l3d.metric("P98 大单总额", lv_display_d)
                         col_l4d, col_l5d, col_l6d = st.columns(3)
                         large_tvr_d = p98_analysis_d.get('large_taker_volume_ratio'); ltvr_display_d = f"{large_tvr_d:.2f}" if isinstance(large_tvr_d, (int, float)) else "N/A"; col_l4d.metric("P98 大单买卖量比", ltvr_display_d)
                         buy_vwap_d = p98_analysis_d.get('large_taker_buy_vwap'); bvwap_display_d = f"{buy_vwap_d:.2f}" if isinstance(buy_vwap_d, (int, float)) else "N/A"; col_l5d.metric("P98 大单买方VWAP", bvwap_display_d)
                         sell_vwap_d = p98_analysis_d.get('large_taker_sell_vwap'); svwap_display_d = f"{sell_vwap_d:.2f}" if isinstance(sell_vwap_d, (int, float)) else "N/A"; col_l6d.metric("P98 大单卖方VWAP", svwap_display_d)
                     else: st.info("未找到有效的 P98 大单分析数据。")
                     st.divider()

                     # 4. 原始 JSON
                     st.subheader("原始成交流JSON数据:")
                     st.json(result_dict_va_detail)
                     # --- 显示结束 ---
                     
            # 处理实际失败的币种 (在 failed_volume_symbols 列表中的)
            elif symbol_va_detail in failed_volume_symbols and isinstance(result_dict_va_detail, dict) and (explicit_error_va_detail := result_dict_va_detail.get('error')):
                 # 直接显示错误信息，不使用 expander
                 st.error(f"分析 {symbol_va_detail} 时出错: {explicit_error_va_detail}")
                 tb_va = result_dict_va_detail.get('traceback')
                 if tb_va:
                     # 允许为错误信息使用 expander
                     with st.expander("查看错误详情 (Traceback)", expanded=False):
                          st.code(tb_va, language='python')
                 st.divider() # 添加分隔符
                 
        # --- 详细分析显示结束 ---

# --- 页脚 (保持不变) ---
st.markdown("---")
# ... (内测交流和免责声明代码保持不变) ...
with st.expander("内测交流 (点击展开)", expanded=False):
    st.markdown("本工具目前处于内部测试阶段，欢迎您加入交流群，分享使用体验、反馈问题、提出宝贵建议或一起探讨 K 线与成交流分析思路！请添加微信号：Q54855742，备注'K线分析工具'，我会邀请您入群。") # 更新文本
with st.expander("免责声明 (点击展开)", expanded=False):
    st.caption("重要提示：加密货币市场具有高风险性，价格波动剧烈。本工具提供的所有分析、数据、图表和信息仅基于历史数据和技术指标生成，旨在提供市场观察和学习参考，不构成任何形式的投资建议、推荐或财务意见。用户应自行承担所有投资决策的风险。在做出任何投资决策前，请务必进行独立研究，并咨询合格的财务顾问。本工具的开发者不对任何因使用或依赖本工具信息而产生的直接或间接损失负责。")

# (移除末尾多余的标记) 