'''
配置管理模块

存储和管理应用程序的配置信息，例如 API 密钥、交易对、策略参数等。
'''

import os

# !! 安全警告 !!
# 不要在代码中直接硬编码您的 API Key 和 Secret!
# 推荐使用环境变量或安全的配置文件 (.env) 来管理密钥。

# --- 币安 API 配置 ---
# 从环境变量获取 API 密钥，如果环境变量未设置，则使用占位符
# 在实际运行时，您需要确保环境变量已正确设置
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "YOUR_API_KEY_PLACEHOLDER") # 使用明确的占位符
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "YOUR_API_SECRET_PLACEHOLDER") # 使用明确的占位符

# 检查密钥是否仍然是占位符，如果是，则发出警告
if BINANCE_API_KEY == "YOUR_API_KEY_PLACEHOLDER" or BINANCE_API_SECRET == "YOUR_API_SECRET_PLACEHOLDER":
    print("警告：API 密钥未配置或仍为占位符。请设置 BINANCE_API_KEY 和 BINANCE_API_SECRET 环境变量或更新 .env 文件。")
    # 可以在这里添加更严格的检查或错误引发
    # raise ValueError("API 密钥未配置!")

# --- 其他配置项 --- 

# 需要分析或交易的交易对列表 (示例)
SYMBOLS = ["BTCUSDT", "ETHUSDT"]

# K线时间间隔 (示例: 1分钟, 5分钟, 1小时, 1天)
# KLINE_INTERVAL = "1h" # 这个被 DEFAULT_INTERVAL 替代，可以注释掉或移除
DEFAULT_INTERVAL = "1h"  # 数据获取模块使用的默认时间间隔

# 策略参数 (示例 - 具体策略可能覆盖这些)
STRATEGY_PARAMS = {
    "ma_short_period": 10,
    "ma_long_period": 30,
    "rsi_period": 14,
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    # ... 其他策略参数可以放在这里或 DEFAULT_STRATEGY_PARAMS 中 ...
}

# 日志配置 (示例)
LOG_LEVEL = "INFO" # 建议用 INFO 查看详细信息
LOG_FILE = "logs/app.log" # 建议统一日志文件

# 报告输出路径 (示例)
REPORT_PATH = "交易报告/"

# 是否启用真实交易 (True: 自动交易, False: 仅生成报告/模拟)
ENABLE_REAL_TRADING = False

# --- 指标解读阈值 --- 
# 您可以在这里调整这些值，以改变指标解读的敏感度
INTERPRETATION_OIR_STRONG = 0.4       # OIR 强信号阈值
INTERPRETATION_OIR_WEAK = 0.1         # OIR 弱信号阈值
INTERPRETATION_CUM_RATIO_STRONG = 1.8 # 累计深度强比率阈值 (买/卖 或 卖/买)
INTERPRETATION_CUM_RATIO_WEAK = 1.3   # 累计深度弱比率阈值
# 大单总数量占对应盘口总数量的比例，超过此值则认为显著
INTERPRETATION_LARGE_ORDER_SIG_FACTOR = 0.1 # 例如，10%
# 相邻订单簿档位价格差超过 (tick_size * 此因子) 则认为是裂口
INTERPRETATION_LIQUIDITY_GAP_FACTOR = 5.0

# --- 动态分析测试循环设置 ---
# 测试时运行多少次迭代以便进行比较
TEST_LOOP_ITERATIONS = 2 
# 每次迭代之间的等待秒数
TEST_LOOP_INTERVAL = 10 

# --- 其他配置（根据需要添加） ---
# DB_HOST = 'localhost'
# DB_PORT = 5432

# --- 成交流分析 (Trade Flow) --- 
TRADE_FLOW_LARGE_ORDER_PERCENTILES = [95, 98, 99] # 定义多个大单成交额百分位进行对比
TRADE_FLOW_PRIMARY_PERCENTILE = 98 # 用于精简显示的主要大单百分位
TRADE_FLOW_ANALYSIS_WINDOWS = [60, 300, 900] # 需要分析的时间窗口列表 (秒)
TRADE_FLOW_FETCH_LIMIT = 5000 # 一次获取的成交记录数量，用于覆盖时间窗口

