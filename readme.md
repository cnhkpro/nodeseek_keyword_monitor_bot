# 🚀 NodeSeek 多用户 RSS 关键词监控 Telegram Bot

这是一个轻量级、支持多用户的 NodeSeek 论坛 RSS 实时监控 Telegram 机器人。支持自定义包含/排除关键词过滤、分类解析、Inline Keyboard 交互操作，并使用 SQLite 实现持久化存储。

## ✨ 功能特性

- 📡 **实时监控**：定时轮询 NodeSeek RSS 订阅源，推送最新帖子。
- 👥 **多用户隔离**：支持多用户独立配置监控规则与推送记录。
- 🎯 **精准过滤**：支持包含关键词（Include）与排除关键词（Exclude）组合过滤。
- 🔘 **交互式 UI**：基于 Telegram Inline Keyboard，无需手动输入繁琐指令即可管理规则。
- 🐳 **Docker 支持**：一键开箱即用，支持 Docker Compose 部署。




## 🛠️ 快速部署

### 部署前的准备工作

1. **克隆仓库**
   ```bash
   git clone https://github.com/cnhkpro/nodeseek_keyword_monitor_bot.git
   
   cd nodeseek_keyword_monitor_bot
   ```

2. **配置环境变量**

   ```bash
   cp .env.example .env
   # 编辑 .env 文件，填入你的 BOT_TOKEN
   vi .env
   ```
### 方式一：使用 Docker Compose部署（推荐）

   ```bash
   docker compose up -d
   ```

### 方式二：直接运行 Python

   ```bash
   pip install -r requirements.txt
   python ns_bot_multi.py
   ```



## 📝 命令说明

- `/start` - 初始化并打开主控制面板
- `/add <关键词>` - 快速添加包含关键词
- `/add_ex <关键词>` - 快速添加排除关键词
- `/list` - 查看并管理当前的规则列表

添加的关键词支持 **正则表达式** 哦！

## 📄 开源协议

本项目基于 [MIT License](LICENSE) 开源。