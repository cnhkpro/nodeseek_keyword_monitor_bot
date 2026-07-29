import os
import re
import time
import threading
import sqlite3
import requests
import feedparser
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

#  显式加载 .env 文件中的环境变量
load_dotenv()


# ==================== 1. 配置区域 ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_FILE = os.getenv("DB_FILE")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL"))  # 轮询间隔时间（秒）
RSS_URL = os.getenv("RSS_URL")

CATEGORY_MAP = {
    "daily": "日常", "tech": "技术", "info": "情报", "review": "测评",
    "trade": "交易", "carpool": "拼车", "promotion": "推广", "life": "生活",
    "dev": "Dev", "photo-share": "贴图", "expose": "曝光", "inside": "内版", "sandbox": "沙盒"
}


bot = telebot.TeleBot(BOT_TOKEN)

# ==================== 2. 数据库模块 ====================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            chat_id TEXT PRIMARY KEY,
            is_paused INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            type TEXT NOT NULL,
            keyword TEXT NOT NULL,
            UNIQUE(chat_id, type, keyword)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pushed (
            chat_id TEXT NOT NULL,
            post_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            PRIMARY KEY(chat_id, post_id)
        )
    ''')
    conn.commit()
    conn.close()

def register_user(chat_id):
  
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    chat_id_str = str(chat_id)
    
    # 1. 强制保证用户存在于 users 表
    cursor.execute("INSERT OR IGNORE INTO users (chat_id, is_paused) VALUES (?, 0)", (chat_id_str,))
    
    # 2. 检查是否是全新用户（规则表是否为空），如果是才加默认规则
    cursor.execute("SELECT COUNT(*) FROM rules WHERE chat_id = ?", (chat_id_str,))
    rule_count = cursor.fetchone()[0]
   
    conn.commit()
    conn.close()

def get_active_users():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM users WHERE is_paused = 0")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def set_user_pause(chat_id, is_paused):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_paused = ? WHERE chat_id = ?", (is_paused, str(chat_id)))
    conn.commit()
    conn.close()

def get_user_rules_with_id(chat_id, rule_type):
    """获取带 ID 的规则，专供生成 Inline Keyboard 使用"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, keyword FROM rules WHERE chat_id = ? AND type = ?", (str(chat_id), rule_type))
    rules = cursor.fetchall()  # 返回 [(id, keyword), ...]
    conn.close()
    return rules

def get_user_rules(chat_id, rule_type):
    """获取纯关键词列表，专供 RSS 轮询匹配使用"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT keyword FROM rules WHERE chat_id = ? AND type = ?", (str(chat_id), rule_type))
    rules = [row[0] for row in cursor.fetchall()]
    conn.close()
    return rules

def add_user_rule(chat_id, rule_type, keyword):
   
    
    # 确保用户表里必定有这个 user
    register_user(chat_id)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO rules (chat_id, type, keyword) VALUES (?, ?, ?)", 
                       (str(chat_id), rule_type, keyword.strip()))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success
def del_user_rule_by_id(chat_id, rule_id):
    """根据 ID 删除规则，彻底解决 callback_data 超长问题"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # 先获取关键词文本供弹窗提示使用
    cursor.execute("SELECT keyword FROM rules WHERE id = ? AND chat_id = ?", (rule_id, str(chat_id)))
    row = cursor.fetchone()
    kw_text = row[0] if row else ""
    
    cursor.execute("DELETE FROM rules WHERE id = ? AND chat_id = ?", (rule_id, str(chat_id)))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0, kw_text

def is_pushed_for_user(chat_id, post_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM pushed WHERE chat_id = ? AND post_id = ?", (str(chat_id), post_id))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def mark_pushed_for_user(chat_id, post_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO pushed (chat_id, post_id) VALUES (?, ?)", (str(chat_id), post_id))
    conn.commit()
    conn.close()

# ==================== 3. 按钮键盘构建函数 (优化 Callback) ====================
def build_keywords_inline_keyboard(chat_id, rule_type="include"):
    rules = get_user_rules_with_id(chat_id, rule_type)
    markup = InlineKeyboardMarkup()

    for rule_id, kw in rules:
        # 截取超长词预览，防止按钮撑爆页面
        display_kw = kw[:18] + "..." if len(kw) > 20 else kw
        btn_kw = InlineKeyboardButton(f"• {display_kw}", callback_data="noop")
        
        # 关键修改：callback_data 格式简化为 "del:数字ID"，非常短，永不超限！
        btn_del = InlineKeyboardButton("❌", callback_data=f"del:{rule_id}:{rule_type}")
        markup.row(btn_kw, btn_del)

    toggle_type = "exclude" if rule_type == "include" else "include"
    toggle_text = "🔄 切换到黑名单" if rule_type == "include" else "🔄 切换到白名单"
    markup.add(InlineKeyboardButton(toggle_text, callback_data=f"sw:{toggle_type}"))

    return markup

# ==================== 4. Telegram 命令交互模块 ====================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    chat_id = str(message.chat.id)
    register_user(chat_id)
    
    help_text = (
        "🤖 <b>欢迎使用 NodeSeek 实时监控机器人</b>\n\n"
        "你可以自由添加想监控的关键词，我会 24 小时监控论坛新帖。\n\n"
        "<b>可用命令列表：</b>\n"
        "<b>/list</b> - 查看并管理我的关键词\n"
        "<b>/add 词语</b> - 添加白名单监控词 (例如 <code>/add 斯巴达</code>)\n"
        "<b>/add_ex 词语</b> - 添加黑名单屏蔽词 (例如 <code>/add_ex 已出</code>)\n"
        "<b>/pause</b> - 暂停我的推送\n"
        "<b>/resume</b> - 恢复我的推送\n"
    )
    bot.reply_to(message, help_text, parse_mode="HTML")

@bot.message_handler(commands=['list'])
def handle_list(message):
    chat_id = str(message.chat.id)
    register_user(chat_id)
    
    markup = build_keywords_inline_keyboard(chat_id, 'include')
    rules = get_user_rules(chat_id, 'include')
    
    text = "🎯 <b>你的白名单监控词列表</b>：\n（点击右侧 ❌ 即可直接删除）" if rules else "🎯 你的白名单列表为空，使用 <code>/add 关键词</code> 添加。"
    bot.reply_to(message, text, parse_mode="HTML", reply_markup=markup)

@bot.message_handler(commands=['add'])
def handle_add(message):
    chat_id = str(message.chat.id)
    register_user(chat_id)
    
    kw = message.text.replace('/add', '').strip()
    if not kw:
        bot.reply_to(message, "⚠️ 请提供要添加的关键词，例如：<code>/add 瓦工</code>", parse_mode="HTML")
        return
    if add_user_rule(chat_id, 'include', kw):
        markup = build_keywords_inline_keyboard(chat_id, 'include')
        bot.reply_to(message, f"✅ 已成功添加监控词：<code>{kw}</code>\n发送 /list 可在线管理。", parse_mode="HTML", reply_markup=markup)
    else:
        bot.reply_to(message, f"⚠️ 你已经添加过 <code>{kw}</code> 了。", parse_mode="HTML")

@bot.message_handler(commands=['add_ex'])
def handle_add_ex(message):
    chat_id = str(message.chat.id)
    register_user(chat_id)
    
    kw = message.text.replace('/add_ex', '').strip()
    if not kw:
        bot.reply_to(message, "⚠️ 请提供要屏蔽的关键词，例如：<code>/add_ex 误报</code>", parse_mode="HTML")
        return
    if add_user_rule(chat_id, 'exclude', kw):
        bot.reply_to(message, f"🚫 已成功添加屏蔽词：<code>{kw}</code>", parse_mode="HTML")
    else:
        bot.reply_to(message, f"⚠️ 屏蔽词 <code>{kw}</code> 已经存在。", parse_mode="HTML")

@bot.message_handler(commands=['pause'])
def handle_pause(message):
    set_user_pause(str(message.chat.id), 1)
    bot.reply_to(message, "⏸️ 监控推送已暂停。使用 /resume 可随时恢复。")

@bot.message_handler(commands=['resume'])
def handle_resume(message):
    set_user_pause(str(message.chat.id), 0)
    bot.reply_to(message, "🟢 监控推送已恢复运行！")

# ==================== 5. 处理按钮点击 (Callback Query) ====================
@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    chat_id = str(call.message.chat.id)
    data = call.data
    
    if data == "noop":
        bot.answer_callback_query(call.id)
        return

    # 1. 点击 ❌ 删除逻辑 (格式: "del:rule_id:rule_type")
    if data.startswith("del:"):
        _, rule_id, rule_type = data.split(":")
        
        success, kw_text = del_user_rule_by_id(chat_id, int(rule_id))
        if success:
            bot.answer_callback_query(call.id, text=f"✅ 已删除：{kw_text}", show_alert=False)
        else:
            bot.answer_callback_query(call.id, text="⚠️ 该词已被删除", show_alert=False)
            
        new_markup = build_keywords_inline_keyboard(chat_id, rule_type)
        rules_left = get_user_rules(chat_id, rule_type)
        type_name = "白名单" if rule_type == "include" else "黑名单"
        
        new_text = f"🎯 <b>你的{type_name}列表</b>：\n（点击右侧 ❌ 即可直接删除）" if rules_left else f"🎯 你的{type_name}列表为空。"
        
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=new_text,
                parse_mode="HTML",
                reply_markup=new_markup
            )
        except Exception:
            pass

    # 2. 点击切换黑/白名单 (格式: "sw:target_type")
    elif data.startswith("sw:"):
        _, target_type = data.split(":", 1)
        new_markup = build_keywords_inline_keyboard(chat_id, target_type)
        rules_left = get_user_rules(chat_id, target_type)
        type_name = "白名单" if target_type == "include" else "黑名单"
        
        new_text = f"🎯 <b>你的{type_name}列表</b>：\n（点击右侧 ❌ 即可直接删除）" if rules_left else f"🎯 你的{type_name}列表为空。"
        
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=new_text,
                parse_mode="HTML",
                reply_markup=new_markup
            )
        except Exception:
            pass
        bot.answer_callback_query(call.id)

# ==================== 6. 后台 RSS 轮询推送引擎 ====================
def send_telegram_notify(chat_id, title, link, matched_word, category="" ,author=""):
   
    
    safe_title = str(title).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_category = str(category).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") if category else "综合"
    safe_word = str(matched_word).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") 
    # 关键修改：强制转为 str(author)，防止 feedparser 的 Dict 对象在条件判断中被识别为空
    safe_author = str(author).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") if str(author).strip() else "未知用户"

    text = (
        f"🎯 <b>NodeSeek 关键词命中</b>\n\n"
        f"🔑 <b>命中词</b>：<code>{safe_word}</code>\n"
        f"📌 <b>标题</b>：{safe_title}\n"
        f"🏷️ <b>分类</b>：{safe_category}\n"
        f"👤 <b>发帖人</b>：<code>{safe_author}</code>\n\n"
        f'🔗 <a href="{link}">点击阅读原文</a>'
    )
    try:
        bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=False)
    except telebot.apihelper.ApiTelegramException as e:
        if e.error_code == 403:
            set_user_pause(chat_id, 1)

def rss_worker():
    print("🚀 RSS 后台轮询引擎启动...")
    while True:
        try:
            feed = feedparser.parse(RSS_URL)
            if not feed.bozo:
                active_users = get_active_users()
                
                for entry in feed.entries:
                    post_id = entry.get('id', entry.link)
                    title = entry.title
                    link = entry.link
                    # 提取发帖者信息
                    author = entry.get('author', '未知用户')

                    
                    category = "综合"
                    if 'tags' in entry and len(entry.tags) > 0:
                        raw_tag = entry.tags[0].term.strip().lower()
                        category = CATEGORY_MAP.get(raw_tag, raw_tag)

                    for chat_id in active_users:
                        if is_pushed_for_user(chat_id, post_id):
                            continue
                            
                        includes = get_user_rules(chat_id, 'include')
                        excludes = get_user_rules(chat_id, 'exclude')
                        
                        if not includes:
                            mark_pushed_for_user(chat_id, post_id)
                            continue

                        include_pattern = r"(" + "|".join(includes) + r")"
                        exclude_pattern = r"(" + "|".join(excludes) + r")" if excludes else None

                        if exclude_pattern and re.search(exclude_pattern, title, re.IGNORECASE):
                            mark_pushed_for_user(chat_id, post_id)
                            continue

                        match = re.search(include_pattern, title, re.IGNORECASE)
                        if match:
                            matched_word = match.group(0)
                            print(f"✨ 用户 [{chat_id}] 命中词 [{matched_word}]: {title} (作者: {author})")
                            # print(f"✨ 用户 [{chat_id}] 命中词 [{matched_word}]: {title}")
                            send_telegram_notify(chat_id, title, link, matched_word, category,author)
                            mark_pushed_for_user(chat_id, post_id)
                        else:
                            mark_pushed_for_user(chat_id, post_id)
                            
        except Exception as e:
            print(f"❌ RSS 轮询过程出错: {e}")

        time.sleep(CHECK_INTERVAL)

# ==================== 7. 主程序入口 ====================
if __name__ == "__main__":
    init_db()
    
    t = threading.Thread(target=rss_worker, daemon=True)
    t.start()
    
    print("🤖 Telegram 机器人已成功启动！在 TG 中发送 /start 即可交互...")
    bot.infinity_polling()