# --- 成交流解读阈值 ---
TRADE_FLOW_INTERPRETATION_THRESHOLDS = {
    # 主动买卖量比率
    'taker_vol_strong_buy': 2.0,     # 强劲买盘
    'taker_vol_weak_buy': 1.3,       # 买盘占优
    'taker_vol_weak_sell': 0.7,      # 卖压占优
    'taker_vol_strong_sell': 0.5,    # 卖压沉重
    # 大单主动买卖量比率
    'large_taker_vol_strong_buy': 1.8,
    'large_taker_vol_weak_buy': 1.2,
    'large_taker_vol_weak_sell': 0.8,
    'large_taker_vol_strong_sell': 0.6,
    # 大单贡献度
    'large_vol_contribution_pct': 20.0, # 大单成交额占比 % (用于判断是否活跃)
    'large_trade_contribution_pct': 10.0, # 大单成交笔数占比 % (用于判断是否活跃)
    # 趋势判断 (比率相对变化)
    'trend_ratio_change_threshold': 0.2, # 主动买卖量比率变化 > 20% 视为趋势
    # (后续可以添加更多趋势阈值，如大单数量/金额变化)
    'trend_large_count_change_threshold': 0.3, # 大单数量变化 > 30% 视为趋势
    'trend_large_volume_change_threshold': 0.3, # 大单金额变化 > 30% 视为趋势

    # --- 新增：价格变化与成交量关联分析阈值 ---
    'price_change_significant_pct': 0.1, # 价格变化超过 0.1% 视为显著变化

    # --- 新增：交易频率趋势阈值 ---
    'trend_frequency_change_threshold': 0.3, # 交易频率变化 > 30% 视为趋势

    # --- 新增：平均成交额趋势阈值 ---
    'trend_avg_trade_size_change_threshold': 0.25,
    'large_price_stddev_high_pct': 0.15, # <-- 新增: 大单价格标准差高分散度阈值 (%)
}

# --- 常用交易对 Tick Size (最小价格精度) ---
# 可以在这里添加更多常用交易对及其 tickSize，以减少 API 调用并提高稳定性
# 可通过访问币安 API /api/v3/exchangeInfo 获取
TICK_SIZES = {
    'BTCUSDT': 0.01,  # 示例：BTC/USDT 现货和 U本位合约通常是 0.01
    'ETHUSDT': 0.01,  # 示例
    'BTCUSDT_FUTURES': 0.1, # <--- 添加或修改这一行
    # 'BNBBTC': 0.000001,
    # ... 其他交易对
}

# --- 微观趋势动量模块 配置 ---

# 需要分析的时间周期列表
MOMENTUM_TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d', '1w']

# 用于最终信号整合的时间周期列表
MOMENTUM_INTEGRATION_TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h']

# 整合时各个时间周期的权重
MOMENTUM_INTEGRATION_WEIGHTS = {
    '1m': 0.5,
    '5m': 0.8,
    '15m': 1.0,
    '1h': 1.2,
    '4h': 1.5
    # 注意：这里只包含整合周期 ('1d', '1w' 不参与加权平均，但其信号可能用于冲突检测或总体判断)
}

# ADX 低于此阈值时视为弱趋势/盘整
MOMENTUM_ADX_WEAK_THRESHOLD = 20

# 整合周期内最高分与最低分差异超过此阈值时，判定为信号冲突
MOMENTUM_CONFLICT_SCORE_DIFF_THRESHOLD = 5.0

# （可选）您也可以将指标计算的参数放在这里，例如：
# MOMENTUM_RSI_PERIOD = 14
# MOMENTUM_EMA_SHORT_PERIOD = 12
# MOMENTUM_EMA_LONG_PERIOD = 26
# 等等...

# --- 其他配置 ---
# ... 您原有的其他配置 ...

