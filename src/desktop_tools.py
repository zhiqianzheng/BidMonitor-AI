"""History browsing and explainable keyword rules for the original desktop app."""
import csv
import sqlite3
import webbrowser
from contextlib import closing
from datetime import date
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from .matcher.keyword import KeywordMatcher


class History:
    def __init__(self, path='data/bids.db'):
        self.path = Path(path).resolve()

    def connect(self):
        from .crawler.listing import is_notice_noise
        db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=10)
        db.create_function('notice_noise', 2, is_notice_noise, deterministic=True)
        return db

    def sources(self):
        if not self.path.exists():
            return []
        with closing(self.connect()) as db:
            return [r[0] for r in db.execute("SELECT DISTINCT source FROM bids WHERE source<>'' AND NOT notice_noise(title,url) ORDER BY source")]

    def query(self, keyword='', source='', notified='', start='', end='', limit=100, offset=0):
        for value in (start, end):
            if value:
                date.fromisoformat(value)
        if start and end and start > end:
            raise ValueError('开始日期不能晚于结束日期')
        clauses, args = ['NOT notice_noise(title,url)'], []
        for term in keyword.split():
            term = term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            clauses.append(r"(title LIKE ? ESCAPE '\' OR content LIKE ? ESCAPE '\' OR purchaser LIKE ? ESCAPE '\')")
            args.extend(['%' + term + '%'] * 3)
        if source:
            clauses.append('source=?')
            args.append(source)
        if notified != '':
            if str(notified) not in ('0', '1'):
                raise ValueError('未知通知状态')
            clauses.append('notified=?')
            args.append(int(notified))
        if start or end:
            clauses.append("substr(publish_date,1,10) GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'")
        for value, operator in ((start, '>='), (end, '<=')):
            if value:
                clauses.append('substr(publish_date,1,10)' + operator + '?')
                args.append(value)
        if not self.path.exists():
            return 0, []
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with closing(self.connect()) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN')
            total = db.execute('SELECT COUNT(*) FROM bids' + where, args).fetchone()[0]
            sql = 'SELECT title,publish_date,source,purchaser,notified,url,created_at FROM bids' + where + ' ORDER BY created_at DESC,id DESC'
            if limit is not None:
                sql += ' LIMIT ? OFFSET ?'
                args.extend([max(1, int(limit)), max(0, int(offset))])
            return total, [dict(r) for r in db.execute(sql, args)]

    def export(self, path, **filters):
        total, rows = self.query(**filters, limit=None)
        def safe(value):
            value = str(value or '')
            return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
        with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['标题', '发布日期', '来源', '采购单位', '通知状态', '原文链接', '入库时间'])
            for row in rows:
                row['notified'] = '已完成通知' if row['notified'] else '待通知'
                writer.writerow([safe(row[k]) for k in ('title', 'publish_date', 'source', 'purchaser', 'notified', 'url', 'created_at')])
        return total


def explain(include, exclude, must, title, content):
    split = lambda text: [w.strip() for w in text.replace('，', ',').split(',') if w.strip()]
    matcher = KeywordMatcher(split(include), split(exclude), split(must))
    text = '\n'.join([title, content]).lower()
    hits = lambda words: '、'.join(w for w in words if w in text) or '无'
    return '\n'.join([
        '关键词规则结果：' + ('符合' if matcher.match_any(title, content).matched else '不符合'),
        '关注词命中：' + hits(matcher.include_keywords),
        '必须包含组命中：' + (hits(matcher.must_contain_keywords) if matcher.must_contain_keywords else '未设置'),
        '排除词命中：' + hits(matcher.exclude_keywords),
        '逻辑：关注词任一命中 AND 必须组任一命中（若设置）AND 无排除词。标题与正文合并判断。',
        '仅预览关键词规则，不调用 AI、不发送通知；正式 AI 判断可能进一步排除。'])


