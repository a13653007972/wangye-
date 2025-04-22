import tkinter as tk
from tkinter import ttk # 使用 themed Tkinter widgets 更好看
from tkinter import scrolledtext # 带滚动条的文本框
from tkinter import messagebox
import threading
import queue
import time
import sys # 导入 sys 用于错误输出

# 导入分析函数和 获取交易所信息 函数
try:
    from deepseek分析模块 import 执行完整分析
    from 数据获取模块 import 获取交易所信息
except ImportError as e:
    messagebox.showerror("导入错误", f"无法导入所需模块: {e}\n请确保 deepseek分析模块.py 和 数据获取模块.py 文件存在。")
    # 定义假的执行函数和获取函数
    def 执行完整分析(symbol, market_type):
        time.sleep(1)
        return f"错误：无法加载分析模块。模拟分析 {symbol} ({market_type})"
    def 获取交易所信息():
        print("警告：无法加载数据获取模块，使用模拟交易对列表。")
        # 返回一个模拟的结构
        return {'symbols': [
            {'symbol': 'BTCUSDT', 'status': 'TRADING', 'quoteAsset': 'USDT'},
            {'symbol': 'ETHUSDT', 'status': 'TRADING', 'quoteAsset': 'USDT'},
            {'symbol': 'NOTUSDT', 'status': 'TRADING', 'quoteAsset': 'USDT'}
        ]}

