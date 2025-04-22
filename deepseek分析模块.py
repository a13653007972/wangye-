import requests
import json
import os
import sys # 导入 sys 模块
from dotenv import load_dotenv # <--- 添加导入

# --- 导入其他分析模块 --- 
try:
    from k线分析模块 import 分析K线结构与形态
except ImportError as e:
    print(f"警告：无法导入 k线分析模块: {e}。将无法获取真实K线分析。")
    def 分析K线结构与形态(*args, **kwargs): return None, None # 返回 None 以便后续处理

try:
    from 订单簿分析 import 分析订单簿
except ImportError as e:
    print(f"警告：无法导入 订单簿分析模块: {e}。将无法获取真实订单簿分析。")
    def 分析订单簿(*args, **kwargs): return None # 返回 None

try:
    import 微观趋势动量
    # 需要导入配置以调用整合函数
    from 配置 import MICRO_TREND_CONFIG
except ImportError as e:
    print(f"警告：无法导入 微观趋势动量 或其配置: {e}。将无法获取真实微观趋势分析。")
    微观趋势动量 = None
    MICRO_TREND_CONFIG = {} # 提供空配置
    # 定义占位函数
    def 执行多周期分析(*args, **kwargs): return None
    def 整合多周期信号(*args, **kwargs): return {'combined_signal': '未知', 'score': 0, 'reasoning': ['微观趋势模块导入失败']}
    if 微观趋势动量: # 如果模块导入成功但配置导入失败
        整合多周期信号 = 微观趋势动量.整合多周期信号 # 覆盖占位符
        执行多周期分析 = 微观趋势动量.执行多周期分析 # 覆盖占位符

try:
    import 深度分析模块
except ImportError as e:
    print(f"警告：无法导入 深度分析模块: {e}。将无法获取真实深度分析。")
    深度分析模块 = None
    # 定义占位函数
    def 分析多层级成交量(*args, **kwargs): return {'error': '深度分析模块导入失败'}

try:
    import 箱体突破分析
except ImportError as e:
    print(f"警告：无法导入 箱体突破分析: {e}。将无法获取真实箱体突破分析。")
    箱体突破分析 = None
    # 定义占位函数
    def 分析箱体突破(*args, **kwargs): return {'status': '未知', 'reason': '箱体突破模块导入失败'}

try:
    import 成交流分析
except ImportError as e:
    print(f"警告：无法导入 成交流分析: {e}。将无法获取真实成交量分析。")
    成交流分析 = None
    # 定义占位函数
    def 分析成交流(*args, **kwargs): return {'error': '成交流分析模块导入失败'}
    def 解读成交流分析(*args, **kwargs): return "(成交流分析模块导入失败)"

# --- 导入结束 ---

# --- 在读取环境变量之前，加载 .env 文件 ---
# 这将查找当前目录或父目录中的 .env 文件并加载
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
else:
    print("(deepseek分析模块) 未找到 .env 文件，依赖系统环境变量或父脚本加载。")
# --- .env 加载结束 ---

# --- 尝试强制设置标准输出/错误的编码为 UTF-8 ---
try:
    # 检查是否支持 reconfigure 方法 (Python 3.7+)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
except Exception as e:
    print(f"警告：尝试重新配置 sys.stdout/stderr 编码时出错: {e}")

# --- 配置加载区域 (移除配置文件读取) ---
# CONFIG_FILE = 'config.json'
# print(f"--- 尝试加载配置文件: {CONFIG_FILE} ---")
# config = {}
# try:
#     with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
#         config = json.load(f)
# except FileNotFoundError:
#     print(f"错误：配置文件 '{CONFIG_FILE}' 未找到。请创建该文件并填入必要信息。")
#     exit(1)
# except json.JSONDecodeError:
#     print(f"错误：配置文件 '{CONFIG_FILE}' 格式错误，无法解析 JSON。")
#     exit(1)
# except Exception as e:
#     print(f"错误：读取配置文件 '{CONFIG_FILE}' 时发生未知错误: {e}")
#     exit(1)

