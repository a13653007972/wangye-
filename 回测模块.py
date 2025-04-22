import pandas as pd
from decimal import Decimal, getcontext
import numpy as np
import math # 用于判断 NaN

# 设置 Decimal 的精度
getcontext().prec = 28 # 设置一个较高的精度

# --- 常量定义 (可以移到配置文件或更合适的位置) ---
ANNUAL_TRADING_DAYS = 252 # 年化计算常用的交易日数 (根据实际情况调整，如 365)

def 加载K线数据(文件路径):
    """
    从指定路径加载K线数据。
    需要根据实际数据格式进行调整。
    """
    # 示例：假设数据是CSV格式
    # return pd.read_csv(文件路径, index_col='日期', parse_dates=True)
    print(f"尝试从 {文件路径} 加载K线数据...")
    # 这里需要替换为实际的数据加载逻辑
    return None

def 加载交易信号(信号来源):
    """
    从指定来源加载交易信号。
    来源可以是文件路径，也可以是k线分析模块的直接输出。
    需要根据实际信号格式进行调整。
    """
    # 示例：假设信号是一个包含 '日期' 和 '信号' 列的DataFrame
    print(f"尝试从 {信号来源} 加载交易信号...")
    # 这里需要替换为实际的信号加载逻辑
    return None

