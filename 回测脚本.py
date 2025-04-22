# -*- coding: utf-8 -*-
"""
简单的回测脚本，使用固定风险比例和止损

修改自之前的马丁格尔版本
"""

import logging
import json
import pandas as pd
import math
from datetime import datetime, timedelta

# --- 日志配置 (提前初始化) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 假设 策略模块 和 数据获取模块 在同一目录
try:
    from 数据获取模块 import 获取K线数据
    # from 策略_5分钟 import rsi_sma_strategy # <-- 注释掉旧策略
    from 策略_5分钟 import macd_ema_strategy # <-- 导入新策略函数
except ImportError as e:
    logger.error(f"无法导入模块: {e}。请确保 '数据获取模块.py' 和 '策略_5分钟.py' 文件存在且路径正确。")
    exit()

# --- 回测引擎类 ---
class BacktestEngine:
    def __init__(self, symbol, market_type, interval, start_time, end_time,
                 initial_capital, commission_rate, sma_period,
                 risk_per_trade, stop_loss_percentage,
                 reward_ratio,
                 leverage):
        self.symbol = symbol
        self.market_type = market_type
        self.interval = interval
        self.start_time_str = start_time
        self.end_time_str = end_time
        self.initial_capital = float(initial_capital)
        self.commission_rate = float(commission_rate)
        self.sma_period = int(sma_period)
        self.risk_per_trade = float(risk_per_trade)
        self.stop_loss_percentage = float(stop_loss_percentage)
        self.reward_ratio = float(reward_ratio)
        self.leverage = float(leverage)

        self.equity = self.initial_capital
        self.position = None # 持仓状态: {'direction': 'LONG'/'SHORT', 'entry_price': float, 'size': float, 'stop_loss_price': float, 'take_profit_price': float, 'entry_timestamp': datetime}
        self.trades = [] # 交易记录
        self.portfolio_history = [] # 资产净值历史

        self.historical_data = None

        # --- 定义指标参数 ---
        # self.sma_period = int(sma_period) # 不再需要 SMA
        # self.rsi_period = 14 # 不再需要 RSI
        self.long_ema_period = 120 # 长期 EMA 周期 (趋势过滤)
        self.macd_fast = 12 # MACD 快线周期
        self.macd_slow = 26 # MACD 慢线周期
        self.macd_signal = 9 # MACD 信号线周期
        # self.atr_period = 14 # 不再需要 ATR

        # logger.info(f"SMA 周期: {sma_period}, RSI 周期: {self.rsi_period}, Long EMA 周期: {self.long_ema_period}, ATR 周期: {self.atr_period}")
        logger.info(f"Long EMA 周期: {self.long_ema_period}")
        logger.info(f"MACD 参数: fast={self.macd_fast}, slow={self.macd_slow}, signal={self.macd_signal}")
        logger.info("回测引擎初始化完成。")
        logger.info(f"参数: Symbol={symbol}, Market={market_type}, Interval={interval}")
        logger.info(f"时间范围: {start_time} to {end_time}")
        logger.info(f"初始资金: {initial_capital:.2f}")
        logger.info(f"风险/交易: {risk_per_trade*100:.2f}%, 止损百分比: {stop_loss_percentage*100:.2f}%")
        logger.info(f"风险回报比 (止损:止盈): 1:{self.reward_ratio:.1f}")
        logger.info(f"杠杆倍数: {self.leverage:.0f}x")

    def _fetch_data(self):
        logger.info(f"正在获取 {self.symbol} {self.market_type} {self.interval} K线数据...")
        self.historical_data = 获取K线数据(
            symbol=self.symbol,
            interval=self.interval,
            start_time=self.start_time_str,
            end_time=self.end_time_str,
            market_type=self.market_type
        )
        if self.historical_data is None or self.historical_data.empty:
            logger.error("获取历史数据失败或数据为空。")
            return False
        logger.info(f"成功获取 {len(self.historical_data)} 条原始 K 线数据。")
        return True

    def _prepare_data(self):
        if self.historical_data is None:
            return False

        # 数据类型转换和时间戳索引
        try:
            ohlcv_cols = ['open', 'high', 'low', 'close', 'volume']
            for col in ohlcv_cols:
                if col in self.historical_data.columns:
                    self.historical_data[col] = pd.to_numeric(self.historical_data[col], errors='coerce')
                else:
                    logger.warning(f"历史数据中缺少列: {col}")

            if 'timestamp' in self.historical_data.columns and not isinstance(self.historical_data.index, pd.DatetimeIndex):
                self.historical_data['timestamp'] = pd.to_datetime(self.historical_data['timestamp'], unit='ms')
                self.historical_data.set_index('timestamp', inplace=True)
            elif isinstance(self.historical_data.index, pd.DatetimeIndex):
                 logger.info("数据获取函数已返回带 DatetimeIndex 的 DataFrame。")
            else:
                 logger.error("无法识别 DataFrame 中的时间戳列或索引。")
                 return False

            if 'close' not in self.historical_data.columns:
                 logger.error("历史数据缺少 'close' 列。")
                 return False

            initial_rows = len(self.historical_data)
            self.historical_data.dropna(subset=ohlcv_cols, inplace=True) # Drop rows with NaN in essential columns
            removed_rows = initial_rows - len(self.historical_data)
            if removed_rows > 0:
                 logger.warning(f"数据清洗：移除了 {removed_rows} 行包含 NaN 的数据。")

        except Exception as e:
             logger.error(f"处理历史数据时发生错误: {e}", exc_info=True)
             return False

        if self.historical_data.empty:
            logger.error("数据清洗后为空。")
            return False

        # --- 预计算指标 ---
        # logger.info(f"预计算 SMA({self.sma_period})...") # 移除
        # self.historical_data['sma'] = self.historical_data['close'].rolling(window=self.sma_period).mean() # 移除

        # logger.info(f"预计算 RSI({self.rsi_period})...") # 移除
        # ... (RSI calculation removed) ...

        # 预计算长期 EMA (保留)
        logger.info(f"预计算 EMA({self.long_ema_period})...")
        try:
            import pandas_ta as ta # 确保导入
            self.historical_data.ta.ema(length=self.long_ema_period, append=True)
            ema_col_name = f'EMA_{self.long_ema_period}'
            self.historical_data.rename(columns={ema_col_name: 'long_ema'}, inplace=True)
            logger.info("长期 EMA 计算完成。")
        except ImportError:
            logger.error("无法导入 'pandas_ta' 库。长期 EMA 指标将不可用。请运行 'pip install pandas_ta'")
            self.historical_data['long_ema'] = pd.NA
        except Exception as e:
            logger.error(f"计算长期 EMA 时出错: {e}", exc_info=True)
            self.historical_data['long_ema'] = pd.NA

        # 预计算 MACD
        logger.info(f"预计算 MACD({self.macd_fast},{self.macd_slow},{self.macd_signal})...")
        try:
            import pandas_ta as ta # 确保导入
            self.historical_data.ta.macd(fast=self.macd_fast, slow=self.macd_slow, signal=self.macd_signal, append=True)
            # pandas_ta 会生成如 MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
            macd_suffix = f'_{self.macd_fast}_{self.macd_slow}_{self.macd_signal}'
            self.historical_data.rename(columns={
                f'MACD{macd_suffix}': 'macd',
                f'MACDh{macd_suffix}': 'macd_hist',
                f'MACDs{macd_suffix}': 'macd_signal'
            }, inplace=True)
            logger.info("MACD 计算完成。")
        except ImportError:
            logger.error("无法导入 'pandas_ta' 库。MACD 指标将不可用。请运行 'pip install pandas_ta'")
            self.historical_data['macd'] = pd.NA
            self.historical_data['macd_hist'] = pd.NA
            self.historical_data['macd_signal'] = pd.NA
        except Exception as e:
            logger.error(f"计算 MACD 时出错: {e}", exc_info=True)
            self.historical_data['macd'] = pd.NA
            self.historical_data['macd_hist'] = pd.NA
            self.historical_data['macd_signal'] = pd.NA

        # logger.info(f"预计算 ATR({self.atr_period})...") # 移除
        # ... (ATR calculation removed) ...

        # 添加前一 K 线数据用于判断穿越
        self.historical_data['prev_close'] = self.historical_data['close'].shift(1)
        # self.historical_data['prev_sma'] = self.historical_data['sma'].shift(1) # 移除
        # self.historical_data['prev_macd'] = self.historical_data['macd'].shift(1) # 不再需要 prev_macd
        # self.historical_data['prev_macd_signal'] = self.historical_data['macd_signal'].shift(1) # 不再需要 prev_macd_signal
        self.historical_data['prev_macd_hist'] = self.historical_data['macd_hist'].shift(1) # <-- 需要 Histogram 前值

        # 移除因计算指标和 shift 产生的初始 NaN 行
        initial_rows = len(self.historical_data)
        # 更新所需列
        required_cols = ['close', 'long_ema', 'macd_hist', 'prev_macd_hist'] # <-- 更新依赖列
        self.historical_data.dropna(subset=required_cols, inplace=True)
        removed_rows = initial_rows - len(self.historical_data)
        if removed_rows > 0:
            logger.info(f"移除了开始的 {removed_rows} 行数据以满足指标计算和数据对齐。")

        if self.historical_data.empty:
            logger.error(f"计算指标并移除 NaN 后数据为空，无法进行回测。")
            return False

        logger.info(f"成功准备 {len(self.historical_data)} 条 K线数据用于回测。")
        return True

    def _execute_trade(self, action, price, size, timestamp, stop_loss_price=None, margin_required=0.0):
        notional_value = size * price
        commission = notional_value * self.commission_rate

        # --- 恢复基于风险回报比的止盈价格计算 ---
        take_profit_price = None
        if stop_loss_price is not None and self.reward_ratio > 0:
            risk_per_contract = abs(price - stop_loss_price)
            if risk_per_contract > 0:
                profit_target_per_contract = risk_per_contract * self.reward_ratio
                if action == 'OPEN_LONG':
                    take_profit_price = price + profit_target_per_contract
                elif action == 'OPEN_SHORT':
                    # Ensure take profit price isn't negative
                    calculated_tp = price - profit_target_per_contract
                    take_profit_price = max(0, calculated_tp) # Price cannot be negative
                    if calculated_tp < 0:
                         logger.warning(f"{timestamp}: 计算出的空单止盈价格为负 ({calculated_tp:.4f})，已修正为 0。")
            else:
                 logger.warning(f"{timestamp}: 止损价等于入场价 ({price:.4f})，无法计算止盈价格。")
        # -------------------------------------------

        if action == 'OPEN_LONG':
            # 检查保证金和手续费
            if self.equity >= margin_required + commission:
                self.equity -= commission # <--- 新：只扣除开仓手续费
                self.position = {
                    'direction': 'LONG',
                    'entry_price': price,
                    'size': size,
                    'stop_loss_price': stop_loss_price,
                    'take_profit_price': take_profit_price,
                    'entry_timestamp': timestamp,
                    'margin_used': margin_required, # <--- 记录使用的保证金
                    'open_commission': commission # <--- 记录开仓手续费
                }
                self.trades.append({
                    'timestamp': timestamp,
                    'action': action,
                    'price': price,
                    'size': size,
                    'commission': commission,
                    'margin_required': margin_required,
                    'equity_after': self.equity
                })
                sl_str = f"{stop_loss_price:.2f}" if stop_loss_price is not None else '无'
                tp_str = f"{take_profit_price:.2f}" if take_profit_price is not None else '无'
                logger.debug(f"{timestamp}: 开多仓 {size:.4f} @ {price:.2f}, 止损: {sl_str}, 止盈: {tp_str}, 保证金: {margin_required:.2f}, 佣金: {commission:.2f}")
                return True
            else:
                logger.warning(f"{timestamp}: 资金不足无法开多仓 ({size:.4f} @ {price:.2f}). 需要保证金: {margin_required:.2f} + 佣金: {commission:.2f}, 可用权益: {self.equity:.2f}")
                return False
        elif action == 'OPEN_SHORT':
            # 检查保证金和手续费
            if self.equity >= margin_required + commission:
                self.equity -= commission # <--- 新：只扣除开仓手续费
                self.position = {
                    'direction': 'SHORT',
                    'entry_price': price,
                    'size': size,
                    'stop_loss_price': stop_loss_price,
                    'take_profit_price': take_profit_price,
                    'entry_timestamp': timestamp,
                    'margin_used': margin_required,
                    'open_commission': commission
                }
                self.trades.append({
                    'timestamp': timestamp,
                    'action': action,
                    'price': price,
                    'size': size,
                    'commission': commission,
                    'margin_required': margin_required,
                    'equity_after': self.equity
                })
                sl_str = f"{stop_loss_price:.2f}" if stop_loss_price is not None else '无'
                tp_str = f"{take_profit_price:.2f}" if take_profit_price is not None else '无'
                logger.debug(f"{timestamp}: 开空仓 {size:.4f} @ {price:.2f}, 止损: {sl_str}, 止盈: {tp_str}, 保证金: {margin_required:.2f}, 佣金: {commission:.2f}")
                return True
            else:
                 logger.warning(f"{timestamp}: 资金不足无法开空仓 ({size:.4f} @ {price:.2f}). 需要保证金: {margin_required:.2f} + 佣金: {commission:.2f}, 可用权益: {self.equity:.2f}")
                 return False
        return False

    def _close_trade(self, price, timestamp, reason="Signal"):
        if not self.position:
            return False

        close_size = self.position['size']
        entry_price = self.position['entry_price']
        direction = self.position['direction']
        open_commission = self.position.get('open_commission', 0.0) # 获取开仓手续费

        # 计算平仓手续费
        close_notional = close_size * price
        close_commission = close_notional * self.commission_rate
        total_commission = open_commission + close_commission

        # 计算原始 PnL (不含手续费)
        pnl_raw = 0
        if direction == 'LONG':
            pnl_raw = (price - entry_price) * close_size
            action = 'CLOSE_LONG'
        elif direction == 'SHORT':
            pnl_raw = (entry_price - price) * close_size
            action = 'CLOSE_SHORT'

        # 计算净 PnL (扣除双边手续费)
        pnl_net = pnl_raw - total_commission

        # 更新权益
        self.equity += pnl_net # <--- 新：直接加上净盈亏

        log_msg_detail = f"开仓: {entry_price:.2f}, 平仓: {price:.2f} ({reason}). PnL(原始): {pnl_raw:.2f}, PnL(净): {pnl_net:.2f}, 总佣金: {total_commission:.2f}"
        if direction == 'LONG':
             logger.debug(f"{timestamp}: 平多仓 {close_size:.4f}. {log_msg_detail}")
        elif direction == 'SHORT':
             logger.debug(f"{timestamp}: 平空仓 {close_size:.4f}. {log_msg_detail}")

        self.trades.append({
            'timestamp': timestamp,
            'action': action,
            'price': price,
            'size': close_size,
            'pnl': pnl_net, # 记录净 PnL
            'commission': total_commission, # 记录总佣金
            'equity_after': self.equity,
            'reason': reason
        })

        # 记录已实现 PnL 和相关统计 (使用净 PnL)
        self.closed_trade_pnl.append(pnl_net)
        if pnl_net > 0:
            self.total_profit += pnl_net
            self.winning_trades += 1
        else:
            self.total_loss += abs(pnl_net)
            self.losing_trades += 1

        self.position = None # 清空仓位
        return True

    def run_backtest(self):
        if not self._fetch_data() or not self._prepare_data():
            logger.error("数据准备失败，无法运行回测。")
            return

        # 初始化统计变量
        self.closed_trade_pnl = []
        self.total_profit = 0.0
        self.total_loss = 0.0
        self.winning_trades = 0
        self.losing_trades = 0

        logger.info(f"开始回测: {self.symbol}, 时间范围: {self.historical_data.index.min()} - {self.historical_data.index.max()}")

        for bar in self.historical_data.itertuples():
            timestamp = bar.Index
            current_price = bar.close
            current_high = bar.high
            current_low = bar.low
            current_sma = bar.sma

            if pd.isna(current_price) or current_price <= 0 or pd.isna(current_sma):
                self.portfolio_history.append({'timestamp': timestamp, 'equity': self.equity})
                continue

            # --- 0. 检查止损 ---
            if self.position:
                sl_price = self.position['stop_loss_price']

                # === 安全检查和日志 ===
                high_is_numeric = isinstance(current_high, (int, float))
                low_is_numeric = isinstance(current_low, (int, float))
                sl_is_numeric = isinstance(sl_price, (int, float))

                if not (high_is_numeric and low_is_numeric and sl_is_numeric):
                    logger.error(f"时间: {timestamp}, 止损检查跳过：无效数据类型。 "
                                 f"High: {current_high} ({type(current_high)}), "
                                 f"Low: {current_low} ({type(current_low)}), "
                                 f"SL: {sl_price} ({type(sl_price)})" )
                else:
                    # === 实际止损逻辑 (现在可以安全比较) ===
                    triggered_sl = False
                    trigger_price = sl_price # 假设止损价成交

                    if self.position['direction'] == 'LONG' and current_low <= sl_price:
                        triggered_sl = True
                        logger.info(f"{timestamp}: 多单止损触发 @ {sl_price:.2f} (当前 Low: {current_low:.2f})")
                    elif self.position['direction'] == 'SHORT' and current_high >= sl_price:
                        triggered_sl = True
                        logger.info(f"{timestamp}: 空单止损触发 @ {sl_price:.2f} (当前 High: {current_high:.2f})")

                    if triggered_sl:
                        self._close_trade(price=trigger_price, timestamp=timestamp, reason="StopLoss")
                        # 止损后，本 K 线不再进行其他操作
                        self.portfolio_history.append({'timestamp': timestamp, 'equity': self.equity})
                        continue # Move to next bar

            # --- 0.5 检查止盈 (在检查止损之后) ---
            if self.position: # 再次检查，因为可能已被止损平仓
                tp_price = self.position.get('take_profit_price') # 使用 get 以防旧数据没有此键

                if tp_price is not None:
                    # === 安全检查和日志 ===
                    high_is_numeric = isinstance(current_high, (int, float))
                    low_is_numeric = isinstance(current_low, (int, float))
                    tp_is_numeric = isinstance(tp_price, (int, float))

                    if not (high_is_numeric and low_is_numeric and tp_is_numeric):
                        logger.error(f"时间: {timestamp}, 止盈检查跳过：无效数据类型。 "
                                     f"High: {current_high} ({type(current_high)}), "
                                     f"Low: {current_low} ({type(current_low)}), "
                                     f"TP: {tp_price} ({type(tp_price)})" )
                    else:
                        # === 实际止盈逻辑 ===
                        triggered_tp = False
                        trigger_price = tp_price # 假设止盈价成交

                        if self.position['direction'] == 'LONG' and current_high >= tp_price:
                            triggered_tp = True
                            logger.info(f"{timestamp}: 多单止盈触发 @ {tp_price:.2f} (当前 High: {current_high:.2f})")
                        elif self.position['direction'] == 'SHORT' and current_low <= tp_price:
                            triggered_tp = True
                            logger.info(f"{timestamp}: 空单止盈触发 @ {tp_price:.2f} (当前 Low: {current_low:.2f})")

                        if triggered_tp:
                            self._close_trade(price=trigger_price, timestamp=timestamp, reason="TakeProfit")
                            # 止盈后，本 K 线不再进行其他操作
                            self.portfolio_history.append({'timestamp': timestamp, 'equity': self.equity})
                            continue # Move to next bar

            # --- 1. 调用策略生成信号 (如果未被止损或止盈) ---
            signal = 'HOLD' # 默认信号
            signal_reason = 'No signal'
            if self.position is None: # 仅在没有持仓时才生成开仓信号
                current_bar_data = pd.Series(bar._asdict()).drop('Index')
                try:
                    # 调用新的 MACD 策略函数
                    strategy_signal_info = macd_ema_strategy(
                        bar_data=current_bar_data,
                        position=self.position,
                        long_ema_period=self.long_ema_period
                    )
                    signal = strategy_signal_info['signal']
                    signal_reason = strategy_signal_info['reason']
                    if signal != 'HOLD':
                         logger.debug(f"时间: {timestamp}, 策略信号: {signal}, 原因: {signal_reason}")
                except KeyError as e:
                     logger.error(f"时间: {timestamp}, 传递给 MACD 策略函数的数据缺少键: {e}。 K线数据: {current_bar_data}", exc_info=True)
                except Exception as e:
                     logger.error(f"时间: {timestamp}, 调用策略函数 macd_ema_strategy 时出错: {e}", exc_info=True)
            # 不再需要为获取平仓信号单独调用策略，因为新策略不生成平仓信号
            # elif self.position: ... (移除此块)

            # --- 2. 执行交易 (基于策略信号) ---
            execution_price = current_price # 简化成交价

            # 开仓逻辑不变，根据 signal 执行
            if signal == 'LONG' and self.position is None:
                stop_loss_price = execution_price * (1 - self.stop_loss_percentage)
                # 计算仓位大小
                potential_loss_per_contract = execution_price - stop_loss_price
                if potential_loss_per_contract <= 0:
                    logger.warning(f"{timestamp}: 潜在损失计算错误 ({potential_loss_per_contract:.4f}), 无法开多仓。SL: {stop_loss_price:.2f}")
                else:
                    risk_amount = self.equity * self.risk_per_trade
                    size = risk_amount / potential_loss_per_contract
                    notional_value = size * execution_price
                    margin_required = notional_value / self.leverage
                    # 检查名义价值是否超过总资金 (粗略杠杆检查) - 这个检查在杠杆下意义不大，保证金检查更重要
                    # if notional_value > self.equity:
                    #     logger.warning(f"计算出的仓位名义价值 ({notional_value:.2f}) 超过总权益 ({self.equity:.2f})，减小仓位。")
                    #     size = self.equity / execution_price * 0.95 # 使用 95% 资金作为最大名义价值
                    #     notional_value = size * execution_price
                    #     margin_required = notional_value / self.leverage

                    if size > 0:
                        # 传递 margin_required 给 _execute_trade
                        self._execute_trade('OPEN_LONG', execution_price, size, timestamp, stop_loss_price, margin_required)

            elif signal == 'SHORT' and self.position is None:
                 stop_loss_price = execution_price * (1 + self.stop_loss_percentage)
                 potential_loss_per_contract = stop_loss_price - execution_price
                 if potential_loss_per_contract <= 0:
                      logger.warning(f"{timestamp}: 潜在损失计算错误 ({potential_loss_per_contract:.4f}), 无法开空仓。SL: {stop_loss_price:.2f}")
                 else:
                      risk_amount = self.equity * self.risk_per_trade
                      size = risk_amount / potential_loss_per_contract
                      notional_value = size * execution_price
                      margin_required = notional_value / self.leverage
                      # if notional_value > self.equity:
                      #      logger.warning(f"计算出的仓位名义价值 ({notional_value:.2f}) 超过总权益 ({self.equity:.2f})，减小仓位。")
                      #      size = self.equity / execution_price * 0.95
                      #      notional_value = size * execution_price
                      #      margin_required = notional_value / self.leverage

                      if size > 0:
                           self._execute_trade('OPEN_SHORT', execution_price, size, timestamp, stop_loss_price, margin_required)

            # 记录每个时间点的资产净值
            current_portfolio_value = self.equity
            if self.position:
                # 估算当前持仓价值波动对净值的影响 (简化)
                if self.position['direction'] == 'LONG':
                    unrealized_pnl = (current_price - self.position['entry_price']) * self.position['size']
                else: # SHORT
                    unrealized_pnl = (self.position['entry_price'] - current_price) * self.position['size']
                # 粗略加上未实现盈亏，不考虑手续费
                current_portfolio_value += unrealized_pnl

            self.portfolio_history.append({'timestamp': timestamp, 'equity': current_portfolio_value})


        logger.info("回测循环结束。")
        self._calculate_metrics()


    def _calculate_metrics(self):
        if not self.portfolio_history:
            logger.warning("没有足够的历史记录来计算指标。")
            return

        portfolio_df = pd.DataFrame(self.portfolio_history)
        portfolio_df.set_index('timestamp', inplace=True)

        # 1. 最终净值 & 总收益率
        final_equity = portfolio_df['equity'].iloc[-1]
        total_return_pct = (final_equity / self.initial_capital - 1) * 100

        # 2. 最大回撤 (基于每日或每个 bar 的净值)
        portfolio_df['peak'] = portfolio_df['equity'].cummax()
        portfolio_df['drawdown'] = portfolio_df['equity'] / portfolio_df['peak'] - 1
        max_drawdown = portfolio_df['drawdown'].min() * 100

        # 3. 夏普比率 (简化：假设无风险利率为0，使用日收益率)
        # 确保索引是 DatetimeIndex
        if not isinstance(portfolio_df.index, pd.DatetimeIndex):
             logger.warning("无法计算夏普比率，因为 portfolio_history 的索引不是 DatetimeIndex。")
             sharpe_ratio = None
        else:
             # 重新采样为日数据（如果原始数据频率低于日）
             daily_equity = portfolio_df['equity'].resample('D').last().ffill()
             daily_returns = daily_equity.pct_change().dropna()
             if len(daily_returns) > 1 and daily_returns.std() != 0:
                 # 年化夏普比率 (假设一年 252 个交易日)
                 sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * math.sqrt(252)
             else:
                 sharpe_ratio = 0 # 无法计算或标准差为 0

        # 4. 交易统计 (基于已关闭的交易)
        num_trades = len(self.closed_trade_pnl)
        num_winning = self.winning_trades
        num_losing = self.losing_trades

        win_rate = (num_winning / num_trades * 100) if num_trades > 0 else 0
        loss_rate = (num_losing / num_trades * 100) if num_trades > 0 else 0
        total_pnl = self.total_profit - self.total_loss
        profit_factor = (self.total_profit / self.total_loss) if self.total_loss > 0 else float('inf')
        avg_win = (self.total_profit / num_winning) if num_winning > 0 else 0
        avg_loss = (self.total_loss / num_losing) if num_losing > 0 else 0 # avg_loss is positive value
        avg_pnl_per_trade = (total_pnl / num_trades) if num_trades > 0 else 0

        # 打印结果
        logger.info("\n--- 回测结果 ---")
        logger.info(f"时间范围: {self.historical_data.index.min()} - {self.historical_data.index.max()}")
        logger.info(f"初始资金: {self.initial_capital:.2f} USDT")
        logger.info(f"最终净值: {final_equity:.2f} USDT")
        logger.info(f"总收益率: {total_return_pct:.2f}%")
        logger.info(f"最大回撤: {max_drawdown:.2f}%")
        logger.info(f"夏普比率 (年化, 简化): {sharpe_ratio:.2f}" if sharpe_ratio is not None else "夏普比率 (年化, 简化): N/A")
        logger.info(f"总平仓交易数: {num_trades}")
        logger.info(f"盈利交易数: {num_winning}")
        logger.info(f"亏损交易数: {num_losing}")
        logger.info(f"胜率: {win_rate:.2f}%")
        # logger.info(f"亏损率: {loss_rate:.2f}%") # Redundant if win rate is shown
        logger.info(f"总盈利: {self.total_profit:.2f} USDT")
        logger.info(f"总亏损: {self.total_loss:.2f} USDT")
        logger.info(f"净利润: {total_pnl:.2f} USDT")
        logger.info(f"盈利因子: {profit_factor:.2f}")
        logger.info(f"平均盈利: {avg_win:.2f} USDT")
        logger.info(f"平均亏损: {avg_loss:.2f} USDT")
        logger.info(f"平均每笔交易盈亏: {avg_pnl_per_trade:.2f} USDT")

        # 可以选择保存结果
        # self.save_results(portfolio_df)

    def save_results(self, portfolio_df):
        try:
            trades_df = pd.DataFrame(self.trades)
            trades_df.to_csv(f"{self.symbol}_trades.csv", index=False)
            portfolio_df.to_csv(f"{self.symbol}_portfolio.csv")
            logger.info("交易记录和资产组合历史已保存到 CSV 文件。")
        except Exception as e:
            logger.error(f"保存结果时出错: {e}")