# --- 直接从环境变量加载配置 ---
# !! 警告：请确保运行前已设置 DEEPSEEK_API_KEY 环境变量或在 .env 文件中定义 !!
# !! 如果未设置，将使用占位符，导致 API 调用失败 !!
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "YOUR_DEEPSEEK_API_KEY_PLACEHOLDER")
# --- 添加检查确保密钥已配置 ---
if deepseek_api_key == "YOUR_DEEPSEEK_API_KEY_PLACEHOLDER" or not deepseek_api_key:
    print("错误：DeepSeek API Key 未在 .env 文件中配置或环境变量未设置。请检查配置后重试。")
    # 可以选择退出程序，防止后续错误
    # exit(1)

deepseek_api_endpoint = os.getenv("DEEPSEEK_API_ENDPOINT", "https://api.deepseek.com/v1/chat/completions") # 也可从环境变量获取，提供默认值
deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat") # 同上
deepseek_max_tokens = int(os.getenv("DEEPSEEK_MAX_TOKENS", 500)) # 同上，注意转为整数
deepseek_temperature = float(os.getenv("DEEPSEEK_TEMPERATURE", 0.7)) # 同上，注意转为浮点数

# --- 占位符分析函数 (模拟其他模块) ---
# !! 注意：这些函数目前只返回固定文本，后续需要替换为真正的分析逻辑 !!

def get_kline_analysis():
    # 模拟 K 线分析模块的输出
    # TODO: 实现真正的 K 线分析逻辑，获取动态数据
    return '日线级别出现看涨吞没形态 (发生在 50000 附近)，收盘价 (51000) 高于5日均线 (50500)'

def get_volume_analysis():
    # 模拟成交量分析模块的输出
    # TODO: 实现真正的成交量分析逻辑
    return '成交量较前一日显著放大，呈价涨量增态势'

def get_order_book_analysis():
    # 模拟订单簿分析模块的输出
    # TODO: 实现真正的订单簿分析逻辑
    return '买一价位 (51000) 挂单量远大于卖一价位 (51050)'

def get_micro_trend_analysis():
    # 模拟微观趋势动量分析模块的输出
    # TODO: 实现真正的微观趋势分析逻辑
    return '5分钟级别MACD指标金叉向上'

def get_depth_analysis():
    # 模拟深度分析模块的输出
    # TODO: 实现真正的深度分析逻辑
    return '累计买单深度是累计卖单深度的1.5倍'

def get_breakout_analysis():
    # 模拟箱体突破分析模块的输出
    # TODO: 实现真正的箱体突破分析逻辑
    return '价格成功突破近期形成的震荡箱体上沿 (50800)，且未跌回'