def 执行回测(k线数据, 交易信号, 初始资金=1000, 手续费率=0.0003, 
             止盈比例=Decimal('0.10'), 止损比例=Decimal('0.10')):
    """
    执行回测过程。
    使用 Decimal 类型进行资金和数量计算以提高精度。
    假设k线数据和交易信号是pandas DataFrame，且有时间索引。
    k线数据需要有 '收盘' 列。
    交易信号需要有 '信号' 列，值为 '买入', '卖出'。
    交易将在信号出现的K线的收盘价执行。
    采用全仓买入/卖出策略。
    """
    print("开始执行回测...")
    if k线数据 is None or 交易信号 is None:
        print("错误：K线数据或交易信号未能加载，无法执行回测。")
        return None
    if not isinstance(k线数据.index, pd.DatetimeIndex) or not isinstance(交易信号.index, pd.DatetimeIndex):
        print("错误：K线数据或交易信号的索引必须是 Pandas DatetimeIndex。")
        return None
    if '收盘' not in k线数据.columns:
        print("错误：K线数据 DataFrame 中缺少 '收盘' 列。")
        return None
    if '信号' not in 交易信号.columns:
         print("错误：交易信号 DataFrame 中缺少 '信号' 列。")
         return None

    # --- 初始化账户状态 (使用 Decimal) ---
    初始资金_dec = Decimal(str(初始资金)) # 从 float 或 int 转 Decimal
    手续费率_dec = Decimal(str(手续费率))
    现金 = 初始资金_dec
    持仓量 = Decimal('0') # 数量也用 Decimal
    持仓成本总额 = Decimal('0') # 新增：跟踪当前持仓的总成本
    账户总值历史 = pd.Series(index=k线数据.index, dtype=object) # 存储 Decimal 对象

    交易记录 = [] # 记录每次交易

    # --- 合并数据 --- (使用 join 确保索引对齐)
    # data = k线数据.copy()
    # data['信号'] = 交易信号['信号'] 
    data = k线数据.join(交易信号[['信号']], how='left') # 左连接，保留所有k线数据，匹配信号
    # 确保 '收盘' 列是浮点数，以便转换为 Decimal
    data['收盘'] = pd.to_numeric(data['收盘'], errors='coerce')
    data.dropna(subset=['收盘'], inplace=True)

    print("数据合并完成，开始遍历K线进行模拟交易 (使用 Decimal 精度)...")

    # --- 模拟交易循环 --- (使用 Decimal)
    last_total_value = 初始资金_dec # 用于记录上一日的总值
    for 日期, row in data.iterrows():
        # 检查价格是否有效 (收盘、最高、最低)
        if pd.isna(row['收盘']) or pd.isna(row['最高']) or pd.isna(row['最低']):
            账户总值历史[日期] = last_total_value # 价格无效时，总值保持不变
            continue # 跳过这一天
            
        当前价格 = Decimal(str(row['收盘'])) # 收盘价，用于信号判断和信号卖出
        当前最高 = Decimal(str(row['最高'])) # 用于检查止盈
        当前最低 = Decimal(str(row['最低'])) # 用于检查止损
        信号 = row['信号']

        # 更新当前总资产 (基于收盘价)
        当前总值 = 现金 + 持仓量 * 当前价格
        触发交易 = False # 标记本 K 线是否已发生交易 (避免重复操作)

        # --- 检查止盈止损 (优先于信号) ---
        if 持仓量 > Decimal('0') and 持仓成本总额 > Decimal('0'): # 必须有持仓和成本记录
            平均持仓成本 = 持仓成本总额 / 持仓量
            止盈价格 = 平均持仓成本 * (Decimal('1') + 止盈比例) # 使用参数
            止损价格 = 平均持仓成本 * (Decimal('1') - 止损比例) # 使用参数
            
            # 打印 TP/SL 检查信息 (只在持仓时打印一次)
            # print(f"    [检查TP/SL] 日期: {日期}, 平均成本: {平均持仓成本:.4f}, TP价: {止盈价格:.4f}, SL价: {止损价格:.4f}, 最高价: {当前最高:.4f}, 最低价: {当前最低:.4f}")

            # 检查止盈 (使用当前 K 线的最高价)
            if 当前最高 >= 止盈价格:
                卖出价格 = 止盈价格 # 以止盈价格成交
                交易数量 = 持仓量
                交易额 = 卖出价格 * 交易数量
                实际手续费 = 交易额 * 手续费率_dec
                卖出净收益 = 交易额 - 实际手续费
                现金 += 卖出净收益
                本次交易盈亏 = 卖出净收益 - 持仓成本总额
                
                交易记录.append({
                    '日期': 日期, '类型': '止盈卖出', '价格': 卖出价格, '数量': 交易数量,
                    '手续费': 实际手续费, '现金': 现金, '持仓': Decimal('0'), 
                    '总值': 现金, '盈亏': 本次交易盈亏
                })
                # 增强日志
                print(f"{日期}: 止盈触发! 平均成本 {平均持仓成本:.4f}, 止盈价 {止盈价格:.4f} <= K线最高价 {当前最高:.4f}")
                print(f"    >> 止盈卖出 @ {卖出价格:.4f}, 数量 {交易数量:.8f}, 盈亏 {本次交易盈亏:.4f}, 现金 {现金:.8f}")
                
                持仓量 = Decimal('0')
                持仓成本总额 = Decimal('0')
                当前总值 = 现金
                触发交易 = True
                
            # 检查止损 (使用当前 K 线的最低价) - 只有在未触发止盈时检查
            elif not 触发交易 and 当前最低 <= 止损价格:
                卖出价格 = 止损价格 # 以止损价格成交
                交易数量 = 持仓量
                交易额 = 卖出价格 * 交易数量
                实际手续费 = 交易额 * 手续费率_dec
                卖出净收益 = 交易额 - 实际手续费
                现金 += 卖出净收益
                本次交易盈亏 = 卖出净收益 - 持仓成本总额
                
                交易记录.append({
                    '日期': 日期, '类型': '止损卖出', '价格': 卖出价格, '数量': 交易数量,
                    '手续费': 实际手续费, '现金': 现金, '持仓': Decimal('0'), 
                    '总值': 现金, '盈亏': 本次交易盈亏
                })
                # 增强日志
                print(f"{日期}: 止损触发! 平均成本 {平均持仓成本:.4f}, 止损价 {止损价格:.4f} >= K线最低价 {当前最低:.4f}")
                print(f"    >> 止损卖出 @ {卖出价格:.4f}, 数量 {交易数量:.8f}, 盈亏 {本次交易盈亏:.4f}, 现金 {现金:.8f}")
                
                持仓量 = Decimal('0')
                持仓成本总额 = Decimal('0')
                当前总值 = 现金
                触发交易 = True

        # --- 检查信号卖出 (如果未触发止盈止损) ---
        if not 触发交易 and 信号 == '卖出' and 持仓量 > Decimal('0'):
            # 获取卖出前的成本用于日志
            卖出前平均成本 = 持仓成本总额 / 持仓量 if 持仓量 > Decimal('0') else Decimal('0') 
            
            卖出价格 = 当前价格 # 信号卖出按收盘价
            交易数量 = 持仓量
            交易额 = 卖出价格 * 交易数量
            实际手续费 = 交易额 * 手续费率_dec
            卖出净收益 = 交易额 - 实际手续费
            现金 += 卖出净收益
            本次交易盈亏 = Decimal('0')
            if 持仓成本总额 > Decimal('0'):
                本次交易盈亏 = 卖出净收益 - 持仓成本总额
                # print(f"    卖出盈亏计算: 卖出净收益 {卖出净收益:.8f} - 持仓成本 {持仓成本总额:.8f} = {本次交易盈亏:.8f}") # 这个内部计算日志可以注释掉
            else:
                print("    警告：信号卖出时未找到持仓成本，无法计算精确盈亏。")

            交易记录.append({
                '日期': 日期, '类型': '信号卖出', '价格': 卖出价格, '数量': 交易数量,
                '手续费': 实际手续费, '现金': 现金, '持仓': Decimal('0'), 
                '总值': 现金, '盈亏': 本次交易盈亏
            })
            # 增强日志
            print(f"{日期}: MA信号卖出 @ {卖出价格:.4f} (基于成本 {卖出前平均成本:.4f})")
            print(f"    >> 信号卖出, 数量 {交易数量:.8f}, 盈亏 {本次交易盈亏:.4f}, 现金 {现金:.8f}")
            
            持仓量 = Decimal('0')
            持仓成本总额 = Decimal('0') 
            当前总值 = 现金
            触发交易 = True # 标记已交易

        # --- 检查信号买入 (如果本 K 线未发生卖出交易) ---
        if not 触发交易 and 信号 == '买入' and 现金 > Decimal('1.0'): 
            # 获取买入前状态用于日志
            买入前平均成本 = 持仓成本总额 / 持仓量 if 持仓量 > Decimal('0') else Decimal('0')
            买入前持仓量 = 持仓量
            
            # 使用 10% 的现金进行购买
            可用于购买的现金 = 现金 * Decimal('0.10')
            
            if 可用于购买的现金 < Decimal('0.1'): # 如果10%的现金太少，则跳过
                print(f"{日期}: 信号买入, 但可用资金的10% ({可用于购买的现金:.8f}) 过少，跳过购买。")
                账户总值历史[日期] = 当前总值 # 记录当天总值（未交易）
                last_total_value = 当前总值
                continue

            if 当前价格 > Decimal('0') and (Decimal('1') + 手续费率_dec) > Decimal('0'):
                # 根据10%的资金计算买入量
                本次可买入数量 = 可用于购买的现金 / (当前价格 * (Decimal('1') + 手续费率_dec))

                买入成本 = 本次可买入数量 * 当前价格
                实际手续费 = 买入成本 * 手续费率_dec
                本次总花费 = 买入成本 + 实际手续费

                # 检查 *总* 现金是否足够支付 *本次* 花费 (理论上应该足够，因为是从10%算的)
                if 本次总花费 <= 现金:
                    持仓量 += 本次可买入数量
                    现金 -= 本次总花费
                    持仓成本总额 += 本次总花费 # 累加成本
                    当前总值 = 现金 + 持仓量 * 当前价格 # 更新当前总值
                    
                    # 计算买入后平均成本用于日志
                    买入后平均成本 = 持仓成本总额 / 持仓量 if 持仓量 > Decimal('0') else Decimal('0')
                    
                    交易记录.append({
                        '日期': 日期, '类型': '买入', '价格': 当前价格, '数量': 本次可买入数量,
                        '手续费': 实际手续费, '现金': 现金, '持仓': 持仓量,
                        '总值': 当前总值,
                        '盈亏': None
                    })
                    # 增强日志
                    print(f"{日期}: MA信号买入 (10%资金) @ {当前价格:.4f}")
                    print(f"    >> 买入数量 {本次可买入数量:.8f}, 花费 {本次总花费:.8f}, 现金 {现金:.8f}")
                    print(f"    >> 持仓变化: {买入前持仓量:.8f} -> {持仓量:.8f}, 成本变化: {买入前平均成本:.4f} -> {买入后平均成本:.4f}")
                    
                    触发交易 = True # 标记已交易 (虽然逻辑上买入后不会再卖出，但保持一致性)
                else:
                    # 这种情况理论上不应该发生，除非 Decimal 精度问题或现金极少
                    print(f"{日期}: 信号买入 (10%资金), 但计算后现金不足 (需 {本次总花费:.8f}, 总现金 {现金:.8f}) - 可能是精度问题")
            else:
                print(f"{日期}: 信号买入 (10%资金), 但价格或手续费计算异常，无法买入。")

        # --- 记录每日账户总值 --- (确保记录的是 Decimal)
        账户总值历史[日期] = 当前总值
        last_total_value = 当前总值 # 更新上一日总值

    print("回测循环结束。")

    # --- 计算并返回结果 --- (确保返回的是原始 Decimal 或需要的格式)
    账户总值历史 = 账户总值历史.dropna() # 移除可能的 NaN 值
    最终总值 = 账户总值历史.iloc[-1] if not 账户总值历史.empty else 初始资金_dec
    总收益率 = (最终总值 / 初始资金_dec) - Decimal('1') if 初始资金_dec > Decimal('0') else Decimal('0')

    print(f"回测完成。初始资金: {初始资金_dec:.8f}, 最终总值: {最终总值:.8f}, 总收益率: {总收益率:.2%}")

    结果 = {
        '初始资金': 初始资金_dec,
        '最终总值': 最终总值,
        '总收益率': 总收益率,
        '账户总值历史': 账户总值历史.astype(float), # 转换为 float 方便后续计算/绘图
        '交易记录': pd.DataFrame(交易记录), # 日期可能不是索引了，需要检查
    }
    # 尝试将交易记录的日期设为索引
    交易记录_df = pd.DataFrame(交易记录)
    if not 交易记录_df.empty and '日期' in 交易记录_df.columns:
        try:
            交易记录_df.set_index('日期', inplace=True)
            结果['交易记录'] = 交易记录_df # 更新结果字典中的 DataFrame
        except Exception as e:
            print(f"设置交易记录索引时出错: {e}")
            结果['交易记录'] = 交易记录_df # 即使设置失败，也返回未设置索引的 DataFrame
    else:
         结果['交易记录'] = 交易记录_df # 如果没记录或没日期列
            
    return 结果