def show_history(gui):
    win = tk.Toplevel(gui.root)
    win.title('历史结果 · 查询与导出')
    win.geometry('1100x620')
    history, variables, offset = History(), {}, [0]
    fields = ttk.Frame(win, padding=10)
    fields.pack(fill='x')
    for col, (key, label, width) in enumerate([('keyword','关键词（空格表示同时匹配）',24), ('source','来源',16), ('notified','通知状态',12), ('start','发布起始 YYYY-MM-DD',16), ('end','发布截止 YYYY-MM-DD',16)]):
        box = ttk.Frame(fields)
        box.grid(row=0, column=col, padx=4)
        ttk.Label(box, text=label).pack(anchor='w')
        variables[key] = tk.StringVar()
        if key in ('source', 'notified'):
            values = ['全部来源'] + history.sources() if key == 'source' else ['全部状态','待通知','已完成通知']
            variables[key].set(values[0])
            widget = ttk.Combobox(box, textvariable=variables[key], values=values, state='readonly', width=width)
        else:
            widget = ttk.Entry(box, textvariable=variables[key], width=width)
        widget.pack(fill='x')
    toolbar = ttk.Frame(win, padding=10)
    toolbar.pack(fill='x')
    frame = ttk.Frame(win, padding=10)
    frame.pack(fill='both', expand=True)
    columns = ('title','publish_date','source','purchaser','notified','url')
    tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse')
    for key, label, width in zip(columns, ['标题','发布日期','来源','采购单位','通知状态','原文链接'], [350,110,150,150,100,250]):
        tree.heading(key, text=label)
        tree.column(key, width=width, minwidth=70)
    vertical = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
    horizontal = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.grid(row=0,column=0,sticky='nsew')
    vertical.grid(row=0,column=1,sticky='ns')
    horizontal.grid(row=1,column=0,sticky='ew')
    frame.rowconfigure(0,weight=1)
    frame.columnconfigure(0,weight=1)
    status = tk.StringVar()
    ttk.Label(win,textvariable=status,padding=10).pack(fill='x')
    active = [{}]
    def filters():
        values = {key: var.get().strip() for key,var in variables.items()}
        if values['source'] == '全部来源': values['source'] = ''
        values['notified'] = {'全部状态':'','待通知':'0','已完成通知':'1'}[values['notified']]
        return values
    def load(reset=False):
        try:
            values = filters()
            position = 0 if reset else offset[0]
            total, rows = history.query(**values, offset=position)
            if position >= total and position:
                position = max(0, ((total - 1) // 100) * 100)
                total, rows = history.query(**values, offset=position)
            offset[0], active[0] = position, values
            for item in tree.get_children(): tree.delete(item)
            for row in rows:
                tree.insert('', 'end', values=[row['title'],row['publish_date'] or '未知',row['source'],row['purchaser'],'已完成通知' if row['notified'] else '待通知',row['url']])
            status.set(f'共 {total} 条 · 第 {position // 100 + 1 if total else 0}/{(total + 99) // 100} 页 · 每页100条；已隐藏导航和平台服务信息，日期筛选不含未知发布日期。')
            previous.configure(state='normal' if position else 'disabled')
            following.configure(state='normal' if position + 100 < total else 'disabled')
        except (ValueError, sqlite3.Error) as error:
            messagebox.showerror('查询失败',str(error),parent=win)
    def page(delta):
        if filters() != active[0]: load(True); return
        offset[0] = max(0,offset[0] + delta)
        load()
    def export():
        try:
            values = filters()
            history.query(**values,limit=1)
            path = filedialog.asksaveasfilename(parent=win,title='导出全部符合条件的结果',defaultextension='.csv',filetypes=[('CSV文件','*.csv')])
            if path:
                count = history.export(path,**values)
                messagebox.showinfo('导出完成',f'已导出 {count} 条符合当前条件的记录。',parent=win)
        except (ValueError,sqlite3.Error,OSError) as error:
            messagebox.showerror('导出失败',str(error),parent=win)
    def open_link(event=None):
        selection = tree.selection()
        if selection:
            url = str(tree.item(selection[0],'values')[-1])
            if url.startswith(('https://','http://')): webbrowser.open(url)
    ttk.Button(toolbar,text='查询 / 刷新',command=lambda:load(True)).pack(side='left')
    ttk.Button(toolbar,text='导出全部符合条件的结果',command=export).pack(side='left',padx=6)
    ttk.Button(toolbar,text='打开选中公告原文',command=open_link).pack(side='left')
    previous = ttk.Button(toolbar,text='上一页',command=lambda:page(-100))
    previous.pack(side='right')
    following = ttk.Button(toolbar,text='下一页',command=lambda:page(100))
    following.pack(side='right',padx=6)
    tree.bind('<Double-1>',open_link)
    win.bind('<Return>',lambda event:load(True))
    load(True)


def show_rules(gui):
    win = tk.Toplevel(gui.root)
    win.title('规则预览 · 不调用 AI')
    win.geometry('800x650')
    frame = ttk.Frame(win,padding=15)
    frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='使用主界面当前规则；关注词为空时沿用原版默认值。预览不会保存设置或开始采集。').pack(anchor='w')
    ttk.Label(frame,text='公告标题').pack(anchor='w',pady=(12,0))
    title = ttk.Entry(frame)
    title.pack(fill='x')
    ttk.Label(frame,text='公告正文（可选）').pack(anchor='w',pady=(10,0))
    content = scrolledtext.ScrolledText(frame,height=8)
    content.pack(fill='both',expand=True)
    result = scrolledtext.ScrolledText(frame,height=10,state='disabled')
    result.pack(fill='both',expand=True,pady=10)
    def preview():
        include = gui.keywords_var.get().strip() or gui.DEFAULT_KEYWORDS
        message = explain(include,gui.exclude_var.get(),gui.must_contain_var.get(),title.get(),content.get('1.0','end-1c'))
        result.configure(state='normal')
        result.delete('1.0','end')
        result.insert('1.0',message)
        result.configure(state='disabled')
    ttk.Button(frame,text='预览匹配结果',command=preview).pack()