# --- 核心分析函数 ---
def analyze_with_deepseek(technical_data: dict) -> str:
    """
    使用 DeepSeek API 分析整合后的技术数据。

    Args:
        technical_data (dict): 一个包含来自各个技术分析模块结果的字典。
                               例如: 
                               {
                                   'kline_analysis': '看涨信号，出现金叉',
                                   'volume_analysis': '成交量放大',
                                   'order_book_analysis': '买盘压力增加',
                                   'micro_trend': '向上动量增强',
                                   'depth_analysis': '买方深度优于卖方',
                                   'breakout_analysis': '向上突破箱体上沿'
                                   # ... 其他模块数据
                               }

    Returns:
        str: DeepSeek API 返回的分析结果文本。如果出错则返回错误信息。
    """

    # --- 修改检查逻辑，现在检查环境变量加载后的结果 ---
    if deepseek_api_key == "YOUR_DEEPSEEK_API_KEY_PLACEHOLDER" or not deepseek_api_key:
        # 这个错误信息现在由脚本开头的检查处理，但保留这里的返回以防万一
        return "错误：DeepSeek API Key 未正确配置。请检查 .env 文件或环境变量。"

    # 1. 整合技术数据，构建更结构化的 Prompt
    prompt_segments = [
        "你是一位专注于加密货币市场的短线交易分析师。", # 更具体的角色设定
        "请基于以下多个技术分析维度的数据，对当前市场状况进行综合分析。",
        "\n输入数据:",
    ]
    # 将字典数据格式化为更清晰的列表
    for module, analysis in technical_data.items():
        prompt_segments.append(f"- {module}: {analysis}")

    prompt_segments.extend([
        "\n分析要求:",
        "- 判断当前主要的市场情绪 (例如：看涨、看跌、震荡、谨慎)。",
        "- 预测短期内最可能的趋势方向。",
        "- 指出明确的关键支撑位和阻力位 (请包含输入数据中提供的具体价格)。",
        "- 基于提供的支撑/阻力价格，给出具体的**合约交易**入场点建议 (例如：在 X 价格附近**做多/做空**)。",
        "- 给出明确的**合约交易**止损位建议 (例如：止损设置在 Y 价格以下/以上)。",
        "- 给出明确的**合约交易**止盈位建议 (例如：目标止盈在 Z 价格附近)。",
        "- 简述主要的风险提示。",
        "\n请注意：",
        "- 使用简洁的文本格式进行输出。",
        "- 避免使用 Markdown 标题符号 (例如 #, ##, ### 等)。",
        "- 可以使用数字或 '-' 进行分点。",
        "\n请给出简洁、条理清晰的分析报告："
    ])

    prompt_message = "\n".join(prompt_segments)

    # 2. 准备 API 请求数据
    headers = {
        "Authorization": f"Bearer {deepseek_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": deepseek_model,
        "messages": [
            # 更新 system message 以匹配角色设定
            {"role": "system", "content": "你是一位专注于加密货币市场的短线交易分析师。"},
            {"role": "user", "content": prompt_message}
        ],
        "max_tokens": deepseek_max_tokens,
        "temperature": deepseek_temperature
    }

    # --- 外层 Try-Except 块，专门捕获 UnicodeEncodeError --- 
    try: 
        # --- 原有的 API 调用和异常处理逻辑 --- 
        try:
            response = requests.post(deepseek_api_endpoint, headers=headers, json=payload, timeout=30)
            response.raise_for_status() # 检查 HTTP 错误状态

            # 4. 解析返回结果
            result = response.json()
            
            # 检查返回结构是否符合预期 (DeepSeek API 可能有特定结构)
            if "choices" in result and len(result["choices"]) > 0 and "message" in result["choices"][0] and "content" in result["choices"][0]["message"]:
                analysis_content = result["choices"][0]["message"]["content"].strip()
                return analysis_content
            else:
                print(f"警告：DeepSeek API 返回结构异常: {result}")
                return "错误：无法从 DeepSeek API 响应中提取分析内容。"

        # --- 修改后的异常处理 --- 
        except requests.exceptions.HTTPError as http_err:
            # 单独处理 HTTP 错误 (4xx, 5xx)
            status_code = http_err.response.status_code
            response_text = ""
            try:
                # 尝试用 utf-8 解码响应内容
                response_text = http_err.response.content.decode('utf-8', errors='replace')
            except Exception:
                # 如果解码失败，尝试获取原始文本 (可能仍有问题)
                try:
                    response_text = http_err.response.text
                except Exception:
                    response_text = "[无法解码或获取响应文本]"
            
            print(f"错误：DeepSeek API 请求失败，HTTP 状态码: {status_code}")
            print(f"响应内容: {response_text}")
            return f"错误：DeepSeek API 请求失败 (HTTP {status_code})"

        except requests.exceptions.RequestException as e:
            # 处理其他请求相关的错误 (连接错误、超时等)
            print(f"错误：调用 DeepSeek API 时发生网络或请求错误。")
            print(f"异常类型: {type(e).__name__}")
            # 避免打印可能导致编码错误的 e 本身
            # print(f"具体错误: {e}") 
            return f"错误：调用 DeepSeek API 时发生网络或请求错误 ({type(e).__name__})"

        except json.JSONDecodeError:
            # 处理 JSON 解析错误
            response_text = ""
            try:
                # 尝试获取原始响应文本
                if 'response' in locals() and hasattr(response, 'text'):
                     response_text = response.text
                else:
                     response_text = "[无法获取响应对象或文本]"
            except Exception:
                response_text = "[获取响应文本时出错]"

            print(f"错误：解析 DeepSeek API 响应时发生 JSON 解码错误。")
            # 尝试安全打印响应文本
            try:
                 print(f"原始响应内容: {response_text}")
            except UnicodeEncodeError:
                 print(f"原始响应内容 (编码后): {response_text.encode('utf-8', errors='replace').decode('utf-8')}")
            return f"错误：解析 DeepSeek API 响应时发生 JSON 解码错误。"
        
        except Exception as e:
            # 捕获其他所有潜在异常
            error_type = type(e).__name__
            
            # 检查捕获到的异常是否就是 UnicodeEncodeError
            if isinstance(e, UnicodeEncodeError):
                print("错误：在处理过程中直接触发了 UnicodeEncodeError。")
                print("这几乎总是由于运行环境 (例如 Windows 控制台) 的默认编码不是 UTF-8 导致的。")
                print("请尝试在运行脚本前设置环境变量: $env:PYTHONIOENCODING = \"utf-8\"")
                # 返回明确指向编码问题的错误
                return "错误：发生 Unicode 编码错误，强烈建议检查运行环境编码设置。"
            else:
                # 如果是其他未知错误
                print(f"错误：处理 DeepSeek 分析时发生未知错误。")
                print(f"异常类型: {error_type}")
                # 返回通用错误
                return f"错误：处理 DeepSeek 分析时发生未知错误 ({error_type})"
    
    # --- 捕获由内部逻辑触发的 UnicodeEncodeError (理论上不应再被触发，但保留) --- 
    except UnicodeEncodeError as uee:
        print("错误：在 API 调用或错误处理过程中直接触发了 UnicodeEncodeError。")
        print("这通常与运行环境处理非 ASCII 字符的方式有关。")
        # 返回一个明确指示编码问题的错误消息
        return "错误：发生 Unicode 编码错误，请检查运行环境的编码设置。"