class 主分析窗口:
    def __init__(self, root):
        self.root = root
        self.root.title("DeepSeek 加密货币分析工具")
        self.root.geometry("700x650")
        
        # ---> 配置根窗口 grid 权重 <--- 
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1) # 批量选择区域可扩展
        self.root.rowconfigure(3, weight=2) # 结果区域可扩展

        self.result_queue = queue.Queue()
        self.is_analyzing = False
        self.all_symbols_list = []
        self.batch_check_vars = {}

        # --- 控件创建与布局 (使用 grid) ---
        # ---> 修改 Frame 布局为 grid <--- 
        input_frame = ttk.Frame(root, padding="10")
        input_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        batch_frame = ttk.Frame(root, padding="10")
        batch_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        control_frame = ttk.Frame(root, padding="10")
        control_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        output_frame = ttk.Frame(root, padding="10")
        output_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=5)
        status_frame = ttk.Frame(root, padding="5")
        status_frame.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 5)) # 底部状态栏

        # --- 单个币种选择 (使用 grid) ---
        # ---> 配置 input_frame grid 列权重 <--- 
        input_frame.columnconfigure(1, weight=1) # 让 Combobox 可以扩展一点

        ttk.Label(input_frame, text="选择或输入单个币种:").grid(row=0, column=0, padx=5, sticky="w")
        self.single_symbol_combo = ttk.Combobox(input_frame, width=25, state='disabled') # 调宽一点
        self.single_symbol_combo.grid(row=0, column=1, padx=5, sticky="ew")
        self.single_symbol_combo.bind('<KeyRelease>', self._on_combobox_keyrelease)
        self.single_symbol_combo.bind('<<ComboboxSelected>>', self._on_combobox_select)

        self.single_analyze_button = ttk.Button(input_frame, text="分析单个币种", command=self.分析单个币, state=tk.DISABLED)
        self.single_analyze_button.grid(row=0, column=2, padx=5)

        # --- 批量币种选择 (Checkbuttons in Scrollable Frame) ---
        # ---> 创建一个 Frame 来容纳标签和全选/反选按钮 <--- 
        batch_header_frame = ttk.Frame(batch_frame)
        batch_header_frame.grid(row=0, column=0, columnspan=2, sticky="ew") # columnspan=2 让 header 跨越下方两列
        batch_header_frame.columnconfigure(1, weight=1) # 让搜索框可以扩展

        ttk.Label(batch_header_frame, text="勾选多个币种 (可搜索):").grid(row=0, column=0, padx=(0,5), sticky="w") # 使用 grid

        # ---> 添加搜索框 <--- 
        self.batch_search_var = tk.StringVar()
        self.batch_search_entry = ttk.Entry(batch_header_frame, textvariable=self.batch_search_var, width=20)
        self.batch_search_entry.grid(row=0, column=1, padx=5, sticky="ew") # 使用 grid
        self.batch_search_entry.bind("<KeyRelease>", self._筛选批量列表) # 绑定事件

        # ---> 全选/全不选按钮使用 grid <--- 
        self.select_all_button = ttk.Button(batch_header_frame, text="全选", command=self._全选币种, width=8, state=tk.DISABLED)
        self.select_all_button.grid(row=0, column=2, padx=(5,0))
        self.deselect_all_button = ttk.Button(batch_header_frame, text="全不选", command=self._全不选币种, width=8, state=tk.DISABLED)
        self.deselect_all_button.grid(row=0, column=3, padx=(5,0))

        # 创建 Canvas 和 Scrollbar
        self.canvas = tk.Canvas(batch_frame, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(batch_frame, orient="vertical", command=self.canvas.yview)
        self.checkbutton_frame = ttk.Frame(self.canvas)
        self.canvas_frame_id = self.canvas.create_window((0, 0), window=self.checkbutton_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.scrollbar.grid(row=1, column=1, sticky="ns")
        self.checkbutton_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind('<Configure>', self._on_canvas_configure)

        self.batch_analyze_button = ttk.Button(batch_frame, text="分析选中币种", command=self.批量分析, state=tk.DISABLED)
        self.batch_analyze_button.grid(row=2, column=0, columnspan=2, pady=5)

        # --- 市场类型选择 (使用 grid) ---
        ttk.Label(control_frame, text="选择市场类型:").grid(row=0, column=0, padx=5, sticky="w")
        self.market_type_var = tk.StringVar(value='期货')
        self.market_options_display = ['期货', '现货']
        self.market_options_map = {'期货': 'futures', '现货': 'spot'}
        self.market_type_menu = ttk.OptionMenu(control_frame, self.market_type_var, self.market_options_display[0], *self.market_options_display)
        self.market_type_menu.grid(row=0, column=1, padx=5, sticky="w") # 左对齐
        self.market_type_menu.config(state=tk.DISABLED)

        # --- 结果显示区 (内部不变，外部 Frame 使用 grid) ---
        # ---> 配置 output_frame grid 行列权重 <--- 
        output_frame.rowconfigure(1, weight=1)
        output_frame.columnconfigure(0, weight=1)

        ttk.Label(output_frame, text="分析结果:").grid(row=0, column=0, sticky="w")
        self.result_text = scrolledtext.ScrolledText(output_frame, width=80, height=10, wrap=tk.WORD, state=tk.DISABLED)
        self.result_text.grid(row=1, column=0, sticky="nsew")

        # --- 状态栏 (内部不变，外部 Frame 使用 grid) ---
        self.status_var = tk.StringVar(value="状态：正在加载交易对列表...")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, anchor=tk.W)
        self.status_label.pack(fill=tk.X) # 状态栏简单用 pack 填充即可

        # --- 启动后台加载交易对和结果队列检查 ---
        self.load_symbols_thread = threading.Thread(target=self._加载交易对, daemon=True)
        self.load_symbols_thread.start()
        self.root.after(100, self._检查队列)

    def _on_frame_configure(self, event=None):
        """当内部 Frame 大小变化时，更新 Canvas 的滚动区域。"""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        """当 Canvas 大小变化时，调整内部 Frame 的宽度。"""
        canvas_width = event.width
        self.canvas.itemconfig(self.canvas_frame_id, width=canvas_width)

    def _加载交易对(self):
        """在后台线程中加载交易对列表"""
        try:
            exchange_info = 获取交易所信息()
            if exchange_info and 'symbols' in exchange_info:
                # 筛选活跃的 USDT 交易对 (期货和现货可能都需要USDT结尾)
                trading_symbols = [
                    s['symbol'] for s in exchange_info['symbols']
                    if s.get('status') == 'TRADING' and s.get('quoteAsset') == 'USDT'
                ]
                # 简单地过滤掉明显非标准的（例如包含下划线的特殊合约）
                self.all_symbols_list = sorted([s for s in trading_symbols if '_' not in s])
                # 通过队列通知主线程更新 GUI
                self.result_queue.put(("UPDATE_SYMBOLS", self.all_symbols_list))
            else:
                self.result_queue.put(("LOAD_ERROR", "未能从交易所信息获取交易对列表。返回数据为空或格式错误。"))
        except Exception as e:
            self.result_queue.put(("LOAD_ERROR", f"加载交易对时发生错误: {e}"))
            print(f"加载交易对时出错: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()

    def _更新交易对列表(self, symbols):
        """在主线程中更新 Combobox 和 Checkbutton 区域"""
        if symbols:
            self.all_symbols_list = symbols
            self.single_symbol_combo['values'] = self.all_symbols_list
            self.single_symbol_combo.config(state='normal')
            if symbols: self.single_symbol_combo.set(symbols[0])
            self.single_analyze_button.config(state=tk.NORMAL)
            
            # ---> 更新 Checkbutton 区域 (使用 Grid 实现多列) <--- 
            for widget in self.checkbutton_frame.winfo_children():
                widget.destroy()
            self.batch_check_vars.clear()
            self.batch_search_var.set("") # 清空搜索框
            
            num_columns = 4 
            for i in range(num_columns):
                self.checkbutton_frame.columnconfigure(i, weight=1)
            
            row_num = 0
            col_num = 0
            for symbol in symbols:
                var = tk.BooleanVar(value=False)
                self.batch_check_vars[symbol] = var
                cb = ttk.Checkbutton(self.checkbutton_frame, text=symbol, variable=var)
                # ---> 确认使用 grid 放置 <--- 
                cb.grid(row=row_num, column=col_num, padx=5, pady=2, sticky='w') 
                col_num += 1
                if col_num >= num_columns:
                    col_num = 0
                    row_num += 1
            
            self.checkbutton_frame.update_idletasks()
            self._on_frame_configure()
            
            # ---> 启用按钮 <--- 
            self.select_all_button.config(state=tk.NORMAL)
            self.deselect_all_button.config(state=tk.NORMAL)
            self.batch_analyze_button.config(state=tk.NORMAL)
            self.market_type_menu.config(state=tk.NORMAL)

            self.status_var.set(f"状态：加载了 {len(symbols)} 个交易对，空闲。")
        else:
            self.status_var.set("状态：未能加载交易对列表。")
            messagebox.showerror("加载失败", "无法加载交易对列表，请检查网络或 API 配置。")
            # 保持控件禁用状态

    def _锁定界面(self):
        self.is_analyzing = True
        self.single_symbol_combo.config(state=tk.DISABLED)
        # ---> 禁用 Checkbutton Frame <--- 
        # 简单方法是禁用按钮，防止重复提交
        self.single_analyze_button.config(state=tk.DISABLED)
        self.batch_analyze_button.config(state=tk.DISABLED)
        self.market_type_menu.config(state=tk.DISABLED)
        # ---> 禁用全选/全不选按钮 <--- 
        self.select_all_button.config(state=tk.DISABLED)
        self.deselect_all_button.config(state=tk.DISABLED)
        # 禁用 Checkbuttons
        for cb in self.checkbutton_frame.winfo_children():
             if isinstance(cb, ttk.Checkbutton):
                 cb.config(state=tk.DISABLED)

        self.status_var.set("状态：正在分析...")
        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete('1.0', tk.END)
        self.result_text.config(state=tk.DISABLED)

    def _解锁界面(self):
        self.is_analyzing = False
        self.single_symbol_combo.config(state='normal') # 改回 normal
        # ---> 启用 Checkbutton Frame <--- 
        self.single_analyze_button.config(state=tk.NORMAL)
        self.batch_analyze_button.config(state=tk.NORMAL)
        self.market_type_menu.config(state=tk.NORMAL)
        # ---> 启用全选/全不选按钮 <--- 
        self.select_all_button.config(state=tk.NORMAL)
        self.deselect_all_button.config(state=tk.NORMAL)
        # 启用 Checkbuttons
        for cb in self.checkbutton_frame.winfo_children():
             if isinstance(cb, ttk.Checkbutton):
                 cb.config(state=tk.NORMAL)

        self.status_var.set("状态：分析完成")
        self.root.after(3000, lambda: self.status_var.set(f"状态：加载了 {len(self.all_symbols_list)} 个交易对，空闲。") if self.all_symbols_list and not self.is_analyzing else None)

    def _显示结果(self, message):
        self.result_text.config(state=tk.NORMAL)
        self.result_text.insert(tk.END, str(message) + "\n\n") # 确保是字符串
        self.result_text.see(tk.END)
        self.result_text.config(state=tk.DISABLED)
        self.root.update_idletasks()

    def 分析单个币(self):
        if self.is_analyzing:
            messagebox.showwarning("请稍候", "当前正在进行分析，请等待完成后再试。")
            return
        
        # ---> 从 Combobox 获取币种 <--- 
        symbol = self.single_symbol_combo.get().strip().upper()
        if not symbol:
            messagebox.showerror("选择错误", "请选择或输入要分析的单个币种。")
            return
        # (可选) 检查输入是否在列表中
        # if symbol not in self.all_symbols_list:
        #     if not messagebox.askyesno("确认", f"币种 \"{symbol}\" 不在加载的列表中，确定要继续分析吗？"):
        #         return

        market_type_display = self.market_type_var.get()
        market_type_actual = self.market_options_map.get(market_type_display, 'futures')

        self._锁定界面()
        self._显示结果(f"--- 开始分析单个币种: {symbol} ({market_type_display}) ---")

        analysis_thread = threading.Thread(target=self._执行分析任务, args=([symbol], market_type_actual), daemon=True)
        analysis_thread.start()

    def 批量分析(self):
        if self.is_analyzing:
            messagebox.showwarning("请稍候", "当前正在进行分析，请等待完成后再试。")
            return

        # ---> 从 Checkbutton 变量获取选中的币种 <--- 
        selected_symbols = [
            symbol for symbol, var in self.batch_check_vars.items() if var.get()
        ]

        if not selected_symbols:
            messagebox.showerror("选择错误", "请至少勾选一个要批量分析的币种。")
            return
        
        # 对选中的币种排序
        selected_symbols.sort()

        market_type_display = self.market_type_var.get()
        market_type_actual = self.market_options_map.get(market_type_display, 'futures')

        self._锁定界面()
        self._显示结果(f"--- 开始批量分析 ({len(selected_symbols)}个币种, 市场: {market_type_display}) ---")
        # 每行显示几个币种，避免过长
        display_limit = 10
        display_str = "选中币种: " + ", ".join(selected_symbols[:display_limit])
        if len(selected_symbols) > display_limit:
            display_str += f", ... (等 {len(selected_symbols)} 个)"
        self._显示结果(display_str)

        analysis_thread = threading.Thread(target=self._执行分析任务, args=(selected_symbols, market_type_actual), daemon=True)
        analysis_thread.start()

    def _执行分析任务(self, symbols, market_type):
        """在后台线程中执行分析任务"""
        all_tasks_completed_normally = True # 标志位
        try:
            total_symbols = len(symbols)
            for i, symbol in enumerate(symbols):
                # 检查主窗口是否仍然存在，如果不存在则提前退出线程
                if not hasattr(self.root, 'winfo_exists') or not self.root.winfo_exists():
                    print("主窗口已关闭，分析线程提前退出。")
                    all_tasks_completed_normally = False
                    break
                
                self.result_queue.put(f"--- ({i+1}/{total_symbols}) 正在分析: {symbol} ({market_type}) ---")
                try:
                    # 调用包装函数进行分析
                    result = 执行完整分析(symbol, market_type)
                    self.result_queue.put(f"--- {symbol} 分析结果 ---")
                    self.result_queue.put(result)
                except Exception as e:
                    all_tasks_completed_normally = False
                    error_msg = f"!!! 分析 {symbol} 时发生严重错误: {e} !!!"
                    self.result_queue.put(error_msg)
                    print(error_msg, file=sys.stderr) # 也打印到控制台
                    import traceback
                    traceback.print_exc() # 打印详细堆栈信息

                time.sleep(0.5) # 短暂暂停，避免过于频繁（可选）
            
            # 只有在正常完成所有任务后才发送完成信号
            if all_tasks_completed_normally and hasattr(self.root, 'winfo_exists') and self.root.winfo_exists():
                 self.result_queue.put(("TASK_DONE", "--- 所有分析任务完成 ---")) # 添加类型标识

        except Exception as e:
             # 捕获线程自身的异常
             print(f"!!! 批量分析线程发生严重错误: {e} !!!", file=sys.stderr)
             import traceback
             traceback.print_exc()
             # 即使线程出错，也尝试通知主线程（如果窗口还存在）
             if hasattr(self.root, 'winfo_exists') and self.root.winfo_exists():
                 self.result_queue.put(("THREAD_ERROR", f"!!! 批量分析线程严重错误，分析可能未完成: {e} !!!")) # 添加类型标识

    def _检查队列(self):
        """定时检查结果队列，并更新 GUI"""
        try:
            while True: # 处理队列中所有消息
                item = self.result_queue.get_nowait()
                
                if isinstance(item, tuple) and len(item) == 2:
                    msg_type, payload = item
                    if msg_type == "UPDATE_SYMBOLS":
                        self._更新交易对列表(payload)
                    elif msg_type == "LOAD_ERROR":
                        self._显示结果(f"加载错误: {payload}")
                        self.status_var.set(f"状态：加载交易对失败。")
                        messagebox.showerror("加载失败", f"无法加载交易对列表:\n{payload}")
                    elif msg_type == "TASK_DONE":
                        self._显示结果(payload)
                        if self.is_analyzing: self._解锁界面()
                    elif msg_type == "THREAD_ERROR":
                        self._显示结果(payload)
                        if self.is_analyzing: self._解锁界面() # 即使线程错误也解锁
                    else:
                        # 未知类型的元组消息，显示原始内容
                        self._显示结果(str(item))
                elif isinstance(item, str):
                     # 处理纯字符串消息（例如分析结果）
                     self._显示结果(item)
                else:
                     # 处理其他未知类型的消息
                     self._显示结果(f"收到未知消息类型: {type(item)}")

        except queue.Empty:
            pass
        except Exception as e:
             print(f"检查队列时发生错误: {e}")

        # 只要窗口存在就继续检查
        if hasattr(self.root, 'winfo_exists') and self.root.winfo_exists():
             self.root.after(200, self._检查队列)

    # --- 添加 Combobox 事件处理函数 --- 
    def _on_combobox_keyrelease(self, event):
        """当 Combobox 输入变化时，筛选下拉列表"""
        value = self.single_symbol_combo.get().upper() # 获取当前输入并转大写
        if value == '':
            # 如果输入为空，显示完整列表
            self.single_symbol_combo['values'] = self.all_symbols_list
        else:
            # 筛选以输入开头的币种
            filtered_list = [symbol for symbol in self.all_symbols_list if symbol.startswith(value)]
            self.single_symbol_combo['values'] = filtered_list
        
        # 小技巧：让下拉列表展开，显示筛选结果
        # 但这可能会有点干扰用户输入，可以注释掉下面这行试试
        # self.single_symbol_combo.event_generate('<Down>') 
    
    def _on_combobox_select(self, event):
        """当用户从下拉列表选择一项后，恢复显示完整列表 (可选) """
        # 当用户明确选择一项后，可能希望下次输入时看到完整列表
        self.single_symbol_combo['values'] = self.all_symbols_list

    # --- 添加 全选/全不选 的方法 --- 
    def _全选币种(self):
        """将所有批量选择的 Checkbutton 设为选中状态"""
        for var in self.batch_check_vars.values():
            var.set(True)
    
    def _全不选币种(self):
        """将所有批量选择的 Checkbutton 设为未选中状态"""
        for var in self.batch_check_vars.values():
            var.set(False)

    # --- 添加批量列表筛选方法 --- 
    def _筛选批量列表(self, event=None):
        """根据搜索框内容筛选批量选择列表中的 Checkbutton"""
        filter_text = self.batch_search_var.get().upper()
        visible_count = 0
        # 遍历内部 Frame 的所有子控件 (Checkbuttons)
        for widget in self.checkbutton_frame.winfo_children():
            if isinstance(widget, ttk.Checkbutton):
                symbol_text = widget.cget("text")
                if filter_text in symbol_text:
                    # 如果匹配，确保它在 grid 中
                    # 注意：我们不能直接知道它原来的行列号，但 grid() 默认会添加到下一个可用位置，
                    # 或者如果它已经被 grid 管理，这会确保它保留 grid 信息并可见
                    # 为了保持原来的多列布局，我们需要重新 grid 它，但这会打乱顺序。
                    # 更简单的方法是 grid() 显示， grid_remove() 隐藏
                    widget.grid() # 确保可见
                    visible_count += 1
                else:
                    # 如果不匹配，从 grid 中移除 (隐藏)
                    widget.grid_remove()
        
        # 更新 Canvas 滚动区域以适应筛选后的内容
        self.checkbutton_frame.update_idletasks()
        self._on_frame_configure()
        # print(f"Filter: '{filter_text}', Visible: {visible_count}") # for debugging

# --- 程序入口 ---
if __name__ == "__main__":
    # 尝试设置高 DPI 支持 (Windows)
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except ImportError:
        pass
    except AttributeError:
        pass

    root = tk.Tk()
    style = ttk.Style(root)
    try:
        available_themes = style.theme_names()
        if 'clam' in available_themes: style.theme_use('clam')
        elif 'vista' in available_themes: style.theme_use('vista')
        elif 'aqua' in available_themes: style.theme_use('aqua')
    except tk.TclError:
        print("无法设置 ttk 主题，将使用默认主题。")
        
    app = 主分析窗口(root)
    root.mainloop() 