# --- 成交流分析 配置 (Trade Flow Analysis Config) ---
TRADE_FLOW_CONFIG = {
    'fetch_limit': 1000, # 获取近期成交记录的数量 (替代之前的全局变量)
    'large_order_percentiles': [95, 98], # 要分析的大单百分位
    'primary_percentile': 98, # 用于主要解读和对比的百分位
    'analysis_windows_seconds': [60, 300, 900], # 要分析的时间窗口 (秒)
    # 解读阈值 (从旧的全局字典移入)
    'INTERPRETATION_THRESHOLDS': {
        # 主动买卖量比率
        'taker_vol_strong_buy': 2.0,
        'taker_vol_weak_buy': 1.3,
        'taker_vol_weak_sell': 0.7,
        'taker_vol_strong_sell': 0.5,
        # 大单主动买卖量比率 (以 primary_percentile 为准)
        'large_taker_vol_strong_buy': 1.8,
        'large_taker_vol_weak_buy': 1.2,
        'large_taker_vol_weak_sell': 0.8,
        'large_taker_vol_strong_sell': 0.6,
        # 大单贡献度 (%)
        'large_vol_contribution_pct': 20.0, 
        'large_trade_contribution_pct': 10.0,
        # 趋势判断 (% 变化)
        'trend_ratio_change_threshold': 0.2,
        'trend_large_count_change_threshold': 0.3,
        'trend_large_volume_change_threshold': 0.3,
        'price_change_significant_pct': 0.1,
        'trend_frequency_change_threshold': 0.3,
        'trend_avg_trade_size_change_threshold': 0.25,
        'large_price_stddev_high_pct': 0.15, 
    }
}

# --- 订单簿分析 配置 (Order Book Analysis Config) ---
ORDER_BOOK_CONFIG = {
    'depth_limit': 500, # <--- 修改这里！获取订单簿的档数 (原为 100)
    'large_order_percentile': 95, # 定义大单挂单的百分位
    'n_levels_analysis': 100, # <--- 修改这里！主要解读使用的档数 (原为 20)
    'cumulative_depth_levels_pct': [0.1, 0.2, 0.5], # 计算累计深度使用的百分比范围
    # 解读阈值 (从旧的全局字典移入，保持键名一致方便模块内部查找)
    'INTERPRETATION_THRESHOLDS': {
        "OIR_STRONG": 0.4,
        "OIR_WEAK": 0.1,
        "CUM_RATIO_STRONG": 1.8,
        "CUM_RATIO_WEAK": 1.3,
        "LARGE_ORDER_SIG_FACTOR": 0.1,
        "LIQUIDITY_GAP_FACTOR": 5.0,
    }
}

# --- 综合分析模块 (Integrated Analysis) ---
INTEGRATED_ANALYSIS_CONFIG = {
    # 用于 _generate_summary 的阈值
    'SUMMARY_THRESHOLDS': {
        'TakerRatioThreshold_Bull': 1.1,
        'TakerRatioThreshold_Bear': 0.9,
        'OIRThreshold_Bull': 0.5,
        'OIRThreshold_Bear': -0.5,
        # 可以添加更多阈值，例如对大单 Taker Ratio 的要求等
        'LargeTakerRatioThreshold_Bull': 1.5,
        'LargeTakerRatioThreshold_Bear': 0.7,
    },
    # (未来可以添加更多综合分析的配置)
}

# ===== 箱体突破分析配置 (改为 日线+1小时 适合短线) =====
BOX_BREAKOUT_CONFIG = {
    # 主箱体 (日线)
    'main_box_timeframe': '1d',      # 时间周期
    'main_box_length': 20,           # 计算箱体的 K 线数量 (例如过去20天)
    
    # 次级箱体 (1小时)
    'secondary_box_timeframe': '1h', # 时间周期 
    'secondary_box_length': 24,      # 计算箱体的 K 线数量 (例如过去24小时)
    
    # 量能分析 (基于主箱体时间周期，即日线)
    'volume_ma_length': 20,         # 计算日线成交量移动平均的周期 (例如过去20天)
    'volume_ratio_threshold': 1.5,  # 上一日成交量 / 日成交量均值 的阈值 (短线要求可能更高)
    
    # 突破确认
    'breakout_confirmation_pct': 0.3, # 突破确认百分比 (短线可适当调低)
    
    # 斐波那契水平 (基于主箱体)
    'fibonacci_levels': [0, 23.6, 38.2, 50, 61.8, 78.6, 100],
}