# --- 添加的包装函数，供外部调用 ---
def 执行完整分析(symbol: str, market_type: str) -> str:
    """
    执行指定币种和市场类型的完整分析流程。

    Args:
        symbol (str): 交易对，例如 'BTCUSDT'。
        market_type (str): 市场类型，'spot' 或 'futures'。

    Returns:
        str: DeepSeek 返回的最终分析报告文本，或流程中发生的错误信息。
    """
    print(f"--- 开始执行 {symbol} ({market_type}) 的完整分析 ---") # 添加日志

    # --- 初始化摘要变量 ---
    kline_summary = "(K线分析未运行)"
    orderbook_summary = "(订单簿分析未运行)"
    micro_trend_summary = "(微观趋势分析未运行)"
    depth_analysis_summary = "(深度分析未运行)"
    breakout_summary = "(箱体突破分析未运行)"
    volume_analysis = "(成交流分析未运行)" # 使用 volume_analysis 作为变量名

    # --- 调用 K线分析模块 ---
    # print("--- 正在调用 K线分析模块... ---\") # 移除
    try:
        # 检查函数是否已导入且可用
        if '分析K线结构与形态' in globals() and 分析K线结构与形态 is not None:
             kline_analysis_results, _ = 分析K线结构与形态(symbol=symbol, market_type=market_type)
             if kline_analysis_results and not kline_analysis_results.get('error'):
                 summary_data = kline_analysis_results.get('confluence_summary')
                 if summary_data and not summary_data.get('error'):
                     bias = summary_data.get('bias', '未知')
                     reason = summary_data.get('reasoning', ['无'])[0] # 取第一条理由
                     kline_summary = f"K线分析偏向: {bias} (理由: {reason})"
                 else:
                     kline_summary = "(K线协同分析失败)"
                     print(f"K线协同分析错误 ({symbol}): {summary_data.get('error') if summary_data else '无结果'}")
             elif kline_analysis_results:
                 kline_summary = f"(K线分析模块错误: {kline_analysis_results.get('error')})"
                 print(f"K线分析模块错误 ({symbol}): {kline_analysis_results.get('error')}")
             else:
                  kline_summary = "(K线分析模块未返回结果)"
                  print(f"K线分析模块 ({symbol}) 未返回结果。")
        else:
             kline_summary = "(K线分析模块未导入或不可用)"
             print(f"警告: K线分析模块未导入或不可用 ({symbol})。")
    except Exception as e:
        kline_summary = f"(K线分析模块执行异常: {e})"
        print(f"!!! K线分析模块 ({symbol}) 执行时发生未捕获异常: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()

    # --- 调用 订单簿分析模块 ---
    # print("--- 正在调用 订单簿分析模块... ---\") # 移除
    try:
        if '分析订单簿' in globals() and 分析订单簿 is not None:
             orderbook_analysis_result = 分析订单簿(symbol=symbol, market_type=market_type)
             if orderbook_analysis_result:
                 interpretation_data = orderbook_analysis_result.get('interpretation')
                 if interpretation_data:
                     interpretations = interpretation_data.get('interpretations', ['无解读信息。'])
                     orderbook_summary = " ".join(interpretations[:2]) # 取前两条拼接
                 else:
                     orderbook_summary = "(订单簿分析未返回解读信息)"
                     print(f"订单簿分析 ({symbol}) 未包含 'interpretation' 键。")
             else:
                 orderbook_summary = "(订单簿分析模块未返回结果)"
                 print(f"订单簿分析模块 ({symbol}) 未返回结果。")
        else:
            orderbook_summary = "(订单簿分析模块未导入或不可用)"
            print(f"警告: 订单簿分析模块未导入或不可用 ({symbol})。")
    except Exception as e:
        orderbook_summary = f"(订单簿分析模块执行异常: {e})"
        print(f"!!! 订单簿分析模块 ({symbol}) 执行时发生未捕获异常: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()

    # --- 调用 微观趋势动量分析模块 ---
    # print("--- 正在调用 微观趋势动量分析模块... ---\") # 移除
    try:
        if '微观趋势动量' in globals() and 微观趋势动量 is not None:
            intervals_to_analyze = MICRO_TREND_CONFIG.get('intervals', ['5m', '15m', '1h', '4h']) # 从配置获取，提供默认值
            if not intervals_to_analyze: # 处理空列表的情况
                 intervals_to_analyze = ['5m', '15m', '1h', '4h']
                 print(f"警告: 微观趋势配置 ({symbol}) 中未找到 'intervals' 键或值为空，使用默认周期列表。")
            mtf_results = 微观趋势动量.执行多周期分析(
                    symbol=symbol,
                    market_type=market_type,
                    intervals=intervals_to_analyze,
                    config=MICRO_TREND_CONFIG
                )
            if mtf_results and not mtf_results.get('error'):
                consolidated_signal = 微观趋势动量.整合多周期信号(mtf_results, MICRO_TREND_CONFIG)
                if consolidated_signal:
                    signal = consolidated_signal.get('combined_signal', '未知')
                    score = consolidated_signal.get('score')
                    reason = consolidated_signal.get('reasoning', ['无'])[0] if consolidated_signal.get('reasoning') else '无理由'
                    score_str = f"{score:.2f}" if isinstance(score, (int, float)) else "N/A"
                    if signal in ['未知', '信号冲突', 'Conflict'] and reason == '无理由':
                        micro_trend_summary = f"微观趋势信号: 冲突 (得分: {score_str}, 理由: 不同时间周期信号不一致)"
                        print(f"检测到微观趋势信号冲突 ({symbol})，已调整摘要。")
                    else:
                        micro_trend_summary = f"微观趋势信号: {signal} (得分: {score_str}, 理由: {reason})"
                else:
                    micro_trend_summary = "(微观趋势整合信号失败)"
                    print(f"微观趋势整合信号函数 ({symbol}) 未返回结果。")
            elif mtf_results:
                 micro_trend_summary = f"(微观趋势多周期分析错误: {mtf_results.get('error')})"
                 print(f"微观趋势多周期分析错误 ({symbol}): {mtf_results.get('error')}")
            else:
                micro_trend_summary = "(微观趋势多周期分析模块未返回结果)"
                print(f"微观趋势多周期分析模块 ({symbol}) 未返回结果。")
        else:
            micro_trend_summary = "(微观趋势模块未导入)"
            print(f"警告: 微观趋势模块未导入 ({symbol})。")
    except Exception as e:
        micro_trend_summary = f"(微观趋势模块执行异常: {e})"
        print(f"!!! 微观趋势模块 ({symbol}) 执行时发生未捕获异常: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()

    # --- 调用 深度分析模块 ---
    # print("--- 正在调用 深度分析模块... ---\") # 移除
    try:
        if '深度分析模块' in globals() and 深度分析模块 is not None:
            depth_results = 深度分析模块.分析多层级成交量(symbol=symbol, market_type=market_type)
            if depth_results and not depth_results.get('error'):
                interpretation_data = depth_results.get('interpretation')
                interpretation_text = None
                if interpretation_data:
                    if isinstance(interpretation_data, str):
                        interpretation_text = interpretation_data
                    elif isinstance(interpretation_data, dict):
                        interpretation_text = interpretation_data.get('suggestion') or \
                                              interpretation_data.get('建议') or \
                                              interpretation_data.get('text') or \
                                              interpretation_data.get('summary')
                        if not interpretation_text:
                            print(f"警告: 深度分析 ({symbol}) 返回的 interpretation 是字典，但未能从常见键提取文本。")
                    else:
                        print(f"警告: 深度分析 ({symbol}) 返回的 interpretation 类型未知 ({type(interpretation_data)})，无法提取文本。")
                if interpretation_text:
                    depth_analysis_summary = interpretation_text[:150] + ('...' if len(interpretation_text) > 150 else '')
                else:
                    metrics = depth_results.get('tier_metrics', {}).get('large', {})
                    buy_vol = metrics.get('buy', {}).get('taker_buy_quote_volume', 0)
                    sell_vol = metrics.get('sell', {}).get('taker_sell_quote_volume', 0)
                    if buy_vol > 0 or sell_vol > 0:
                         bias = "偏买" if buy_vol > sell_vol else ("偏卖" if sell_vol > buy_vol else "均衡")
                         depth_analysis_summary = f"大单成交: {bias} (买: {buy_vol:.0f}, 卖: {sell_vol:.0f})"
                    else:
                         depth_analysis_summary = "(深度分析: 无解读文本或大单数据)"
                    print(f"深度分析模块 ({symbol}) 未返回有效解读文本或提取失败，使用指标生成摘要。")
            elif depth_results:
                depth_analysis_summary = f"(深度分析错误: {depth_results.get('error')})"
                print(f"深度分析错误 ({symbol}): {depth_results.get('error')}")
            else:
                depth_analysis_summary = "(深度分析模块未返回结果)"
                print(f"深度分析模块 ({symbol}) 未返回结果。")
        else:
            depth_analysis_summary = "(深度分析模块未导入)"
            print(f"警告: 深度分析模块未导入 ({symbol})。")
    except Exception as e:
        depth_analysis_summary = f"(深度分析模块执行异常: {e})"
        print(f"!!! 深度分析模块 ({symbol}) 执行时发生未捕获异常: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()

    # --- 调用 箱体突破分析模块 ---
    # print("--- 正在调用 箱体突破分析模块... ---\") # 移除
    try:
        if '箱体突破分析' in globals() and 箱体突破分析 is not None:
            breakout_results = 箱体突破分析.分析箱体突破(symbol=symbol, market_type=market_type)
            if breakout_results:
                status = breakout_results.get('status', '未知状态')
                reason = breakout_results.get('reason', '无详细理由')
                if status != '数据不足或错误' and status != '未知状态':
                     breakout_summary = f"{status} (细节: {reason.split('.')[0]})"
                elif reason:
                     breakout_summary = f"(箱体突破分析: {reason})"
                else:
                    breakout_summary = "(箱体突破分析返回未知状态且无理由)"
            else:
                 breakout_summary = "(箱体突破分析模块意外返回None)"
                 print(f"箱体突破分析模块 ({symbol}) 返回了 None，非预期行为。")
        else:
            breakout_summary = "(箱体突破模块未导入)"
            print(f"警告: 箱体突破分析模块未导入 ({symbol})。")
    except Exception as e:
        breakout_summary = f"(箱体突破模块执行异常: {e})"
        print(f"!!! 箱体突破分析模块 ({symbol}) 执行时发生未捕获异常: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()

    # --- 调用 成交流分析模块 ---
    # print("--- 正在调用 成交流分析模块... ---\") # 移除
    try:
        if '成交流分析' in globals() and 成交流分析 is not None:
            trade_flow_metrics = 成交流分析.分析成交流(symbol=symbol, market_type=market_type)
            if trade_flow_metrics and not trade_flow_metrics.get('error'):
                interpretation_result = 成交流分析.解读成交流分析(trade_flow_metrics)
                if isinstance(interpretation_result, dict):
                    overall_summary_list = interpretation_result.get('overall', {}).get('summary')
                    if isinstance(overall_summary_list, list) and overall_summary_list:
                        volume_analysis = overall_summary_list[0]
                    else:
                        volume_analysis = "(成交流分析: 未能从解读结果提取摘要)"
                        print(f"成交流分析模块 ({symbol}) 解读结果格式不符合预期 (overall->summary)。")
                elif isinstance(interpretation_result, str):
                     volume_analysis = interpretation_result
                elif not interpretation_result:
                    volume_analysis = "(成交流分析: 解读函数未生成有效摘要)"
                    print(f"成交流分析模块 ({symbol}) 的解读函数未返回有效摘要。")
                else:
                    volume_analysis = f"(成交流分析: 解读结果类型未知 {type(interpretation_result)})"
                    print(f"成交流分析 ({symbol}) 解读结果类型未知: {type(interpretation_result)}。")
            elif trade_flow_metrics:
                 volume_analysis = f"(成交流分析错误: {trade_flow_metrics.get('error')})"
                 print(f"成交流分析错误 ({symbol}): {trade_flow_metrics.get('error')}")
            else:
                volume_analysis = "(成交流分析函数未返回结果)"
                print(f"成交流分析模块 ({symbol}) 的分析函数未返回结果。")
        else:
             volume_analysis = "(成交流分析模块未导入)"
             print(f"警告: 成交流分析模块未导入 ({symbol})。")
    except Exception as e:
        volume_analysis = f"(成交流分析模块执行异常: {e})"
        print(f"!!! 成交流分析模块 ({symbol}) 执行时发生未捕获异常: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()

    # --- 整合分析结果 ---
    technical_data = {
        'symbol': symbol, # 添加 symbol 和 market_type 到数据中
        'market_type': market_type,
        'kline_analysis': kline_summary,
        'order_book_analysis': orderbook_summary,
        'micro_trend': micro_trend_summary,
        'depth_analysis': depth_analysis_summary,
        'breakout_analysis': breakout_summary,
        'volume_analysis': volume_analysis,
    }

    # --- 调用 DeepSeek 进行分析 --- 
    # print("--- 正在调用 DeepSeek API 进行最终分析... ---\") # 移除
    try:
        # 检查 analyze_with_deepseek 是否存在
        if 'analyze_with_deepseek' in globals() and analyze_with_deepseek is not None:
             final_analysis = analyze_with_deepseek(technical_data)
        else:
             final_analysis = "错误: DeepSeek 分析函数 (analyze_with_deepseek) 未找到。"
             print("错误: DeepSeek 分析函数 (analyze_with_deepseek) 未找到。")
    except Exception as e:
        final_analysis = f"调用 DeepSeek 分析时发生异常: {e}"
        print(f"!!! 调用 DeepSeek 分析 ({symbol}) 时发生未捕获异常: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()

    print(f"--- {symbol} ({market_type}) 分析完成 ---")
    return final_analysis


# --- 示例用法 (注释掉或移除，因为主要入口是 GUI) ---
# if __name__ == "__main__":
#     # # print("--- 进入主执行块 (__name__ == '__main__') ---") # 移除
#
#     # # 定义要分析的交易对和市场类型
#     # test_symbol = 'NOTUSDT' # <--- 修改为 NOTUSDT
#     # test_market_type = 'futures'
#     # # print(f\"--- 目标: {test_symbol} ({test_market_type}) ---\") # 移除
#
#     # # --- 初始化摘要变量 ---
#     # kline_summary = \"(K线分析未运行)\"
#     # orderbook_summary = \"(订单簿分析未运行)\"
#     # micro_trend_summary = \"(微观趋势分析未运行)\"
#     # depth_analysis_summary = \"(深度分析未运行)\"
#     # breakout_summary = \"(箱体突破分析未运行)\"
#     # volume_analysis = \"(成交流分析未运行)\"
#
#     # # --- 调用 K线分析模块 ---
#     # # print(\"--- 正在调用 K线分析模块... ---\") # 移除
#     # try:
#     #     # ... (原 K线分析逻辑) ...
#     # except Exception as e:
#     #     # ... (原 K线错误处理) ...
#
#     # # --- 调用 订单簿分析模块 ---
#     # # print(\"--- 正在调用 订单簿分析模块... ---\") # 移除
#     # try:
#     #     # ... (原订单簿分析逻辑) ...
#     # except Exception as e:
#     #     # ... (原订单簿错误处理) ...
#
#     # # --- 调用 微观趋势动量分析模块 ---
#     # # print(\"--- 正在调用 微观趋势动量分析模块... ---\") # 移除
#     # try:
#     #     # ... (原微观趋势分析逻辑) ...
#     # except Exception as e:
#     #     # ... (原微观趋势错误处理) ...
#
#     # # --- 调用 深度分析模块 ---
#     # # print(\"--- 正在调用 深度分析模块... ---\") # 移除
#     # try:
#     #     # ... (原深度分析逻辑) ...
#     # except Exception as e:
#     #     # ... (原深度错误处理) ...
#
#     # # --- 调用 箱体突破分析模块 ---
#     # # print(\"--- 正在调用 箱体突破分析模块... ---\") # 移除
#     # try:
#     #     # ... (原箱体突破分析逻辑) ...
#     # except Exception as e:
#     #     # ... (原箱体突破错误处理) ...
#
#     # # --- 调用 成交流分析模块 ---
#     # # print(\"--- 正在调用 成交流分析模块... ---\") # 移除
#     # try:
#     #     # ... (原成交流分析逻辑) ...
#     # except Exception as e:
#     #     # ... (原成交流错误处理) ...
#
#     # # --- 整合分析结果 (全部真实数据) ---
#     # technical_data = {
#     #     'kline_analysis': kline_summary,
#     #     'order_book_analysis': orderbook_summary,
#     #     'micro_trend': micro_trend_summary,
#     #     'depth_analysis': depth_analysis_summary,
#     #     'breakout_analysis': breakout_summary,
#     #     'volume_analysis': volume_analysis,
#     # }
#     # # print(\"--- 整合后的技术数据 (全部真实): ---\") # 移除
#     # # print(json.dumps(technical_data, indent=2, ensure_ascii=False)) # 移除
#
#     # # --- 调用 DeepSeek 进行分析 ---
#     # # print(\"--- 正在调用 DeepSeek API 进行最终分析... ---\") # 移除
#     # final_analysis = analyze_with_deepseek(technical_data)
#
#     # # --- 打印最终结果 ---
#     # # print(\"\\n=========== DeepSeek 分析报告 ===========\") # 移除
#     # print(final_analysis)
#     # # print(\"=========================================\") # 移除
#
#     # print(\"--- 脚本执行完毕 ---\")
#     pass # 保留 if __name__ == \"__main__\": 块但内容为空或注释掉
# # --- 文件结束 --- 