def 计算绩效指标(回测结果):
    """
    根据回测结果计算详细的绩效指标。
    """
    print("计算绩效指标...")
    指标 = {}

    if not 回测结果 or 回测结果['账户总值历史'].empty:
        print("警告：回测结果为空或缺少账户历史，无法计算绩效指标。")
        return {'错误': '结果不足'}

    账户总值历史 = 回测结果['账户总值历史']
    初始资金 = float(回测结果['初始资金']) # 转为 float
    最终总值 = float(回测结果['最终总值'])
    总收益率 = float(回测结果['总收益率'])
    交易记录 = 回测结果['交易记录']

    指标['初始资金'] = f"{初始资金:.2f}"
    指标['最终总值'] = f"{最终总值:.2f}"
    指标['总收益率'] = f"{总收益率:.2%}"
    指标['总交易次数'] = len(交易记录)

    # --- 时间跨度 --- 
    if len(账户总值历史) > 1:
        start_date = 账户总值历史.index[0]
        end_date = 账户总值历史.index[-1]
        指标['回测开始日期'] = start_date.strftime('%Y-%m-%d %H:%M:%S')
        指标['回测结束日期'] = end_date.strftime('%Y-%m-%d %H:%M:%S')
        回测天数 = (end_date - start_date).days
        指标['回测持续天数'] = 回测天数
        年化因子 = ANNUAL_TRADING_DAYS / 回测天数 if 回测天数 > 0 else 0 # 避免除以零
    else:
        指标['回测持续天数'] = 0
        年化因子 = 0

    # --- 年化收益率 --- (仅当持续时间大于0)
    if 年化因子 > 0:
        年化收益率 = (1 + 总收益率) ** 年化因子 - 1
        指标['年化收益率'] = f"{年化收益率:.2%}"
    else:
        指标['年化收益率'] = "N/A (持续时间不足)"

    # --- 最大回撤 --- 
    if len(账户总值历史) > 1:
        历史峰值 = 账户总值历史.cummax()
        回撤 = (账户总值历史 - 历史峰值) / 历史峰值
        最大回撤 = 回撤.min() if not 回撤.empty else 0
        指标['最大回撤'] = f"{最大回撤:.2%}"
    else:
        指标['最大回撤'] = "N/A (数据不足)"

    # --- 夏普比率 --- 
    if 年化因子 > 0 and len(账户总值历史) > 1:
        # 计算周期收益率 (例如日收益率)
        周期收益率 = 账户总值历史.pct_change().dropna()
        if len(周期收益率) > 1:
            # 计算年化波动率 (周期收益率标准差 * sqrt(年化因子调整))
            年化波动率 = 周期收益率.std() * np.sqrt(ANNUAL_TRADING_DAYS) # 假设是日收益率，乘以sqrt(年交易日)
                                                              # 如果是其他周期，这里的因子需要调整
            指标['年化波动率'] = f"{年化波动率:.2%}"
            
            # 夏普比率 (假设无风险利率为 0)
            if 年化波动率 > 1e-9: # 避免除以极小值或零
                夏普比率 = (年化收益率 if isinstance(年化收益率, (int, float)) else 0) / 年化波动率
                指标['夏普比率'] = f"{夏普比率:.2f}"
            else:
                指标['夏普比率'] = "N/A (波动率为零或负)"
        else:
            指标['年化波动率'] = "N/A (收益率数据不足)"
            指标['夏普比率'] = "N/A (收益率数据不足)"
    else:
        指标['年化波动率'] = "N/A (持续时间或数据不足)"
        指标['夏普比率'] = "N/A (持续时间或数据不足)"

    # 可以在这里继续添加胜率、盈亏比等更复杂的指标计算

    print("绩效指标计算完成。")
    return 指标