# --- 其他全局配置 ---
# 可以在这里添加如数据库连接、通知设置等其他全局配置项
# ...

# --- 打印加载的配置 (可选，用于调试) ---
# print(f"Loaded Config - API Key Set: {BINANCE_API_KEY != 'YOUR_API_KEY_PLACEHOLDER'}")
# print(f"Loaded Config - Default Interval: {DEFAULT_INTERVAL}")
# print(f"Loaded Config - Micro Trend Config Params: {MICRO_TREND_CONFIG.get('PARAMS', {})}")
# print(f"Loaded Config - Order Book Config Thresholds: {ORDER_BOOK_CONFIG.get('interpretation_thresholds', {})}")

# --- 结束配置 --- 
print("配置模块加载完毕。")

# --- 微观趋势动量模块 配置字典 (添加) ---
MICRO_TREND_CONFIG = {
    'PARAMS': {
        'ema_short_period': 10,
        'ema_long_period': 30,
        'roc_period': 9,
        'rsi_period': 14,
        'bb_period': 20,
        'bb_std_dev': 2.0,
        'macd_fast_period': 12,
        'macd_slow_period': 26,
        'macd_signal_period': 9,
        'volume_ma_period': 20,
        'kdj_length': 9,
        'kdj_signal': 3,
        'kdj_k_period': 3,
        'ichimoku_tenkan': 9,
        'ichimoku_kijun': 26,
        'ichimoku_senkou_b': 52,
        'adx_length': 14
    },
    'THRESHOLDS': { # 解读用阈值
        'trend_strength_threshold': 0.001,
        'momentum_strength_threshold': 0.1,
        'rsi_oversold': 30,
        'rsi_overbought': 70,
        'volume_increase_threshold': 1.2,
        'kdj_overbought': 80,
        'kdj_oversold': 20,
        'adx_trend_threshold': 25,
        'adx_weak_threshold': 20 # 这个就是 MOMENTUM_ADX_WEAK_THRESHOLD
    },
    'SCORING': { # 评分用权重和阈值
        'WEIGHTS': {
            'strong_bull_trend': 3, 'bull_trend': 1, 'strong_bear_trend': -3, 'bear_trend': -1,
            'strong_pos_mom': 2, 'pos_mom': 1, 'strong_neg_mom': -2, 'neg_mom': -1,
            'rsi_overbought': -2, 'rsi_oversold': 2,
            'kdj_overbought': -1, 'kdj_oversold': 1,
            'macd_gold_cross': 3, 'macd_dead_cross': -3,
            'kdj_gold_cross': 2, 'kdj_dead_cross': -2,
            'macd_hist_pos': 1, 'macd_hist_neg': -1,
            'kdj_k_above_d': 0.5, 'kdj_d_above_k': -0.5,
            'price_above_cloud': 2, 'price_below_cloud': -2,
            'tenkan_above_kijun': 1, 'kijun_above_tenkan': -1,
            'adx_strong_pos': 2, 'adx_medium_pos': 1, 'adx_strong_neg': -2, 'adx_medium_neg': -1
            # 可以添加 volume 相关的评分权重
        },
        'THRESHOLDS': { # 评分映射信号用阈值
            'strong_bullish': 8, 'bullish': 3, 'strong_bearish': -8, 'bearish': -3,
            'adx_weak_override_enabled': True,
            'adx_weak_max_signal': 1 # ADX弱趋势时，评分绝对值超过此值也会被覆盖
        }
    }
    # INTEGRATION 配置已移出到全局配置变量
} 