# --- 主执行逻辑 ---
if __name__ == "__main__":
    # --- 回测配置 ---
    SYMBOL = 'BTCUSDT'
    MARKET_TYPE = 'futures' # 重要：确保使用合约数据
    KLINE_INTERVAL = '5m'
    # 设置为最近 3 个月
    backtest_end_time = datetime.now()
    backtest_start_time = backtest_end_time - timedelta(days=90) # 近似 3 个月
    # 或者取消注释并使用具体日期字符串:
    # backtest_start_time = "2024-04-18 00:00:00"
    # backtest_end_time = "2025-04-18 00:00:00"

    # --- 策略参数 ---
    SMA_PERIOD = 20
    INITIAL_CAPITAL = 10000.0
    COMMISSION_RATE = 0.0004
    RISK_PER_TRADE = 0.02 # 每次交易承担 2% 的风险
    STOP_LOSS_PERCENTAGE = 0.02
    REWARD_RATIO = 1.5 # <--- 恢复并设置为 1:1.5
    LEVERAGE = 10.0
    # ATR 过滤参数
    ATR_PERIOD = 14 # 与策略模块中默认值一致 (虽然引擎不直接用，但保持一致性)
    MIN_RELATIVE_VOLATILITY = 0.001 # ATR/Close 必须 > 0.1% 才开仓

    engine = BacktestEngine(
        symbol=SYMBOL,
        market_type=MARKET_TYPE,
        interval=KLINE_INTERVAL,
        start_time=backtest_start_time,
        end_time=backtest_end_time,
        initial_capital=INITIAL_CAPITAL,
        commission_rate=COMMISSION_RATE,
        sma_period=SMA_PERIOD,
        risk_per_trade=RISK_PER_TRADE,
        stop_loss_percentage=STOP_LOSS_PERCENTAGE,
        reward_ratio=REWARD_RATIO, # <--- 恢复传递 reward_ratio
        leverage=LEVERAGE # <--- 传递杠杆参数
    )

    # 策略函数参数由 BacktestEngine 的 run_backtest 内部处理传递所需数据
    # 但如果策略函数需要直接从引擎获取参数，需要修改引擎初始化和 run_backtest 调用

    engine.run_backtest() 