def 可视化回测结果(回测结果, 资金曲线数据=None):
    """
    将回测结果可视化，例如绘制资金曲线。
    """
    print("可视化回测结果...")
    # 这里需要实现可视化逻辑，可能需要 matplotlib 或其他库
    pass

# --- 主程序入口 (示例) ---
if __name__ == '__main__':
    # 1. 从 k线分析模块 获取数据和信号
    try:
        # !! 重要 !! 导入 k线分析模块 中的实际分析函数
        from k线分析模块 import 分析K线结构与形态

        # 定义要回测的参数
        交易对 = 'BTCUSDT' # <<-- 需要修改为你想要的交易对
        时间周期 = '1h'   # <<-- 需要修改为你想要的时间周期
        市场类型 = 'futures' # <<-- 或 'spot'

        print(f"正在从 k线分析模块 获取 {交易对} {市场类型} {时间周期} 的分析结果和K线数据...")
        # 调用实际的分析函数，注意参数名和格式
        # 分析K线结构与形态 返回分析结果字典 和 包含各周期K线数据的字典
        analysis_results, kline_data_all_tf = 分析K线结构与形态(
            symbol=交易对, 
            market_type=市场类型, 
            timeframes=[时间周期] # 分析函数需要时间周期列表
        )

        # ------------------------------------------------------------------
        # !! 重要 !! 下一步：处理返回结果，准备回测所需的数据
        # ------------------------------------------------------------------

        # --- 打印返回的数据结构以供调试 ---
        print("\n--- 调试信息 --- ")
        if 时间周期 in kline_data_all_tf and kline_data_all_tf[时间周期] is not None:
            print(f"kline_data_all_tf['{时间周期}'] 的类型: {type(kline_data_all_tf[时间周期])}")
            if isinstance(kline_data_all_tf[时间周期], pd.DataFrame):
                print(f"kline_data_all_tf['{时间周期}'] 的列名: {kline_data_all_tf[时间周期].columns.tolist()}")
                print(f"kline_data_all_tf['{时间周期}'] 的前5行数据:")
                print(kline_data_all_tf[时间周期].head())
            else:
                # 如果不是 DataFrame，尝试打印前 100 个字符看看
                try:
                     print(f"kline_data_all_tf['{时间周期}'] 的内容预览 (前100字符): {str(kline_data_all_tf[时间周期])[:100]}")
                except:
                     print(f"无法预览 kline_data_all_tf['{时间周期}'] 的内容。")
        else:
            print(f"kline_data_all_tf 中没有找到 '{时间周期}' 的数据。")

        if analysis_results:
            print(f"analysis_results 的类型: {type(analysis_results)}")
            print(f"analysis_results 的主要键: {list(analysis_results.keys())}")
            # 可以取消注释下面这行来打印完整的 analysis_results，但如果内容很多可能会刷屏
            # import json; print(json.dumps(analysis_results, indent=2, ensure_ascii=False))
        else:
            print("analysis_results 为空或 None。")
        print("--- 调试信息结束 --- \n")
        # ------------------------------------------------------------------

        # 2.a 从 kline_data_all_tf 提取目标周期的 K线数据，并转换为 DataFrame
        #     需要确保 DataFrame 有 DatetimeIndex 和 '收盘', 'high', 'low' 列
        k_data = None # 先初始化为 None
        if 时间周期 in kline_data_all_tf and isinstance(kline_data_all_tf[时间周期], pd.DataFrame) and not kline_data_all_tf[时间周期].empty:
            df = kline_data_all_tf[时间周期].copy() # 获取 DataFrame 副本
            print(f"开始处理 {时间周期} 的K线数据...")
            try:
                # 1. 转换时间戳为 DatetimeIndex (假设是毫秒)
                if 'timestamp' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    df.set_index('timestamp', inplace=True)
                    print("  - 时间戳已设置为索引。")
                else:
                    raise ValueError("K线数据缺少 'timestamp' 列")
                
                # 2. 重命名列: close -> 收盘, high -> 最高, low -> 最低 (如果存在)
                rename_map = {}
                required_cols = {'close': '收盘', 'high': '最高', 'low': '最低'}
                missing_original = []
                for original, renamed in required_cols.items():
                    if original in df.columns:
                        rename_map[original] = renamed
                        print(f"  - '{original}' 列将重命名为 '{renamed}'")
                    else:
                        missing_original.append(original)
                
                if missing_original:
                     # 如果缺少 close, high, low 中的任何一个，都无法进行完整回测
                     raise ValueError(f"K线数据缺少必要的列: {', '.join(missing_original)}")
                     
                df.rename(columns=rename_map, inplace=True)
                
                # 3. 确保价格列是数值类型
                price_cols = ['收盘', '最高', '最低']
                for col in price_cols:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                df.dropna(subset=price_cols, inplace=True) # 移除任何价格无效的行

                # 4. 检查数据是否足够
                if len(df) < 20: # MA20 需要至少20条数据
                    print(f"警告：处理后的K线数据不足20条({len(df)})，可能无法生成MA信号。")
                
                k_data = df # 将处理好的数据赋值给 k_data
                print(f"K线数据处理完成 (含最高/最低价)，数据条数: {len(k_data)}")
                
            except Exception as e:
                print(f"错误：处理K线数据时出错: {e}")
                k_data = None
        else:
            print(f"错误：未能从 k线分析模块 返回的数据中找到有效的 {时间周期} K线 DataFrame。")

        # 2.b 从 k_data 生成交易信号 DataFrame (基于MA交叉策略)
        signals = None # 先初始化为 None
        if k_data is not None and not k_data.empty:
            # --- 定义 MA 周期 ---
            ma_window = 20 # <<< 可以修改这里来改变 MA 周期
            print(f"开始基于 MA({ma_window}) 交叉生成 {时间周期} 交易信号...")
            # ---------------------
            try:
                # window = 20 # 使用上面定义的 ma_window
                if len(k_data) >= ma_window:
                    # 1. 计算 MA
                    k_data[f'MA{ma_window}'] = k_data['收盘'].rolling(window=ma_window).mean()
                    
                    # 2. 创建信号 DataFrame
                    signals = pd.DataFrame(index=k_data.index)
                    signals['信号'] = None # 初始化信号列
                    
                    # 3. 寻找交叉点 (基于指定的 MA 周期)
                    ma_col = f'MA{ma_window}'
                    # 上穿：当天收盘 > MA 且 前一天收盘 <= MA
                    signals.loc[(k_data['收盘'] > k_data[ma_col]) & (k_data['收盘'].shift(1) <= k_data[ma_col].shift(1)), '信号'] = '买入'
                    # 下穿：当天收盘 < MA 且 前一天收盘 >= MA
                    signals.loc[(k_data['收盘'] < k_data[ma_col]) & (k_data['收盘'].shift(1) >= k_data[ma_col].shift(1)), '信号'] = '卖出'
                    
                    # 移除前 ma_window-1 行的 NaN 信号
                    signals = signals.iloc[ma_window-1:]
                    # k_data = k_data.iloc[ma_window-1:] # 相应调整 k_data (可选)

                    # 打印生成的信号统计
                    buy_signals = signals[signals['信号'] == '买入'].shape[0]
                    sell_signals = signals[signals['信号'] == '卖出'].shape[0]
                    print(f"交易信号生成完成。买入信号: {buy_signals} 个, 卖出信号: {sell_signals} 个。")
                else:
                    print(f"K线数据不足 {ma_window} 条，无法计算 MA({ma_window}) 或生成信号。")
                    signals = pd.DataFrame(index=k_data.index) # 创建空的 signals 避免后面出错

            except Exception as e:
                print(f"错误：生成交易信号时出错: {e}")
                signals = None
        else:
            print("无法生成交易信号，因为 K线数据无效。")

        # ------------------------------------------------------------------

        # 检查处理后的数据是否有效
        if k_data is not None and signals is not None:
            print("K线数据和交易信号准备就绪（占位），尝试执行回测...")
            # 3. 执行回测 (使用默认参数: 初始资金1000, 手续费率0.0003)
            results = 执行回测(k_data, signals)
        else:
            print("错误：未能准备好有效的 K线数据 或 交易信号，无法执行回测。")
            results = None

    except ImportError:
        print("错误：无法导入 'k线分析模块'。请确保该文件存在于同一目录或 Python 路径中。")
        results = None
    except Exception as e:
        print(f"错误：调用 k线分析模块 或 处理数据时发生异常: {e}")
        results = None


    # 4. 计算绩效 (如果需要更详细的指标)
    if results:
        # !! 重要 !! 计算绩效指标函数也需要你实现
        performance = 计算绩效指标(results)
        print("\n绩效指标:")
        # 打印计算出的详细指标
        for key, value in performance.items():
            print(f"  {key}: {value}")

        # 5. 可视化 (如果需要)
        # !! 重要 !! 可视化函数需要你实现，并且可能需要安装matplotlib
        # 可视化回测结果(results, 资金曲线数据=results['账户总值历史'])
    else:
        print("\n回测未能成功执行，请检查 K线分析模块 的输出和后续数据处理逻辑。")
